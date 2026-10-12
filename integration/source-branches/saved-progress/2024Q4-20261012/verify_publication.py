import json,hashlib,pathlib
p=pathlib.Path(__file__).parent
i=json.loads((p/'INVENTORY.json').read_text())
assert i['denominator']==480 and len(set(i['sets']['expected_unit_ids']))==480
for k,v in i['sets'].items():
 assert len(v)==len(set(v)), k
 assert len(v)==i['counts'][k], k
for x in json.loads((p/'PUBLICATION_MANIFEST.json').read_text())['files']:
 b=(p/x['path']).read_bytes()
 assert len(b)==x['bytes'] and hashlib.sha256(b).hexdigest()==x['sha256'],x['path']
print(json.dumps({'counts':i['counts'],'manifest_verified':True}))
