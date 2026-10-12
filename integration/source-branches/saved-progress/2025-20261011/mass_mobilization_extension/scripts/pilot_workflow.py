#!/usr/bin/env python3
"""Small deterministic preflight, inventory, checkpoint, and pilot telemetry helpers."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import html.parser
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
from typing import Any

FINISHED = {"researched_open_web_pending_review", "root_reviewed_open_gaps"}
MONTHS = ("2022-01", "2022-02", "2022-03")
PILOT_COUNTRIES = ("Dominican Republic", "Ecuador", "Egypt", "El Salvador")
REQUIRED_EVENT = ("candidate_id", "country", "unit_month", "title", "start_date",
                  "start_precision", "end_date", "end_precision", "source_ids",
                  "field_evidence", "eligibility", "coding_status", "open_questions")
SOURCE_LIKE = {"alias_of", "redirected_from_url", "redirected_to_url", "history",
               "access_history", "source_history", "prior_sources", "source_aliases"}
LONG_CAPTURE_ALIASES = {"first_response_text", "native_header", "discovery_title"}
EXPORT_SUFFIXES = {".json", ".jsonl", ".csv", ".html", ".htm"}


def _research_module():
    path = pathlib.Path(__file__).with_name("research.py")
    spec = importlib.util.spec_from_file_location("mass_mobilization_research", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _json(path: pathlib.Path, default=None):
    if path is None:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _jsonl(path: pathlib.Path) -> list[Any]:
    # JSON text can contain U+2028/U+2029. Only LF is a physical JSONL boundary.
    return _parse_jsonl_bytes(path.read_bytes())


def _parse_jsonl_bytes(raw: bytes) -> list[Any]:
    return [json.loads(line.decode("utf-8")) for line in raw.split(b"\n")
            if line.strip()]


def export_preflight(path: pathlib.Path) -> dict[str, Any]:
    """Read-only scan common structured export formats for aliases/history; never rewrites."""
    path = pathlib.Path(path)
    issues, scanned = [], 0
    if path.is_file():
        candidates = [path]
    elif path.is_dir():
        for current, directories, _ in os.walk(path, followlinks=False):
            for name in directories:
                if (pathlib.Path(current) / name).is_symlink():
                    issues.append({"path": str(pathlib.Path(current) / name), "type": "symlink_refused"})
        candidates = sorted(file for file in path.rglob("*") if file.is_file())
    else:
        candidates = []

    def field_issue(candidate, field):
        normalized = str(field).casefold().replace("-", "_").replace(" ", "_")
        if (normalized in SOURCE_LIKE or ("source" in normalized and
                any(token in normalized for token in ("alias", "history", "redirect"))) or
                normalized in LONG_CAPTURE_ALIASES or
                (len(normalized) > 48 and any(token in normalized
                                              for token in ("source", "origin", "alias", "history")))):
            issues.append({"path": str(candidate), "field": str(field),
                           "type": "review_required_source_like_field"})

    def visit(node, candidate):
        if isinstance(node, dict):
            for key, child in node.items():
                field_issue(candidate, key)
                visit(child, candidate)
        elif isinstance(node, list):
            for child in node:
                visit(child, candidate)

    for candidate in candidates:
        if candidate.suffix.casefold() not in EXPORT_SUFFIXES:
            continue
        if candidate.is_symlink():
            issues.append({"path": str(candidate), "type": "symlink_refused"})
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
            suffix = candidate.suffix.casefold()
            if suffix == ".json":
                visit(json.loads(text), candidate)
            elif suffix == ".jsonl":
                for line_number, line in enumerate(text.split("\n"), 1):
                    if line.strip():
                        visit(json.loads(line), candidate)
            elif suffix == ".csv":
                reader = csv.DictReader(text.splitlines())
                for field in reader.fieldnames or []:
                    field_issue(candidate, field)
                for row in reader:
                    visit(row, candidate)
            else:
                parser = _ExportHTMLScanner(candidate, field_issue)
                parser.feed(text)
                parser.close()
        except (OSError, UnicodeError, json.JSONDecodeError, csv.Error, ValueError) as exc:
            issues.append({"path": str(candidate), "type": "unreadable_export", "detail": str(exc)})
            continue
        scanned += 1
    return {"ok": not issues, "review_required": bool(issues), "scanned_files": scanned,
            "supported_formats": sorted(EXPORT_SUFFIXES),
            "scan_scope": "review-required field-name scan only; no copyright determination or mutation",
            "issues": issues, "mutated": False}


class _ExportHTMLScanner(html.parser.HTMLParser):
    def __init__(self, path, issue_callback):
        super().__init__(convert_charrefs=True)
        self.path, self.issue_callback, self.in_header = path, issue_callback, False

    def handle_starttag(self, tag, attrs):
        self.in_header = tag.casefold() in {"th", "dt"}
        for key, value in attrs:
            self.issue_callback(self.path, key)
            if key.casefold() in {"name", "data-field", "data-column"} and value:
                self.issue_callback(self.path, value)

    def handle_data(self, data):
        if self.in_header:
            self.issue_callback(self.path, data.strip())

    def handle_endtag(self, tag):
        if tag.casefold() in {"th", "dt"}:
            self.in_header = False


def final_handoff_preflight(unit_dir: pathlib.Path, export_path: pathlib.Path | None = None) -> dict[str, Any]:
    unit_dir = pathlib.Path(unit_dir)
    validator = _research_module().validate_unit(unit_dir)
    issues = [{"type": "unit_validation", **item} for item in validator.get("issues", [])]
    status = _json(unit_dir / "status.json", {})
    if status.get("status") not in FINISHED:
        issues.append({"type": "completion_status", "file": "status.json",
                       "message": "status must be one of the accepted finished review states"})
    if not validator.get("valid"):
        pass
    events = _json(unit_dir / "events.json", [])
    if isinstance(events, list):
        for index, event in enumerate(events, 1):
            if isinstance(event, dict):
                for key in REQUIRED_EVENT:
                    if key not in event:
                        issues.append({"type": "missing_event_field", "file": f"events.json:{index}",
                                       "field": key})
    preflight = export_preflight(export_path or unit_dir / "events.json")
    return {"valid": not issues and preflight["ok"], "unit_dir": str(unit_dir),
            "validator": validator, "export_preflight": preflight, "issues": issues}


def _no_symlink_below(path: pathlib.Path, root: pathlib.Path) -> None:
    path, root = pathlib.Path(os.path.abspath(path)), pathlib.Path(os.path.abspath(root))
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path is outside declared root: {path}") from exc
    current = root
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            raise ValueError(f"symlink path refused: {current}")


def _load_registry(registry_path: pathlib.Path):
    registry_path = pathlib.Path(registry_path).absolute()
    if not registry_path.exists():
        raise FileNotFoundError(f"explicit draft registry is missing: {registry_path}")
    if registry_path.is_symlink():
        raise ValueError(f"symlink registry refused: {registry_path}")
    raw = registry_path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"draft registry is unreadable: {exc}") from exc
    if (not isinstance(value, dict) or value.get("schema_version") != 1 or
            value.get("complete") is not True):
        raise ValueError("draft registry must declare schema_version: 1 and complete: true")
    entries = value.get("drafts")
    if not isinstance(entries, list):
        raise ValueError("draft registry must contain a drafts array")
    return value, raw, registry_path


def _enumerate_root(root_id: str, physical_root: pathlib.Path, required: bool):
    if physical_root.is_symlink():
        raise ValueError(f"symlink physical root refused: {physical_root}")
    resolved_root = physical_root.resolve(strict=True)
    if not resolved_root.is_dir():
        raise ValueError(f"registered physical root is not a directory: {physical_root}")
    found = []
    for current, directories, files in os.walk(resolved_root, followlinks=False):
        for name in directories:
            path = pathlib.Path(current) / name
            if path.is_symlink():
                raise ValueError(f"symlink directory refused: {path}")
        for name in files:
            if name not in {"sources.jsonl", "source_checks.jsonl"}:
                continue
            path = pathlib.Path(current) / name
            if path.is_symlink():
                raise ValueError(f"symlink ledger refused: {path}")
            resolved = path.resolve(strict=True)
            if resolved_root not in resolved.parents:
                raise ValueError(f"ledger escapes declared root {root_id}: {path}")
            relative = path.relative_to(resolved_root).as_posix()
            if name == "source_checks.jsonl" and relative != "review/source_checks.jsonl":
                continue
            found.append((f"{root_id}/{relative}", path))
    if required and not any(path.name == "sources.jsonl" for _, path in found):
        raise FileNotFoundError(f"registered root has no sources.jsonl ledger: {root_id}")
    return found, resolved_root


def _inventory_ledgers(root_id: str, found):
    if root_id != "canonical":
        return list(found)
    return [(logical, path) for logical, path in found
            if (logical.endswith("review/source_checks.jsonl") or
                (logical.startswith("canonical/units/") and logical.endswith("sources.jsonl")))]


def _manifest_entry(path: pathlib.Path, root: pathlib.Path, root_id: str):
    candidate = path if path.is_absolute() else root / path
    _no_symlink_below(candidate, root)
    resolved = candidate.resolve(strict=True)
    if root.resolve() not in resolved.parents:
        raise ValueError(f"manifest escapes declared root {root_id}: {candidate}")
    if not resolved.is_file():
        raise ValueError(f"manifest is not a file: {candidate}")
    return f"@manifest:{root_id}/{resolved.relative_to(root.resolve()).as_posix()}", resolved.read_bytes(), resolved


def source_inventory(data_root: pathlib.Path, registry_path: pathlib.Path,
                     reviewed_hashes: dict[str, str] | None = None) -> dict[str, Any]:
    """Hash all current ledgers and preserve parsed rows, including denials and origin holds."""
    root = pathlib.Path(data_root).absolute()
    if not root.is_dir():
        raise FileNotFoundError(f"data root is missing: {root}")
    if root.is_symlink():
        raise ValueError(f"symlink data root refused: {root}")
    registry, registry_raw, registry_file = _load_registry(pathlib.Path(registry_path))
    ledger_paths: dict[str, pathlib.Path] = {}
    canonical_entries, canonical_root = _enumerate_root("canonical", root, required=False)
    root_specs = {"canonical": {"path": canonical_root, "required": False,
                                 "identity": (canonical_root.stat().st_dev, canonical_root.stat().st_ino)}}
    for logical, ledger in _inventory_ledgers("canonical", canonical_entries):
        ledger_paths[logical] = ledger
    if "canonical/review/source_checks.jsonl" not in ledger_paths:
        raise FileNotFoundError("required input is missing: canonical review/source_checks.jsonl")
    root_ids = {"canonical"}
    manifest_bytes = {"@registry": registry_raw}
    snapshot_files = {"@registry": registry_file}
    draft_roots = {}
    for draft in registry["drafts"]:
        if not isinstance(draft, dict):
            raise ValueError("draft registry entries must be objects")
        root_id, physical = draft.get("root_id"), draft.get("physical_path")
        if not isinstance(root_id, str) or not root_id or root_id in root_ids:
            raise ValueError("draft root_id values must be non-empty and unique")
        if not isinstance(physical, str) or not physical:
            raise ValueError(f"draft {root_id} must declare physical_path")
        root_ids.add(root_id)
        physical_root = pathlib.Path(physical)
        if not physical_root.is_absolute():
            physical_root = registry_file.parent / physical_root
        if physical_root.is_symlink():
            raise ValueError(f"symlink physical root refused: {physical_root}")
        draft_roots[root_id] = physical_root.resolve(strict=True)
    manifests = registry.get("manifests", [])
    if not isinstance(manifests, list):
        raise ValueError("draft registry manifests must be an array")
    for item in manifests:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise ValueError("manifest entries need a path")
        root_id = item.get("root_id", "canonical")
        if root_id == "canonical":
            declared_root = canonical_root
        else:
            declared_root = draft_roots.get(root_id)
            if declared_root is None:
                raise ValueError(f"manifest references unknown root_id: {root_id}")
        key, raw, manifest_file = _manifest_entry(pathlib.Path(item["path"]), declared_root, root_id)
        manifest_bytes[key] = raw
        snapshot_files[key] = manifest_file
    for draft in registry["drafts"]:
        root_id = draft["root_id"]
        entries, resolved_root = _enumerate_root(root_id, draft_roots[root_id], required=True)
        root_specs[root_id] = {"path": resolved_root, "required": True,
                               "identity": (resolved_root.stat().st_dev, resolved_root.stat().st_ino)}
        declared = draft.get("source_ledgers")
        actual_rel = sorted(path.relative_to(resolved_root).as_posix() for _, path in entries)
        if declared is not None:
            if not isinstance(declared, list) or sorted(declared) != actual_rel:
                raise ValueError(f"registered ledger manifest does not match physical files: {root_id}")
        for logical, ledger in _inventory_ledgers(root_id, entries):
            if logical in ledger_paths:
                raise ValueError(f"duplicate ledger identity: {logical}")
            ledger_paths[logical] = ledger
        manifest = draft.get("manifest_path")
        if manifest:
            key, raw, manifest_file = _manifest_entry(pathlib.Path(manifest), resolved_root, root_id)
            manifest_bytes[key] = raw
            snapshot_files[key] = manifest_file
    entries = []
    compare_to_reviewed = reviewed_hashes is not None
    reviewed_hashes = reviewed_hashes or {}
    current_bytes = dict(manifest_bytes)
    for logical, path in sorted(ledger_paths.items()):
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"inventory input is unreadable during scan: {logical}: {exc}") from exc
        digest = hashlib.sha256(raw).hexdigest()
        current_bytes[logical] = raw
        snapshot_files[logical] = path
        rows = _parse_jsonl_bytes(raw)
        entries.append({"path": logical, "sha256": digest, "bytes": len(raw), "rows": rows,
                        "manual_review_reused": False,
                        "access_authorized": False})
    for logical, path in snapshot_files.items():
        try:
            current = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"inventory input changed or became unreadable during scan: {logical}: {exc}") from exc
        if current != current_bytes[logical]:
            raise ValueError(f"inventory input changed during scan; rerun complete inventory: {logical}")
    current_paths = {}
    for root_id, spec in root_specs.items():
        found, resolved_root = _enumerate_root(root_id, spec["path"], required=spec["required"])
        identity = (resolved_root.stat().st_dev, resolved_root.stat().st_ino)
        if resolved_root != spec["path"] or identity != spec["identity"]:
            raise ValueError(f"inventory root identity changed during scan: {root_id}")
        for logical, path in _inventory_ledgers(root_id, found):
            if logical in current_paths:
                raise ValueError(f"duplicate ledger identity after re-enumeration: {logical}")
            current_paths[logical] = path
    if set(current_paths) != set(ledger_paths):
        added = sorted(set(current_paths) - set(ledger_paths))
        removed = sorted(set(ledger_paths) - set(current_paths))
        raise ValueError(f"inventory path set changed during scan; added={added}; removed={removed}")
    digest_map = {key: hashlib.sha256(raw).hexdigest() for key, raw in current_bytes.items()}
    added = sorted(set(digest_map) - set(reviewed_hashes)) if compare_to_reviewed else []
    changed = sorted(key for key in set(digest_map) & set(reviewed_hashes)
                     if digest_map[key] != reviewed_hashes[key]) if compare_to_reviewed else []
    removed = sorted(set(reviewed_hashes) - set(digest_map)) if compare_to_reviewed else []
    invalidated = bool(added or changed or removed)
    if compare_to_reviewed and not invalidated:
        for entry in entries:
            entry["manual_review_reused"] = reviewed_hashes.get(entry["path"]) == entry["sha256"]
    input_fingerprint = hashlib.sha256(json.dumps(digest_map, sort_keys=True).encode()).hexdigest()
    return {"inputs": entries, "hashes": digest_map, "input_fingerprint": input_fingerprint,
            "reviewed_hashes": {e["path"]: e["sha256"] for e in entries
                                if e["manual_review_reused"]},
            "added": added, "changed": changed, "removed": removed,
            "invalidated": invalidated,
            "preserves_all_rows": True, "stable": True, "grants_access": False,
            "automatic_retrieval_authorized": False,
            "note": "Each new target/action needs a fresh inventory digest and manual scope review."}


def derive_checkpoint(data_root: pathlib.Path, git_root: pathlib.Path | None = None) -> dict[str, Any]:
    """Derive progress from current plan/dossiers and the committed Git tree, never summaries."""
    root = pathlib.Path(data_root)
    plan_path = root / "planning/coverage_matrix.csv"
    with plan_path.open(encoding="utf-8-sig", newline="") as source:
        plan = list(csv.DictReader(source))
    actual = {}
    for assignment_path in sorted(root.glob("units/**/assignment.json")):
        if assignment_path.is_symlink():
            raise ValueError(f"symlink assignment refused: {assignment_path}")
        assignment = _json(assignment_path, {})
        if assignment.get("unit_id"):
            actual[assignment["unit_id"]] = _json(assignment_path.parent / "status.json", {}).get("status")
    git_root = pathlib.Path(git_root or root)
    committed = subprocess.run(["git", "-C", str(git_root), "ls-tree", "-r", "--name-only", "HEAD"],
                               check=True, capture_output=True, text=True).stdout.splitlines()
    committed_units = []
    committed_unit_file_count = 0
    for item in committed:
        parts = item.split("/")
        try:
            index = next(i for i, part in enumerate(parts)
                         if part == "units" and i > 0 and parts[i - 1] == "mass_mobilization_extension")
        except StopIteration:
            continue
        if len(parts) >= index + 4:
            committed_units.append("/".join(parts[index + 1:index + 3]))
            committed_unit_file_count += 1
    return {"planned_units": len(plan), "current_dossier_units": len(actual),
            "current_finished_units": sorted(k for k, v in actual.items() if v in FINISHED),
            "committed_unit_directories": sorted(set(committed_units)),
            "committed_unit_file_count": committed_unit_file_count,
            "source": "planning/coverage_matrix.csv, units/**/assignment.json and status.json, git ls-tree HEAD"}


def pilot_units() -> list[dict[str, str]]:
    result = []
    for country in PILOT_COUNTRIES:
        for month in MONTHS:
            result.append({"country": country, "month": month,
                           "quarter_context": "Q1-2022" if country in PILOT_COUNTRIES[:2] else "monthly",
                           "unit_id": f"{country.casefold().replace(' ', '_')}_{month}"})
    return result


def append_telemetry(path: pathlib.Path, phase: str, event: str = "start", at: str | None = None,
                     unit_id: str | None = None, details: dict | None = None) -> dict:
    timestamp = at or dt.datetime.now(dt.timezone.utc).isoformat()
    parsed = dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("telemetry timestamps must include a timezone")
    row = {"phase": phase, "event": event, "at_utc": parsed.astimezone(dt.timezone.utc).isoformat()}
    if unit_id:
        row["unit_id"] = unit_id
    if details:
        row["details"] = details
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as output:
        output.write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
    return row


def summarize_telemetry(path: pathlib.Path) -> dict[str, Any]:
    rows = _jsonl(path)
    starts, intervals, unmatched_ends, phases = {}, [], [], {}
    for row in rows:
        key = (row.get("phase"), row.get("unit_id"))
        when = dt.datetime.fromisoformat(row["at_utc"].replace("Z", "+00:00"))
        if when.tzinfo is None:
            raise ValueError("telemetry timestamps must include a timezone")
        when = when.astimezone(dt.timezone.utc)
        if row.get("event") == "start":
            if key in starts:
                raise ValueError(f"repeated ambiguous telemetry start for {key}")
            starts[key] = when
        elif row.get("event") == "end" and key in starts:
            started = starts.pop(key)
            if when < started:
                raise ValueError(f"reversed telemetry interval for {key}")
            seconds = (when - started).total_seconds()
            interval = {"phase": key[0], "unit_id": key[1], "start_utc": started.isoformat(),
                        "end_utc": when.isoformat(), "seconds": seconds}
            intervals.append(interval)
            phases.setdefault(key[0], []).append(interval)
        elif row.get("event") == "end":
            unmatched_ends.append({"phase": key[0], "unit_id": key[1], "at_utc": when.isoformat()})
    def union_seconds(items):
        ranges = sorted((dt.datetime.fromisoformat(item["start_utc"]),
                         dt.datetime.fromisoformat(item["end_utc"])) for item in items)
        if not ranges:
            return 0.0
        total, start, end = 0.0, *ranges[0]
        for next_start, next_end in ranges[1:]:
            if next_start > end:
                total += (end - start).total_seconds()
                start, end = next_start, next_end
            elif next_end > end:
                end = next_end
        return total + (end - start).total_seconds()
    def envelope(items):
        if not items:
            return {"wall_seconds": 0.0, "active_union_seconds": 0.0,
                    "start_utc": None, "end_utc": None}
        earliest = min(dt.datetime.fromisoformat(item["start_utc"]) for item in items)
        latest = max(dt.datetime.fromisoformat(item["end_utc"]) for item in items)
        return {"wall_seconds": (latest - earliest).total_seconds(),
                "active_union_seconds": union_seconds(items),
                "start_utc": earliest.isoformat(), "end_utc": latest.isoformat()}
    pilot = envelope(intervals)
    return {"intervals": intervals,
            "phase_summary": {name: {"interval_count": len(items), **envelope(items)}
                              for name, items in phases.items()},
            "unmatched_starts": [{"phase": k[0], "unit_id": k[1], "at_utc": value.isoformat()}
                                 for k, value in starts.items()],
            "unmatched_ends": unmatched_ends,
            "valid": not unmatched_ends and not starts,
            "pilot_summary": pilot,
            "duration_policy": "wall envelope and union-active intervals; concurrent durations are never summed"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    handoff = commands.add_parser("handoff-preflight")
    handoff.add_argument("unit_dir", type=pathlib.Path)
    handoff.add_argument("--export", type=pathlib.Path)
    inventory = commands.add_parser("inventory")
    inventory.add_argument("data_root", type=pathlib.Path)
    inventory.add_argument("--registry", required=True, type=pathlib.Path)
    inventory.add_argument("--reviewed-hashes", type=pathlib.Path)
    checkpoint = commands.add_parser("checkpoint")
    checkpoint.add_argument("data_root", type=pathlib.Path)
    checkpoint.add_argument("--git-root", type=pathlib.Path)
    commands.add_parser("pilot-units")
    for name in ("telemetry-start", "telemetry-end"):
        command = commands.add_parser(name)
        command.add_argument("path", type=pathlib.Path)
        command.add_argument("phase")
        command.add_argument("--unit-id")
    summary = commands.add_parser("telemetry-summary")
    summary.add_argument("path", type=pathlib.Path)
    args = parser.parse_args(argv)
    if args.command == "handoff-preflight":
        result = final_handoff_preflight(args.unit_dir, args.export)
    elif args.command == "inventory":
        result = source_inventory(args.data_root, args.registry, _json(args.reviewed_hashes, {}) or {})
    elif args.command == "checkpoint":
        result = derive_checkpoint(args.data_root, args.git_root)
    elif args.command == "pilot-units":
        result = {"units": pilot_units()}
    elif args.command.startswith("telemetry-") and args.command != "telemetry-summary":
        result = append_telemetry(args.path, args.phase,
                                  "start" if args.command.endswith("start") else "end",
                                  unit_id=args.unit_id)
    else:
        result = summarize_telemetry(args.path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("valid", result.get("ok", True)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
