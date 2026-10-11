#!/usr/bin/env python3
"""Regression: Unicode separators inside JSON strings are not JSONL boundaries."""
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class JsonlSeparatorsTest(unittest.TestCase):
    def test_consolidation_and_year_delivery_preserve_unicode(self):
        scripts = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(prefix='jsonl-separators-') as temporary:
            root = Path(temporary) / 'input'
            for directory in ['planning', 'review', 'units/example/2023-01', 'protocol']:
                (root / directory).mkdir(parents=True, exist_ok=True)
            shutil.copytree(scripts, root / 'scripts')
            unit = root / 'units/example/2023-01'
            identity = {'unit_id': 'example_2023-01', 'country': 'Example', 'month': '2023-01'}
            plan = {**identity, 'directory': 'units/example/2023-01', 'agent_task': '/fixture',
                    'queue_order': '1', 'status': 'researched_open_web_pending_review'}
            with (root / 'planning/coverage_matrix.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(plan))
                writer.writeheader()
                writer.writerow(plan)
            def save(path, value):
                path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
            save(unit / 'assignment.json', identity)
            for name in ['events.json', 'excluded.json', 'continuations.json', 'gaps.json']:
                save(unit / name, [])
            (unit / 'search_log.jsonl').write_text('')
            (unit / 'report.txt').write_text('Synthetic regression fixture.')
            source = {'source_id': 'S1', 'url': 'https://example.invalid/source',
                      'title': 'Before\u2028between\u2029after', 'access_status': 'search_only'}
            (unit / 'sources.jsonl').write_text(json.dumps(source, ensure_ascii=False) + '\n')
            save(unit / 'status.json', {**identity, 'status': plan['status'], 'n_sources': 1,
                 'n_queries': 0, 'n_candidates': 0, 'n_excluded': 0, 'n_continuations': 0, 'n_gaps': 0})
            checks = [{'url': source['url'], 'note': source['title']}, {'url': source['url'], 'note': 'Second'}]
            (root / 'review/source_checks.jsonl').write_text(''.join(
                json.dumps(row, ensure_ascii=False) + '\n' for row in checks))
            subprocess.run([sys.executable, str(root / 'scripts/consolidate.py'), '--root', str(root)],
                           check=True, capture_output=True, text=True)
            self.assertEqual(json.loads((root / 'review/validation_issues.json').read_text()), [])
            self.assertEqual(json.loads((root / 'aggregate/sources.json').read_text())[0]['title'], source['title'])
            output = Path(temporary) / 'delivery'
            subprocess.run([sys.executable, str(root / 'scripts/build_year_delivery.py'), '--root', str(root),
                            '--year', '2023', '--output', str(output)], check=True, capture_output=True, text=True)
            self.assertEqual([json.loads(line) for line in (output / 'review/source_checks.jsonl').read_text().split('\n')
                              if line.strip()], checks)
            self.assertEqual(json.loads((output / 'summary.json').read_text())['researched_country_months'], 1)


if __name__ == '__main__':
    unittest.main()
