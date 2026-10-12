import importlib.util
import json
import os
import pathlib
import tempfile
import unittest


DEFAULT_SCRIPT = pathlib.Path(__file__).with_name("research.py")
SCRIPT = pathlib.Path(os.environ.get("MM_RESEARCH_SCRIPT", DEFAULT_SCRIPT)).resolve()
spec = importlib.util.spec_from_file_location("research_under_test", SCRIPT)
research = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(research)


def source(source_id, url, publisher, **extra):
    return {"source_id": source_id, "url": url, "publisher": publisher,
            "access_status": "search_only", **extra}


def denied_check(url):
    return {"access_status": "blocked", "url": url,
            "response": {"http": {"status": 403}}}


class PublisherScopeAliasRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mm-publisher-scope-test-")
        self.base = pathlib.Path(self.temp.name)
        self.root = self.base / "archive"
        self.unit = self.root / "units" / "exampleland" / "2022-01"
        self.unit.mkdir(parents=True)
        (self.root / "review").mkdir(parents=True)
        (self.cache_dir).mkdir(parents=True, exist_ok=True)
        self.cache = self.base / "temporary" / "access-index.json"
        self.receipt_dir = self.base / "temporary" / "receipts"
        self.receipt_dir.mkdir(parents=True)
        self.receipt_number = 0

    @property
    def cache_dir(self):
        return self.base / "temporary"

    def tearDown(self):
        self.temp.cleanup()

    def write_archive(self, cards, checks):
        (self.unit / "sources.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in cards),
            encoding="utf-8")
        (self.root / "review" / "source_checks.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in checks),
            encoding="utf-8")

    def check(self, url):
        self.receipt_number += 1
        receipt = self.receipt_dir / f"receipt-{self.receipt_number}.json"
        result = research.access_check(self.root, self.cache, receipt, url)
        self.assertTrue(result["ok"], result)
        self.assertFalse(result["automatic_retrieval_authorized"])
        return result

    def test_saved_amp_alias_holds_new_url_and_existing_exact_card_only(self):
        denied_url = "https://amp.dw.com/old-story"
        new_url = "https://amp.dw.com/new-story"
        exact_url = "https://amp.dw.com/existing-story"
        unrelated_url = "https://example.net/new-story"
        scope = {
            "publisher_alias_scope": ["amp.dw.com", "Deutsche Welle"],
            "actual_denials": [{"url": denied_url, "http_status": 403}],
        }
        self.write_archive(
            [source("S001", denied_url, "Deutsche Welle", access_prescreen_snapshot=scope),
             source("S002", exact_url, "Deutsche Welle"),
             source("S003", unrelated_url, "Unrelated News")],
            [denied_check(denied_url)])

        new_target = self.check(new_url)
        self.assertEqual(new_target["exact_url_matches"], [])
        self.assertEqual(new_target["decision"], "hold")
        self.assertEqual(len(new_target["publisher_scope_holds"]), 1)
        self.assertEqual(new_target["observed_exact_denials"], [])
        self.assertEqual(new_target["documented_written_origin_matches"], [])

        existing_target = self.check(exact_url)
        self.assertEqual(existing_target["decision"], "hold")
        self.assertTrue(existing_target["exact_url_matches"])
        self.assertEqual(len(existing_target["publisher_scope_holds"]), 1)
        self.assertEqual(existing_target["observed_exact_denials"], [])

        unrelated_target = self.check(unrelated_url)
        self.assertEqual(unrelated_target["decision"], "manual_review")
        self.assertEqual(unrelated_target["publisher_scope_holds"], [])
        self.assertEqual(unrelated_target["observed_exact_denials"], [])
        self.assertEqual(unrelated_target["documented_written_origin_matches"], [])

    def test_text_alias_uses_observed_exact_host_without_inference(self):
        denied_url = "https://dw.example/denied"
        observed_url = "https://amp.dw.com/archived-story"
        new_url = "https://amp.dw.com/new-story"
        subdomain_url = "https://news.amp.dw.com/new-story"
        unrelated_url = "https://other.example/story"
        scope = {
            "publisher_alias_scope": ["Deutsche Welle"],
            "actual_denials": [{"url": denied_url, "http_status": 403}],
            "matched_source_cards": [{"card": {
                "source_id": "S002", "publisher": "Deutsche Welle", "url": observed_url,
            }}],
        }
        self.write_archive(
            [source("S001", denied_url, "Deutsche Welle", access_prescreen_snapshot=scope),
             source("S002", observed_url, "Deutsche Welle"),
             source("S003", unrelated_url, "Deutsche Welle")],
            [denied_check(denied_url)])

        new_target = self.check(new_url)
        self.assertEqual(new_target["exact_url_matches"], [])
        self.assertEqual(new_target["decision"], "hold")
        self.assertEqual(len(new_target["publisher_scope_holds"]), 1)
        self.assertEqual(new_target["observed_exact_denials"], [])

        existing_target = self.check(observed_url)
        self.assertEqual(existing_target["decision"], "hold")
        self.assertTrue(existing_target["exact_url_matches"])
        self.assertEqual(len(existing_target["publisher_scope_holds"]), 1)

        subdomain_target = self.check(subdomain_url)
        self.assertEqual(subdomain_target["decision"], "manual_review")
        self.assertEqual(subdomain_target["publisher_scope_holds"], [])

        unrelated_target = self.check(unrelated_url)
        self.assertEqual(unrelated_target["decision"], "manual_review")
        self.assertEqual(unrelated_target["publisher_scope_holds"], [])
        self.assertEqual(unrelated_target["observed_exact_denials"], [])

    def test_exact_denial_and_written_origin_remain_distinct(self):
        denied_url = "https://wire.example/story"
        linked_url = "https://reprint.example/story"
        self.write_archive(
            [source("S010", denied_url, "Wire Publisher"),
             source("S011", linked_url, "Reprint Publisher",
                    same_story_variant_source_ids=["S010"])],
            [denied_check(denied_url)])

        exact_denial = self.check(denied_url)
        self.assertEqual(exact_denial["decision"], "hold")
        self.assertTrue(exact_denial["observed_exact_denials"])
        self.assertEqual(exact_denial["observed_exact_denials"][0]["denial_kinds"], ["http_403"])
        self.assertEqual(exact_denial["publisher_scope_holds"], [])

        linked_story = self.check(linked_url)
        self.assertEqual(linked_story["decision"], "hold")
        self.assertEqual(linked_story["observed_exact_denials"], [])
        self.assertEqual(linked_story["publisher_scope_holds"], [])
        self.assertEqual(len(linked_story["documented_written_origin_matches"]), 1)
        self.assertEqual(
            linked_story["documented_written_origin_matches"][0]["denials"][0]["denial_kinds"],
            ["http_403"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
