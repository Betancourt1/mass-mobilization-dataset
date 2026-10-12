import hashlib
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT_DIR = pathlib.Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
import research


def card(source_id, url, **extra):
    return {
        "source_id": source_id,
        "url": url,
        "publisher": "Example News",
        "access_status": "search_only",
        **extra,
    }


def check(url, **extra):
    return {"access_status": "blocked", "url": url, "read_scope": "HTTP 403 Forbidden.", **extra}


class AccessIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.temp.name)
        self.root = self.base / "extension"
        self.cache = self.base / "temporary" / "access-index.json"
        self.receipt = self.base / "temporary" / "receipt.json"
        self.write_unit("exampleland", "2021-01", [])
        self.write_checks([])

    def tearDown(self):
        self.temp.cleanup()

    def write_unit(self, country, month, rows):
        directory = self.root / "units" / country / month
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "sources.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )
        return directory / "sources.jsonl"

    def write_checks(self, rows):
        path = self.root / "review" / "source_checks.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                        encoding="utf-8")
        return path

    def run_check(self, url):
        return research.access_check(self.root, self.cache, self.receipt, url)

    def test_exact_raw_url_and_independent_full_scan_parity(self):
        url = "https://news.example/story?id=1"
        source_path = self.write_unit("exampleland", "2021-01", [card("S001", url)])
        self.write_checks([{"access_status": "blocked", "source_urls": [url],
                            "read_scope": "Same URL returned HTTP 403 Forbidden."}])

        result = self.run_check(url)
        receipt = json.loads(self.receipt.read_text(encoding="utf-8"))

        expected = []
        for path in sorted(self.root.glob("units/*/*/sources.jsonl")) + [self.root / "review/source_checks.jsonl"]:
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                row = json.loads(line)
                urls = [row.get("url"), row.get("source_url"), row.get("target_url")]
                urls.extend(row.get("source_urls", []) if isinstance(row.get("source_urls"), list) else [])
                if url in urls:
                    kind = "source_card" if path.name == "sources.jsonl" else "source_check"
                    expected.append((path.relative_to(self.root).as_posix(), kind, line_number, row))
        actual = [(row["file"], row["kind"], row["line"], row["record"])
                  for row in result["exact_url_matches"]]
        self.assertTrue(result["ok"])
        self.assertEqual(result["decision"], "hold")
        self.assertEqual(sorted(actual, key=lambda row: row[:3]),
                         sorted(expected, key=lambda row: row[:3]))
        self.assertEqual(receipt["checked_inputs"], result["checked_inputs"])
        self.assertEqual(source_path.as_posix().endswith("sources.jsonl"), True)
        self.assertFalse(result["automatic_retrieval_authorized"])

        variant = self.run_check(url + "/")
        self.assertEqual(variant["decision"], "manual_review")
        self.assertEqual(variant["exact_url_matches"], [])
        self.assertFalse(variant["automatic_retrieval_authorized"])

    def test_nested_http_status_is_observed_denial_evidence(self):
        target = "https://news.example/story"
        self.write_unit("exampleland", "2021-01", [card("S001", target)])
        self.write_checks([{
            "access_status": "blocked",
            "requested_url": target,
            "response": {"http": {"status": 403}},
        }])

        result = self.run_check(target)

        self.assertEqual(result["decision"], "hold")
        self.assertEqual(result["observed_exact_denials"][0]["denial_kinds"], ["http_403"])

    def test_observed_http_401_402_403_prose_and_structured_statuses_are_denials(self):
        target = "https://news.example/story"
        self.write_unit("exampleland", "2021-01", [card("S001", target)])
        prose = {
            401: "The server returned HTTP 401 Unauthorized.",
            402: "The server returned HTTP 402 Payment Required.",
            403: "The server returned HTTP 403 Forbidden.",
        }

        for code, assessment in prose.items():
            with self.subTest(prose_status=code):
                self.write_checks([{"access_status": "blocked", "url": target,
                                    "assessment": assessment}])
                result = self.run_check(target)
                self.assertEqual(result["decision"], "hold")
                self.assertIn("access_restriction_in_saved_prose",
                              result["observed_exact_denials"][0]["denial_kinds"])

            with self.subTest(structured_status=code):
                self.write_checks([{"access_status": "blocked", "url": target,
                                    "response": {"http": {"status": code}}}])
                result = self.run_check(target)
                self.assertEqual(result["decision"], "hold")
                self.assertEqual(result["observed_exact_denials"][0]["denial_kinds"],
                                 [f"http_{code}"])

    def test_negated_and_uncertain_http_401_402_403_prose_stays_manual_review(self):
        target = "https://news.example/story"
        self.write_unit("exampleland", "2021-01", [card("S001", target)])

        for code in (401, 402, 403):
            with self.subTest(code=code):
                self.write_checks([
                    {"access_status": "blocked", "url": target,
                     "assessment": f"No HTTP {code} observed."},
                    {"access_status": "blocked", "url": target,
                     "assessment": f"Possibly HTTP {code}, but it remains unconfirmed."},
                    {"access_status": "blocked", "url": target,
                     "assessment": f"The server may have returned HTTP {code}."},
                ])
                result = self.run_check(target)
                self.assertEqual(result["decision"], "manual_review")
                self.assertEqual(result["observed_exact_denials"], [])
                self.assertEqual(len(result["blocked_without_denial_evidence"]), 3)

    def test_only_explicit_publisher_scope_matches_listed_host(self):
        denied_url = "https://news.example/denied"
        target_url = "https://news.example/target"
        unlisted_host_url = "https://clone.example/target"
        scope = {
            "publisher_alias_scope": ["news.example", "Example News"],
            "actual_denials": [{"url": denied_url, "http_status": 403}],
            "matched_source_cards": [{"card": {"publisher": "Example News", "url": target_url}}],
        }
        self.write_unit("exampleland", "2021-01", [
            card("S001", target_url, access_prescreen_snapshot=scope),
            card("S002", unlisted_host_url),
        ])
        self.write_checks([check(denied_url)])

        listed = self.run_check(target_url)
        unlisted = self.run_check(unlisted_host_url)

        self.assertEqual(listed["decision"], "hold")
        self.assertEqual(len(listed["publisher_scope_holds"]), 1)
        self.assertEqual(listed["publisher_scope_holds"][0]["denials"][0]["source_check_line"], 1)
        self.assertEqual(unlisted["decision"], "manual_review")
        self.assertEqual(unlisted["publisher_scope_holds"], [])
        self.assertEqual(unlisted["exact_url_matches"][0]["record"]["publisher"], "Example News")

    def test_exact_publisher_names_do_not_use_fuzzy_same_name_matching(self):
        denied_url = "https://gazette.example/denied"
        target_url = "https://gazette.example/target"
        near_name_url = "https://other.example/target"
        scope = {
            "publisher_alias_scope": ["Gazette News", "gazette.example"],
            "actual_denials": [{"url": denied_url, "http_status": 403}],
            "matched_source_cards": [{"card": {"publisher": "Gazette News", "url": target_url}}],
        }
        self.write_unit("exampleland", "2021-01", [
            card("S010", target_url, publisher="Gazette News", access_prescreen_snapshot=scope),
            card("S011", near_name_url, publisher="Gazette News International"),
        ])
        self.write_checks([check(denied_url)])

        result = self.run_check(near_name_url)

        self.assertEqual(result["decision"], "manual_review")
        self.assertEqual(result["publisher_scope_holds"], [])

    def test_publisher_name_without_domain_or_recorded_host_does_not_extend_scope(self):
        denied_url = "https://blocked.example/denied"
        target_url = "https://other.example/story"
        scope = {
            "publisher_alias_scope": ["Gazette News"],
            "actual_denials": [{"url": denied_url, "http_status": 403}],
        }
        self.write_unit("exampleland", "2021-01", [
            card("S001", target_url, publisher="Gazette News", access_prescreen_snapshot=scope),
        ])
        self.write_checks([check(denied_url)])

        result = self.run_check(target_url)

        self.assertEqual(result["decision"], "manual_review")
        self.assertEqual(result["publisher_scope_holds"], [])
        self.assertFalse(result["automatic_retrieval_authorized"])

    def test_ambiguous_multi_url_denial_prose_stays_manual_review(self):
        target = "https://one.example/story"
        other = "https://two.example/story"
        self.write_unit("exampleland", "2021-01", [card("S001", target)])
        self.write_checks([{
            "access_status": "dossier_and_provenance_review_only",
            "source_urls": [target, other],
            "assessment": "One article returned HTTP 403, but the saved note does not identify which URL.",
        }])

        result = self.run_check(target)

        self.assertEqual(result["decision"], "manual_review")
        self.assertEqual(result["observed_exact_denials"], [])

    def test_negated_or_uncertain_denial_words_stay_manual_review(self):
        target = "https://one.example/story"
        self.write_unit("exampleland", "2021-01", [card("S001", target)])
        self.write_checks([
            {"access_status": "blocked", "url": target, "assessment": "No HTTP 403 observed."},
            {"access_status": "blocked", "url": target,
             "assessment": "Possibly a paywall, but the restriction is unconfirmed."},
        ])

        result = self.run_check(target)

        self.assertEqual(result["decision"], "manual_review")
        self.assertEqual(result["observed_exact_denials"], [])
        self.assertEqual(len(result["blocked_without_denial_evidence"]), 2)

    def test_negated_source_id_bound_denial_stays_manual_review(self):
        target = "https://one.example/story"
        other = "https://two.example/story"
        self.write_unit("exampleland", "2021-01", [card("S001", target)])
        for code in (401, 402, 403):
            with self.subTest(code=code):
                self.write_checks([{
                    "unit_id": "exampleland_2021-01",
                    "source_ids": ["S001"],
                    "source_urls": [target, other],
                    "assessment": f"S001: no HTTP {code} observed; possibly a paywall, unconfirmed.",
                }])

                result = self.run_check(target)

                self.assertEqual(result["decision"], "manual_review")
                self.assertEqual(result["observed_exact_denials"], [])

    def test_source_id_bound_compact_http_401_402_403_remains_url_specific(self):
        target = "https://one.example/story"
        other = "https://two.example/story"
        self.write_unit("exampleland", "2021-01", [
            card("S001", target), card("S002", other),
        ])

        for code in (401, 402, 403):
            with self.subTest(code=code):
                self.write_checks([{
                    "unit_id": "exampleland_2021-01",
                    "source_ids": ["S001", "S002"],
                    "source_urls": [target, other],
                    "assessment": f"S001 actual{code}/exit0/no body; S002 stayed accessible.",
                }])

                target_result = self.run_check(target)
                other_result = self.run_check(other)

                self.assertEqual(target_result["decision"], "hold")
                self.assertEqual(target_result["observed_exact_denials"][0]["denial_kinds"],
                                 ["saved_prose_source_id_match"])
                self.assertEqual(other_result["decision"], "manual_review")

    def test_adjacent_source_id_results_do_not_leak_between_ids(self):
        first = "https://one.example/story"
        second = "https://two.example/story"
        self.write_unit("exampleland", "2021-01", [card("S001", first), card("S002", second)])
        cases = (
            ("S001 actual{code}; S002 accessible.", "hold", "manual_review"),
            ("S001 accessible; S002 actual{code}.", "manual_review", "hold"),
            ("S001 no HTTP {code} observed; S002 actual{code}.", "manual_review", "hold"),
            ("S001 actual{code}; S002 no HTTP {code} observed.", "hold", "manual_review"),
        )

        for code in (401, 402, 403):
            for assessment, first_decision, second_decision in cases:
                with self.subTest(code=code, assessment=assessment):
                    self.write_checks([{
                        "unit_id": "exampleland_2021-01",
                        "source_ids": ["S001", "S002"],
                        "source_urls": [first, second],
                        "assessment": assessment.format(code=code),
                    }])
                    first_result = self.run_check(first)
                    second_result = self.run_check(second)
                    self.assertEqual(first_result["decision"], first_decision)
                    self.assertEqual(second_result["decision"], second_decision)

    def test_ambiguous_multi_id_clause_and_partial_source_id_stay_manual_review(self):
        target = "https://one.example/story"
        other = "https://two.example/story"
        self.write_unit("exampleland", "2021-01", [card("S001", target), card("S002", other)])
        self.write_checks([{
            "unit_id": "exampleland_2021-01",
            "source_ids": ["S001", "S002"],
            "source_urls": [target, other],
            "assessment": "The observed HTTP 403 applies to source IDs S001 and S002.",
        }])

        ambiguous_first = self.run_check(target)
        ambiguous_second = self.run_check(other)

        self.assertEqual(ambiguous_first["decision"], "manual_review")
        self.assertEqual(ambiguous_second["decision"], "manual_review")

        self.write_checks([{
            "unit_id": "exampleland_2021-01",
            "source_ids": ["S001"],
            "source_urls": [target, other],
            "assessment": "S0010 actual403; S002 accessible.",
        }])
        partial_match = self.run_check(target)
        self.assertEqual(partial_match["decision"], "manual_review")
        self.assertEqual(partial_match["observed_exact_denials"], [])

    def test_source_id_without_unit_requires_unique_archive_match(self):
        first = "https://one.example/story"
        second = "https://two.example/story"
        self.write_unit("exampleland", "2021-01", [card("S001", first)])
        self.write_unit("otherland", "2021-02", [card("S001", second)])
        self.write_checks([{
            "source_ids": ["S001"],
            "source_urls": [first, second],
            "assessment": "S001 actual403; other article stayed accessible.",
        }])

        first_result = self.run_check(first)
        second_result = self.run_check(second)

        self.assertEqual(first_result["decision"], "manual_review")
        self.assertEqual(second_result["decision"], "manual_review")

    def test_documented_story_link_matches_but_byline_topic_and_photo_do_not(self):
        denied_url = "https://wire.example/story"
        linked_url = "https://reprint.example/story"
        unrelated_url = "https://other.example/story"
        self.write_unit("exampleland", "2021-01", [
            card("S001", denied_url),
            card("S002", linked_url, same_story_variant_source_ids=["S001"]),
            card("S003", unrelated_url, origin_agency="Example News",
                 byline="Example News", photo_credit="Example News",
                 topic="same protest as S001"),
        ])
        self.write_checks([check(denied_url)])

        linked = self.run_check(linked_url)
        unrelated = self.run_check(unrelated_url)

        self.assertEqual(linked["decision"], "hold")
        self.assertEqual(len(linked["documented_written_origin_matches"]), 1)
        self.assertEqual(unrelated["decision"], "manual_review")
        self.assertEqual(unrelated["documented_written_origin_matches"], [])

    def test_cache_miss_and_tls_failure_are_not_denials_but_later_403_is(self):
        target = "https://journal.example/story"
        other = "https://journal.example/other"
        self.write_unit("exampleland", "2021-01", [
            card("S023", target, access_attempts=[
                {"requested_url": target, "result": "Cache miss; no HTTP response."},
                {"requested_url": target, "result": "TLS handshake timed out before HTTP response."},
            ]),
            card("S025", other),
        ])
        self.write_checks([{
            "unit_id": "exampleland_2021-01",
            "source_ids": ["S023", "S025"],
            "source_urls": [target, other],
            "assessment": "S023 cache miss then DNS failure; no HTTP status.",
        }])

        before_denial = self.run_check(target)
        other_result = self.run_check(other)
        self.assertEqual(before_denial["decision"], "manual_review")
        self.assertEqual(before_denial["observed_exact_denials"], [])
        self.assertTrue(before_denial["retrieval_failures"])
        self.assertEqual(other_result["decision"], "manual_review")

        self.write_checks([{
            "unit_id": "exampleland_2021-01",
            "source_ids": ["S023", "S025"],
            "source_urls": [target, other],
            "assessment": "S023403/exit0/no body; S025 stayed accessible.",
        }])
        after_denial = self.run_check(target)
        other_after_denial = self.run_check(other)
        self.assertEqual(after_denial["decision"], "hold")
        self.assertEqual(after_denial["observed_exact_denials"][0]["denial_kinds"],
                         ["saved_prose_source_id_match"])
        self.assertEqual(other_after_denial["decision"], "manual_review")
        self.assertIn("review/source_checks.jsonl", after_denial["refreshed_inputs"])

    def test_added_changed_and_removed_files_refresh_only_their_entries(self):
        old_path = self.write_unit("oldland", "2021-01", [card("OLD", "https://old.example/story")])
        changed_path = self.write_unit("exampleland", "2021-01", [card("S001", "https://one.example/story")])
        self.write_checks([])
        first = self.run_check("https://old.example/story")
        self.assertEqual(first["decision"], "manual_review")

        old_path.unlink()
        self.write_unit("newland", "2021-02", [card("NEW", "https://new.example/story")])
        self.write_unit("exampleland", "2021-01", [card("S001", "https://one.example/story"),
                                                     card("S002", "https://two.example/story")])
        second = self.run_check("https://old.example/story")

        self.assertEqual(second["decision"], "manual_review")
        self.assertEqual(second["exact_url_matches"], [])
        self.assertIn("units/newland/2021-02/sources.jsonl", second["refreshed_inputs"])
        self.assertIn("units/exampleland/2021-01/sources.jsonl", second["refreshed_inputs"])
        self.assertIn("units/oldland/2021-01/sources.jsonl", second["removed_inputs"])
        self.assertIn("review/source_checks.jsonl", second["reused_inputs"])
        self.assertIn(changed_path.as_posix(), [str(self.root / p) for p in second["refreshed_inputs"]])

    def test_malformed_jsonl_and_unstable_input_defer_without_replacing_cache(self):
        path = self.write_unit("exampleland", "2021-01", [card("S001", "https://one.example/story")])
        initial = self.run_check("https://one.example/story")
        cached_bytes = self.cache.read_bytes()
        path.write_text(path.read_text(encoding="utf-8") + "{bad json}\n", encoding="utf-8")

        malformed = self.run_check("https://one.example/story")
        self.assertEqual(malformed["decision"], "defer")
        self.assertTrue(malformed["parse_errors"])
        self.assertEqual(self.cache.read_bytes(), cached_bytes)

        path.write_text(json.dumps(card("S001", "https://one.example/story")) + "\n", encoding="utf-8")
        original_snapshot = research.access_snapshot
        calls = {"count": 0}

        def change_between_fingerprints(root):
            calls["count"] += 1
            if calls["count"] == 2:
                path.write_text(json.dumps(card("S002", "https://two.example/story")) + "\n", encoding="utf-8")
            return original_snapshot(root)

        cached_before_unstable = self.cache.read_bytes()
        with mock.patch.object(research, "access_snapshot", side_effect=change_between_fingerprints):
            unstable = self.run_check("https://one.example/story")

        self.assertEqual(unstable["decision"], "defer")
        self.assertFalse(unstable["inputs_stable"])
        self.assertEqual(self.cache.read_bytes(), cached_before_unstable)
        self.assertTrue(initial["ok"])

    def test_durable_receipt_in_own_unit_folder_preserves_indexed_hashes(self):
        source_path = self.write_unit("exampleland", "2021-01", [card("S001", "https://example.test/")])
        self.write_checks([])
        before, errors = research.access_snapshot(self.root)
        self.assertEqual(errors, [])
        self.receipt = source_path.parent / "access_receipts" / "worker-001.json"

        result = self.run_check("https://example.test/")
        receipt_bytes = self.receipt.read_bytes()
        after, errors = research.access_snapshot(self.root)

        self.assertTrue(result["ok"])
        self.assertTrue(self.receipt.is_file())
        self.assertEqual(errors, [])
        self.assertEqual(
            {name: row["sha256"] for name, row in before.items()},
            {name: row["sha256"] for name, row in after.items()},
        )
        self.assertNotIn("units/exampleland/2021-01/access_receipts/worker-001.json",
                         [item["path"] for item in result["checked_inputs"]])

        duplicate = self.run_check("https://example.test/")
        self.assertFalse(duplicate["ok"])
        self.assertEqual(duplicate["decision"], "defer")
        self.assertIn("unique filename", duplicate["errors"][0])
        self.assertEqual(self.receipt.read_bytes(), receipt_bytes)

    def test_receipt_rejects_indexed_and_other_archive_files_and_cache_stays_outside(self):
        source_path = self.write_unit("exampleland", "2021-01", [card("S001", "https://example.test/")])
        checks_path = self.write_checks([])
        before = {source_path: source_path.read_bytes(), checks_path: checks_path.read_bytes()}
        invalid_paths = [
            source_path,
            checks_path,
            source_path.parent / "required-dossier-file.json",
        ]

        for receipt_path in invalid_paths:
            result = research.access_check(self.root, self.cache, receipt_path, "https://example.test/")
            self.assertFalse(result["ok"])
            self.assertEqual(result["decision"], "defer")
            self.assertIn("access_receipts", result["errors"][0])

        bad_cache = research.access_check(self.root, self.root / "cache.json",
                                          self.base / "receipt.json", "https://example.test/")
        self.assertFalse(bad_cache["ok"])
        self.assertEqual(bad_cache["decision"], "defer")
        self.assertIn("cache path must be outside", bad_cache["errors"][0])
        self.assertEqual({path: path.read_bytes() for path in before}, before)


if __name__ == "__main__":
    unittest.main()
