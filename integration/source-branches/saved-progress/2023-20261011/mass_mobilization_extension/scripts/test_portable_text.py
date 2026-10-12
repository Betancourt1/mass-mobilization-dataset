#!/usr/bin/env python3
"""Check safe export fingerprints and byte-preserved research inputs."""
import copy
import hashlib
import json
import pathlib
import tempfile
import unittest
from build_year_delivery import portable_text, copy_portable


class PortableTextTest(unittest.TestCase):
    def test_long_source_text_is_omitted_without_changing_research(self):
        source = {'query_id': 'Q1', 'returned_results': [
            {'title': 'passage ' * 32, 'url': 'https://example.test/report', 'order': 1}],
            'raw_response': 'raw passage ' * 30, 'display_metadata': '[wordlim: 200] ' + 'excerpt ' * 80, 'notes': 'research judgment ' * 300,
            'participants_min': None, 'source_ids': ['S1'], 'summary': 'copied source prose ' * 22,
            'returned_urls': ['https://example.test/' + '-'.join(['slug'] * 60), 'https://example.test/report?source=two']}
        original = copy.deepcopy(source)
        omissions = []
        exported = portable_text(source, 'queries.json/0', omissions,
                                 {hashlib.sha256(source['summary'].encode()).hexdigest()})
        self.assertEqual(source, original)
        self.assertEqual(portable_text({'summary': 'authored analysis ' * 50}, 'note.json', [],
                                       {hashlib.sha256(source['summary'].encode()).hexdigest()}),
                         {'summary': 'authored analysis ' * 50})
        self.assertEqual(portable_text('authored analysis ' * 50, 'note.json', []),
                         'authored analysis ' * 50)
        self.assertEqual(exported['notes'], source['notes'])
        self.assertEqual(exported['returned_results'][0]['url'], source['returned_results'][0]['url'])
        self.assertEqual(exported['source_ids'], ['S1'])
        self.assertEqual(len(omissions), 4)
        self.assertEqual(exported['returned_urls'][0], source['returned_urls'][0])
        self.assertEqual(len(exported['returned_urls']), 2)
        self.assertEqual(exported['returned_urls'][1], source['returned_urls'][1])
        for field, value in [('raw_response', source['raw_response']),
                             ('display_metadata', source['display_metadata']),
                             ('summary', source['summary']),
                             ('title', source['returned_results'][0]['title'])]:
            record = next(row for row in omissions if row['field'].endswith('/' + field))
            self.assertEqual(record['original_sha256'], hashlib.sha256(value.encode()).hexdigest())
            self.assertFalse(record['original_text_included'])
            self.assertNotIn(value, json.dumps(exported))

    def test_jsonl_copy_preserves_unicode_records_and_original_bytes(self):
        with tempfile.TemporaryDirectory(prefix='portable-text-test-') as directory:
            source = pathlib.Path(directory) / 'source.jsonl'
            target = pathlib.Path(directory) / 'export.jsonl'
            rows = [{'query_id': 'Q1', 'title': 'short\u2028native title'},
                    {'query_id': 'Q2', 'raw_header': 'protected ' * 40}]
            original = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows).encode()
            source.write_bytes(original)
            omissions = []
            copy_portable(source, target, 'source.jsonl', omissions)
            self.assertEqual(source.read_bytes(), original)
            saved = [json.loads(line) for line in target.read_text().split('\n') if line.strip()]
            self.assertEqual(saved[0], rows[0])
            self.assertEqual(saved[1]['query_id'], 'Q2')
            self.assertEqual(saved[1]['raw_header_portable_metadata']['original_word_count'], 40)
            self.assertEqual(len(saved), 2)
            self.assertEqual(len(omissions), 1)


    def test_historical_literal_newline_projects_without_rewriting_original(self):
        with tempfile.TemporaryDirectory(prefix='portable-snapshot-test-') as directory:
            root = pathlib.Path(directory)
            source = root / 'capture_revisions' / 'search_capture.json'
            source.parent.mkdir()
            original = json.dumps({'title': 'protected ' * 30}).encode() + b'\\n'
            source.write_bytes(original)
            target = root / 'export.json'
            omissions = []
            copy_portable(source, target, 'capture_revisions/search_capture.json', omissions)
            saved = json.loads(target.read_text())
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(saved['title'], '[Source text omitted from portable export]')
            self.assertEqual(saved['historical_capture_encoding_correction']['original_sha256'],
                             hashlib.sha256(original).hexdigest())
            self.assertEqual(saved['historical_capture_encoding_correction']['original_bytes'], len(original))
            current = root / 'search_capture.json'
            current.write_bytes(original)
            with self.assertRaises(json.JSONDecodeError):
                copy_portable(current, target, 'search_capture.json', [])
            source.write_bytes(b'{"query_id":"Q1"}garbage')
            with self.assertRaises(json.JSONDecodeError):
                copy_portable(source, target, 'capture_revisions/search_capture.json', [])


    def test_raw_capture_aliases_are_omitted_and_authored_scope_is_preserved(self):
        aliases = ['first_response_text', 'native_header', 'discovery_title']
        source = {key: 'captured source words ' * 10 for key in aliases}
        source['known_same_article_card'] = 'Authored access comparison ' * 10
        source['content'] = 'Authored event recovery description ' * 10
        original = copy.deepcopy(source)
        omissions = []
        saved = portable_text(source, 'capture.json', omissions)
        self.assertEqual(source, original)
        self.assertEqual(len(omissions), 3)
        for key in aliases:
            self.assertEqual(saved[key], '[Source text omitted from portable export]')
            self.assertEqual(saved[key + '_portable_metadata']['original_sha256'],
                             hashlib.sha256(source[key].encode()).hexdigest())
        self.assertEqual(saved['known_same_article_card'], source['known_same_article_card'])
        self.assertEqual(saved['content'], source['content'])


if __name__ == '__main__':
    unittest.main()
