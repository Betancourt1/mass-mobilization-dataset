#!/usr/bin/env python3
"""Verify preserved branch trees, source manifests, and inventory dimensions."""
import csv
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "integration" / "inventory"


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def git_optional(*args):
    result = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def verify_manifest(manifest_path, base, path_key, size_key="bytes"):
    data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    files = data.get("files", [])
    verified = 0
    for entry in files:
        rel = entry.get(path_key)
        if not rel:
            raise ValueError(f"missing {path_key} in {manifest_path}")
        candidate = (base / rel).resolve()
        if not candidate.is_relative_to(base.resolve()):
            raise ValueError(f"path escapes manifest root: {manifest_path}: {rel}")
        if not candidate.is_file():
            raise ValueError(f"missing manifest file: {manifest_path}: {rel}")
        if entry.get("sha256") != sha(candidate):
            raise ValueError(f"SHA256 mismatch: {manifest_path}: {rel}")
        if entry.get(size_key) != candidate.stat().st_size:
            raise ValueError(f"byte-size mismatch: {manifest_path}: {rel}")
        verified += 1
    return verified


def main():
    branches = list(csv.DictReader((ROOT / "integration/BRANCH_REGISTER.csv").open(encoding="utf-8")))
    if not branches:
        raise SystemExit("empty branch register")
    retirement_path = ROOT / "integration/REMOTE_BRANCH_RETIREMENT.csv"
    retirements = {
        row["remote_ref"]: row
        for row in csv.DictReader(retirement_path.open(encoding="utf-8"))
    } if retirement_path.exists() else {}
    branch_results = []
    for row in branches:
        ref = row["source_ref"]
        source_head = row["source_head"]
        archive = row["archive_path"].rstrip("/")
        source_tree = row["source_tree"]
        archived_tree = git("rev-parse", f"HEAD:{archive}")
        source_commit_type = git_optional("cat-file", "-t", source_head)
        source_commit_tree = git_optional("rev-parse", f"{source_head}^{{tree}}")
        reachable = subprocess.run(
            ["git", "merge-base", "--is-ancestor", source_head, "HEAD"], cwd=ROOT
        ).returncode == 0
        tracked_head = git_optional("rev-parse", "--verify", "--quiet", ref)
        remote_ref_matches = tracked_head is None or tracked_head == source_head
        remote_ref_name = f"refs/heads/{ref.removeprefix('origin/')}"
        retirement = retirements.get(remote_ref_name)
        if tracked_head is None:
            retired_and_verified = bool(
                retirement
                and retirement.get("remote_absence_verified") == "true"
                and retirement.get("retirement_status") == "remote_ref_deleted_and_absence_verified"
                and retirement.get("source_head") == source_head
                and retirement.get("source_tree") == source_tree
            )
        else:
            retired_and_verified = True
        if (
            source_commit_type != "commit"
            or source_commit_tree != source_tree
            or archived_tree != source_tree
            or not reachable
            or not remote_ref_matches
            or not retired_and_verified
        ):
            raise SystemExit(
                f"branch preservation mismatch: {ref}; source_commit={source_commit_type}, "
                f"source_tree={source_commit_tree}, registered_tree={source_tree}, "
                f"archived_tree={archived_tree}, reachable={reachable}, "
                f"tracked_ref_matches={remote_ref_matches}, retirement_receipt={retired_and_verified}"
            )
        branch_root = ROOT / archive
        branch_manifest_count = 0
        pub = branch_root / "PUBLICATION_MANIFEST.json"
        if pub.exists():
            count = verify_manifest(pub, branch_root, "path")
            branch_manifest_count += count
        for manifest_name, key in [
            ("CLOSEOUT_COPY_MANIFEST.json", "path"),
            ("LOCAL_CLOSURE_MANIFEST.json", "source_relative_path"),
            ("STAGING_SHA256_MANIFEST.json", "relative_path"),
        ]:
            for manifest in branch_root.rglob(manifest_name):
                branch_manifest_count += verify_manifest(manifest, manifest.parent, key)
        branch_results.append({
            "source_ref": ref,
            "source_head": row["source_head"],
            "source_tree": source_tree,
            "archived_tree": archived_tree,
            "source_head_is_ancestor": reachable,
            "remote_tracking_ref_present": tracked_head is not None,
            "remote_tracking_ref_matches_registered_head": remote_ref_matches,
            "remote_ref_retirement_verified": retired_and_verified,
            "verified_manifest_file_entries": branch_manifest_count,
        })

    inventory = json.loads((OUT / "INVENTORY_BUILD.json").read_text(encoding="utf-8"))
    with (OUT / "country_month_inventory.csv").open(encoding="utf-8") as f:
        country_rows = list(csv.DictReader(f))
    with (OUT / "quarter_inventory_summary.csv").open(encoding="utf-8") as f:
        quarter_rows = list(csv.DictReader(f))
    with (OUT / "unit_evidence_manifest.csv").open(encoding="utf-8") as f:
        evidence_records = list(csv.DictReader(f))
    evidence_rows = len(evidence_records)
    with (ROOT / "integration" / "QUARTER_RECOVERY_STATUS.csv").open(encoding="utf-8") as f:
        recovery_rows = list(csv.DictReader(f))
    recovery_by_quarter = {r["quarter"]: r for r in recovery_rows}
    if len(country_rows) != 12640 or len(quarter_rows) != 27 or evidence_rows != inventory["evidence_manifest_rows"]:
        raise SystemExit(f"inventory dimensions mismatch: {len(country_rows)} / {len(quarter_rows)} / {evidence_rows}")
    if len(recovery_rows) != 27 or len(recovery_by_quarter) != 27:
        raise SystemExit(f"recovery table dimensions mismatch: {len(recovery_rows)}")
    if sum(1 for r in recovery_rows if r["quarter_specific_remote_ref"]) != 12:
        raise SystemExit("expected 12 quarter-specific refs in the recovery register")
    if sum(1 for r in recovery_rows if r["exact_declared_commit_object_available"] == "true") != 2:
        raise SystemExit("declared exact closure commit count mismatch")
    for row in country_rows:
        recovery = recovery_by_quarter.get(row["quarter"])
        if not recovery or row["quarter_recovery_status"] != recovery["recovery_status"] or row["quarter_specific_remote_ref"] != recovery["quarter_specific_remote_ref"]:
            raise SystemExit(f"country-month recovery mapping mismatch: {row['unit_id']}")
    for row in evidence_records:
        source = ROOT / row["source_path"]
        if not source.is_file() or source.stat().st_size != int(row["bytes"]) or sha(source) != row["sha256"]:
            raise SystemExit(f"evidence manifest file/hash mismatch: {row['source_path']}")
    if sum(1 for r in country_rows if r["quarter"] == "2026Q4") != 160:
        raise SystemExit("2026Q4 denominator mismatch")
    if any(sum(1 for r in country_rows if r["quarter"] == q) != n for q, n in [(q, 480) for q in recovery_by_quarter if q != "2026Q4"]):
        raise SystemExit("full-quarter country-month denominator mismatch")
    if any(r["quarter"] == "2026Q4" and r["coverage_window"] != "2026-10-01 through 2026-10-07 only" for r in country_rows):
        raise SystemExit("2026Q4 window mismatch")

    result = {
        "branch_refs_registered": len(branches),
        "branch_heads_and_archived_trees_verified": len(branch_results),
        "manifest_file_entries_verified": sum(r["verified_manifest_file_entries"] for r in branch_results),
        "country_month_rows_verified": len(country_rows),
        "quarter_rows_verified": len(quarter_rows),
        "source_evidence_manifest_rows_verified": evidence_rows,
        "branch_results": branch_results,
    }
    target = OUT / "INTEGRATION_VERIFICATION.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "branch_results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
