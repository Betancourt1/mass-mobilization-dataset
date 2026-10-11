#!/usr/bin/env python3
"""Extract exposed search metadata; never write dossiers or request sources."""
import argparse
import datetime
import hashlib
import json
import pathlib


def extract(events_path, output):
    extension = pathlib.Path(__file__).resolve().parents[1]
    output = output.resolve()
    if output == extension or extension in output.parents:
        raise ValueError('Capture artifacts must be outside the extension')
    captures = []
    with events_path.open(encoding='utf-8') as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except ValueError:
                if line.endswith('\n'):
                    raise ValueError('Malformed completed runtime JSONL record')
                continue  # An active runtime can have an unfinished last line.
            if event.get('type') != 'event_msg':
                continue
            payload = event.get('payload', {})
            item = payload.get('item', {})
            action = item.get('action', {})
            if item.get('kind') != 'web.search' or action.get('type') != 'search':
                continue
            headers = [{'order': n, **{k: v for k, v in h.items() if k != 'snippet'}} for n, h in enumerate(item['results'], 1)]
            clocks = {}
            for key, original in [('executed_at', 'started_at_ms'),
                                  ('response_captured_at', 'completed_at_ms')]:
                value = payload.get(original)
                clocks[key] = (datetime.datetime.fromtimestamp(
                    value / 1000, datetime.timezone.utc).isoformat()
                    if isinstance(value, (int, float)) else None)
            query = action.get('query')
            if query is None:
                query = 'Original batched invocation: ' + json.dumps(
                    action.get('queries'), ensure_ascii=False)
            captures.append({'query_id': f'CAPTURE-{len(captures)+1:04d}',
                             'query': query, 'tool': 'web.run search_query',
                             'returned_results': headers,
                             'returned_urls': [h['url'] for h in headers],
                             **clocks, 'original_action': action,
                             'original_event_id': item['id'],
                             'notes': 'Original exposed search metadata. No repeated '
                             'query or guessed partition. Map to the existing query '
                             'ID before capture; preserve partial repair history.'})
    output.mkdir(parents=True, exist_ok=False)
    manifest = []
    for capture in captures:
        name = capture['query_id'].lower() + '.json'
        raw = (json.dumps(capture, ensure_ascii=False, indent=2) + '\n').encode()
        (output / name).write_bytes(raw)
        manifest.append({'file': name, 'sha256': hashlib.sha256(raw).hexdigest(),
                         'event_id': capture['original_event_id'],
                         'query': capture['query'],
                         'headers': len(capture['returned_results'])})
    (output / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events', type=pathlib.Path, required=True)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()
    result = extract(args.events, args.output)
    print(json.dumps({'output': str(args.output), 'captures': len(result),
                      'headers': sum(x['headers'] for x in result)}))
