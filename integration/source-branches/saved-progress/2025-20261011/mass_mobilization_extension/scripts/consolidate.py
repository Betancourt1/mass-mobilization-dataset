#!/usr/bin/env python3
"""Validate and consolidate research units. Does not approve or export official MM observations."""
import csv,io,json,pathlib,sqlite3,re,collections,datetime,argparse,hashlib
ap=argparse.ArgumentParser();ap.add_argument('--root',default=str(pathlib.Path(__file__).resolve().parents[1]));args=ap.parse_args();R=pathlib.Path(args.root);A=R/'aggregate';A.mkdir(exist_ok=True)
def load(p,default=None):
 if not p.exists():return default
 return json.loads(p.read_text())
def lines(p):return [json.loads(s) for s in p.read_bytes().split(b'\n') if s.strip()] if p.exists() else []
def writecsv(p,rows,fields=None):
 fields=fields or (list(rows[0]) if rows else ['empty']);s=io.StringIO();w=csv.DictWriter(s,fieldnames=fields,extrasaction='ignore');w.writeheader()
 for row in rows:w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()})
 temporary=p.with_name(p.name+'.tmp');temporary.write_bytes(s.getvalue().encode('utf-8-sig'));temporary.replace(p)
def dump(p,obj):
 temporary=p.with_name(p.name+'.tmp');temporary.write_text(json.dumps(obj,ensure_ascii=False,indent=2));temporary.replace(p)
plan=list(csv.DictReader((R/'planning/coverage_matrix.csv').open(encoding='utf-8-sig')));byunit={p['unit_id']:p for p in plan}
required=['assignment.json','search_log.jsonl','sources.jsonl','events.json','excluded.json','continuations.json','gaps.json','report.txt','status.json']
responses={'accommodation','arrests','beatings','crowd_dispersal','ignore','killings','shootings'};demandset={'labor_wage_dispute','land_farm_issue','police_brutality','political_behavior_process','price_increases_tax_policy','social_restrictions','removal_of_politician'}
events=[];sources=[];queries=[];gaps=[];excluded=[];continuations=[];evidence=[];issues=[];units=[];semantic_flags=[]
decisions={d['candidate_id']:d for d in load(R/'review/decisions.json',[]) if d.get('candidate_id')}
status_overrides=load(R/'review/unit_status_overrides.json',{})
for directory in sorted((R/'units').glob('*/*')):
 ass=load(directory/'assignment.json',{});unit=ass.get('unit_id');state=load(directory/'status.json',{})
 if not unit or unit not in byunit:issues.append({'unit_id':unit,'type':'invalid_assignment','detail':str(directory)});continue
 override=status_overrides.get(unit,{})
 if override and hashlib.sha256((directory/'status.json').read_bytes()).hexdigest()==override.get('source_status_sha256'):
  state={**state,'status':override['status']}
 if not state or state.get('status') not in ['researched_open_web_pending_review','root_reviewed_open_gaps']:continue # Read only finished worker units.
 p=byunit[unit];missing=[f for f in required if not (directory/f).exists()]
 if missing:issues.append({'unit_id':unit,'type':'missing_files','detail':missing});continue
 try:ss=lines(directory/'sources.jsonl');qq=lines(directory/'search_log.jsonl');ee=load(directory/'events.json',[]);xx=load(directory/'excluded.json',[]);cc=load(directory/'continuations.json',[]);gg=load(directory/'gaps.json',[])
 except Exception as e:issues.append({'unit_id':unit,'type':'unreadable_json','detail':str(e)});continue
 source_ids=[s.get('source_id') for s in ss];source_set=set(source_ids)
 if len(source_set)!=len(ss) or None in source_set:issues.append({'unit_id':unit,'type':'source_id_problem','detail':'duplicate or absent'})
 for s in ss:sources.append({'unit_id':unit,'global_source_id':unit+':'+str(s.get('source_id')),**s})
 for q in qq:queries.append({'unit_id':unit,**q})
 def checkrefs(refs,owner):
  if isinstance(refs,str):refs=[refs]
  for sid in refs or []:
   if sid not in source_set:issues.append({'unit_id':unit,'type':'unresolved_source','detail':str(owner)+':'+str(sid)})
 for e in ee:
  cid=e.get('candidate_id');checkrefs(e.get('source_ids'),cid)
  for field in ['candidate_id','country','unit_month','title','start_date','start_precision','source_ids','field_evidence','eligibility','coding_status','open_questions']:
   if field not in e:issues.append({'unit_id':unit,'type':'missing_event_field','detail':str(cid)+':'+field})
  start=e.get('start_date')
  if not (start is None and e.get('start_precision')=='unknown') and (not isinstance(start,str) or not start.startswith(p['month'])):issues.append({'unit_id':unit,'type':'start_outside_unit','detail':str(cid)+':'+str(start)})
  if e.get('unit_month')!=p['month']:issues.append({'unit_id':unit,'type':'unit_month_mismatch','detail':str(cid)})
  if e.get('end_date') and start and e['end_date']<start:issues.append({'unit_id':unit,'type':'reversed_dates','detail':str(cid)})
  for datefield,precisionfield in [('start_date','start_precision'),('end_date','end_precision')]:
   datevalue=e.get(datefield);prec=e.get(precisionfield)
   if prec not in ['day','month','year','unknown']:issues.append({'unit_id':unit,'type':'invalid_precision','detail':str(cid)+':'+precisionfield})
   if prec=='day':
    try:datetime.date.fromisoformat(datevalue)
    except Exception:issues.append({'unit_id':unit,'type':'invalid_date','detail':str(cid)+':'+datefield+':'+str(datevalue)})
  if e.get('protester_violence') not in ['yes','no_explicit','unknown']:issues.append({'unit_id':unit,'type':'violence_value','detail':str(cid)})
  if e.get('eligibility') not in ['proposed_include','pending_threshold','pending_state_target','pending_unit','pending_evidence']:issues.append({'unit_id':unit,'type':'eligibility_value','detail':str(cid)})
  sr=e.get('state_response',{})
  if not isinstance(sr,dict) or set(sr)!=responses:issues.append({'unit_id':unit,'type':'response_schema','detail':str(cid)})
  elif any(v not in ['yes','no_explicit','unknown'] for v in sr.values()):issues.append({'unit_id':unit,'type':'response_value','detail':str(cid)})
  if set(e.get('demands',[]))-demandset:issues.append({'unit_id':unit,'type':'demand_value','detail':str(cid)})
  lo=e.get('participants_min');hi=e.get('participants_max')
  for field in ['participants_min','participants_max']:
   val=e.get(field)
   if val is not None and (isinstance(val,bool) or not isinstance(val,(int,float)) or val<0):issues.append({'unit_id':unit,'type':'participant_type','detail':str(cid)+':'+field})
  if lo is not None and hi is not None:
   try:
    if float(lo)>float(hi):issues.append({'unit_id':unit,'type':'reversed_participants','detail':str(cid)})
   except Exception:issues.append({'unit_id':unit,'type':'nonnumeric_participants','detail':str(cid)})
  fe=e.get('field_evidence',{})
  if isinstance(fe,dict):
   for field,fact in fe.items():
    if isinstance(fact,dict):refs=fact.get('source_ids',[]);checkrefs(refs,str(cid)+':'+field);evidence.append({'unit_id':unit,'candidate_id':cid,'field':field,'source_ids':refs,'summary':fact.get('summary','')})
    else:issues.append({'unit_id':unit,'type':'field_evidence_schema','detail':str(cid)+':'+field})
  reviewed={'unit_id':unit,'baseline_gate':'pending_official_baseline','coordinator_review_status':'not_reviewed',**e}
  if cid in decisions:
   d=decisions[cid];reviewed['coordinator_eligibility']=d.get('coordinator_eligibility',e.get('eligibility'));reviewed['coordinator_review_note']=d.get('note');reviewed['coordinator_review_status']=d.get('status','root_reviewed_open_gaps')
   for field,value in d.get('field_overrides',{}).items():reviewed['agent_'+field]=reviewed.get(field);reviewed[field]=value
  reviewed['eligibility_effective']=reviewed.get('coordinator_eligibility',reviewed.get('eligibility'))
  if reviewed.get('start_date') is None and reviewed.get('start_precision')=='unknown':semantic_flags.append({'unit_id':unit,'candidate_id':cid,'type':'ownership_unconfirmed','detail':'Discovery month is not proven start month; preserve null and verify episode owner.'})
  events.append(reviewed)
 for row in xx:checkrefs(row.get('source_ids'),row.get('candidate_id'));excluded.append({'unit_id':unit,**row})
 for row in cc:checkrefs(row.get('source_ids'),row.get('candidate_id',row.get('title')));continuations.append({'unit_id':unit,**row})
 for row in gg:
  checkrefs(row.get('source_ids'),row.get('gap_id'));t=str(row.get('type','')).lower();dims=[]
  for dimension,pattern in [('baseline','baseline'),('participants','threshold|participant|size|gathering'),('state_target','state_target|rally|electoral'),('episode_unit','unit|episode|continu|ownership|handoff'),('dates','date|chronolog|event_end|missing_end|physical_end'),('state_response','state_response|responses|repression'),('violence_casualties','casualty|fatality|protester_violence'),('source_access','block|inaccess|archive|partial_source|mutated_url|unopened|unread|discovery|discovered|unverified_lead'),('source_independence','agency_dependency|syndication|source_independence'),('language','language'),('coverage','coverage|geographic|regional'),('search_method','method|protocol|filter|temporal_search'),('contested_evidence','conflict|contested|contradict|allegation|state_version')]:
   if re.search(pattern,t):dims.append(dimension)
  gaps.append({'unit_id':unit,**row,'gap_dimensions':dims or ['other'],'normalization_basis':'rule on original type label only; not semantic adjudication'})
 st='researched_open_web_pending_review';p['status']=st
 for key,actual in [('n_queries',len(qq)),('n_sources',len(ss)),('n_candidates',len(ee)),('n_excluded',len(xx)),('n_continuations',len(cc)),('n_gaps',len(gg))]:
  if state.get(key)!=actual:issues.append({'unit_id':unit,'type':'status_count_mismatch','detail':key+': reported '+str(state.get(key))+' actual '+str(actual)})
 units.append({'unit_id':unit,'country':p['country'],'month':p['month'],'agent_task':p['agent_task'],'status':st,'n_queries':len(qq),'n_sources':len(ss),'n_candidates':len(ee),'n_excluded':len(xx),'n_continuations':len(cc),'n_gaps':len(gg),'source_opened':sum(s.get('access_status')=='opened' for s in ss),'source_search_only':sum(s.get('access_status')=='search_only' for s in ss),'source_blocked':sum(s.get('access_status')=='blocked' for s in ss),'coverage_assessment':state.get('coverage_assessment',''),'baseline_gate':'pending_official_baseline'})
ids=[e.get('candidate_id') for e in events]
for cid,n in collections.Counter(ids).items():
 if n>1:issues.append({'unit_id':'global','type':'duplicate_candidate_id','detail':str(cid)})
for name,rows in [('candidates',events),('sources',sources),('queries',queries),('gaps',gaps),('excluded',excluded),('continuations',continuations),('evidence_by_field',evidence),('unit_summary',units)]:
 dump(A/(name+'.json'),rows); fields=sorted(set(k for row in rows for k in row)) if rows else ['empty'];writecsv(A/(name+'.csv'),rows,fields)
writecsv(R/'planning/coverage_matrix.csv',plan)
writecsv(R/'planning/next_units.csv',sorted((p for p in plan if p['status'] in ['planned_not_assigned','queued_next_batch']),key=lambda p:int(p.get('queue_order',0))))
dump(R/'review/validation_issues.json',issues)
dump(R/'review/semantic_flags.json',semantic_flags)
cross=[]
for e in events:
 for c in continuations:
  if e.get('country')!=c.get('country',byunit[c['unit_id']]['country']):continue
  if e['unit_id']==c['unit_id']:continue
  ek=e.get('episode_key');ck=c.get('episode_key');es=set(e.get('source_ids',[]));cs=set(c.get('source_ids',[]))
  if ek and ck and ek==ck:cross.append({'event_candidate':e.get('candidate_id'),'event_unit':e['unit_id'],'continuation_unit':c['unit_id'],'reason':'same_episode_key','status':'pending_manual_comparison'})
dump(R/'review/cross_month_flags.json',cross)
db=A/'research.sqlite';temporary_db=A/'research.sqlite.tmp'
if temporary_db.exists():temporary_db.unlink()
con=sqlite3.connect(temporary_db)
con.execute('CREATE TABLE candidates(candidate_id TEXT PRIMARY KEY,unit_id TEXT NOT NULL, country TEXT, start_date TEXT, eligibility TEXT, data_json TEXT NOT NULL)')
con.execute('CREATE TABLE sources(global_source_id TEXT PRIMARY KEY,unit_id TEXT NOT NULL,url TEXT, access_status TEXT, data_json TEXT NOT NULL)')
for e in events:con.execute('INSERT INTO candidates VALUES (?,?,?,?,?,?)',(e.get('candidate_id'),e['unit_id'],e.get('country'),e.get('start_date'),e.get('eligibility_effective'),json.dumps(e,ensure_ascii=False)))
for s in sources:con.execute('INSERT INTO sources VALUES (?,?,?,?,?)',(s['global_source_id'],s['unit_id'],s.get('url'),s.get('access_status'),json.dumps(s,ensure_ascii=False)))
con.execute('CREATE INDEX candidate_date ON candidates(country,start_date)');con.execute('CREATE INDEX source_url ON sources(url)');con.commit();assert con.execute('PRAGMA integrity_check').fetchone()[0]=='ok';con.close();temporary_db.replace(db)
flat=[]
for e in events:
 v={k:e.get(k) for k in ['candidate_id','country','unit_month','title','start_date','start_precision','end_date','end_precision','location','scope','organizer','participants_original','participants_min','participants_max','participants_estimate','participants_precision','threshold_50_evidence','protester_violence','eligibility','eligibility_effective','coding_status','coordinator_review_status','coordinator_review_note','episode_key','baseline_gate','notes','open_questions']}
 v['demands']='; '.join(e.get('demands',[]));v['source_ids']='; '.join(e.get('source_ids',[]))
 for k,value in e.get('state_response',{}).items():v['state_'+k]=value
 v['source_urls']='; '.join(s.get('url','') for s in sources if s['unit_id']==e['unit_id'] and s.get('source_id') in e.get('source_ids',[]))
 flat.append(v)
writecsv(A/'candidates_flat.csv',flat,list(flat[0]) if flat else ['empty'])
summary={'planned_country_months':len(plan),'researched_country_months':len(units),'assigned_in_progress':sum(p['status']=='assigned_researching' for p in plan),'planned_not_researched':len(plan)-len(units),'candidates':len(events),'excluded':len(excluded),'continuations':len(continuations),'sources':len(sources),'sources_distinct_exact_urls':len({s.get('url') for s in sources if s.get('url')}),'source_access_status_counts':dict(collections.Counter(s.get('access_status','missing') for s in sources)),'queries':len(queries),'unit_gaps':len(gaps),'validation_issues':len(issues),'cross_month_flags':len(cross),'coordinator_reviewed_candidates':sum(e.get('coordinator_review_status')=='root_reviewed_open_gaps' for e in events),'effective_eligibility_counts':dict(collections.Counter(e['eligibility_effective'] for e in events)),'approved_official_observations':0,'baseline_gate':'pending_official_baseline','coverage_claim':'documented open-web first pass, not exhaustive','cutoff':'2026-10-07'}
dump(A/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))
