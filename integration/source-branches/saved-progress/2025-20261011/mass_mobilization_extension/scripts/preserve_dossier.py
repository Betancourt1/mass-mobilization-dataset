#!/usr/bin/env python3
"""Preserve exact authored dossier bytes before one guarded 2025 update."""
import argparse
import datetime
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
import uuid

FILES = ('search_log.jsonl', 'sources.jsonl', 'events.json', 'excluded.json',
         'continuations.json', 'gaps.json', 'report.txt', 'status.json')
ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def exclusive(path, data):
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def guarded_write(unit, filename, data, expected_sha256, reason):
    unit = Path(unit)
    if any(path.is_symlink() for path in (unit, unit.parent, unit.parent.parent)) or filename not in FILES:
        raise ValueError('Only the eight authored dossier files may be updated.')
    unit = unit.resolve(strict=True)
    relative = unit.relative_to(ROOT / 'units')
    if len(relative.parts) != 2 or re.fullmatch(r'2025-(0[1-9]|1[0-2])', unit.name) is None:
        raise ValueError('This isolated writer accepts 2025 monthly units only.')
    if not reason.strip():
        raise ValueError('A preservation reason is required.')
    quarantine = ROOT / 'sessions/2025/writer_quarantine.json'
    if quarantine.exists():
        hold = json.loads(quarantine.read_text())
        assignment = json.loads((unit / 'assignment.json').read_text())
        suspended = set(hold.get('additional_suspended_writers', []))
        if hold.get('writer_suspended'):
            suspended.add(hold.get('affected_writer'))
        if assignment.get('agent_task') in suspended:
            raise ValueError('The affected writer is quarantined pending reviewed repair.')
    lock = unit / '.preserve-write.lock'
    lock.mkdir()  # Fail closed if another cooperative writer owns this unit.
    temporary = None
    try:
        original = {}
        for name in FILES:
            path = unit / name
            if path.is_symlink():
                raise ValueError('Symlink dossier files are refused.')
            original[name] = path.read_bytes()
        if digest(original[filename]) != expected_sha256:
            raise ValueError('Stale expected hash; no authored file was updated.')
        if filename.endswith('.json'):
            json.loads(data.decode('utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        elif filename.endswith('.jsonl'):
            for line in data.split(b'\n'):
                if line.strip():
                    json.loads(line.decode('utf-8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        history = unit / 'private_reading' / 'preservation'
        if history.is_symlink() or history.parent.is_symlink():
            raise ValueError('Symlink preservation directories are refused.')
        history.mkdir(parents=True, exist_ok=True)
        snapshot = history / str(uuid.uuid4())
        snapshot.mkdir()
        for name, raw in original.items():
            exclusive(snapshot / name, raw)
        record = {'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'reason': reason, 'unit': str(unit), 'updated_file': filename,
                  'files': {name: {'bytes': len(raw), 'sha256': digest(raw)}
                            for name, raw in original.items()},
                  'new_sha256': digest(data), 'new_bytes': len(data)}
        exclusive(snapshot / 'manifest.json', (json.dumps(record, indent=2) + '\n').encode())
        # Verify durable backup bytes and unchanged complete input set before replacement.
        for name, raw in original.items():
            if (snapshot / name).read_bytes() != raw or (unit / name).read_bytes() != raw:
                raise ValueError('Backup or current dossier changed; update refused.')
        with tempfile.NamedTemporaryFile(prefix='.preserve-write-', dir=unit, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, (unit / filename).stat().st_mode & 0o777)
        os.replace(temporary, unit / filename)
        temporary = None
        return {'preservation_manifest': str(snapshot / 'manifest.json'),
                'old_sha256': expected_sha256, 'new_sha256': digest(data)}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        lock.rmdir()


def guarded_capture(unit, filename, input_path, expected_sha256, reason,
                    operation, source_id=None):
    """Compute an existing CLI update privately; only the guard writes the dossier."""
    import research
    targets = {'capture-search': 'search_log.jsonl', 'save-source': 'sources.jsonl'}
    if operation not in targets or filename != targets[operation]:
        raise ValueError('Capture operation and authored target must match.')
    if operation == 'save-source' and not source_id:
        raise ValueError('save-source requires an exact source ID.')
    unit = Path(unit)
    # The disposable CLI never sees the canonical target as its mutation directory.
    old = (unit / filename).read_bytes()
    if digest(old) != expected_sha256:
        raise ValueError('Stale expected hash; capture computation and write refused.')
    with tempfile.TemporaryDirectory(prefix='preserve-capture-') as temporary:
        shadow = Path(temporary)
        (shadow / filename).write_bytes(old)
        if operation == 'capture-search':
            result = research.capture_search(shadow, input_path)
        else:
            result = research.save_source(shadow, source_id, input_path)
        if not result.get('ok'):
            raise ValueError('Capture validation failed: ' + json.dumps(result))
        data = (shadow / filename).read_bytes()
    # Rechecks scope, quarantine, lock, current SHA and all durable backup bytes.
    proof = guarded_write(unit, filename, data, expected_sha256, reason)
    return {'capture_result': result, **proof}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit', required=True, type=Path)
    parser.add_argument('--file', required=True, choices=FILES)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--reason', required=True)
    parser.add_argument('--operation', choices=('write', 'capture-search', 'save-source'), default='write')
    parser.add_argument('--source-id')
    args = parser.parse_args()
    if args.operation == 'write':
        result = guarded_write(args.unit, args.file, args.input.read_bytes(), args.expected_sha256, args.reason)
    else:
        result = guarded_capture(args.unit, args.file, args.input, args.expected_sha256,
                                 args.reason, args.operation, args.source_id)
    print(json.dumps(result, indent=2))
