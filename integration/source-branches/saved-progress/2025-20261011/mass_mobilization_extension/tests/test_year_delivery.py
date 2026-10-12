import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest


SCRIPTS = pathlib.Path(__file__).parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('year_delivery', SCRIPTS / 'build_year_delivery.py')
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


class SetupDeliveryTests(unittest.TestCase):
    def test_setup_archive_reports_no_completed_research(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = pathlib.Path(temporary)
            root = base / 'data'
            for name in ('planning', 'review', 'aggregate', 'scripts'):
                (root / name).mkdir(parents=True)
            (root / 'planning/coverage_matrix.csv').write_text(
                'unit_id,country,month,directory,status\n'
                'example_2025-01,Example,2025-01,units/example/2025-01,assigned_researching\n')
            (root / 'review/validation_issues.json').write_text('[]')
            for name in delivery.SETS:
                (root / 'aggregate' / (name + '.json')).write_text('[]')
            shutil.copyfile(SCRIPTS / 'consolidate.py', root / 'scripts/consolidate.py')
            result = delivery.build(root, 2025, base / 'output')
            summary = json.loads((base / 'output/summary.json').read_text())
            self.assertEqual(summary['researched_country_months'], 0)
            self.assertEqual(summary['remaining_first_passes'], 1)
            self.assertIn('No completed', summary['coverage_claim'])
            self.assertEqual(result['summary'], summary)
            self.assertIn('0 first passes / 1 planned', (base / 'output/index.html').read_text())


if __name__ == '__main__':
    unittest.main()
