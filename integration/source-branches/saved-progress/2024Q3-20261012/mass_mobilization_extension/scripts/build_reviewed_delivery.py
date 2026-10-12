#!/usr/bin/env python3
"""Build the delivery with dated coordinator updates beside historical gaps."""
import argparse
import datetime
import hashlib
import html
import json
import pathlib
import re
import subprocess
import sys
import zipfile

parser = argparse.ArgumentParser()
parser.add_argument('--output', required=True)
args = parser.parse_args()
root = pathlib.Path(__file__).resolve().parents[1]
subprocess.run([sys.executable, str(root / 'scripts/build_delivery.py'),
                '--output', args.output], check=True)
updates = json.loads((root / 'review/gap_followups.json').read_text())
index = root / 'review/index.html'
body = index.read_text()
for update in updates:
    prefix = '<tr><td>' + html.escape(update['unit_id']) + '</td><td>'
    prefix += html.escape(update['gap_id']) + '</td><td>'
    pattern = '(' + re.escape(prefix) + r'[^<]*</td><td>)(.*?)(</td><td>)'
    links = ' · '.join('<a href="' + html.escape(name, quote=True) + '">' +
                       html.escape(name) + '</a>' for name in update['evidence_files'])
    note = '<p data-coordinator-followup="' + html.escape(update['gap_id'], quote=True)
    note += '"><strong>Coordinator follow-up ' + html.escape(update['reviewed_at'])
    note += ':</strong> ' + html.escape(update['description']) + '<br>' + links + '</p>'
    body, count = re.subn(pattern, lambda match: match[1] + match[2] + note + match[3],
                         body, flags=re.DOTALL)
    if count != 1:
        raise ValueError('Expected one rendered gap: ' + update['gap_id'])
index.write_text(body)

# Refresh only the generated package after inserting the dated review notes.
manifest_path = root / 'manifest.json'
manifest = json.loads(manifest_path.read_text())
manifest['created_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
for entry in manifest['files']:
    content = (root / entry['path']).read_bytes()
    entry.update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
temporary = manifest_path.with_suffix('.json.tmp')
temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
temporary.replace(manifest_path)
archive = pathlib.Path(args.output) / 'mass_mobilization_etapa_1.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as package:
    for name in sorted([entry['path'] for entry in manifest['files']] + ['manifest.json']):
        package.write(root / name, pathlib.Path(root.name) / name)
print(json.dumps({'zip': str(archive.resolve()), 'coordinator_gap_updates': len(updates),
                  'bytes': archive.stat().st_size,
                  'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}, indent=2))
