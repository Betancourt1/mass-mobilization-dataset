"""Refresh staging file availability only; no scientific validation or peer review."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

root = Path(__file__).resolve().parent
queue_path = root / 'queue.json'
queue = json.loads(queue_path.read_text())
staged = []
for package in queue['packages']:
    underscored = package['country'].lower().replace(' ', '_').replace('-', '_')
    hyphenated = package['country'].lower().replace(' ', '-')
    candidates = [root / underscored / 'discovery.json', root / hyphenated / 'discovery.json']
    if package['country'] == 'United Arab Emirate':
        candidates.append(root / 'united-arab-emirates' / 'discovery.json')
    artifact = next((p for p in candidates if p.is_file()), None)
    if artifact is not None:
        package['status'] = 'provisional_discovery_staged'
        package['artifact'] = str(artifact)
        staged.append({
            'country': package['country'],
            'path': str(artifact),
            'bytes': artifact.stat().st_size,
            'sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
            'canonical_validation': False,
            'supporting_artifacts': [
                {
                    'path': str(support),
                    'bytes': support.stat().st_size,
                    'sha256': hashlib.sha256(support.read_bytes()).hexdigest(),
                }
                for support in sorted(artifact.parent.iterdir())
                if support.is_file() and support != artifact
            ],
        })
    else:
        package['status'] = 'assigned_for_discovery'
queue['formal_firstpass_units_completed'] = 0
queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + '\n')
checkpoint_path = root / 'checkpoint.json'
checkpoint = json.loads(checkpoint_path.read_text())
checkpoint['updated_at_utc'] = datetime.now(timezone.utc).isoformat()
checkpoint['provisional_country_packages_staged'] = len(staged)
checkpoint['country_month_scope_represented_in_staging'] = 3 * len(staged)
checkpoint['scientific_firstpass_units_completed'] = 0
checkpoint['researchers_launched'] = 6
checkpoint['public_discovery_allowed'] = True
checkpoint['canonical_integration_available'] = False
checkpoint['automatic_resume'] = False
checkpoint['evidence_complete'] = False
checkpoint['batches_with_all_four_country_artifacts'] = [
    b for b in range(1, 41)
    if all(p['status'] == 'provisional_discovery_staged'
           for p in queue['packages'] if p['batch'] == b)
]
checkpoint_path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2) + '\n')
(root / 'STAGING_ARTIFACTS.json').write_text(json.dumps({
    'artifact_type': 'file availability and checksums only; not scientific acceptance',
    'quarter': '2026Q2',
    'files': staged,
}, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({
    'provisional_country_packages_staged': len(staged),
    'country_month_scope_represented_in_staging': 3 * len(staged),
    'canonical_validated_units': 0,
    'batches_with_all_four_country_artifacts': checkpoint['batches_with_all_four_country_artifacts'],
}))
