#!/usr/bin/env python3
"""Keep links and discovery metadata while omitting copied search excerpts."""
import json
import pathlib
import re

root = pathlib.Path(__file__).resolve().parents[1]
private = root / 'private_reading'
private.mkdir(exist_ok=True)
changes = []

india = root / 'units/india/2021-01/discovery_index.json'
data = json.loads(india.read_text())
if any('metadata' in card for card in data):
    (private / 'india_2021_01_discovery_index.raw.json').write_bytes(india.read_bytes())
    for card in data:
        raw = card.pop('metadata', '')
        for label, key in [('Published', 'search_publication_label'), ('Crawled', 'search_crawl_label')]:
            match = re.search(label + r': ([^;\n]{1,80});', raw)
            if match:
                card[key] = match.group(1)
        card['distribution_note'] = 'Fragmento del buscador omitido; título, URL y referencia conservados. No es evidencia de ocurrencia.'
    india.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    changes.append('India enero: fragmentos de discovery_index omitidos; enlaces y etiquetas relativas conservados.')

myanmar = root / 'units/myanmar/2021-02/research_metadata.json'
data = json.loads(myanmar.read_text())
changed = [0]

def clean(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'headers' and isinstance(item, list) and any(isinstance(x, str) for x in item):
                cards = []
                for raw in item:
                    if not isinstance(raw, str):
                        cards.append(raw)
                        continue
                    heading = raw.split('\n', 1)[0]
                    url = re.search(r'\((https?://[^\s)]+)\)\s*$', heading)
                    ref = re.search(r'【(turn[^】]+)】', raw)
                    cards.append({'title': heading[:url.start()].strip() if url else heading,
                                  'url': url.group(1) if url else None,
                                  'web_ref': ref.group(1) if ref else None,
                                  'distribution_note': 'Fragmento del buscador omitido; no sustituye lectura de la fuente.'})
                    changed[0] += 1
                value[key] = cards
            else:
                clean(item)
    elif isinstance(value, list):
        for item in value:
            clean(item)

original = myanmar.read_bytes()
clean(data)
if changed[0]:
    (private / 'myanmar_2021_02_research_metadata.raw.json').write_bytes(original)
    myanmar.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    changes.append(f'Myanmar febrero: {changed[0]} cabeceras de descubrimiento convertidas a fichas de título/URL/referencia.')

note = root / 'review/distribution_metadata.txt'
if changes:
    note.write_text('PREPARACIÓN DEL MATERIAL PARA DISTRIBUCIÓN\n\n'
                    + '\n'.join(changes)
                    + '\n\nLos expedientes de candidatos y sus fuentes codificadas no se alteraron por esta operación.\n'
                    'Se conservan consultas, enlaces, referencias, metadatos y paráfrasis. Los fragmentos\n'
                    'copiados del buscador no se redistribuyen; las copias privadas de lectura quedan\n'
                    'fuera del ZIP. Este cambio de representación no valida ni descarta fuentes.\n')
print(json.dumps({'changed': changes}, ensure_ascii=False))
