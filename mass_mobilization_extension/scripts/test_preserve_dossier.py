import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import preserve_dossier as writer


class PreservationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.root_patch = patch.object(writer, 'ROOT', self.root)
        self.root_patch.start()
        self.unit = self.root / 'units/example/2025-05'
        self.unit.mkdir(parents=True)
        self.original = {}
        for name in writer.FILES:
            data = b'[]\r\n' if name.endswith('.json') else ('original\u2028text\r\n'.encode() if name == 'report.txt' else b'')
            (self.unit / name).write_bytes(data)
            self.original[name] = data
        (self.unit / 'assignment.json').write_text(json.dumps({'agent_task': '/root/example'}))

    def tearDown(self):
        self.root_patch.stop()
        self.temporary.cleanup()

    def update(self, expected=None):
        return writer.guarded_write(self.unit, 'events.json', b'[{"candidate_id":"new"}]\n',
                                    expected or writer.digest(self.original['events.json']), 'review correction')

    def test_exact_all_eight_bytes_preserved_before_update(self):
        result = self.update()
        manifest = Path(result['preservation_manifest'])
        record = json.loads(manifest.read_text())
        for name, raw in self.original.items():
            self.assertEqual((manifest.parent / name).read_bytes(), raw)
            self.assertEqual(record['files'][name]['sha256'], writer.digest(raw))
        self.assertEqual(json.loads((self.unit / 'events.json').read_text())[0]['candidate_id'], 'new')

    def test_stale_hash_refuses_write(self):
        with self.assertRaisesRegex(ValueError, 'Stale'):
            self.update('0' * 64)
        self.assertEqual((self.unit / 'events.json').read_bytes(), self.original['events.json'])
        self.assertFalse((self.unit / '.preserve-write.lock').exists())

    def test_backup_failure_refuses_write(self):
        with patch.object(writer, 'exclusive', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.update()
        self.assertEqual((self.unit / 'events.json').read_bytes(), self.original['events.json'])
        self.assertFalse((self.unit / '.preserve-write.lock').exists())

    def test_concurrent_input_change_refuses_write(self):
        actual = writer.exclusive
        def changing(path, data):
            actual(path, data)
            if path.name == 'manifest.json':
                (self.unit / 'sources.jsonl').write_bytes(b'{"concurrent":true}\n')
        with patch.object(writer, 'exclusive', side_effect=changing):
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.update()
        self.assertEqual((self.unit / 'events.json').read_bytes(), self.original['events.json'])

    def test_existing_lock_refuses_write(self):
        (self.unit / '.preserve-write.lock').mkdir()
        with self.assertRaises(FileExistsError):
            self.update()
        self.assertEqual((self.unit / 'events.json').read_bytes(), self.original['events.json'])

    def test_quarantined_writer_refuses_write(self):
        session = self.root / 'sessions/2025'
        session.mkdir(parents=True)
        (session / 'writer_quarantine.json').write_text(json.dumps({'writer_suspended': True, 'affected_writer': '/root/example'}))
        with self.assertRaisesRegex(ValueError, 'quarantined'):
            self.update()
        self.assertEqual((self.unit / 'events.json').read_bytes(), self.original['events.json'])

    def test_invalid_json_refuses_write(self):
        with self.assertRaises(ValueError):
            writer.guarded_write(self.unit, 'events.json', b'{bad}', writer.digest(self.original['events.json']), 'test')
        self.assertEqual((self.unit / 'events.json').read_bytes(), self.original['events.json'])

    def test_symlink_history_refused_before_creating_external_backup(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (self.unit / 'private_reading').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            self.update()
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual((self.unit / 'events.json').read_bytes(), self.original['events.json'])

    def test_outside_named_units_tree_refused(self):
        outside = self.root / 'outside/units/example/2025-05'
        outside.mkdir(parents=True)
        with self.assertRaises(ValueError):
            writer.guarded_write(outside, 'events.json', b'[]', '0' * 64, 'test')
        self.assertEqual(list(outside.iterdir()), [])

    def test_invalid_month_refused(self):
        invalid = self.root / 'units/example/2025-13'
        invalid.mkdir()
        with self.assertRaises(ValueError):
            writer.guarded_write(invalid, 'events.json', b'[]', '0' * 64, 'test')
        self.assertEqual(list(invalid.iterdir()), [])

    def test_second_update_preserves_first_version_without_overwriting_history(self):
        first = self.update()
        data = (self.unit / 'events.json').read_bytes()
        second = writer.guarded_write(self.unit, 'events.json', b'[]\n', writer.digest(data), 'second correction')
        self.assertNotEqual(first['preservation_manifest'], second['preservation_manifest'])
        self.assertEqual((Path(second['preservation_manifest']).parent / 'events.json').read_bytes(), data)
        self.assertEqual((Path(first['preservation_manifest']).parent / 'events.json').read_bytes(), self.original['events.json'])

    def capture_record(self):
        path = self.root / 'capture.json'
        path.write_text(json.dumps({'query_id': 'Q001', 'query': 'actual query', 'tool': 'web__run',
            'returned_results': [{'order': 1, 'title': 'Visible title', 'url': 'https://example.com/story', 'ref': 'turn1search0'}],
            'returned_urls': ['https://example.com/story'], 'notes': 'Actual recorded invocation.'}))
        return path

    def capture(self, expected=None):
        return writer.guarded_capture(self.unit, 'search_log.jsonl', self.capture_record(),
            expected or writer.digest((self.unit / 'search_log.jsonl').read_bytes()),
            'Actual capture with fail-closed preservation', 'capture-search')

    def test_capture_success_preserves_all_eight_before_canonical_append(self):
        result = self.capture()
        self.assertTrue(result['capture_result']['ok'])
        snapshot = Path(result['preservation_manifest']).parent
        for name, raw in self.original.items():
            self.assertEqual((snapshot / name).read_bytes(), raw)
            if name != 'search_log.jsonl':
                self.assertEqual((self.unit / name).read_bytes(), raw)
        self.assertEqual(json.loads((self.unit / 'search_log.jsonl').read_text())['query_id'], 'Q001')

    def test_capture_stale_guard_never_calls_raw_cli(self):
        import research
        with patch.object(research, 'capture_search') as raw:
            with self.assertRaisesRegex(ValueError, 'Stale'):
                self.capture('0' * 64)
            raw.assert_not_called()
        for name, data in self.original.items():
            self.assertEqual((self.unit / name).read_bytes(), data)

    def test_capture_duplicate_or_invalid_record_cannot_mutate_canonical(self):
        self.capture()
        old = (self.unit / 'search_log.jsonl').read_bytes()
        with self.assertRaisesRegex(ValueError, 'validation failed'):
            self.capture()
        self.assertEqual((self.unit / 'search_log.jsonl').read_bytes(), old)

    def test_capture_backup_failure_cannot_append_canonical(self):
        with patch.object(writer, 'exclusive', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.capture()
        for name, data in self.original.items():
            self.assertEqual((self.unit / name).read_bytes(), data)

    def test_additional_suspended_writer_refused(self):
        session = self.root / 'sessions/2025'
        session.mkdir(parents=True)
        (session / 'writer_quarantine.json').write_text(json.dumps({'writer_suspended': False,
            'additional_suspended_writers': ['/root/example']}))
        with self.assertRaisesRegex(ValueError, 'quarantined'):
            self.capture()
        self.assertEqual((self.unit / 'search_log.jsonl').read_bytes(), b'')

    def test_save_source_preserves_original_bytes_and_unaffected_record(self):
        source = {'source_id': 'S001', 'url': 'https://example.com/story', 'title': 'Title',
                  'access_status': 'search_only', 'publication_date': None, 'accessed_at': None}
        second = dict(source, source_id='S002', title='Other\u2028title')
        unchanged = json.dumps(second, ensure_ascii=False).encode() + b'\r\n'
        old = json.dumps(source).encode() + b'\r\n' + unchanged
        (self.unit / 'sources.jsonl').write_bytes(old)
        patch_path = self.root / 'source_patch.json'
        patch_path.write_text(json.dumps({'source_id': 'S001', 'title': 'Corrected title'}))
        result = writer.guarded_capture(self.unit, 'sources.jsonl', patch_path,
            writer.digest(old), 'Correct metadata', 'save-source', 'S001')
        self.assertEqual((Path(result['preservation_manifest']).parent / 'sources.jsonl').read_bytes(), old)
        self.assertTrue((self.unit / 'sources.jsonl').read_bytes().endswith(unchanged))

    def test_capture_operation_target_mismatch_refused(self):
        with self.assertRaisesRegex(ValueError, 'must match'):
            writer.guarded_capture(self.unit, 'events.json', self.capture_record(),
                writer.digest(self.original['events.json']), 'Invalid target', 'capture-search')
        self.assertEqual((self.unit / 'events.json').read_bytes(), self.original['events.json'])


if __name__ == '__main__':
    unittest.main()
