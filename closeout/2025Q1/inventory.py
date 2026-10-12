import pathlib,json,csv,hashlib,collections,sys
B=pathlib.Path(sys.argv[1]); O=pathlib.Path(sys.argv[2]);O.mkdir(parents=True,exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):
 try:return json.loads(p.read_text())
 except:return {}
def lines(p):
 if not p.exists():return []
 return [loadline(x) for x in p.read_text().splitlines() if x.strip()]
def loadline(x):
 try:return json.loads(x)
 except:return {}
def keys(obj):
 if isinstance(obj,dict):
  for k,v in obj.items():
   yield k,v
   yield from keys(v)
 elif isinstance(obj,list):
  for v in obj:yield from keys(v)
rows=[r for r in csv.DictReader((B/'planning/coverage_matrix.csv').open()) if r['quarter']=='2025Q1'];freq=collections.Counter(r['unit_id'] for r in rows);result=[];private=[]
for uid in sorted(freq):
 row=next(r for r in rows if r['unit_id']==uid);base=B/row['directory'];statuses=list(base.rglob('status.json')) if base.exists() else []
 roots=sorted({p.parent for p in statuses},key=lambda p:(max((x.stat().st_mtime_ns for x in p.iterdir() if x.is_file()),default=0),str(p)))
 # Select latest saved status-bearing generation, excluding reviewer subdirectories.
 roots=[p for p in roots if 'opreviews' not in p.parts]
 root=roots[-1] if roots else base
 q=lines(root/'search_log.jsonl');s=lines(root/'sources.jsonl');kv=list(keys(s));url=any(k in ('url','source_url') and isinstance(v,str) and v.startswith('http') for k,v in kv);extract=any(k in ('summary','excerpt','extract','snippet','quote','rendered_header','body_text') and bool(v) for k,v in kv);meta=any(k in ('publisher','title','publication_date','source_type') and bool(v) for k,v in kv)
 core=['status.json','events.json','excluded.json','continuations.json','gaps.json','report.txt','search_log.jsonl','sources.jsonl'];hashes={n:sha(root/n) for n in core if (root/n).is_file()};st=load(root/'status.json');reviews=[]
 for p in (base.rglob('operational_review.json') if base.exists() else []):
  d=load(p);h=d.get('evidence_hash_manifest',d.get('delivery_core_hashes',d.get('reviewed_evidence_hashes',{})))
  if not isinstance(h,dict):continue
  valid=bool(h) and all(isinstance(v,str) and (root/k).is_file() and sha(root/k)==v for k,v in h.items())
  reviews.append({'receipt_sha256':sha(p),'hashes_match_selected_generation':valid,'disposition':d.get('review_disposition',d.get('disposition','unknown'))})
 note=base.exists() and any(base.rglob('report.txt'));query=any(any(k in ('query','queries','search_query','search_terms') and bool(v) for k,v in keys(x)) for x in q)
 dossier=all(n in hashes for n in core) and query and url and extract and meta
 item={'unit_id':uid,'has_directory':base.exists(),'has_notes':note,'saved_generations':len(roots),'query_records':len(q),'has_actual_query_record':query,'source_records':len(s),'has_source_url':url,'has_extract_or_summary':extract,'has_source_metadata':meta,'dossier_with_query_url_extract_metadata':dossier,'partial_or_prepared':base.exists() and not dossier,'declared_status':st.get('status','unknown'),'selected_core_sha256':hashes,'reviews':reviews,'current_hash_accept':any(r['hashes_match_selected_generation'] and r['disposition']=='ACCEPT_BOUNDED_WITH_GAPS' for r in reviews)}
 result.append(item);private.append({'unit_id':uid,'selected_root':str(root.relative_to(B)) if root.exists() else None})
counts={'expected':480,'unique_queue_ids':len(freq),'duplicate_queue_rows':sum(v-1 for v in freq.values()),'directories':sum(x['has_directory'] for x in result),'notes':sum(x['has_notes'] for x in result),'dossiers_with_query_url_extract_metadata':sum(x['dossier_with_query_url_extract_metadata'] for x in result),'partial_or_prepared':sum(x['partial_or_prepared'] for x in result),'units_with_current_hash_accept':sum(x['current_hash_accept'] for x in result),'units_with_multiple_saved_generations':sum(x['saved_generations']>1 for x in result),'official_complete_units':0}
report={'scope':'2025Q1','counts':counts,'definitions':{'selected_generation':'Latest status-bearing saved generation by maximum direct-file mtime_ns, then relative path; reviewer subdirectories excluded. This filesystem heuristic is not an owner delivery or scientific approval.','dossier':'All eight core files plus nonempty actual query field and saved source URL, summary/extract, metadata; summary is not necessarily a verbatim extract. Not structural/scientific validation.','current_review':'All declared evidence_hash_manifest/delivery_core_hashes/reviewed_evidence_hashes match selected root exactly; unrecognized schemas not accepted.','sets':'Notes, dossiers and reviews overlap; versions are not duplicate units.'},'missing_directory_ids':[x['unit_id'] for x in result if not x['has_directory']],'missing_evidence_dossier_ids':[x['unit_id'] for x in result if not x['dossier_with_query_url_extract_metadata']],'duplicate_queue_ids':[k for k,v in freq.items() if v>1],'units':result,'input_queue_sha256':sha(B/'planning/coverage_matrix.csv')}
(O/'INVENTORY.json').write_text(json.dumps(report,indent=2)+'\n');(O/'PRIVATE_ROOT_SELECTION.json').write_text(json.dumps(private,indent=2)+'\n');print(json.dumps(counts))
skips=load(B/'planning/skip_units.json');excluded=sorted({x['unit_id'] for x in skips if x.get('quarter')=='2025Q1'});report['excluded_prior_or_reserved_ids']=excluded;report['counts']['excluded_prior_or_reserved']=len(excluded);report['counts']['accounted_universe_ids']=len(set(freq)|set(excluded));report['counts']['missing_from_universe_accounting']=480-len(set(freq)|set(excluded));report['limitations']=['Only current partition inspected; excluded original-owner evidence not imported or counted as absent globally.','Metadata deficit does not imply unfinished research: zero-candidate units can have no source cards.','Current-hash accept count is conservative for recognized schemas and selected filesystem generation; not a replacement for all historical review metrics.','No new scientific review, validation approval or official completion.'];(O/'INVENTORY.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report['counts']))
