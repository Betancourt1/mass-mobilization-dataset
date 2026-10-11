#!/usr/bin/env python3
"""Package an annual first-pass research cohort without changing its judgments."""
import argparse
import collections
import csv
import datetime
import hashlib
import html
import io
import json
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile

SETS = ('candidates', 'sources', 'queries', 'gaps', 'excluded', 'continuations',
        'evidence_by_field', 'unit_summary')
FINISHED = {'researched_open_web_pending_review', 'root_reviewed_open_gaps'}
PRIVATE = {'mm_codebook.txt', 'mm_codebook.pdf'}


def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def cell(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return '' if value is None else str(value)


def export_csv(path, rows):
    fields = sorted({key for row in rows for key in row}) or ['empty']
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows({key: cell(row.get(key)) for key in fields} for row in rows)
    path.write_bytes(stream.getvalue().encode('utf-8-sig'))
    saved = list(csv.DictReader(path.open(encoding='utf-8-sig')))
    assert saved == [{key: cell(row.get(key)) for key in fields} for row in rows]


def allowed(path):
    return path.is_file() and path.name not in PRIVATE and not any(
        part in {'private_reading', '__pycache__'} for part in path.parts)


def omit_source_text(value, location, omissions):
    metadata = {'field': location,
                'original_sha256': hashlib.sha256(value.encode('utf-8')).hexdigest(),
                'original_word_count': len(value.split()), 'original_text_included': False}
    omissions.append(metadata)
    return '[Source text omitted from portable export]', metadata


def portable_text(value, location, omissions, reviewed_hashes=()):
    """Keep fingerprints while omitting raw passages and reviewed copied summaries."""
    if isinstance(value, list):
        return [portable_text(item, location + '/' + str(i), omissions, reviewed_hashes)
                for i, item in enumerate(value)]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        field = location + '/' + key
        raw_passage = (key in {'raw_response', 'raw_header', 'display_metadata', 'title',
                               'first_response_text', 'native_header', 'discovery_title'}
                       and isinstance(item, str) and len(item.split()) > 20)
        reviewed_copy = (key == 'summary' and isinstance(item, str)
                         and hashlib.sha256(item.encode('utf-8')).hexdigest() in reviewed_hashes)
        if raw_passage or reviewed_copy:
            result[key], result[key + '_portable_metadata'] = omit_source_text(item, field, omissions)
        else:
            result[key] = portable_text(item, field, omissions, reviewed_hashes)
    return result


def copy_portable(source, target, location, omissions, reviewed_hashes=()):
    if source.suffix not in {'.json', '.jsonl'}:
        shutil.copyfile(source, target)
        return
    corrected_snapshot = False
    try:
        value = ([json.loads(line) for line in source.read_text().split('\n') if line.strip()]
                 if source.suffix == '.jsonl' else read(source))
    except json.JSONDecodeError:
        # Preserve the observed historical capture bug; current records still fail.
        if source.suffix != '.json' or 'capture_revisions' not in source.parts:
            raise
        text = source.read_text()
        value, end = json.JSONDecoder().raw_decode(text)
        if text[end:].strip() != r'\n' or not isinstance(value, dict):
            raise
        value['historical_capture_encoding_correction'] = {
            'original_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'original_bytes': source.stat().st_size,
            'reason': 'Literal backslash-n after completed JSON; original retained unchanged.'}
        corrected_snapshot = True
    before = len(omissions)
    value = portable_text(value, location, omissions, reviewed_hashes)
    if len(omissions) == before and not corrected_snapshot:
        shutil.copyfile(source, target)
    elif source.suffix == '.jsonl':
        target.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in value))
    else:
        dump(target, value)


def build(root, year, output):
    if output.exists():
        raise ValueError('Delivery destination already exists; use a new dated path.')
    if root == output or root in output.parents:
        raise ValueError('Delivery must be outside the input data root.')
    plan_path = root / 'planning/coverage_matrix.csv'
    year_session = root / 'sessions' / str(year)

    def inputs():
        paths = {plan_path, root / 'review/validation_issues.json'}
        paths.update(root / 'aggregate' / (name + '.json') for name in SETS)
        directories = list((root / 'units').glob('*/' + str(year) + '-??'))
        for directory in directories + [root / 'protocol', root / 'scripts', year_session]:
            if directory.exists():
                paths.update(p for p in directory.rglob('*') if allowed(p))
        paths.update(p for p in (root / 'review').glob('*')
                     if p.suffix in {'.json', '.jsonl'} and allowed(p))
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(paths) if p.exists()}

    before = inputs()
    plan = [row for row in csv.DictReader(plan_path.open(encoding='utf-8-sig'))
            if row['month'].startswith(str(year) + '-')]
    if not plan:
        raise ValueError('Year has no planned units.')
    ids = {row['unit_id'] for row in plan}
    if len(ids) != len(plan):
        raise ValueError('Duplicate planned unit IDs.')
    data = {name: [row for row in read(root / 'aggregate' / (name + '.json'))
                   if row.get('unit_id') in ids] for name in SETS}
    directories = [root / row['directory'] for row in plan]
    finished = {row['unit_id'] for row, directory in zip(plan, directories)
                if read(directory / 'status.json', {}).get('status') in FINISHED}
    if finished != {row['unit_id'] for row in data['unit_summary']}:
        raise ValueError('Annual consolidation is stale; consolidate stable dossiers first.')
    if len(data['unit_summary']) != len(finished):
        raise ValueError('Duplicate annual consolidated units.')
    for name, count_field in [('candidates', 'n_candidates'), ('sources', 'n_sources'),
                              ('queries', 'n_queries'), ('gaps', 'n_gaps'),
                              ('excluded', 'n_excluded'), ('continuations', 'n_continuations')]:
        counts = collections.Counter(row['unit_id'] for row in data[name])
        if any(row[count_field] != counts[row['unit_id']] for row in data['unit_summary']):
            raise ValueError('Annual aggregate count mismatch: ' + name)
        if set(counts) - finished:
            raise ValueError('Annual records have no finished dossier: ' + name)
    issues = [row for row in read(root / 'review/validation_issues.json', [])
              if row.get('unit_id') in ids or row.get('unit_id') == 'global']
    if issues:
        raise ValueError('Resolve annual/global validation issues before delivery.')
    for row, directory in zip(plan, directories):
        if row['unit_id'] in finished:
            subprocess.run([sys.executable, str(root / 'scripts/research.py'),
                            'validate-unit', str(directory)], check=True,
                           stdout=subprocess.DEVNULL)
    # Reuse the canonical derivations; regenerate only in a disposable copy.
    with tempfile.TemporaryDirectory(prefix='annual-validation-') as temporary:
        shadow = pathlib.Path(temporary)
        (shadow / 'planning').mkdir()
        (shadow / 'review').mkdir()
        shutil.copyfile(plan_path, shadow / 'planning/coverage_matrix.csv')
        if (root / 'review/decisions.json').exists():
            shutil.copyfile(root / 'review/decisions.json', shadow / 'review/decisions.json')
        for row, directory in zip(plan, directories):
            if row['unit_id'] in finished:
                target = shadow / row['directory']
                target.mkdir(parents=True)
                for name in ('assignment.json', 'search_log.jsonl', 'sources.jsonl',
                             'events.json', 'excluded.json', 'continuations.json',
                             'gaps.json', 'report.txt', 'status.json'):
                    shutil.copyfile(directory / name, target / name)
        subprocess.run([sys.executable, str(root / 'scripts/consolidate.py'),
                        '--root', str(shadow)], check=True, stdout=subprocess.DEVNULL)
        for name in SETS:
            if read(shadow / 'aggregate' / (name + '.json')) != data[name]:
                raise ValueError('Annual consolidation is stale: ' + name)
    reviewed_hashes = {row['original_sha256'] for row in read(
        root / 'review/portable_text_review.json', [])
        if row.get('classification') == 'copied_source_summary'}
    omissions = []
    data = {name: portable_text(rows, 'aggregate/' + name + '.json', omissions, reviewed_hashes)
            for name, rows in data.items()}
    candidate_ids = {row.get('candidate_id') for name in ('candidates', 'excluded')
                     for row in data[name] if row.get('candidate_id')}
    urls = {row.get('url') for row in data['sources'] if row.get('url')}

    references = ids | candidate_ids | urls

    def relevant(value):
        if isinstance(value, str):
            return value in references
        if isinstance(value, dict):
            return any(relevant(item) for item in value.values())
        if isinstance(value, list):
            return any(relevant(item) for item in value)
        return False

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = pathlib.Path(tempfile.mkdtemp(prefix='annual-', dir=output.parent))
    try:
        for directory in directories + [root / 'protocol', root / 'scripts', year_session]:
            if directory.exists():
                for path in directory.rglob('*'):
                    if allowed(path):
                        target = stage / path.relative_to(root)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        copy_portable(path, target, path.relative_to(root).as_posix(), omissions, reviewed_hashes)
        export_csv(stage / 'coverage.csv', plan)
        connection = sqlite3.connect(stage / 'research.sqlite')
        for name, rows in data.items():
            dump(stage / 'aggregate' / (name + '.json'), rows)
            export_csv(stage / 'aggregate' / (name + '.csv'), rows)
            connection.execute('CREATE TABLE ' + name +
                               '(row_number INTEGER PRIMARY KEY, unit_id TEXT NOT NULL, data_json TEXT NOT NULL)')
            connection.executemany('INSERT INTO ' + name + ' VALUES (?,?,?)',
                                   [(i, row['unit_id'], json.dumps(row, ensure_ascii=False))
                                    for i, row in enumerate(rows, 1)])
            assert [json.loads(value[0]) for value in connection.execute(
                'SELECT data_json FROM ' + name + ' ORDER BY row_number')] == rows
        connection.commit()
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        connection.close()
        for path in (root / 'review').glob('*'):
            if path.suffix == '.json':
                rows = read(path, [])
                if isinstance(rows, list):
                    dump(stage / 'review' / path.name, portable_text(
                        [row for row in rows if relevant(row)], 'review/' + path.name, omissions, reviewed_hashes))
            elif path.suffix == '.jsonl':
                rows = [json.loads(line) for line in path.read_text().split('\n') if line.strip()]
                rows = portable_text([row for row in rows if relevant(row)],
                                     'review/' + path.name, omissions, reviewed_hashes)
                target = stage / 'review' / path.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n'
                                          for row in rows))
        reviews = read(year_session / 'unit_reviews.json', [])
        reviewed = {row.get('unit_id') for row in reviews
                    if row.get('status') == 'root_reviewed_open_gaps'} & finished
        summary = {'year': year, 'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'cutoff': '2026-10-07', 'planned_country_months': len(plan),
                   'researched_country_months': len(finished),
                   'coordinator_reviewed_units': len(reviewed),
                   'remaining_first_passes': len(plan) - len(finished),
                   'plan_status_counts': dict(collections.Counter(row['status'] for row in plan)),
                   'record_counts': {name: len(rows) for name, rows in data.items()},
                   'coordinator_reviewed_candidates': sum(row.get('coordinator_review_status') ==
                       'root_reviewed_open_gaps' for row in data['candidates']),
                   'approved_official_observations': 0, 'baseline_gate': 'pending_official_baseline',
                   'coverage_claim': 'Documented open-web first passes; not exhaustive.',
                   'liveness_note': 'Assignment statuses are provenance, not live processes. See dated session records.',
                   'review_selection': 'Exact unit/candidate IDs or cohort source URLs; cross-year references preserved.',
                   'portable_text_omissions': len(omissions),
                   'portable_text_note': 'Long raw source passages are omitted in exports only; original hashes and lengths are recorded in manifest.json. Research inputs remain unchanged.'}
        dump(stage / 'summary.json', summary)
        rows = ''.join('<tr><td>' + html.escape(row['country']) + '</td><td>' + row['month'] +
                       '</td><td>' + html.escape(row['status']) + '</td><td><a href="' +
                       html.escape(row['directory'], quote=True) + '/report.txt">Dossier</a></td></tr>'
                       for row in plan if (stage / row['directory'] / 'report.txt').exists())
        (stage / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Annual research</title>'
            '<h1>Mass Mobilization ' + str(year) + '</h1><p>' + str(len(finished)) + ' first passes / ' +
            str(len(plan)) + ' planned; ' + str(len(reviewed)) + ' coordinator-reviewed units. '
            'Official observations approved: 0. Cutoff: 2026-10-07.</p>'
            '<p>Assignment status does not prove agent liveness. Unknowns and open gaps remain in dossiers. '
            'Cross-year episode references identify context; they are not additional annual observations.</p>'
            '<p>Long raw source text is omitted from portable files; original hashes and lengths are in manifest.json.</p>'
            '<p><a href="summary.json">Summary</a> · <a href="coverage.csv">Annual plan</a> · '
            '<a href="research.sqlite">SQLite</a> · <a href="aggregate/candidates.csv">Candidates</a> · '
            '<a href="aggregate/gaps.csv">Gaps</a> · <a href="review/decisions.json">Review decisions</a>'
            '</p><table><tr><th>Country</th><th>Month</th>'
            '<th>Plan status</th><th>Evidence</th></tr>' + rows + '</table>')
        if before != inputs():
            raise ValueError('Inputs changed during delivery; stop writers and rebuild.')
        manifest = {'year': year, 'created_at': summary['created_at'], 'cutoff': summary['cutoff'],
                    'input_sha256': before, 'portable_text_omissions': omissions, 'excluded': ['private_reading/', *sorted(PRIVATE)],
                    'files': [{'path': path.relative_to(stage).as_posix(), 'bytes': path.stat().st_size,
                               'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                              for path in sorted(stage.rglob('*')) if path.is_file()]}
        dump(stage / 'manifest.json', manifest)
        archive = stage / ('mass_mobilization_' + str(year) + '.zip')
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zipped:
            for path in sorted(stage.rglob('*')):
                if path.is_file() and path != archive:
                    zipped.write(path, path.relative_to(stage))
        with zipfile.ZipFile(archive) as zipped:
            for entry in manifest['files']:
                assert hashlib.sha256(zipped.read(entry['path'])).hexdigest() == entry['sha256']
            assert json.loads(zipped.read('manifest.json')) == manifest
        archive_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
        stage.rename(output)
        return {'output': str(output), 'year': year, 'summary': summary, 'zip_sha256': archive_hash}
    except Exception:
        shutil.rmtree(stage)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[1])
    parser.add_argument('--year', type=int, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.root.resolve(), arguments.year, arguments.output.resolve()),
                     ensure_ascii=False, indent=2))
