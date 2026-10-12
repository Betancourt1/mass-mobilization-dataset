import json
import hashlib
import pathlib
import subprocess
import sys
import tempfile
import unittest


SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import research


RESPONSES = {key: "unknown" for key in research.RESPONSES}


def source(source_id="S001", **extra):
    return {
        "source_id": source_id,
        "url": f"https://example.test/{source_id}",
        "title": "Example",
        "access_status": "opened",
        "publication_date": None,
        "accessed_at": None,
        **extra,
    }


def query():
    url = "https://example.test/result"
    return {
        "query_id": "Q001",
        "query": "example protest",
        "executed_at": None,
        "response_captured_at": None,
        "tool": "web.run.search_query",
        "returned_results": [{"order": 1, "url": url, "ref": "turn1search0", "title": "First\nsecond"}],
        "returned_urls": [url],
    }


def event():
    return {
        "candidate_id": "unit_2021-02_E001",
        "country": "Exampleland",
        "unit_month": "2021-02",
        "title": "Example event\nwith a second line",
        "start_date": None,
        "start_precision": "unknown",
        "end_date": None,
        "end_precision": "unknown",
        "source_ids": ["S001"],
        "field_evidence": {"start_date": {"source_ids": ["S001"], "summary": "Date remains unknown."}},
        "eligibility": "pending_evidence",
        "coding_status": "candidate",
        "protester_violence": "unknown",
        "demands": [],
        "state_response": dict(RESPONSES),
    }


class ResearchCliTests(unittest.TestCase):
    def make_unit(self, directory, sources=None, report=""):
        directory.mkdir(parents=True)
        rows = sources if sources is not None else [source(body_read_scope="Visible article paragraphs.")]
        for name, value in {
            "assignment.json": {"unit_id": "unit_2021-02", "country": "Exampleland", "month": "2021-02"},
            "status.json": {
                "unit_id": "unit_2021-02", "country": "Exampleland", "month": "2021-02",
                "n_queries": 1, "n_sources": len(rows), "n_candidates": 1,
                "n_excluded": 0, "n_continuations": 0, "n_gaps": 0,
                "source_access_counts": {state: sum(row["access_status"] == state for row in rows)
                                          for state in research.ACCESS},
            },
            "events.json": [event()],
            "excluded.json": [],
            "continuations.json": [],
            "gaps.json": [],
        }.items():
            (directory / name).write_text(json.dumps(value), encoding="utf-8")
        (directory / "search_log.jsonl").write_text(json.dumps(query()) + "\n", encoding="utf-8")
        (directory / "sources.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        (directory / "report.txt").write_text(report, encoding="utf-8")
        return directory

    def test_capture_preserves_header_order_null_times_and_multiline_title(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = pathlib.Path(temp) / "unit"
            unit.mkdir()
            (unit / "search_log.jsonl").write_bytes(b"")
            capture = pathlib.Path(temp) / "capture.json"
            record = query()
            capture.write_text(json.dumps(record), encoding="utf-8")

            result = research.capture_search(unit, capture)
            saved = (unit / "search_log.jsonl").read_bytes()

            self.assertTrue(result["ok"])
            self.assertEqual(saved.count(b"\n"), 1)
            self.assertEqual(json.loads(saved.splitlines()[0]), record)
            self.assertIsNone(json.loads(saved)["executed_at"])

    def test_bad_capture_alignment_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = pathlib.Path(temp) / "unit"
            unit.mkdir()
            original = b'{"existing":true}\n'
            (unit / "search_log.jsonl").write_bytes(original)
            capture = pathlib.Path(temp) / "capture.json"
            record = query()
            record["returned_urls"] = ["https://wrong.test/"]
            capture.write_text(json.dumps(record), encoding="utf-8")

            result = research.capture_search(unit, capture)

            self.assertFalse(result["ok"])
            self.assertEqual((unit / "search_log.jsonl").read_bytes(), original)

    def test_capture_rejects_nonstandard_json_without_traceback_or_write(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = pathlib.Path(temp) / "unit"
            unit.mkdir()
            log = unit / "search_log.jsonl"
            original = b'{"existing":true}\n'
            log.write_bytes(original)
            capture = pathlib.Path(temp) / "capture.json"
            capture.write_text(json.dumps({**query(), "extra": float("nan")}), encoding="utf-8")

            result = subprocess.run([sys.executable, "-B", str(SCRIPT_DIR / "research.py"),
                                     "capture-search", str(unit), str(capture)],
                                    capture_output=True, text=True)

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(log.read_bytes(), original)

    def test_source_update_changes_only_the_exact_card(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = pathlib.Path(temp) / "unit"
            unit.mkdir()
            path = unit / "sources.jsonl"
            first = b'{ "source_id" : "S001", "url":"https://example.test/1", "title":null,"access_status":"search_only"}\n'
            second = json.dumps(source("S002", summary="old")).encode() + b"\n"
            path.write_bytes(first + second)
            patch = pathlib.Path(temp) / "patch.json"
            patch.write_text(json.dumps({"source_id": "S002", "summary": "updated"}), encoding="utf-8")

            result = research.save_source(unit, "S002", patch)
            after = path.read_bytes()

            self.assertTrue(result["ok"])
            self.assertTrue(after.startswith(first))
            self.assertEqual(json.loads(after.splitlines()[1])["summary"], "updated")

    def test_invalid_source_update_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = pathlib.Path(temp) / "unit"
            unit.mkdir()
            path = unit / "sources.jsonl"
            original = (json.dumps(source()) + "\n").encode()
            path.write_bytes(original)
            patch = pathlib.Path(temp) / "patch.json"
            patch.write_text(json.dumps({"source_id": "S001", "access_status": "maybe"}), encoding="utf-8")

            result = research.save_source(unit, "S001", patch)

            self.assertFalse(result["ok"])
            self.assertEqual(path.read_bytes(), original)

    def test_source_update_rejects_nonstandard_json_without_traceback_or_write(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = pathlib.Path(temp) / "unit"
            unit.mkdir()
            path = unit / "sources.jsonl"
            original = (json.dumps(source()) + "\n").encode()
            path.write_bytes(original)
            patch = pathlib.Path(temp) / "patch.json"
            patch.write_text(json.dumps({"source_id": "S001", "extra": float("inf")}), encoding="utf-8")

            result = subprocess.run([sys.executable, "-B", str(SCRIPT_DIR / "research.py"),
                                     "save-source", str(unit), "S001", str(patch)],
                                    capture_output=True, text=True)

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertEqual(path.read_bytes(), original)

    def test_valid_unit_keeps_null_dates_and_aligned_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = self.make_unit(pathlib.Path(temp) / "unit")
            result = research.validate_unit(unit)
            self.assertTrue(result["valid"], result["issues"])
            self.assertEqual(result["counts"]["headers"], 1)

    def test_year_precision_start_date_uses_assigned_year(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = self.make_unit(pathlib.Path(temp) / "unit")
            year_event = event()
            year_event["start_date"] = "2021"
            year_event["start_precision"] = "year"
            (unit / "events.json").write_text(json.dumps([year_event]), encoding="utf-8")

            valid = research.validate_unit(unit)
            self.assertTrue(valid["valid"], valid["issues"])

            year_event["start_date"] = "2020"
            (unit / "events.json").write_text(json.dumps([year_event]), encoding="utf-8")
            outside_year = research.validate_unit(unit)
            self.assertIn("start_date is outside assigned month",
                          " ".join(issue["message"] for issue in outside_year["issues"]))

    def test_date_order_only_rejects_definitely_earlier_end(self):
        cases = [
            ("2021-02-20", "day", "2021-02", "month", True),
            ("2021-02", "month", "2021", "year", True),
            ("2021-02-20", "day", "2021-01", "month", False),
            ("2021-02-20", "day", "2021-02-19", "day", False),
        ]
        with tempfile.TemporaryDirectory() as temp:
            unit = self.make_unit(pathlib.Path(temp) / "unit")
            for start, start_precision, end, end_precision, expected_valid in cases:
                with self.subTest(start=start, end=end):
                    candidate = event()
                    candidate.update(start_date=start, start_precision=start_precision,
                                     end_date=end, end_precision=end_precision)
                    (unit / "events.json").write_text(json.dumps([candidate]), encoding="utf-8")

                    result = research.validate_unit(unit)

                    self.assertEqual(result["valid"], expected_valid, result["issues"])
                    if not expected_valid:
                        self.assertIn("end_date precedes start_date",
                                      " ".join(issue["message"] for issue in result["issues"]))

    def test_status_counts_require_nonnegative_integers_and_access_mapping(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = self.make_unit(pathlib.Path(temp) / "unit")
            status_path = unit / "status.json"
            status = json.loads(status_path.read_text())
            status["n_queries"] = True
            status["n_sources"] = -1
            status["source_access_counts"] = "bad"
            status_path.write_text(json.dumps(status), encoding="utf-8")

            malformed = research.validate_unit(unit)
            messages = " ".join(issue["message"] for issue in malformed["issues"])
            self.assertIn("n_queries must be a non-negative integer", messages)
            self.assertIn("n_sources must be a non-negative integer", messages)
            self.assertIn("source_access_counts must be an object", messages)

            status["n_queries"] = 1
            status["n_sources"] = 1
            status["source_access_counts"] = {state: int(state == "opened") for state in research.ACCESS}
            status["source_access_counts"]["opened"] = True
            status_path.write_text(json.dumps(status), encoding="utf-8")
            boolean_count = research.validate_unit(unit)
            self.assertIn("source_access_counts.opened must be a non-negative integer",
                          " ".join(issue["message"] for issue in boolean_count["issues"]))

    def test_summary_is_stable_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = self.make_unit(pathlib.Path(temp) / "unit")
            before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in unit.iterdir() if p.is_file()}
            first = research.summarize_unit(unit)
            second = research.summarize_unit(unit)
            after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in unit.iterdir() if p.is_file()}
            self.assertEqual(first, second)
            self.assertEqual(before, after)

    def test_validator_catches_bad_reference_precision_count_and_alignment(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = self.make_unit(pathlib.Path(temp) / "unit")
            bad_event = event()
            bad_event["source_ids"] = ["S404"]
            bad_event["start_precision"] = "week"
            (unit / "events.json").write_text(json.dumps([bad_event]), encoding="utf-8")
            status = json.loads((unit / "status.json").read_text())
            status["n_candidates"] = 9
            (unit / "status.json").write_text(json.dumps(status), encoding="utf-8")
            bad_query = query()
            bad_query["returned_urls"] = ["https://wrong.test/"]
            (unit / "search_log.jsonl").write_text(json.dumps(bad_query) + "\n", encoding="utf-8")

            result = research.validate_unit(unit)
            messages = " ".join(issue["message"] for issue in result["issues"])
            self.assertFalse(result["valid"])
            self.assertIn("unknown source_id S404", messages)
            self.assertIn("invalid precision", messages)
            self.assertIn("n_candidates reports 9", messages)
            self.assertIn("returned_urls[0]", messages)

    def test_validator_reports_malformed_json_types_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp:
            unit = self.make_unit(pathlib.Path(temp) / "unit", [source(access_status=["opened"])])
            bad_event = event()
            bad_event["source_ids"] = [{"id": "S001"}]
            bad_event["eligibility"] = []
            bad_event["start_precision"] = []
            bad_event["state_response"]["arrests"] = ["unknown"]
            (unit / "events.json").write_text(json.dumps([bad_event]), encoding="utf-8")

            result = research.validate_unit(unit)
            messages = " ".join(issue["message"] for issue in result["issues"])

            self.assertFalse(result["valid"])
            self.assertIn("source_id reference must be a string", messages)
            self.assertIn("invalid eligibility", messages)
            self.assertIn("start_date: invalid precision", messages)
            self.assertIn("invalid state_response", messages)
            self.assertIn("access_status is invalid", messages)

    def test_summary_handles_malformed_source_id_as_validation_issue(self):
        with tempfile.TemporaryDirectory() as temp:
            malformed = source(source_id=["S001"], body_read_scope="Visible article text.")
            unit = self.make_unit(pathlib.Path(temp) / "unit", [malformed])

            summary = research.summarize_unit(unit)

            self.assertFalse(summary["validation"]["valid"])
            self.assertIn("source_id must be a non-empty string",
                          " ".join(issue["message"] for issue in summary["validation"]["issues"]))
            self.assertEqual(summary["source_read_scope"]["recorded_scope_cards"], 1)

    def test_summary_keeps_blocked_attempt_and_ambiguous_open_scope_unknown(self):
        current = [source(f"C{i:02}", body_read_scope="Selected article text.") for i in range(1, 17)]
        current[0]["body_capture_limitations"] = "Images and links not read."
        current[1]["redirected_to_url"] = "https://example.test/redirected"
        prior = [source("P01", prior_unit_consultation={"unit_id": "unit_2021-01"}),
                 source("P02", prior_unit_consultation={"unit_id": "unit_2021-01"})]
        unknown = source("U01", body_read_ref="view-without-recorded-scope")
        blocked = source("B01", access_status="blocked", body_read_scope="Old failed request context.",
                         body_http_status=403, body_response_captured_at="2026-10-09T00:00:00Z")
        report = "16 current-unit body opens plus two prior-unit-only consultations."
        with tempfile.TemporaryDirectory() as temp:
            unit = self.make_unit(pathlib.Path(temp) / "unit", current + prior + [unknown, blocked], report)
            status = json.loads((unit / "status.json").read_text())
            status["coverage_assessment"] = "16 current-unit body opens and two prior-unit-only cards."
            (unit / "status.json").write_text(json.dumps(status), encoding="utf-8")

            summary = research.summarize_unit(unit)
            scope = summary["source_read_scope"]
            self.assertEqual(scope["opened_cards"], 19)
            self.assertEqual(scope["current_body_read_cards"], 16)
            self.assertEqual(scope["prior_consultation_cards"], 2)
            self.assertEqual(scope["explicitly_limited_scope_cards"], 1)
            self.assertEqual(scope["alias_or_redirect_cards"], 1)
            self.assertEqual(scope["opened_cards_with_unknown_scope"], 1)
            self.assertEqual(summary["reported_scope_count_mismatches"], [])

            report = "17 current-unit body opens plus one prior-unit-only consultation."
            (unit / "report.txt").write_text(report, encoding="utf-8")
            mismatched = research.summarize_unit(unit)
            self.assertEqual(mismatched["reported_scope_count_mismatches"][0]["file"], "report.txt")


if __name__ == "__main__":
    unittest.main()
