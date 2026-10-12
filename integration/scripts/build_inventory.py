#!/usr/bin/env python3
"""Rebuild country-month and quarter inventory from the preserved source trees.

This is a preservation/catalogue pass. File presence, review receipts, bounded
acceptance, and official completion remain separate dimensions. Missing files
in a safety-filtered public snapshot do not establish that work was not done.
"""
from __future__ import annotations

import csv
import calendar
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "integration" / "inventory"
SOURCES = ROOT / "integration" / "source-branches"
BRANCH_REGISTER = ROOT / "integration" / "BRANCH_REGISTER.csv"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    cache_key = str(path.resolve())
    if cache_key in HASH_CACHE:
        return HASH_CACHE[cache_key]
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    result = h.hexdigest()
    HASH_CACHE[cache_key] = result
    return result


HASH_CACHE: dict[str, str] = {}


def slugify(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def list_months(year: int, quarter: int) -> list[str]:
    start = (quarter - 1) * 3 + 1
    if year == 2026 and quarter == 4:
        return ["2026-10"]
    return [f"{year}-{month:02d}" for month in range(start, start + 3)]


def quarter_order():
    return [(2020, 2), (2020, 3), (2020, 4)] + [
        (year, q) for year in range(2021, 2026) for q in range(1, 5)
    ] + [(2026, q) for q in range(1, 5)]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    with BRANCH_REGISTER.open(encoding="utf-8") as f:
        branches = list(csv.DictReader(f))
    branch_by_ref = {row["source_ref"]: row for row in branches}
    recovery_map = {}
    with (ROOT / "integration" / "QUARTER_RECOVERY_STATUS.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            recovery_map[row["quarter"]] = row

    # The quarter closeout's 480 expected IDs define the inherited provisional
    # universe; the country CSV explicitly warns that it is not official.
    q4_inventory = read_json(SOURCES / "saved-progress/2024Q4-20261012/INVENTORY.json")
    expected_ids = q4_inventory["sets"]["expected_unit_ids"]
    country_slugs = sorted({unit.rsplit("_2024-", 1)[0] for unit in expected_ids})
    if len(expected_ids) != 480 or len(country_slugs) != 160:
        raise SystemExit(f"unexpected inherited universe: {len(expected_ids)} IDs / {len(country_slugs)} countries")
    country_csv = SOURCES / "saved-progress/2024Q3-20261012/mass_mobilization_extension/planning/countries_provisional.csv"
    country_rows = list(csv.DictReader(country_csv.open(encoding="utf-8-sig")))
    country_names = {slugify(r["country"]): r["country"] for r in country_rows}
    if not set(country_slugs).issubset(country_names):
        raise SystemExit("provisional country list does not cover the 160 expected IDs")

    quarters = quarter_order()
    months_by_quarter = {f"{y}Q{q}": list_months(y, q) for y, q in quarters}
    expected_months = {m for months in months_by_quarter.values() for m in months}
    country_by_slug = {slug: country_names[slug] for slug in country_slugs}
    q4_root = SOURCES / "codex/closure-2026Q4-20261012/quarter-staging/2026Q4/local-closure-20261011T094114675567Z"
    index_path = q4_root / "discovery-staging-index.json"
    q4_index = read_json(index_path)
    q4_unit_ids = {e["unit"] for e in q4_index["entries"]}
    q4_integrity_holds = set(q4_index.get("integrity_hold_units", []))

    # Each source-file occurrence is retained. A quarter-country record may be
    # referenced by the three monthly rows it covers; the scope column prevents
    # that reference from being mistaken for a distinct month-level document.
    evidence = []
    unmapped = []
    status_observations = []
    seen_evidence = set()
    unit_dir_re = re.compile(r"(?:^|/)mass_mobilization_extension/units/([^/]+)/(\d{4}-\d{2})(?:/|$)")
    month_re = re.compile(r"^(\d{4})-(\d{2})$")

    def add_evidence(ref, path, unit_id, scope, role):
        key = (ref, path.as_posix(), unit_id, scope)
        if key in seen_evidence:
            return
        seen_evidence.add(key)
        branch = branch_by_ref[ref]
        evidence.append({
            "unit_id": unit_id,
            "quarter": unit_id.rsplit("_", 1)[1][:4] + "Q" + str((int(unit_id.rsplit("_", 1)[1][5:7]) - 1) // 3 + 1),
            "artifact_scope": scope,
            "artifact_role": role,
            "source_ref": ref,
            "source_head": branch["source_head"],
            "source_tree": branch["source_tree"],
            "source_path": path.relative_to(ROOT).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        })

    for branch in branches:
        ref = branch["source_ref"]
        branch_root = ROOT / branch["archive_path"]
        if not branch_root.exists():
            raise SystemExit(f"missing archived source tree: {branch_root}")
        for path in branch_root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(branch_root).as_posix()
            match = unit_dir_re.search("/" + rel)
            if match:
                source_slug, month = match.groups()
                if month in expected_months and source_slug in country_by_slug:
                    unit_id = f"{source_slug}_{month}"
                    role = "status_snapshot" if path.name == "status.json" else "unit_directory_file"
                    add_evidence(ref, path, unit_id, "month", role)
                    if path.name == "status.json":
                        try:
                            s = read_json(path)
                        except Exception:
                            s = {}
                        access = s.get("source_access_counts", {}) if isinstance(s, dict) else {}
                        status_observations.append({
                            "unit_id": unit_id,
                            "quarter": unit_id.rsplit("_", 1)[1][:4] + "Q" + str((int(month[5:7]) - 1) // 3 + 1),
                            "source_ref": ref,
                            "source_head": branch["source_head"],
                            "source_path": path.relative_to(ROOT).as_posix(),
                            "sha256": sha256_file(path),
                            "status": s.get("status", ""),
                            "firstpass_complete": s.get("firstpass_complete", ""),
                            "official_approved": s.get("official_approved", ""),
                            "review_state": s.get("review_state", ""),
                            "n_queries": s.get("n_queries", ""),
                            "n_sources": s.get("n_sources", ""),
                            "opened": access.get("opened", ""),
                            "search_only": access.get("search_only", ""),
                            "blocked": access.get("blocked", ""),
                            "not_found": access.get("not_found", ""),
                        })
                elif month in expected_months:
                    unmapped.append({
                        "source_ref": ref,
                        "source_head": branch["source_head"],
                        "country_slug": source_slug,
                        "month": month,
                        "source_path": path.relative_to(ROOT).as_posix(),
                        "sha256": sha256_file(path),
                        "bytes": path.stat().st_size,
                        "reason": "country slug is outside the inherited 160-country provisional universe",
                    })

            # 2026Q2 preserves one country package for Apr-Jun. Attach those
            # exact files as quarter-country references to each of its months.
            if ref == "origin/closeout/2026Q2-3ff07fabd46f":
                q2 = re.search(r"quarter-closeouts/2026Q2/[^/]+/([^/]+)/([^/]+)$", rel)
                if q2:
                    raw_slug, filename = q2.groups()
                    source_slug = slugify(raw_slug)
                    if source_slug == "united_arab_emirates":
                        source_slug = "united_arab_emirate"
                    if source_slug in country_by_slug:
                        for month in months_by_quarter["2026Q2"]:
                            add_evidence(ref, path, f"{source_slug}_{month}", "country-quarter", "provisional_discovery_package")

            # Map named, preserved 2026Q4 artifacts without flattening duplicate
            # or reconstructed files into the primary note slot.
            if ref == "origin/codex/closure-2026Q4-20261012":
                for unit_id in q4_unit_ids:
                    if unit_id in rel:
                        add_evidence(ref, path, unit_id, "country-window", "named_staging_or_preservation_file")

    # Primary Q4 notes and sidecar hashes are declared in a preserved index.
    for entry in q4_index["entries"]:
        unit_id = entry["unit"]
        note = q4_root / entry["primary_note_relative_path"]
        if not note.exists() or sha256_file(note) != entry["primary_note_sha256"] or note.stat().st_size != entry["primary_note_bytes"]:
            raise SystemExit(f"Q4 primary note failed index hash/size: {unit_id}")
        add_evidence("origin/codex/closure-2026Q4-20261012", note, unit_id, "country-window", "indexed_primary_discovery_note")
        for extra in entry.get("additional_preserved_artifacts", []):
            sidecar = q4_root / extra["relative_path"]
            if not sidecar.exists() or sha256_file(sidecar) != extra["sha256"] or sidecar.stat().st_size != extra["bytes"]:
                raise SystemExit(f"Q4 sidecar failed index hash/size: {unit_id}: {extra['relative_path']}")
            add_evidence("origin/codex/closure-2026Q4-20261012", sidecar, unit_id, "country-window", "indexed_preserved_sidecar")

    # Quarter-specific, unit-level facts are copied by ID from the saved reports.
    review_facts = []

    def fact(ref, report_path, unit_id, name, value, basis="explicit unit-level report"):
        p = SOURCES / ref.removeprefix("origin/") / report_path
        review_facts.append({
            "unit_id": unit_id,
            "quarter": unit_id.rsplit("_", 1)[1][:4] + "Q" + str((int(unit_id.rsplit("_", 1)[1][5:7]) - 1) // 3 + 1),
            "fact": name,
            "value": value,
            "basis": basis,
            "source_ref": ref,
            "source_head": branch_by_ref[ref]["source_head"],
            "source_path": p.relative_to(ROOT).as_posix(),
            "source_sha256": sha256_file(p),
        })

    p = "UNIT_PROGRESS.json"
    ref = "origin/saved-progress/2024Q3-20261012"
    q3_2024 = read_json(SOURCES / "saved-progress/2024Q3-20261012" / p)
    for key, label in [("delivered_dossiers", "delivered_dossier"), ("partial_not_delivered", "partial_not_delivered"), ("current_hash_reviews", "current_hash_review"), ("current_hash_bounded_accepted", "bounded_accepted_current_hash"), ("missing_material_vs_480", "missing_material_in_saved_selection")]:
        for unit_id in q3_2024.get(key, []):
            fact(ref, p, unit_id, label, "true")

    ref = "origin/saved-progress/2024Q2-20261012"
    p = "PROGRESS.json"
    q2_2024 = read_json(SOURCES / "saved-progress/2024Q2-20261012" / p)
    for unit_id in q2_2024.get("missing_unit_ids", []):
        fact(ref, p, unit_id, "missing_material_in_safe_selection", "true", "explicit missing-unit ID in saved safe-snapshot report; private evidence may be omitted")

    ref = "origin/saved-progress/2024Q4-20261012"
    p = "INVENTORY.json"
    q4_2024 = read_json(SOURCES / "saved-progress/2024Q4-20261012" / p)
    for row in q4_2024.get("units", []):
        unit_id = row["unit_id"]
        labels = {
            "excluded_from_new_queue": "excluded_from_new_queue",
            "has_note": "note_present_in_selected_generation",
            "has_actual_query": "actual_query_present_in_selected_generation",
            "dossier_query_url_text_metadata_core": "dossier_core_present_in_selected_generation",
            "researcher_delivered_core": "delivered_core",
            "current_hash_independent_review": "current_hash_review",
            "current_hash_accept_bounded": "bounded_accepted_current_hash",
        }
        for source_field, label in labels.items():
            if source_field in row:
                fact(ref, p, unit_id, label, str(bool(row.get(source_field))).lower())

    ref = "origin/saved-progress/2025Q1-20261012"
    p = "closeout/2025Q1/INVENTORY.json"
    q1_2025 = read_json(SOURCES / "saved-progress/2025Q1-20261012" / p)
    for row in q1_2025.get("units", []):
        unit_id = row["unit_id"]
        labels = {
            "has_directory": "directory_present_in_selected_generation",
            "has_notes": "notes_present_in_selected_generation",
            "dossier_with_query_url_extract_metadata": "dossier_present_in_selected_generation",
            "partial_or_prepared": "partial_or_prepared",
            "current_hash_accept": "bounded_accepted_current_hash",
        }
        for source_field, label in labels.items():
            if source_field in row:
                fact(ref, p, unit_id, label, str(bool(row.get(source_field))).lower(), "selected-generation heuristic in saved inventory; not scientific re-review")
        if row.get("declared_status"):
            fact(ref, p, unit_id, "declared_status", row["declared_status"], "status field in saved inventory; current generation selected by saved heuristic")
    for unit_id in q1_2025.get("excluded_prior_or_reserved_ids", []):
        fact(ref, p, unit_id, "excluded_prior_or_reserved", "true")

    ref = "origin/saved-progress/2026Q3-20261012"
    p = "PROGRESS.json"
    q3_2026 = read_json(SOURCES / "saved-progress/2026Q3-20261012" / p)
    for key, label in [("delivered_dossiers", "delivered_dossier"), ("partial_dossiers", "partial_dossier"), ("notes_only", "notes_only"), ("template_or_no_research", "template_or_no_research"), ("current_review_unit_ids", "current_hash_review"), ("current_bounded_acceptance_ids", "bounded_accepted_current_hash"), ("current_verified_provisional_candidate_ids", "verified_provisional_candidate")]:
        value = q3_2026.get(key, [])
        if isinstance(value, dict):
            continue
        for unit_id in value:
            fact(ref, p, unit_id, label, "true")

    ref = "origin/saved-progress/2025Q3-20261012"
    p = "PROGRESS.json"
    q3_2025 = read_json(SOURCES / "saved-progress/2025Q3-20261012" / p)
    for unit_id in q3_2025.get("partial_ids", []):
        fact(ref, p, unit_id, "partial_dossier", "true", "explicit partial ID in saved quarter report")
    for unit_id in q3_2025.get("historical_receipt_hash_mismatch_units", []):
        fact(ref, p, unit_id, "historical_receipt_hash_mismatch", "true", "saved report records historical receipt hash mismatch; not a current review result")

    ref = "origin/closeout/2026Q2-3ff07fabd46f"
    p = "quarter-closeouts/2026Q2/20261011T094026762770Z/HANDOFF.md"
    for month in months_by_quarter["2026Q2"]:
        for slug in country_slugs:
            unit_id = f"{slug}_{month}"
            fact(ref, p, unit_id, "scientific_firstpass_complete", "false", "handoff explicitly says all 480 units have zero scientific first-pass completion")
            fact(ref, p, unit_id, "formal_acceptance_pending", "true", "handoff explicitly says all 480 units remain pending formal acceptance")
            fact(ref, p, unit_id, "canonical_validation_complete", "false", "handoff explicitly says canonical validation remains zero for the 480-unit scope")
    for entry in q4_index["entries"]:
        unit_id = entry["unit"]
        fact("origin/codex/closure-2026Q4-20261012", "quarter-staging/2026Q4/local-closure-20261011T094114675567Z/discovery-staging-index.json", unit_id, "primary_discovery_note_indexed", "true")
        fact("origin/codex/closure-2026Q4-20261012", "quarter-staging/2026Q4/local-closure-20261011T094114675567Z/discovery-staging-index.json", unit_id, "formal_firstpass_complete", str(bool(entry.get("formal_firstpass_complete"))).lower())
        fact("origin/codex/closure-2026Q4-20261012", "quarter-staging/2026Q4/local-closure-20261011T094114675567Z/discovery-staging-index.json", unit_id, "integrity_completion_hold", str(bool(entry.get("integrity_completion_hold"))).lower())

    # Exact unit status is preserved as an observation, never promoted to a
    # current scientific decision when multiple snapshots disagree.
    status_by_unit = defaultdict(list)
    for row in status_observations:
        status_by_unit[row["unit_id"]].append(row)
    evidence_by_unit = defaultdict(list)
    for row in evidence:
        evidence_by_unit[row["unit_id"]].append(row)
    facts_by_unit = defaultdict(list)
    for row in review_facts:
        facts_by_unit[row["unit_id"]].append(row)

    country_months = []
    for y, q in quarters:
        quarter = f"{y}Q{q}"
        for month in months_by_quarter[quarter]:
            for slug in country_slugs:
                unit_id = f"{slug}_{month}"
                files = evidence_by_unit.get(unit_id, [])
                exact = [r for r in files if r["artifact_scope"] == "month"]
                quarter_scoped = [r for r in files if r["artifact_scope"] != "month"]
                statuses = status_by_unit.get(unit_id, [])
                row_facts = facts_by_unit.get(unit_id, [])
                manifest_parts = [f"{r['source_ref']}\t{r['source_path']}\t{r['sha256']}\t{r['bytes']}" for r in sorted(files, key=lambda x: (x["source_ref"], x["source_path"], x["artifact_scope"]))]
                manifest_digest = sha256_bytes(("\n".join(manifest_parts) + ("\n" if manifest_parts else "")).encode())
                has_qscope = any(r["artifact_scope"] == "country-quarter" for r in files)
                has_window = any(r["artifact_scope"] == "country-window" for r in files)
                if exact:
                    observation = "month-specific public files present"
                elif has_qscope:
                    observation = "country-quarter records present; no month-specific file claim"
                elif has_window:
                    observation = "country-window note present; Oct 1-7 only"
                else:
                    observation = "no source file under the unit directory observed in fetched snapshots"
                q4_hold = "true" if unit_id in q4_integrity_holds else "false"
                country_months.append({
                    "quarter": quarter,
                    "country_slug": slug,
                    "country_label_provisional": country_by_slug[slug],
                    "unit_id": unit_id,
                    "period_start": month + ("-01" if month != "2026-10" else "-01"),
                    "period_end": (month + "-07" if month == "2026-10" else f"{month}-{calendar.monthrange(int(month[:4]), int(month[5:7]))[1]:02d}"),
                    "coverage_window": "2026-10-01 through 2026-10-07 only" if month == "2026-10" else "calendar month in inherited provisional scope",
                    "month_specific_file_occurrences": len(exact),
                    "quarter_or_window_file_references": len(quarter_scoped),
                    "all_source_file_references": len(files),
                    "source_branch_count": len({r["source_ref"] for r in files}),
                    "source_refs": ";".join(sorted({r["source_ref"] for r in files})),
                    "unit_artifact_manifest_sha256": manifest_digest,
                    "status_file_observations": len(statuses),
                    "status_values_seen": ";".join(sorted({str(s["status"]) for s in statuses if s["status"]})),
                    "firstpass_values_seen": ";".join(sorted({str(s["firstpass_complete"]).lower() for s in statuses if s["firstpass_complete"] != ""})),
                    "official_approval_values_seen": ";".join(sorted({str(s["official_approved"]).lower() for s in statuses if s["official_approved"] != ""})),
                    "explicit_unit_facts": json.dumps(sorted({f["fact"] + "=" + f["value"] for f in row_facts}), ensure_ascii=False, separators=(",", ":")),
                    "q4_integrity_hold": q4_hold,
                    "quarter_recovery_status": recovery_map[quarter]["recovery_status"],
                    "quarter_specific_remote_ref": recovery_map[quarter]["quarter_specific_remote_ref"],
                    "public_snapshot_observation": observation,
                    "work_status_if_no_file": "unknown; absence from a safety-filtered public snapshot does not show that research was not done",
                })

    # Produce a compact, separately traceable record for every mapped source file.
    evidence_rows = sorted(evidence, key=lambda r: (r["quarter"], r["unit_id"], r["source_ref"], r["source_path"], r["artifact_scope"]))
    write_csv(OUT / "country_month_inventory.csv", country_months)
    write_csv(OUT / "unit_evidence_manifest.csv", evidence_rows)
    write_csv(OUT / "unit_status_observations.csv", status_observations)
    write_csv(OUT / "unit_review_facts.csv", sorted(review_facts, key=lambda r: (r["quarter"], r["unit_id"], r["fact"])))
    write_csv(OUT / "unmapped_unit_files.csv", sorted(unmapped, key=lambda r: (r["month"], r["source_ref"], r["source_path"])))

    # Preserve duplicate evidence references as a review queue. No files are
    # deleted or selected away; the archive remains byte-for-byte by branch.
    dup_groups = defaultdict(list)
    for row in evidence_rows:
        if row["artifact_scope"] == "country-quarter":
            continue
        dup_groups[(row["unit_id"], row["sha256"])].append(row)
    duplicate_rows = []
    for (unit_id, digest), members in sorted(dup_groups.items()):
        distinct_paths = {(m["source_ref"], m["source_path"]) for m in members}
        if len(distinct_paths) > 1:
            for m in members:
                duplicate_rows.append({
                    "unit_id": unit_id,
                    "sha256": digest,
                    "duplicate_path_count": len(distinct_paths),
                    "source_ref": m["source_ref"],
                    "source_path": m["source_path"],
                    "bytes": m["bytes"],
                    "handling": "preserved; grouped by exact content hash; no original removed",
                })
    write_csv(OUT / "duplicate_evidence_references.csv", duplicate_rows)

    # Quarter report metrics and their exact provenance. Reported aggregates are
    # intentionally not projected onto individual units unless the saved
    # report supplied exact IDs.
    report_rows = []
    def add_quarter_report(quarter, ref, path, metrics, limit):
        p = SOURCES / ref.removeprefix("origin/") / path
        report_rows.append({
            "quarter": quarter,
            "source_ref": ref,
            "source_head": branch_by_ref[ref]["source_head"],
            "source_path": p.relative_to(ROOT).as_posix(),
            "source_sha256": sha256_file(p),
            **metrics,
            "interpretation_limit": limit,
        })

    add_quarter_report("2023Q1", "origin/saved-progress/2023Q1-20261012", "PROGRESS.json", {
        "reported_expected_units": 480, "reported_materialized_units": 184, "reported_dossiers": 184,
        "reported_partial_units": 47, "reported_current_hash_reviews": 166, "reported_bounded_accepted_units": "",
        "reported_official_complete_units": 0, "reported_missing_material_units": 296,
        "reported_missing_directories": "", "reported_formal_pending_units": "",
        "status_file_observations": 164, "status_firstpass_true_observations": 37,
        "status_not_started_observations": 84,
    }, "Snapshot aggregate and subset of status files; private local checkpoint/history is absent; first pass is not official acceptance.")
    add_quarter_report("2020Q4", "origin/saved-progress/2020Q4-20261012", "PROGRESS.json", {
        "reported_expected_units": 480, "reported_materialized_units": 181, "reported_dossiers": 172,
        "reported_partial_units": 3, "reported_current_hash_reviews": 90, "reported_bounded_accepted_units": 22,
        "reported_official_complete_units": 0, "reported_missing_material_units": 299,
        "reported_missing_directories": "", "reported_formal_pending_units": "",
        "notes_or_evidence_only_units": 6, "multiple_manifests": 94, "unparseable_input_json": 18,
        "safe_files": 3066, "private_files_not_in_public_selection": 15917,
    }, "Counts are copied from an existing checkpoint; no scientific re-review. The safe manifest cannot prove missing local work and the private archive bytes are unavailable.")
    add_quarter_report("2022Q1", "origin/saved-progress/2022Q1-20261012", "PROGRESS.json", {
        "reported_expected_units": 480, "reported_materialized_units": 404, "reported_dossiers": 404,
        "reported_partial_units": 0, "reported_current_hash_reviews": 171, "reported_bounded_accepted_units": 48,
        "reported_official_complete_units": 0, "reported_missing_material_units": 76,
        "reported_missing_directories": "", "reported_formal_pending_units": "",
        "intact_reviewed_snapshot_units": 241, "review_receipts": 369,
        "unique_review_receipt_units": 304, "safe_files": 2975,
    }, "Checkpoint manifest recount for the saved safe selection only; 76 are without observed work in that selected snapshot. Current-hash receipts do not imply fresh scientific review; private archive omitted.")
    add_quarter_report("2023Q2", "origin/saved-progress/2023Q2-20261012", "PROGRESS.json", {
        "reported_expected_units": 480, "reported_materialized_units": 156, "reported_dossiers": 151,
        "reported_partial_units": 5, "reported_current_hash_reviews": 142, "reported_bounded_accepted_units": 107,
        "reported_official_complete_units": 0, "reported_missing_material_units": 324,
        "reported_missing_directories": "", "reported_formal_pending_units": "",
        "status_file_observations": 33, "status_firstpass_true_observations": 18,
        "status_not_started_observations": 15,
    }, "Acceptance/review aggregates are not allocated to IDs in this saved summary; 33 status files are a subset; no official completion.")
    add_quarter_report("2024Q2", "origin/saved-progress/2024Q2-20261012", "PROGRESS.json", {
        "reported_expected_units": 480, "reported_materialized_units": 207, "reported_dossiers": 174,
        "reported_partial_units": 33, "reported_current_hash_reviews": 101, "reported_bounded_accepted_units": "",
        "reported_official_complete_units": 0, "reported_missing_material_units": 273,
        "reported_missing_directories": 273, "reported_formal_pending_units": "",
        "full_hash_verified_reviews": 92, "safe_files": 1338, "omitted_files": 9146,
    }, "Public safe selection only. Full private evidence/ZIP and source/search ledgers are unavailable; aggregate review IDs are not allocated here.")
    add_quarter_report("2024Q3", "origin/saved-progress/2024Q3-20261012", "UNIT_PROGRESS.json", {
        "reported_expected_units": 480, "reported_materialized_units": 246, "reported_dossiers": 231,
        "reported_partial_units": 15, "reported_current_hash_reviews": 210, "reported_bounded_accepted_units": 36,
        "reported_official_complete_units": 0, "reported_missing_material_units": 234,
        "reported_missing_directories": "", "reported_formal_pending_units": "",
        "safe_files": 10,
    }, "Unit ID lists are present for delivered/partial/review/bounded accepted/missing categories; safe export has no private full evidence.")
    add_quarter_report("2024Q4", "origin/saved-progress/2024Q4-20261012", "INVENTORY.json", {
        "reported_expected_units": 480, "reported_materialized_units": 333, "reported_dossiers": 327,
        "reported_partial_units": 6, "reported_current_hash_reviews": 321, "reported_bounded_accepted_units": 62,
        "reported_official_complete_units": 0, "reported_missing_material_units": 153,
        "reported_missing_directories": 144, "reported_formal_pending_units": "",
        "status_file_observations": 91, "status_firstpass_true_observations": 63,
        "status_not_started_observations": 0,
    }, "Saved inventory has exact per-unit selected-generation flags; raw/search/review receipt/archive files were omitted; 28 JSONL lines were unparseable.")
    add_quarter_report("2025Q1", "origin/saved-progress/2025Q1-20261012", "closeout/2025Q1/INVENTORY.json", {
        "reported_expected_units": 480, "reported_materialized_units": 396, "reported_dossiers": 378,
        "reported_partial_units": 18, "reported_current_hash_reviews": 146, "reported_bounded_accepted_units": 146,
        "reported_official_complete_units": 0, "reported_missing_material_units": 84,
        "reported_missing_directories": 48, "reported_formal_pending_units": "",
        "units_with_multiple_generations": 357, "excluded_prior_or_reserved": 36,
    }, "The saved inventory selected a generation by a filesystem heuristic. Current-hash acceptance receipts are not official approval or scientific re-review.")
    ref = "origin/saved-progress/2025Q3-20261012"
    q3_2025 = read_json(SOURCES / "saved-progress/2025Q3-20261012/PROGRESS.json")
    for unit_id in q3_2025.get("partial_ids", []):
        fact(ref, "PROGRESS.json", unit_id, "partial_evidence_only", "true")
    for unit_id in q3_2025.get("historical_receipt_hash_mismatch_units", []):
        fact(ref, "PROGRESS.json", unit_id, "historical_receipt_hash_mismatch", "true")
    ref = "origin/saved-progress/2024Q2-20261012"
    q2_2024 = read_json(SOURCES / "saved-progress/2024Q2-20261012/PROGRESS.json")
    for unit_id in q2_2024.get("missing_unit_ids", []):
        fact(ref, "PROGRESS.json", unit_id, "unit_files_missing_in_public_safe_selection", "true")
    ref = "origin/closeout/2026Q2-3ff07fabd46f"
    for month in months_by_quarter["2026Q2"]:
        for slug in country_slugs:
            unit_id = f"{slug}_{month}"
            fact(ref, "quarter-closeouts/2026Q2/20261011T094026762770Z/HANDOFF.md", unit_id, "formal_acceptance_pending", "true", "handoff explicitly applies to all 480 Apr-Jun country-month units")
            fact(ref, "quarter-closeouts/2026Q2/20261011T094026762770Z/HANDOFF.md", unit_id, "canonical_validation_complete", "false", "handoff explicitly says canonical validation is zero")
    add_quarter_report("2025Q3", "origin/saved-progress/2025Q3-20261012", "PROGRESS.json", {
        "reported_expected_units": 480, "reported_materialized_units": 441, "reported_dossiers": 441,
        "reported_partial_units": 3, "reported_current_hash_reviews": 219, "reported_bounded_accepted_units": "",
        "reported_official_complete_units": 0, "reported_missing_material_units": 39,
        "reported_missing_directories": "", "reported_formal_pending_units": "",
        "verified_provisional_candidates": 169, "pending_coverage": 136, "pending_sources": 107,
        "historical_receipt_hash_mismatch_units": 3, "excluded_prior_or_reserved": 36,
        "safe_files": 1280,
    }, "No new research, review, consolidation, or official approval was performed for publication; candidate count is not acceptance; partial and mismatch IDs are exact in this report.")
    add_quarter_report("2026Q2", "origin/closeout/2026Q2-3ff07fabd46f", "quarter-closeouts/2026Q2/20261011T094026762770Z/HANDOFF.md", {
        "reported_expected_units": 480, "reported_materialized_units": 480, "reported_dossiers": "",
        "reported_partial_units": "", "reported_current_hash_reviews": "", "reported_bounded_accepted_units": "",
        "reported_official_complete_units": 0, "reported_missing_material_units": 0,
        "reported_missing_directories": 0, "reported_formal_pending_units": 480,
        "country_quarter_packages": 160, "canonical_validated_units": 0,
    }, "Handoff says 160 country packages cover Apr-Jun (480 country-month scope); package evidence is quarter scoped. All units await formal acceptance; kit transfer blocked.")
    add_quarter_report("2026Q3", "origin/saved-progress/2026Q3-20261012", "PROGRESS.json", {
        "reported_expected_units": 480, "reported_materialized_units": 60, "reported_dossiers": 48,
        "reported_partial_units": 12, "reported_current_hash_reviews": 30, "reported_bounded_accepted_units": 15,
        "reported_official_complete_units": 0, "reported_missing_material_units": 420,
        "reported_missing_directories": "", "reported_formal_pending_units": "",
        "verified_provisional_candidates": 19,
        "status_file_observations": 27, "status_not_started_observations": 27,
    }, "Per-unit arrays identify delivered/partial/review/bounded sets; 27 not_started status files are not exhaustive and conflict with later aggregate counts unless versioned.")
    add_quarter_report("2026Q4", "origin/codex/closure-2026Q4-20261012", "quarter-staging/2026Q4/local-closure-20261011T094114675567Z/discovery-staging-index.json", {
        "reported_expected_units": 160, "reported_materialized_units": 160, "reported_dossiers": "",
        "reported_partial_units": "", "reported_current_hash_reviews": "", "reported_bounded_accepted_units": "",
        "reported_official_complete_units": 0, "reported_missing_material_units": 0,
        "reported_missing_directories": 0, "reported_formal_pending_units": 160,
        "indexed_primary_notes": 160, "integrity_hold_units": 3, "unrecoverable_predecessor_note_versions": 2,
    }, "Only Oct 1-7 is in scope; indexed notes are noncanonical discovery, zero first passes and no canonical integration; held units and unrecoverable predecessor versions remain unresolved.")
    write_csv(OUT / "quarter_reported_metrics.csv", report_rows)

    # Annual reports are broad scope checkpoints and cannot be distributed to
    # quarter rows without unit IDs.
    annual_rows = []
    annual_refs = [
        ("2020", "origin/saved-progress/2020-20261011", 0, "Twelve Apr-Jun dossiers remain partial and unreviewed."),
        ("2021", "origin/saved-progress/2021-20261011", 279, "Reported scoped reviews do not equal official approvals; year snapshot records zero official approvals."),
        ("2022", "origin/saved-progress/2022-20261011", 40, "Annual snapshot only; 2022Q4 six-unit closure is not currently in the remote source archive."),
        ("2023", "origin/saved-progress/2023-20261011", 56, "Annual aggregate cannot be allocated across quarters from this file."),
        ("2024", "origin/saved-progress/2024-20261011", 36, "Annual aggregate cannot be allocated across quarters from this file."),
        ("2025", "origin/saved-progress/2025-20261011", 30, "Annual aggregate cannot be allocated across quarters from this file."),
        ("2026", "origin/saved-progress/2026-20261011", 28, "Jan-Oct 7 partial scope; annual count cannot be allocated across quarters."),
    ]
    for year, ref, count, note in annual_refs:
        p = "PROGRESS.json"
        d = read_json(SOURCES / ref.removeprefix("origin/") / p)
        full = d.get("committed_first_pass_units", count)
        annual_rows.append({
            "year": year,
            "source_ref": ref,
            "source_head": branch_by_ref[ref]["source_head"],
            "source_path": (SOURCES / ref.removeprefix("origin/") / p).relative_to(ROOT).as_posix(),
            "source_sha256": sha256_file(SOURCES / ref.removeprefix("origin/") / p),
            "reported_year_scope_units": d.get("provisional_year_scope", ""),
            "reported_committed_first_pass_units": full,
            "reported_official_approvals": d.get("official_approvals", ""),
            "cutoff": d.get("cutoff", ""),
            "export_status": d.get("export_status", ""),
            "boundary": note + " " + d.get("boundary", ""),
        })
    write_csv(OUT / "annual_scope_summary.csv", annual_rows)

    # Every quarter in the prescribed universe gets one reproducible denominator
    # row; explicit reports stay independent fields above.
    metrics_by_quarter = {r["quarter"]: r for r in report_rows}
    closure_map = {}
    with (ROOT / "integration" / "DECLARED_CLOSURES.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            closure_map[row["scope"]] = row
    month_rows_by_q = defaultdict(list)
    for row in country_months:
        month_rows_by_q[row["quarter"]].append(row)
    quarter_rows = []
    for y, q in quarters:
        name = f"{y}Q{q}"
        rows = month_rows_by_q[name]
        exact_with_files = sum(int(r["month_specific_file_occurrences"]) > 0 for r in rows)
        quarter_refs = sum(int(r["quarter_or_window_file_references"]) > 0 for r in rows)
        status_ids = {r["unit_id"] for r in status_observations if r["quarter"] == name}
        not_started = {r["unit_id"] for r in status_observations if r["quarter"] == name and r["status"] == "not_started"}
        m = metrics_by_quarter.get(name, {})
        closure = closure_map.get(name, {})
        recovery = recovery_map.get(name, {})
        quarter_rows.append({
            "quarter": name,
            "in_scope_units": len(rows),
            "months_in_inventory": ";".join(months_by_quarter[name]),
            "country_months_with_month_specific_files": exact_with_files,
            "country_months_with_quarter_or_window_references": quarter_refs,
                "country_months_with_no_source_file_under_unit_directory": len(rows) - exact_with_files,
            "status_json_unit_ids_observed": len(status_ids),
            "status_json_unit_ids_not_started_in_a_snapshot": len(not_started),
            "reported_dossiers_or_notes": m.get("reported_dossiers", ""),
            "reported_partial_units": m.get("reported_partial_units", ""),
            "reported_current_hash_reviews": m.get("reported_current_hash_reviews", ""),
            "reported_bounded_accepted_units": m.get("reported_bounded_accepted_units", ""),
            "reported_official_complete_units": m.get("reported_official_complete_units", ""),
            "reported_missing_material_units": m.get("reported_missing_material_units", ""),
            "reported_formal_pending_units": m.get("reported_formal_pending_units", ""),
            "quarter_report_ref": m.get("source_ref", ""),
            "quarter_report_path": m.get("source_path", ""),
            "reported_metrics_limit": m.get("interpretation_limit", "No fetched quarter-specific status report; annual snapshot aggregates are not allocated here."),
            "declared_closure_commit": closure.get("declared_commit", ""),
            "exact_declared_commit_available": closure.get("exact_commit_object_available", "not reported"),
            "recovery_or_source_limit": closure.get("coverage_and_limit", "No quarter-specific safe closeout branch in fetched remote refs; see annual snapshots and file evidence."),
            "recovery_status_as_of_2026_10_12": recovery.get("recovery_status", "not recorded"),
            "quarter_specific_remote_ref": recovery.get("quarter_specific_remote_ref", ""),
            "reported_local_candidate_commit_not_integrated": recovery.get("reported_local_candidate_commit", ""),
            "recovery_notes": recovery.get("known_pending_or_limit", ""),
        })
    write_csv(OUT / "quarter_inventory_summary.csv", quarter_rows)

    meta = {
        "inventory_range": "2020Q2-2026Q4",
        "provisional_country_universe": 160,
        "country_month_rows": len(country_months),
        "quarter_rows": len(quarter_rows),
        "full_quarters": sum(1 for r in quarter_rows if r["in_scope_units"] == 480),
        "partial_2026Q4_unit_rows": sum(r["in_scope_units"] for r in quarter_rows if r["quarter"] == "2026Q4"),
        "evidence_manifest_rows": len(evidence_rows),
        "unit_status_observations": len(status_observations),
        "unit_review_facts": len(review_facts),
        "duplicate_reference_rows": len(duplicate_rows),
        "unmapped_unit_file_rows": len(unmapped),
        "limitations": [
            "The 160-country universe is the inherited provisional list; its source CSV says it must be checked against the official current universe.",
            "Safety-filtered public exports omit private files, raw/search ledgers, and some evidence; no public file observed is not proof of no research.",
            "First pass, a current-hash review, bounded acceptance, and official completion are distinct states.",
            "No quarter aggregate has been projected onto units unless the preserved report supplied exact unit IDs.",
            "All duplicate files and generations remain in their archived source-branch trees; the duplicate index groups by content hash without removing originals.",
            "2026Q4 includes only 2026-10-01 through 2026-10-07 and 160 country-month IDs.",
        ],
    }
    (OUT / "INVENTORY_BUILD.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
