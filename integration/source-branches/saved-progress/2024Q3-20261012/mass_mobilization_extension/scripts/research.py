#!/usr/bin/env python3
"""Persist captured research records and inspect a unit without approving it."""

import argparse
import collections
import datetime
import hashlib
import json
import os
import pathlib
import re
import stat
import tempfile
import urllib.parse


REQUIRED = {
    "assignment.json": dict,
    "status.json": dict,
    "events.json": list,
    "excluded.json": list,
    "continuations.json": list,
    "gaps.json": list,
    "search_log.jsonl": "jsonl",
    "sources.jsonl": "jsonl",
    "report.txt": "text",
}
ACCESS = {"opened", "search_only", "blocked", "not_found"}
PRECISION = {"day", "month", "year", "unknown"}
DATE_PRECISION_DEPTH = {"year": 1, "month": 2, "day": 3}
ELIGIBILITY = {"proposed_include", "pending_threshold", "pending_state_target", "pending_unit", "pending_evidence"}
VALUE = {"yes", "no_explicit", "unknown"}
RESPONSES = {"accommodation", "arrests", "beatings", "crowd_dispersal", "ignore", "killings", "shootings"}
DEMANDS = {"labor_wage_dispute", "land_farm_issue", "police_brutality", "political_behavior_process",
           "price_increases_tax_policy", "social_restrictions", "removal_of_politician"}
WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
         "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
ACCESS_INDEX_FORMAT = "mass-mobilization-source-access-index"
ACCESS_INDEX_VERSION = 1
ACCESS_URL_KEYS = {"url", "source_url", "source_urls", "target_url", "requested_url", "request_url"}
ACCESS_DENIAL_CODES = {401, 402, 403}
ACCESS_FAILURE_RE = re.compile(
    r"\b(cache\s+miss|dns\s+(?:failure|failed|error)|tls\s+(?:handshake\s+)?(?:timeout|failed|failure)|"
    r"timed?\s*out\s+before\s+(?:an?\s+)?http|no\s+http\s+(?:response|status)|"
    r"connection\s+(?:failed|refused|error))\b",
    re.IGNORECASE,
)
ACCESS_DENIAL_RE = re.compile(
    r"(?:\bhttp(?:\s+status(?:\s+code)?)?\s*[:=]?\s*(?:401|402|403)\b|"
    r"\breturned\s+(?:http\s+)?(?:401|402|403)\b|"
    r"\b401\s+unauthorized\b|\b402\s+payment\s+required\b|\b403\s+forbidden\b|"
    r"\bactual(?:ly)?\s+(?:http\s+)?(?:401|402|403)\b|"
    r"\bpaywall\b|\bsubscriber[- ]only\b|\bsubscriber\s+paywall\b|"
    r"\blog[- ]?in\s+required\b|\brequires?\s+(?:a\s+)?log[- ]?in\b|"
    r"\brobots?\s+restriction\b|\banti[- ]?bot\b|\bcaptcha\b)",
    re.IGNORECASE,
)
ACCESS_DENIAL_UNCERTAINTY_RE = re.compile(
    r"\b(?:no|not|without|may|might|could|maybe|possibly|possible|potentially|uncertain|unclear|"
    r"unconfirmed|unverified|alleged|hypothetical)\b(?:\s+\w+){0,5}\s*$",
    re.IGNORECASE,
)
ACCESS_DENIAL_NEGATED_SUFFIX_RE = re.compile(
    r"^\s*(?:(?:was|is|has\s+been)\s+)?(?:not|never|uncertain|unclear|unconfirmed|unverified)\b",
    re.IGNORECASE,
)
ACCESS_SOURCE_ID_CLAUSE_RE = re.compile(r"[;.!?\n]")
ACCESS_PROSE_KEYS = {
    "assessment", "basis", "classification", "error", "limitation", "limitations",
    "note", "read_scope", "reason", "result", "status_detail",
}
ACCESS_ORIGIN_ID_KEYS = {
    "same_story_variant_source_ids", "written_origin_source_ids",
    "written_origin_source_id", "original_source_id", "origin_source_id",
}
ACCESS_ORIGIN_URL_KEYS = {
    "written_origin_urls", "written_origin_url", "original_source_url",
    "written_story_url",
}


def json_line(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def strict_json_loads(value):
    def reject_constant(constant):
        raise ValueError(f"non-standard JSON constant: {constant}")

    return json.loads(value, parse_constant=reject_constant)


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2))


def atomic_write(path, data):
    path = pathlib.Path(path)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = pathlib.Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            os.chmod(temp, stat.S_IMODE(path.stat().st_mode))
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def parse_jsonl(data, name):
    records, chunks, errors = [], data.splitlines(keepends=True), []
    for number, chunk in enumerate(chunks, 1):
        line = chunk.rstrip(b"\r\n")
        if not line.strip():
            errors.append(f"{name}:{number}: blank JSONL line")
            continue
        try:
            record = strict_json_loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            errors.append(f"{name}:{number}: invalid JSONL record: {exc}")
            continue
        if not isinstance(record, dict):
            errors.append(f"{name}:{number}: record must be an object")
            continue
        records.append(record)
    return records, chunks, errors


def read_json(path, expected, issues):
    try:
        value = strict_json_loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        issues.append(f"{pathlib.Path(path).name}: cannot read JSON: {exc}")
        return None
    if not isinstance(value, expected):
        issues.append(f"{pathlib.Path(path).name}: expected {expected.__name__}")
        return None
    return value


def query_errors(record):
    errors = []
    if not isinstance(record, dict):
        return ["query capture must be a JSON object"]
    for key in ("query_id", "query", "tool"):
        if not isinstance(record.get(key), str) or not record[key].strip():
            errors.append(f"{key} must be a non-empty string")
    headers, urls = record.get("returned_results"), record.get("returned_urls")
    if not isinstance(headers, list):
        errors.append("returned_results must be an array of captured headers")
        headers = []
    if not isinstance(urls, list):
        errors.append("returned_urls must be an array from the same response")
        urls = []
    if len(headers) != len(urls):
        errors.append("returned_results and returned_urls lengths differ")
    for index, header in enumerate(headers):
        label = f"returned_results[{index}]"
        if not isinstance(header, dict):
            errors.append(f"{label} must be an object")
            continue
        url = header.get("url")
        if not isinstance(url, str) or not url:
            errors.append(f"{label}.url must be a captured non-empty URL")
        elif index < len(urls) and urls[index] != url:
            errors.append(f"returned_urls[{index}] does not align with {label}.url")
        if "order" in header and header["order"] != index + 1:
            errors.append(f"{label}.order does not match its one-based position")
        for key in ("title", "ref", "web_ref"):
            if key in header and header[key] is not None and not isinstance(header[key], str):
                errors.append(f"{label}.{key} must be a string or null")
    for key in ("executed_at", "response_captured_at"):
        if record.get(key) is not None and not isinstance(record[key], str):
            errors.append(f"{key} must be a string or null")
    return errors


def source_errors(source, label="source"):
    errors = []
    if not isinstance(source.get("source_id"), str) or not source["source_id"].strip():
        errors.append(f"{label}.source_id must be a non-empty string")
    if not isinstance(source.get("url"), str) or not source["url"].strip():
        errors.append(f"{label}.url must be a non-empty string")
    if source.get("title") is not None and not isinstance(source["title"], str):
        errors.append(f"{label}.title must be a string or null")
    if not isinstance(source.get("access_status"), str) or source["access_status"] not in ACCESS:
        errors.append(f"{label}.access_status is invalid")
    for key in ("publication_date", "accessed_at"):
        if source.get(key) is not None and not isinstance(source[key], str):
            errors.append(f"{label}.{key} must be a string or null")
    return errors


def capture_search(unit_dir, record_path):
    path = pathlib.Path(unit_dir) / "search_log.jsonl"
    try:
        record = strict_json_loads(pathlib.Path(record_path).read_text(encoding="utf-8"))
        old = path.read_bytes()
    except (OSError, UnicodeError, ValueError) as exc:
        return {"ok": False, "errors": [f"cannot read capture or search log: {exc}"]}
    queries, _, errors = parse_jsonl(old, path.name)
    errors.extend(query_errors(record))
    if isinstance(record, dict) and any(row.get("query_id") == record.get("query_id") for row in queries):
        errors.append(f"query_id already exists: {record.get('query_id')}")
    if errors:
        return {"ok": False, "errors": errors}
    separator = b"\n" if old and not old.endswith(b"\n") else b""
    atomic_write(path, old + separator + json_line(record).encode("utf-8") + b"\n")
    return {"ok": True, "query_id": record["query_id"], "headers_saved": len(record["returned_results"])}


def save_source(unit_dir, source_id, patch_path):
    path = pathlib.Path(unit_dir) / "sources.jsonl"
    try:
        patch = strict_json_loads(pathlib.Path(patch_path).read_text(encoding="utf-8"))
        raw = path.read_bytes()
    except (OSError, UnicodeError, ValueError) as exc:
        return {"ok": False, "errors": [f"cannot read source patch or sources.jsonl: {exc}"]}
    if not isinstance(patch, dict) or patch.get("source_id") != source_id:
        return {"ok": False, "errors": ["patch must be an object whose source_id exactly matches the requested ID"]}
    records, chunks, errors = parse_jsonl(raw, path.name)
    matches = [i for i, row in enumerate(records) if row.get("source_id") == source_id]
    ids = [row.get("source_id") for row in records]
    if len(matches) != 1:
        errors.append(f"source_id must match exactly one card; found {len(matches)}")
    string_ids = [value for value in ids if isinstance(value, str)]
    if len(string_ids) != len(set(string_ids)):
        errors.append("source_id values must be unique")
    if errors:
        return {"ok": False, "errors": errors}
    row = dict(records[matches[0]])
    row.update(patch)
    errors = source_errors(row, f"source {source_id}")
    if errors:
        return {"ok": False, "errors": errors}
    chunks[matches[0]] = (json_line(row) + "\n").encode("utf-8")
    atomic_write(path, b"".join(chunks))
    return {"ok": True, "source_id": source_id, "updated_fields": sorted(set(patch) - {"source_id"})}


def date_parts(value, precision):
    if not isinstance(precision, str) or precision not in PRECISION:
        return None, "invalid precision"
    if value is None:
        return (None, None) if precision == "unknown" else (None, "null date requires unknown precision")
    if not isinstance(value, str) or precision == "unknown":
        return None, "unknown date requires null; known dates must be strings"
    try:
        if precision == "day":
            parsed = datetime.date.fromisoformat(value)
            if parsed.isoformat() != value:
                raise ValueError
            return (parsed.year, parsed.month, parsed.day), None
        if precision == "month":
            parsed = datetime.date.fromisoformat(value + "-01")
            if parsed.strftime("%Y-%m") != value:
                raise ValueError
            return (parsed.year, parsed.month, 0), None
        if len(value) == 4 and value.isdigit() and 1 <= int(value) <= 9999:
            return (int(value), 0, 0), None
    except ValueError:
        pass
    return None, f"invalid ISO {precision} date"


def inspect_unit(unit_dir):
    unit_dir = pathlib.Path(unit_dir)
    issues, data = [], {}
    for name, kind in REQUIRED.items():
        path = unit_dir / name
        if not path.is_file():
            issues.append({"file": name, "message": "required file is missing"})
        elif kind == "jsonl":
            rows, _, errors = parse_jsonl(path.read_bytes(), name)
            data[name] = rows
            issues.extend({"file": name, "message": e} for e in errors)
        elif kind == "text":
            try:
                path.read_text(encoding="utf-8")
                data[name] = True
            except (OSError, UnicodeError) as exc:
                issues.append({"file": name, "message": f"cannot read text: {exc}"})
        else:
            errors = []
            data[name] = read_json(path, kind, errors)
            issues.extend({"file": name, "message": e} for e in errors)
    if any(name not in data for name in REQUIRED) or any(
        data.get(name) is None for name, kind in REQUIRED.items() if kind not in ("jsonl", "text")
    ):
        return {"valid": False, "unit_dir": str(unit_dir), "issues": issues}, data

    assignment, status = data["assignment.json"], data["status.json"]
    queries, sources = data["search_log.jsonl"], data["sources.jsonl"]
    events, excluded = data["events.json"], data["excluded.json"]
    continuations, gaps = data["continuations.json"], data["gaps.json"]
    unit_id, country, month = assignment.get("unit_id"), assignment.get("country"), assignment.get("month")
    if not isinstance(unit_id, str) or not unit_id:
        issues.append({"file": "assignment.json", "message": "unit_id must be a non-empty string"})
    if not isinstance(country, str) or not country:
        issues.append({"file": "assignment.json", "message": "country must be a non-empty string"})
    for field, expected in (("unit_id", unit_id), ("country", country), ("month", month)):
        if status.get(field) != expected:
            issues.append({"file": "status.json", "message": f"{field} does not match assignment.json"})
    try:
        parsed_month = datetime.date.fromisoformat(month + "-01") if isinstance(month, str) else None
        if parsed_month is None or parsed_month.strftime("%Y-%m") != month:
            raise ValueError
    except ValueError:
        issues.append({"file": "assignment.json", "message": "month must use YYYY-MM form"})

    query_ids = []
    header_count = 0
    for i, query in enumerate(queries, 1):
        qid = query.get("query_id")
        query_ids.append(qid)
        for message in query_errors(query):
            issues.append({"file": f"search_log.jsonl:{i}", "message": message})
        header_count += len(query.get("returned_results", [])) if isinstance(query.get("returned_results"), list) else 0
    query_ids = [value for value in query_ids if isinstance(value, str)]
    if len(query_ids) != len(set(query_ids)):
        issues.append({"file": "search_log.jsonl", "message": "query_id values must be unique"})

    source_ids = [source.get("source_id") for source in sources]
    source_ids = [value for value in source_ids if isinstance(value, str)]
    if len(source_ids) != len(set(source_ids)):
        issues.append({"file": "sources.jsonl", "message": "source_id values must be unique"})
    for i, source in enumerate(sources, 1):
        issues.extend({"file": f"sources.jsonl:{i}", "message": e} for e in source_errors(source))
    known_sources = set(source_ids)

    def check_refs(refs, where):
        if not isinstance(refs, list):
            issues.append({"file": where, "message": "source_ids must be an array"})
        else:
            for ref in refs:
                if not isinstance(ref, str):
                    issues.append({"file": where, "message": "source_id reference must be a string"})
                elif ref not in known_sources:
                    issues.append({"file": where, "message": f"unknown source_id {ref}"})

    candidate_ids = []
    for i, event in enumerate(events, 1):
        where = f"events.json:{i}"
        if not isinstance(event, dict):
            issues.append({"file": where, "message": "record must be an object"})
            continue
        required = ("candidate_id", "country", "unit_month", "title", "start_date", "start_precision",
                    "end_date", "end_precision", "source_ids", "field_evidence", "eligibility", "coding_status")
        for field in required:
            if field not in event:
                issues.append({"file": where, "message": f"missing {field}"})
        candidate_ids.append(event.get("candidate_id"))
        if not isinstance(event.get("candidate_id"), str) or not event["candidate_id"]:
            issues.append({"file": where, "message": "candidate_id must be a non-empty string"})
        if event.get("country") != country or event.get("unit_month") != month:
            issues.append({"file": where, "message": "country/unit_month does not match assignment"})
        check_refs(event.get("source_ids"), where)
        if not isinstance(event.get("eligibility"), str) or event["eligibility"] not in ELIGIBILITY:
            issues.append({"file": where, "message": "invalid eligibility"})
        if not isinstance(event.get("coding_status"), str) or event["coding_status"] not in {"candidate", "agent_coded_pending_review"}:
            issues.append({"file": where, "message": "invalid coding_status"})
        if not isinstance(event.get("protester_violence"), str) or event["protester_violence"] not in VALUE:
            issues.append({"file": where, "message": "invalid protester_violence"})
        demands = event.get("demands", [])
        if not isinstance(demands, list) or any(not isinstance(value, str) or value not in DEMANDS for value in demands):
            issues.append({"file": where, "message": "invalid demands category"})
        response = event.get("state_response")
        if (not isinstance(response, dict) or set(response) != RESPONSES
                or any(not isinstance(v, str) or v not in VALUE for v in response.values())):
            issues.append({"file": where, "message": "invalid state_response dimensions or values"})
        dates = {}
        for date_key, precision_key in (("start_date", "start_precision"), ("end_date", "end_precision")):
            dates[date_key], error = date_parts(event.get(date_key), event.get(precision_key))
            if error:
                issues.append({"file": where, "message": f"{date_key}: {error}"})
        if dates["start_date"] and isinstance(month, str):
            if event.get("start_precision") == "year":
                outside_month = f"{dates['start_date'][0]:04d}" != month[:4]
            else:
                outside_month = not event["start_date"].startswith(month)
            if outside_month:
                issues.append({"file": where, "message": "start_date is outside assigned month"})
        if dates["start_date"] and dates["end_date"]:
            shared_depth = min(DATE_PRECISION_DEPTH[event["start_precision"]],
                               DATE_PRECISION_DEPTH[event["end_precision"]])
            if dates["end_date"][:shared_depth] < dates["start_date"][:shared_depth]:
                issues.append({"file": where, "message": "end_date precedes start_date"})
        evidence = event.get("field_evidence")
        if not isinstance(evidence, dict):
            issues.append({"file": where, "message": "field_evidence must be an object"})
        else:
            for field, item in evidence.items():
                if not isinstance(item, dict):
                    issues.append({"file": where, "message": f"field_evidence.{field} must be an object"})
                else:
                    check_refs(item.get("source_ids", []), f"{where} field_evidence.{field}")
    candidate_ids = [value for value in candidate_ids if isinstance(value, str)]
    if len(candidate_ids) != len(set(candidate_ids)):
        issues.append({"file": "events.json", "message": "candidate_id values must be unique"})

    for filename, rows, id_keys in (("excluded.json", excluded, ("candidate_id",)),
                                    ("continuations.json", continuations, ("continuation_id", "candidate_id")),
                                    ("gaps.json", gaps, ("gap_id",))):
        ids = []
        for i, row in enumerate(rows, 1):
            where = f"{filename}:{i}"
            if not isinstance(row, dict):
                issues.append({"file": where, "message": "record must be an object"})
                continue
            key = next((candidate for candidate in id_keys if isinstance(row.get(candidate), str) and row[candidate]), None)
            ids.append(row.get(key) if key else None)
            if key is None:
                issues.append({"file": where, "message": f"one of {', '.join(id_keys)} must be a non-empty string"})
            check_refs(row.get("source_ids", []), where)
            evidence = row.get("field_evidence")
            if evidence is not None:
                if not isinstance(evidence, dict):
                    issues.append({"file": where, "message": "field_evidence must be an object"})
                else:
                    for field, item in evidence.items():
                        if not isinstance(item, dict):
                            issues.append({"file": where, "message": f"field_evidence.{field} must be an object"})
                        else:
                            check_refs(item.get("source_ids", []), f"{where} field_evidence.{field}")
        string_ids = [value for value in ids if isinstance(value, str)]
        if len(string_ids) != len(set(string_ids)):
            issues.append({"file": filename, "message": "record IDs must be unique"})

    counts = {"n_queries": len(queries), "n_sources": len(sources), "n_candidates": len(events),
              "n_excluded": len(excluded), "n_continuations": len(continuations), "n_gaps": len(gaps)}
    for key, actual in counts.items():
        reported = status.get(key)
        if type(reported) is not int or reported < 0:
            issues.append({"file": "status.json", "message": f"{key} must be a non-negative integer"})
        elif reported != actual:
            issues.append({"file": "status.json", "message": f"{key} reports {status.get(key)!r}; records contain {actual}"})
    access_counts = collections.Counter(
        source.get("access_status") if isinstance(source.get("access_status"), str) else "invalid"
        for source in sources
    )
    declared_access = status.get("source_access_counts")
    if "source_access_counts" in status and not isinstance(declared_access, dict):
        issues.append({"file": "status.json", "message": "source_access_counts must be an object"})
    elif isinstance(declared_access, dict):
        card_keys = {f"{state}_cards" for state in ACCESS}
        for state in ACCESS:
            key = f"{state}_cards" if card_keys & declared_access.keys() else state
            reported = declared_access.get(key)
            if type(reported) is not int or reported < 0:
                issues.append({"file": "status.json", "message": f"source_access_counts.{key} must be a non-negative integer"})
            elif reported != access_counts[state]:
                issues.append({"file": "status.json", "message": f"source_access_counts.{key} differs from source cards"})
    else:
        for state in ACCESS:
            key = f"{state}_cards"
            if key in status:
                reported = status[key]
                if type(reported) is not int or reported < 0:
                    issues.append({"file": "status.json", "message": f"{key} must be a non-negative integer"})
                elif reported != access_counts[state]:
                    issues.append({"file": "status.json", "message": f"{key} differs from source cards"})
    integrity = status.get("query_capture_integrity")
    if isinstance(integrity, dict) and "captured_header_count" in integrity:
        reported = integrity["captured_header_count"]
        if type(reported) is not int or reported < 0:
            issues.append({"file": "status.json", "message": "captured_header_count must be a non-negative integer"})
        elif reported != header_count:
            issues.append({"file": "status.json", "message": "captured_header_count differs from query headers"})
    counts["headers"] = header_count
    return {"valid": not issues, "unit_dir": str(unit_dir), "counts": counts, "issues": issues}, data


def validate_unit(unit_dir):
    return inspect_unit(unit_dir)[0]


def body_scope(source):
    for key in ("body_read_scope", "read_scope"):
        if isinstance(source.get(key), str) and source[key].strip():
            return source[key]
    body_read = source.get("body_read")
    if isinstance(body_read, dict) and isinstance(body_read.get("read_scope"), str):
        return body_read["read_scope"]
    return None


def body_read(source):
    # Status, request clocks, refs and failed attempts alone are not body reads.
    evidence = source.get("body_evidence") or source.get("body_observations")
    return (
        source.get("body_read") is True
        or isinstance(source.get("body_read"), dict) and bool(body_scope(source))
        or bool(body_scope(source))
        or bool(evidence)
    )


def prior_consultation(source):
    return isinstance(source.get("prior_unit_consultation"), dict) and bool(source["prior_unit_consultation"])


def alias_or_redirect(source):
    return bool(source.get("alias_of") or source.get("redirected_from_url") or source.get("redirected_to_url")) or (
        isinstance(source.get("final_url"), str) and bool(source["final_url"]) and source["final_url"] != source.get("url")
    )


def reported_scope_claim(text):
    if not isinstance(text, str):
        return None

    def before(marker):
        prefix = text.lower().split(marker, 1)[0]
        token = prefix.rstrip(" ,;:(").split()[-1:]
        if not token:
            return None
        value = token[0].strip("()")
        return int(value) if value.isdigit() else WORDS.get(value)

    current, prior = before("current-unit body opens"), before("prior-unit-only")
    if current is None or prior is None:
        return None
    return {"current_body_read_cards": current, "prior_consultation_cards": prior}


def summarize_unit(unit_dir):
    validation, data = inspect_unit(unit_dir)
    assignment, status = data.get("assignment.json") or {}, data.get("status.json") or {}
    sources, queries = data.get("sources.jsonl", []), data.get("search_log.jsonl", [])
    body_cards = [s for s in sources if s.get("access_status") == "opened" and not prior_consultation(s) and body_read(s)]
    prior_cards = [s for s in sources if prior_consultation(s)]
    opened_unknown = [s for s in sources if s.get("access_status") == "opened" and not prior_consultation(s) and body_scope(s) is None]
    scoped_cards = [s for s in body_cards if body_scope(s)]
    scopes = {s["source_id"]: body_scope(s) for s in scoped_cards if isinstance(s.get("source_id"), str)}
    limited = [s for s in body_cards if s.get("partial_read") is True or s.get("body_scope_complete") is False or s.get("body_capture_limitations")]
    claims = {"status.json": reported_scope_claim(status.get("coverage_assessment"))}
    try:
        report = (pathlib.Path(unit_dir) / "report.txt").read_text(encoding="utf-8")
        claims["report.txt"] = reported_scope_claim(report)
    except (OSError, UnicodeError):
        claims["report.txt"] = None
    actual = {"current_body_read_cards": len(body_cards), "prior_consultation_cards": len(prior_cards)}
    mismatches = [{"file": name, "reported": claim, "derived_from_source_metadata": actual}
                  for name, claim in claims.items() if claim is not None and claim != actual]
    headers = sum(len(q.get("returned_results", q.get("returned_headers", [])))
                  for q in queries if isinstance(q.get("returned_results", q.get("returned_headers", [])), list))
    counts = {"queries": len(queries), "result_headers": headers, "source_cards": len(sources),
              "events": len(data.get("events.json") or []), "excluded": len(data.get("excluded.json") or []),
              "continuations": len(data.get("continuations.json") or []), "gaps": len(data.get("gaps.json") or [])}
    return {
        "unit_id": assignment.get("unit_id"),
        "derived_counts": counts,
        "source_access_counts": dict(collections.Counter(
            s.get("access_status") if isinstance(s.get("access_status"), str) else "invalid"
            for s in sources
        )),
        "source_read_scope": {
            "opened_cards": sum(s.get("access_status") == "opened" for s in sources),
            "current_body_read_cards": len(body_cards),
            "prior_consultation_cards": len(prior_cards),
            "recorded_scope_cards": len(scoped_cards),
            "explicitly_limited_scope_cards": len(limited),
            "alias_or_redirect_cards": sum(alias_or_redirect(s) for s in sources),
            "opened_cards_with_unknown_scope": len(opened_unknown),
            "documented_current_body_scopes": scopes,
            "note": "Counts come from saved metadata. Categories can overlap; they do not establish independent publishers, unique stories or full-text reading.",
        },
        "reported_scope_claims": claims,
        "reported_scope_count_mismatches": mismatches,
        "validation": validation,
    }


def access_input_paths(data_root):
    data_root = pathlib.Path(data_root)
    paths = sorted(data_root.glob("units/*/*/sources.jsonl"))
    checks = data_root / "review" / "source_checks.jsonl"
    if checks.is_file():
        paths.append(checks)
    return paths


def access_snapshot(data_root):
    data_root = pathlib.Path(data_root)
    snapshots, errors = {}, []
    for path in access_input_paths(data_root):
        relative = path.relative_to(data_root).as_posix()
        try:
            raw = path.read_bytes()
        except OSError as exc:
            errors.append(f"{relative}: cannot read input: {exc}")
            continue
        snapshots[relative] = {"path": path, "raw": raw, "sha256": hashlib.sha256(raw).hexdigest()}
    if not (data_root / "review" / "source_checks.jsonl").is_file():
        errors.append("review/source_checks.jsonl: required input is missing")
    return snapshots, errors


def access_fingerprint(snapshots):
    manifest = [{"path": name, "sha256": item["sha256"]} for name, item in sorted(snapshots.items())]
    return hashlib.sha256(json_line(manifest).encode("utf-8")).hexdigest()


def access_rows_hash(rows):
    return hashlib.sha256(json_line(rows).encode("utf-8")).hexdigest()


def parse_access_records(raw, relative, unit_id, kind):
    rows, errors = [], []
    for number, chunk in enumerate(raw.splitlines(), 1):
        if not chunk.strip():
            errors.append(f"{relative}:{number}: blank JSONL line")
            continue
        try:
            record = strict_json_loads(chunk.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            errors.append(f"{relative}:{number}: invalid JSONL record: {exc}")
            continue
        if not isinstance(record, dict):
            errors.append(f"{relative}:{number}: record must be an object")
            continue
        rows.append({
            "kind": kind,
            "file": f"{pathlib.PurePosixPath(relative).parent.as_posix()}/{pathlib.PurePosixPath(relative).name}",
            "line": number,
            "unit_id": unit_id,
            "record": record,
        })
    return rows, errors


def access_input_rows(relative, raw):
    path = pathlib.PurePosixPath(relative)
    if path.parts[:1] == ("units",) and len(path.parts) == 4:
        country, month = path.parts[1], path.parts[2]
        return parse_access_records(raw, relative, f"{country}_{month}", "source_card")
    return parse_access_records(raw, relative, None, "source_check")


def access_cache_path_is_safe(path, data_root):
    resolved = pathlib.Path(path).expanduser().resolve()
    root = pathlib.Path(data_root).expanduser().resolve()
    return resolved != root and root not in resolved.parents


def access_receipt_kind(path, data_root):
    requested = pathlib.Path(path).expanduser()
    root = pathlib.Path(data_root).expanduser().resolve()
    requested_absolute = pathlib.Path(os.path.abspath(requested))
    resolved = requested.resolve()
    try:
        requested_absolute.relative_to(root)
        requested_is_inside = True
    except ValueError:
        requested_is_inside = False
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        return None if requested_is_inside else "temporary"
    parts = relative.parts
    if (len(parts) == 5 and parts[0] == "units" and parts[3] == "access_receipts"
            and pathlib.Path(parts[4]).suffix == ".json"
            and (root / "units" / parts[1] / parts[2] / "sources.jsonl").is_file()):
        return "durable"
    return None


def write_access_receipt(path, result, receipt_kind):
    data = (json.dumps(result, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")
    if receipt_kind != "durable":
        try:
            atomic_write(path, data)
        except OSError as exc:
            return {"ok": False, "decision": "defer", "target_url": result.get("target_url"),
                    "errors": [f"cannot save receipt: {exc}"], "automatic_retrieval_authorized": False}
        return result
    try:
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    except OSError as exc:
        return {"ok": False, "decision": "defer", "target_url": result.get("target_url"),
                "errors": [f"cannot create durable receipt: {exc}"], "automatic_retrieval_authorized": False}
    temp = pathlib.Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temp, path)
    except FileExistsError:
        return {"ok": False, "decision": "defer", "target_url": result.get("target_url"),
                "errors": ["durable receipt already exists; choose a unique filename"],
                "automatic_retrieval_authorized": False}
    except OSError as exc:
        return {"ok": False, "decision": "defer", "target_url": result.get("target_url"),
                "errors": [f"cannot save durable receipt: {exc}"], "automatic_retrieval_authorized": False}
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
    return result


def access_url_values(record, kind):
    values = []
    if kind == "source_card":
        value = record.get("url")
        return [value] if isinstance(value, str) else []

    skipped = {"access_prescreen_snapshot", "pre_body_guard", "prebody_guard",
               "publisher_cards", "publisher_checks", "matched_source_cards",
               "matched_coordinator_checks", "matching_related_cards", "matching_related_checks"}

    def visit(value, parent_key=None):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in skipped:
                    continue
                if key in ACCESS_URL_KEYS:
                    if isinstance(child, str):
                        values.append(child)
                    elif isinstance(child, list):
                        values.extend(item for item in child if isinstance(item, str))
                visit(child, key)
        elif isinstance(value, list):
            for child in value:
                visit(child, parent_key)

    visit(record)
    return list(dict.fromkeys(values))


def access_walk(value, path=()):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"access_prescreen_snapshot", "pre_body_guard", "prebody_guard",
                       "publisher_cards", "publisher_checks", "matched_source_cards",
                       "matched_coordinator_checks", "matching_related_cards", "matching_related_checks"}:
                continue
            yield from access_walk(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from access_walk(child, path + (str(index),))
    else:
        yield path, value


def access_status_codes(record):
    codes = []
    for path, value in access_walk(record):
        if not path:
            continue
        key = path[-1]
        parent_keys = {part.lower() for part in path[:-1]}
        if key in {"http_status", "status_code"} or (
            key == "status" and parent_keys & {"http", "response", "attempt", "access_attempts"}
        ):
            if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599:
                codes.append(value)
            elif isinstance(value, str) and value.isdigit() and 100 <= int(value) <= 599:
                codes.append(int(value))
    return sorted(set(codes))


def access_prose(record):
    values = []
    for path, value in access_walk(record):
        if path and path[-1] in ACCESS_PROSE_KEYS and isinstance(value, str):
            values.append(value)
    return values


def access_denial_text_is_uncertain(text, start, end):
    boundaries = [0] + [match.end() for match in re.finditer(r"[.!?\n]", text)]
    ends = [match.start() for match in re.finditer(r"[.!?\n]", text)] + [len(text)]
    sentence_start = max((point for point in boundaries if point <= start), default=0)
    sentence_end = min((point for point in ends if point >= end), default=len(text))
    before = text[max(sentence_start, start - 80):start]
    after = text[end:min(sentence_end, end + 45)]
    return bool(ACCESS_DENIAL_UNCERTAINTY_RE.search(before)
                or ACCESS_DENIAL_NEGATED_SUFFIX_RE.search(after))


def access_source_id_occurrences(text, source_ids):
    occurrences = []
    for source_id in source_ids:
        if not source_id:
            continue
        for match in re.finditer(re.escape(source_id), text, re.IGNORECASE):
            before = text[match.start() - 1] if match.start() else ""
            after = text[match.end():]
            compact_status = re.match(r"(?:401|402|403)(?![\w])", after)
            if before and (before.isalnum() or before == "_"):
                continue
            if after and (after[0].isalnum() or after[0] == "_") and not compact_status:
                continue
            occurrences.append({"source_id": source_id, "start": match.start(), "end": match.end()})
    return sorted(occurrences, key=lambda item: (item["start"], item["end"], item["source_id"]))


def access_source_id_context(text, occurrence, occurrences):
    start, end = occurrence["start"], occurrence["end"]
    if any(other is not occurrence and other["start"] < end and start < other["end"]
           for other in occurrences):
        return None
    clause_start = max((match.end() for match in ACCESS_SOURCE_ID_CLAUSE_RE.finditer(text, 0, start)),
                       default=0)
    clause_end = min((match.start() for match in ACCESS_SOURCE_ID_CLAUSE_RE.finditer(text, end)),
                     default=len(text))
    clause_ids = [other for other in occurrences
                  if clause_start <= other["start"] and other["end"] <= clause_end]
    previous = [other for other in clause_ids if other["start"] < start]
    following = [other for other in clause_ids if other["start"] > start]
    if previous and not following:
        return None
    if len(clause_ids) > 1:
        context_start = end
    else:
        context_start = max(clause_start, start - 16)
    context_end = min(end + 24, following[0]["start"] if following else clause_end)
    return text[context_start:context_end]


def access_denial_kinds(record, include_prose=False):
    kinds = []
    for code in access_status_codes(record):
        if code in ACCESS_DENIAL_CODES:
            kinds.append(f"http_{code}")
    if include_prose:
        for prose in access_prose(record):
            for match in ACCESS_DENIAL_RE.finditer(prose):
                if access_denial_text_is_uncertain(prose, match.start(), match.end()):
                    continue
                kinds.append("access_restriction_in_saved_prose")
                break
            if "access_restriction_in_saved_prose" in kinds:
                break
    return sorted(set(kinds))


def access_failure_kinds(record):
    kinds = []
    for text in access_prose(record):
        kinds.extend(match.group(1).lower().replace(" ", "_") for match in ACCESS_FAILURE_RE.finditer(text))
    for path, value in access_walk(record):
        if path and path[-1] in {"access_attempts", "attempts", "access_history"}:
            text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            kinds.extend(match.group(1).lower().replace(" ", "_") for match in ACCESS_FAILURE_RE.finditer(text))
    return sorted(set(kinds))


def access_guard_scopes(rows, exact_url):
    scopes = []
    for entry in rows:
        if entry["kind"] != "source_card":
            continue
        record = entry["record"]
        for guard_key in ("access_prescreen_snapshot", "pre_body_guard", "prebody_guard"):
            guard = record.get(guard_key)
            if not isinstance(guard, dict):
                continue
            aliases = guard.get("publisher_alias_scope", guard.get("reviewed_publisher_aliases", []))
            if not isinstance(aliases, list):
                continue
            aliases = [value for value in aliases if isinstance(value, str) and value.strip()]
            if not aliases:
                continue
            denial_rows = []
            for key in ("actual_denials", "publisher_denials", "matched_actual_restrictions",
                        "matched_check_denials"):
                values = guard.get(key, [])
                if isinstance(values, dict):
                    values = [values]
                if not isinstance(values, list):
                    continue
                for value in values:
                    if isinstance(value, dict) and access_denial_kinds(value, include_prose=True):
                        denial_url = value.get("url", value.get("source_url"))
                        check_lines = [match["line"] for match in exact_url.get(denial_url, [])
                                       if match["kind"] == "source_check"]
                        check_line = value.get("source_checks_line", value.get("line"))
                        if check_line is None and len(check_lines) == 1:
                            check_line = check_lines[0]
                        denial_rows.append({
                            "guard_field": key,
                            "source_check_line": check_line,
                            "url": denial_url,
                            "denial_kinds": access_denial_kinds(value, include_prose=True),
                            "evidence": value,
                        })
            if not denial_rows:
                continue
            name_aliases = [value for value in aliases if " " in value or not re.search(r"\.", value)]
            domain_aliases = [value.casefold().rstrip(".") for value in aliases
                              if " " not in value and re.search(r"\.", value)]
            observed_cards = []
            for key in ("matched_source_cards", "publisher_cards", "matching_related_cards"):
                values = guard.get(key, [])
                if not isinstance(values, list):
                    continue
                for value in values:
                    card = value.get("card", value) if isinstance(value, dict) else None
                    if not isinstance(card, dict):
                        continue
                    publisher = card.get("publisher")
                    url = card.get("url")
                    if isinstance(publisher, str) and publisher.casefold() in {a.casefold() for a in name_aliases}:
                        host = urllib.parse.urlsplit(url).hostname if isinstance(url, str) else None
                        if host:
                            observed_cards.append({"publisher": publisher, "host": host.casefold(), "url": url})
            scopes.append({
                "file": entry["file"], "line": entry["line"], "guard_field": guard_key,
                "aliases": aliases, "name_aliases": name_aliases,
                "domain_aliases": domain_aliases, "observed_cards": observed_cards,
                "denials": denial_rows,
            })
    return scopes


def access_origin_ids(record):
    values = []
    for key in ACCESS_ORIGIN_ID_KEYS:
        value = record.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    return list(dict.fromkeys(values))


def access_origin_urls(record):
    values = []
    for key in ACCESS_ORIGIN_URL_KEYS:
        value = record.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    return list(dict.fromkeys(values))


def build_access_index(rows):
    exact_url, cards_by_unit_id, cards_by_id = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    denials_by_url, failures_by_url, blocked_by_url = collections.defaultdict(list), collections.defaultdict(list), collections.defaultdict(list)
    for entry in rows:
        record, kind = entry["record"], entry["kind"]
        for url in access_url_values(record, kind):
            exact_url[url].append(entry)
        if kind == "source_card":
            source_id = record.get("source_id")
            if isinstance(source_id, str):
                cards_by_unit_id[(entry["unit_id"], source_id)].append(entry)
                cards_by_id[source_id].append(entry)
            url = record.get("url")
            if isinstance(url, str):
                evidence = {"file": entry["file"], "line": entry["line"], "source_id": source_id,
                            "access_status": record.get("access_status"), "publisher": record.get("publisher")}
                attempts = record.get("access_attempts", [])
                if isinstance(attempts, dict):
                    attempts = [attempts]
                if isinstance(attempts, list):
                    for attempt in attempts:
                        if isinstance(attempt, dict) and access_denial_kinds(attempt, include_prose=True):
                            denials_by_url[url].append({**evidence, "denial_kinds": access_denial_kinds(attempt, include_prose=True),
                                                        "evidence": attempt})
                        elif isinstance(attempt, dict) and access_failure_kinds(attempt):
                            failures_by_url[url].append({**evidence, "failure_kinds": access_failure_kinds(attempt),
                                                         "evidence": attempt})
                if record.get("access_status") == "blocked" and not denials_by_url.get(url):
                    blocked_by_url[url].append(evidence)
        else:
            urls = access_url_values(record, kind)
            denial_kinds = access_denial_kinds(record, include_prose=len(urls) == 1)
            failure_kinds = access_failure_kinds(record)
            if len(urls) == 1:
                url = urls[0]
                if denial_kinds:
                    denials_by_url[url].append({
                        "file": entry["file"], "line": entry["line"], "source_id": record.get("source_id"),
                        "unit_id": record.get("unit_id"), "access_status": record.get("access_status"),
                        "denial_kinds": denial_kinds, "evidence": record,
                    })
                if failure_kinds:
                    failures_by_url[url].append({
                        "file": entry["file"], "line": entry["line"], "unit_id": record.get("unit_id"),
                        "failure_kinds": failure_kinds, "evidence": record,
                    })
            if record.get("access_status") == "blocked" and not denial_kinds:
                for url in urls:
                    blocked_by_url[url].append({
                        "file": entry["file"], "line": entry["line"], "unit_id": record.get("unit_id"),
                        "access_status": "blocked", "reason": "blocked label without observed denial evidence",
                    })
            prose = "\n".join(access_prose(record))
            source_ids = record.get("source_ids", [])
            if isinstance(record.get("unit_source_id"), str):
                source_ids = list(source_ids) + [record["unit_source_id"]] if isinstance(source_ids, list) else [record["unit_source_id"]]
            if isinstance(record.get("source_id"), str):
                source_ids = list(source_ids) + [record["source_id"]] if isinstance(source_ids, list) else [record["source_id"]]
            if not isinstance(source_ids, list):
                source_ids = []
            source_ids = list(dict.fromkeys(value for value in source_ids if isinstance(value, str)))
            occurrences = access_source_id_occurrences(prose, source_ids)
            for occurrence in occurrences:
                source_id = occurrence["source_id"]
                context = access_source_id_context(prose, occurrence, occurrences)
                if context is None:
                    continue
                context_denial = bool(access_denial_kinds({"assessment": context}, include_prose=True))
                bare_status = re.search(r"(?:401|402|403)\b", context)
                if not context_denial and bare_status:
                    context_denial = not access_denial_text_is_uncertain(
                        context, bare_status.start(), bare_status.end())
                context_failure = bool(ACCESS_FAILURE_RE.search(context))
                if not context_denial and not context_failure:
                    continue
                unit_id = record.get("unit_id")
                targets = (cards_by_unit_id.get((unit_id, source_id), [])
                           if isinstance(unit_id, str) else cards_by_id.get(source_id, []))
                if len(targets) != 1:
                    continue
                target_url = targets[0]["record"].get("url")
                linked = {"file": entry["file"], "line": entry["line"], "unit_id": unit_id,
                          "source_id": source_id, "match_basis": "source ID named beside access result",
                          "evidence_excerpt": context}
                if isinstance(target_url, str):
                    if context_denial:
                        denials_by_url[target_url].append({**linked, "denial_kinds": ["saved_prose_source_id_match"]})
                    if context_failure:
                        failures_by_url[target_url].append({**linked, "failure_kinds": ["saved_prose_source_id_match"]})
    for mapping, field in ((denials_by_url, "denial_kinds"), (failures_by_url, "failure_kinds")):
        for url, values in mapping.items():
            unique = {}
            for value in values:
                signature = (
                    value.get("file"), value.get("line"), value.get("unit_id"), value.get("source_id"),
                    tuple(value.get(field, [])), value.get("match_basis"),
                )
                unique.setdefault(signature, value)
            mapping[url] = list(unique.values())
    scopes = access_guard_scopes(rows, exact_url)
    origins = []
    for entry in rows:
        if entry["kind"] != "source_card":
            continue
        source_id = entry["record"].get("source_id")
        if not isinstance(source_id, str):
            continue
        for related_id in access_origin_ids(entry["record"]):
            targets = cards_by_id.get(related_id, [])
            same_unit = cards_by_unit_id.get((entry["unit_id"], related_id), [])
            if same_unit:
                targets = same_unit
            elif len(targets) != 1:
                targets = []
            for target in targets:
                origins.append({"source": entry, "related": target, "basis": "explicit source ID relationship"})
        for related_url in access_origin_urls(entry["record"]):
            for target in exact_url.get(related_url, []):
                if target["kind"] == "source_card":
                    origins.append({"source": entry, "related": target, "basis": "explicit written-origin URL"})
    return {
        "exact_url": dict(exact_url), "cards_by_unit_id": dict(cards_by_unit_id), "cards_by_id": dict(cards_by_id),
        "denials_by_url": dict(denials_by_url), "failures_by_url": dict(failures_by_url),
        "blocked_by_url": dict(blocked_by_url), "publisher_scopes": scopes, "origins": origins,
    }


def access_scope_matches(scope, url):
    host = urllib.parse.urlsplit(url).hostname.casefold() if isinstance(url, str) and urllib.parse.urlsplit(url).hostname else None
    if host and host in scope["domain_aliases"]:
        return True
    if host and any(item["host"] == host for item in scope["observed_cards"]):
        return True
    return False


def evaluate_access_target(index, target_url):
    exact_matches = index["exact_url"].get(target_url, [])
    target_cards = [entry for entry in exact_matches if entry["kind"] == "source_card"]
    denials = list(index["denials_by_url"].get(target_url, []))
    failures = list(index["failures_by_url"].get(target_url, []))
    blocked = list(index["blocked_by_url"].get(target_url, []))
    publisher_holds = []
    for scope in index["publisher_scopes"]:
        if not access_scope_matches(scope, target_url):
            continue
        publisher_holds.append({
            "file": scope["file"], "line": scope["line"], "guard_field": scope["guard_field"],
            "aliases": scope["aliases"], "denials": scope["denials"],
        })
    origin_matches = []
    target_keys = {(entry["unit_id"], entry["record"].get("source_id")) for entry in target_cards}
    for relation in index["origins"]:
        source, related = relation["source"], relation["related"]
        source_key = (source["unit_id"], source["record"].get("source_id"))
        related_key = (related["unit_id"], related["record"].get("source_id"))
        if source_key in target_keys or related_key in target_keys:
            related_url = related["record"].get("url")
            source_url = source["record"].get("url")
            if index["denials_by_url"].get(related_url) or index["denials_by_url"].get(source_url):
                origin_matches.append({
                    "basis": relation["basis"], "source": {"file": source["file"], "line": source["line"],
                        "source_id": source["record"].get("source_id"), "url": source_url},
                    "related": {"file": related["file"], "line": related["line"],
                        "source_id": related["record"].get("source_id"), "url": related_url},
                    "denials": index["denials_by_url"].get(related_url, index["denials_by_url"].get(source_url, [])),
                })
    decision = "hold" if denials or publisher_holds or origin_matches else "manual_review"
    return {
        "target_url": target_url,
        "exact_url_matches": exact_matches,
        "observed_exact_denials": denials,
        "publisher_scope_holds": publisher_holds,
        "documented_written_origin_matches": origin_matches,
        "retrieval_failures": failures,
        "blocked_without_denial_evidence": blocked,
        "decision": decision,
        "automatic_retrieval_authorized": False,
        "decision_note": (
            "A saved restriction applies to this target; do not request a body."
            if decision == "hold" else
            "No saved restriction matched. Manual review is required; absence of a match is not retrieval permission."
        ),
    }


def access_check(data_root, cache_path, receipt_path, target_url):
    data_root, cache_path, receipt_path = map(pathlib.Path, (data_root, cache_path, receipt_path))
    data_root, cache_path, receipt_path = (
        path.expanduser().resolve() for path in (data_root, cache_path, receipt_path)
    )
    if cache_path.expanduser().resolve() == receipt_path.expanduser().resolve():
        return {"ok": False, "decision": "defer", "errors": ["cache and receipt paths must be different"]}
    if not access_cache_path_is_safe(cache_path, data_root):
        return {"ok": False, "decision": "defer", "errors": ["cache path must be outside the source archive"]}
    receipt_kind = access_receipt_kind(receipt_path, data_root)
    if receipt_kind is None:
        return {"ok": False, "decision": "defer", "errors": [
            "receipt must be outside the source archive or a new .json file in an existing unit access_receipts directory"
        ]}
    if receipt_kind == "durable" and (receipt_path.exists() or receipt_path.is_symlink()):
        return {"ok": False, "decision": "defer", "errors": [
            "durable receipt already exists; choose a unique filename"
        ]}
    if not isinstance(target_url, str) or not target_url:
        return {"ok": False, "decision": "defer", "errors": ["target URL must be a non-empty raw URL string"]}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = cache_path.with_name(cache_path.name + ".lock")
    if lock_path.expanduser().resolve() == receipt_path.expanduser().resolve():
        return {"ok": False, "decision": "defer", "errors": ["receipt path must not overlap the cache lock"]}
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        result = {"ok": False, "decision": "defer", "target_url": target_url,
                  "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  "errors": ["another access-index invocation holds the cache lock"],
                  "automatic_retrieval_authorized": False}
        return write_access_receipt(receipt_path, result, receipt_kind)
    try:
        with os.fdopen(lock_fd, "w", encoding="utf-8") as lock:
            lock.write(str(os.getpid()))
        before, errors = access_snapshot(data_root)
        before_fingerprint = access_fingerprint(before)
        if errors:
            result = {"ok": False, "decision": "defer", "target_url": target_url, "errors": errors,
                      "checked_inputs": [{"path": key, "sha256": value["sha256"]} for key, value in sorted(before.items())],
                      "fingerprint_before": before_fingerprint}
            return write_access_receipt(receipt_path, result, receipt_kind)
        old_hash = hashlib.sha256(cache_path.read_bytes()).hexdigest() if cache_path.is_file() else None
        try:
            cached = strict_json_loads(cache_path.read_text(encoding="utf-8")) if cache_path.is_file() else {}
        except (OSError, UnicodeError, ValueError):
            cached = {}
        old_entries = cached.get("entries", {}) if (
            isinstance(cached, dict) and cached.get("format") == ACCESS_INDEX_FORMAT
            and cached.get("version") == ACCESS_INDEX_VERSION and isinstance(cached.get("entries"), dict)
        ) else {}
        entries, parse_errors, refreshed, reused = {}, [], [], []
        for relative, snapshot in sorted(before.items()):
            old = old_entries.get(relative)
            if (isinstance(old, dict) and old.get("sha256") == snapshot["sha256"]
                    and isinstance(old.get("rows"), list)
                    and old.get("rows_sha256") == access_rows_hash(old["rows"])):
                entries[relative] = old
                reused.append(relative)
            else:
                rows, row_errors = access_input_rows(relative, snapshot["raw"])
                parse_errors.extend(row_errors)
                entries[relative] = {
                    "sha256": snapshot["sha256"], "rows_sha256": access_rows_hash(rows), "rows": rows,
                }
                refreshed.append(relative)
        removed = sorted(set(old_entries) - set(entries))
        after, after_errors = access_snapshot(data_root)
        after_fingerprint = access_fingerprint(after)
        stable = not after_errors and before_fingerprint == after_fingerprint and {
            name: value["sha256"] for name, value in before.items()
        } == {name: value["sha256"] for name, value in after.items()}
        if after_errors:
            parse_errors.extend(after_errors)
        rows = [
            row for kind in ("source_card", "source_check")
            for item in entries.values() for row in item["rows"]
            if row["kind"] == kind
        ]
        source_count = sum(row["kind"] == "source_card" for row in rows)
        check_count = sum(row["kind"] == "source_check" for row in rows)
        if parse_errors or not stable:
            result = {
                "ok": False, "decision": "defer", "target_url": target_url,
                "index_version": ACCESS_INDEX_VERSION, "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "checked_inputs": [{"path": key, "sha256": value["sha256"]} for key, value in sorted(before.items())],
                "fingerprint_before": before_fingerprint, "fingerprint_after": after_fingerprint,
                "inputs_stable": stable, "source_cards": source_count, "source_checks": check_count,
                "refreshed_inputs": refreshed, "reused_inputs": reused, "removed_inputs": removed,
                "parse_errors": parse_errors, "automatic_retrieval_authorized": False,
            }
            return write_access_receipt(receipt_path, result, receipt_kind)
        if cache_path.is_file() and old_hash is not None:
            current_hash = hashlib.sha256(cache_path.read_bytes()).hexdigest()
            if current_hash != old_hash:
                result = {"ok": False, "decision": "defer", "target_url": target_url,
                          "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                          "checked_inputs": [{"path": key, "sha256": value["sha256"]} for key, value in sorted(before.items())],
                          "fingerprint_before": before_fingerprint, "fingerprint_after": after_fingerprint,
                          "errors": ["cache changed during index refresh; retry against a stable cache"],
                          "automatic_retrieval_authorized": False}
                return write_access_receipt(receipt_path, result, receipt_kind)
        index = build_access_index(rows)
        cached_index = {
            "format": ACCESS_INDEX_FORMAT, "version": ACCESS_INDEX_VERSION,
            "fingerprint": before_fingerprint,
            "inputs": [{"path": key, "sha256": value["sha256"]} for key, value in sorted(before.items())],
            "entries": entries,
            "exact_url_keys": sorted(index["exact_url"]),
            "publisher_scope_count": len(index["publisher_scopes"]),
            "written_origin_relation_count": len(index["origins"]),
        }
        atomic_write(cache_path, (json.dumps(cached_index, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode("utf-8"))
        result = {
            "ok": True, "index_version": ACCESS_INDEX_VERSION,
            "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "checked_inputs": [{"path": key, "sha256": value["sha256"]} for key, value in sorted(before.items())],
            "fingerprint_before": before_fingerprint, "fingerprint_after": after_fingerprint, "inputs_stable": True,
            "source_cards": source_count, "source_checks": check_count,
            "refreshed_inputs": refreshed, "reused_inputs": reused, "removed_inputs": removed,
            **evaluate_access_target(index, target_url),
        }
        return write_access_receipt(receipt_path, result, receipt_kind)
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return {"ok": False, "decision": "defer", "target_url": target_url,
                "errors": [f"access index failed closed: {exc}"]}
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Persist captured research records and inspect dossiers. No web requests are made.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("capture-search", "append an actual query and aligned result headers"),
                            ("validate-unit", "read-only structural validation"),
                            ("summarize-unit", "read-only counts and source-scope inventory")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("unit_dir", type=pathlib.Path)
        if name == "capture-search":
            command.add_argument("record_json", type=pathlib.Path)
    save = commands.add_parser("save-source", help="merge fields into one exact source_id card")
    save.add_argument("unit_dir", type=pathlib.Path)
    save.add_argument("source_id")
    save.add_argument("patch_json", type=pathlib.Path)
    access = commands.add_parser("access-check", help="refresh a temporary source-access index and write a review receipt")
    access.add_argument("url", help="exact raw target URL; no redirects or network request are made")
    access.add_argument("--data-root", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1])
    access.add_argument("--cache", type=pathlib.Path, required=True, help="temporary cache path outside the source archive")
    access.add_argument("--receipt", type=pathlib.Path, required=True,
                        help="temporary path outside the archive or new per-unit access_receipts/*.json")
    args = parser.parse_args(argv)
    if args.command == "capture-search":
        result = capture_search(args.unit_dir, args.record_json)
    elif args.command == "save-source":
        result = save_source(args.unit_dir, args.source_id, args.patch_json)
    elif args.command == "validate-unit":
        result = validate_unit(args.unit_dir)
    elif args.command == "access-check":
        result = access_check(args.data_root, args.cache, args.receipt, args.url)
    else:
        result = summarize_unit(args.unit_dir)
    emit(result)
    if args.command in {"capture-search", "save-source"} and not result.get("ok"):
        return 2
    if args.command == "validate-unit" and not result.get("valid"):
        return 1
    if args.command == "access-check" and not result.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
