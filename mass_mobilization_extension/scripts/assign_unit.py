#!/usr/bin/env python3
"""Record an actual delegation; do not mark merely planned units assigned."""
import argparse,csv,datetime,io,json,pathlib
p=argparse.ArgumentParser();p.add_argument('unit_id');p.add_argument('agent_task');p.add_argument('--resume',action='store_true',help='Reassign an interrupted in-progress unit, preserving its files and assignment history');a=p.parse_args()
r=pathlib.Path(__file__).resolve().parents[1]
path=r/'planning/coverage_matrix.csv'
rows=list(csv.DictReader(path.open(encoding='utf-8-sig')))
matches=[v for v in rows if v['unit_id']==a.unit_id]
if len(matches)!=1:raise SystemExit('Unit must be uniquely planned')
v=matches[0]
allowed=['assigned_researching'] if a.resume else ['queued_next_batch','planned_not_assigned']
if v['status'] not in allowed:raise SystemExit('Unit state does not permit this assignment; --resume is only for interrupted in-progress units')
d=r/v['directory'];d.mkdir(parents=True,exist_ok=True)
if a.resume and (d/'assignment.json').exists():
 previous=json.loads((d/'assignment.json').read_text())
 with (d/'assignment_history.jsonl').open('a') as history:history.write(json.dumps(previous,ensure_ascii=False)+'\n')
v.update(status='assigned_researching',agent_task=a.agent_task)
s=io.StringIO();w=csv.DictWriter(s,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows);temporary=path.with_name(path.name+'.tmp');temporary.write_bytes(s.getvalue().encode('utf-8-sig'));temporary.replace(path)
assignment={**v,'assigned_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
temporary=d/'assignment.json.tmp';temporary.write_text(json.dumps(assignment,ensure_ascii=False,indent=2));temporary.replace(d/'assignment.json')
print(json.dumps(assignment,ensure_ascii=False))
