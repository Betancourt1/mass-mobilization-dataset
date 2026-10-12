#!/usr/bin/env python3
"""Make a browsable project index and a ZIP of documented research material."""
import json,pathlib,html,zipfile,hashlib,datetime,argparse
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
r=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(parents=True,exist_ok=True)
def read(name):return json.loads((r/name).read_text())
def esc(x):return html.escape(str(x if x is not None else 'desconocido'))
s=read('aggregate/summary.json');units=read('aggregate/unit_summary.json');events=read('aggregate/candidates.json');gaps=read('aggregate/gaps.json')
rows=''.join('<tr>'+''.join('<td>'+esc(u[k])+'</td>' for k in ['country','month','n_candidates','n_sources','n_queries','n_gaps'])+'<td><a href="../'+esc(next(v['directory'] for v in __import__('csv').DictReader((r/'planning/coverage_matrix.csv').open(encoding='utf-8-sig')) if v['unit_id']==u['unit_id']))+'/report.txt">Informe</a></td></tr>' for u in units)
candidate_rows=''.join('<tr>'+''.join('<td>'+esc(e.get(k))+'</td>' for k in ['candidate_id','country','start_date','end_date','title','eligibility_effective'])+'</tr>' for e in events)
gap_rows=''.join('<tr>'+''.join('<td>'+esc(g.get(k))+'</td>' for k in ['unit_id','gap_id','type','description','required_followup'])+'</tr>' for g in gaps)
stamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
body=f'''<!doctype html><html lang="es"><meta charset="utf-8"><title>Mass Mobilization · Etapa 1</title><style>body{{font:16px/1.5 system-ui;max-width:1280px;margin:35px auto;padding:0 24px;color:#182534;background:#f7f8fa}}h1{{font-size:30px}}h2{{margin-top:35px}}table{{border-collapse:collapse;width:100%;font-size:14px;background:white}}td,th{{padding:9px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}}th{{background:#e6edf3}}.notice{{border-left:4px solid #bd7115;padding:14px;background:#fff3dc}}a{{color:#1555a0}}.scroll{{overflow:auto}}code{{font-size:14px}}small{{color:#536273}}</style>
<h1>Mass Mobilization · Investigación, etapa 1</h1>
<p>Primer barrido documentado. Corte de eventos: <b>{esc(s['cutoff'])}</b>. Compilación: {esc(stamp)}.</p>
<p class="notice">Los metadatos DOI registran v5.1, CC0 y cobertura hasta marzo de 2020; la descarga de los últimos archivos oficiales y su compatibilidad siguen pendientes. Estos registros son candidatos; hay <b>0 observaciones aprobadas</b> para el dataset oficial. Una búsqueda sin resultados no demuestra ausencia de protestas.</p>
<p><b>{s['researched_country_months']}</b> combinaciones investigadas de <b>{s['planned_country_months']:,}</b> provisionales. Restan <b>{s['planned_not_researched']:,}</b>. Hay <b>{s['candidates']}</b> candidatos, <b>{s['sources']}</b> fichas de fuentes, <b>{s['queries']}</b> consultas y <b>{s['unit_gaps']}</b> huecos registrados por las unidades.</p>
<p>Los países se heredaron de una copia local anterior: el universo no representa automáticamente todos los Estados. La investigación continúa en el orden de la matriz. Los primeros doce expedientes conservan su procedencia histórica; cada combinación nueva recibe su propio subagente. No se extrapola representatividad desde esos expedientes.</p>
<h2>Cómo navegar</h2><p><a href="../README.txt">Guía del proyecto</a> · <a href="../planning/coverage_matrix.csv">Matriz completa país–mes</a> · <a href="../baseline/access_gaps.txt">Bloqueos generales</a> · <a href="../review/coordinator_review.txt">Revisión del coordinador</a> · <a href="../protocol/worker_instructions.txt">Protocolo</a></p>
<p>En <code>units/país/AAAA-MM/</code> están las búsquedas, fuentes, evidencia por campo, exclusiones, continuaciones e incógnitas. <code>aggregate/</code> contiene los mismos datos consolidados en JSON, CSV y SQLite. Las fuentes se conservan como enlaces y paráfrasis; los artículos completos no se redistribuyen.</p>
<h2>Unidades ejecutadas</h2><div class="scroll"><table><tr><th>País</th><th>Mes</th><th>Candidatos</th><th>Fuentes</th><th>Consultas</th><th>Huecos</th><th>Expediente</th></tr>{rows}</table></div>
<h2>Candidatos a revisar</h2><p>Las fechas parciales y desconocidas se mantienen como tales; un fin vacío no significa un acto de un solo día. Los episodios continuos no se duplican por cambiar de mes.</p><div class="scroll"><table><tr><th>ID local</th><th>País</th><th>Inicio</th><th>Fin</th><th>Protesta</th><th>Elegibilidad provisional</th></tr>{candidate_rows}</table></div>
<h2>Huecos por unidad</h2><div class="scroll"><table><tr><th>Unidad</th><th>Hueco</th><th>Tipo</th><th>Descripción</th><th>Seguimiento</th></tr>{gap_rows}</table></div>
<h2>Para continuar</h2><p>Seguir la cola explícita de la matriz mientras se intenta resolver la base oficial, comparar el periodo anterior pendiente y validar el protocolo. Antes de exportar observaciones se requiere revisión de candidatos y vínculos entre meses. Consulte NEXT_ACTION.txt y sessions/current.json para reanudar. Ningún PR se ha abierto.</p><small>Generado por scripts/build_delivery.py. Consulte los archivos de revisión para decisiones y limitaciones.</small></html>'''
index=r/'review/index.html';index.write_text(body)
excluded={'baseline/mm_codebook.txt','baseline/mm_codebook.pdf'}
def distributable(p):
 return p.is_file() and p.relative_to(r).as_posix() not in excluded and '__pycache__' not in p.parts and 'private_reading' not in p.relative_to(r).parts
paths=sorted(p for p in r.rglob('*') if distributable(p))
manifest={'created_at':stamp,'events_cutoff':s['cutoff'],'excluded_from_distribution':sorted(excluded)+['private_reading/'],'files':[{'path':p.relative_to(r).as_posix(),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths if p.relative_to(r).as_posix()!='manifest.json']}
temporary=r/'manifest.json.tmp';temporary.write_text(json.dumps(manifest,ensure_ascii=False,indent=2));temporary.replace(r/'manifest.json')
z=out/'mass_mobilization_etapa_1.zip'
with zipfile.ZipFile(z,'w',zipfile.ZIP_DEFLATED) as f:
 for p in sorted(r.rglob('*')):
  if distributable(p):f.write(p,pathlib.Path(r.name)/p.relative_to(r))
print(json.dumps({'zip':str(z.resolve()),'bytes':z.stat().st_size,'files':len(manifest['files'])+1,'sha256':hashlib.sha256(z.read_bytes()).hexdigest()},indent=2))
