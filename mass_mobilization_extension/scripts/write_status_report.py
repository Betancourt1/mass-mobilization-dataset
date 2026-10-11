#!/usr/bin/env python3
"""Write transparent progress and selective-review scope from consolidated data."""
import pathlib,json,datetime,collections,csv
r=pathlib.Path(__file__).resolve().parents[1]
def read(name):return json.loads((r/name).read_text())
s=read('aggregate/summary.json');units=read('aggregate/unit_summary.json');d=read('review/decisions.json');events=read('aggregate/candidates.json');sources=read('aggregate/sources.json');queries=read('aggregate/queries.json')
notes=read('review/cross_month_manual_notes.json')
uniqueq=len({(q['unit_id'],q.get('query')) for q in queries})
opened=s['source_access_status_counts'].get('opened',0)
counts='\n'.join(f"{u['country']} {u['month']}: {u['n_candidates']} candidatos; {u['n_queries']} consultas; {u['n_sources']} fichas ({u['source_opened']} abiertas); {u['n_gaps']} huecos. Procedencia de subagente: {u['agent_task']} (no acredita proceso activo)." for u in units)
txt=f'''REVISIÓN DEL COORDINADOR — CORTE DE PROGRESO
Compilación UTC: {datetime.datetime.now(datetime.timezone.utc).isoformat()}
Corte de eventos: {s['cutoff']}. Investigación acumulativa de la primera etapa, todavía en curso.
Estado de sesión y agentes realmente activos: sessions/current.json (verificar vigencia).

COBERTURA REAL
{s['researched_country_months']} unidades con primer barrido escrito de {s['planned_country_months']} planeadas.
{s['assigned_in_progress']} asignadas todavía en trabajo; {s['planned_not_researched']} sin barrido consolidado.
{s['candidates']} candidatos, {s['excluded']} registros en excluded.json (incluidas pistas pendientes) y {s['continuations']} continuaciones/vínculos.
{s['queries']} ejecuciones de consultas; {uniqueq} textos de consulta distintos dentro de sus unidades.
{s['sources']} fichas de URL por unidad; {s['sources_distinct_exact_urls']} URLs exactas distintas.
{opened} fichas con apertura registrada; algunas son parciales, según limitations. Abierta no equivale
a corroboración ni lectura humana independiente. search_only es descubrimiento pendiente.
{s['unit_gaps']} huecos de información por unidad, además de los bloqueos generales de baseline/.
Un hueco puede afectar varios candidatos. Estos números no cuentan protestas ausentes ni errores únicos.

{counts}

ALCANCE DE LA REVISIÓN
{s['coordinator_reviewed_candidates']} candidatos tuvieron comprobación selectiva del coordinador, con decisiones
separadas del expediente del agente. Se reabrieron fuentes de casos de fechas, umbral, objetivo,
respuesta estatal y episodios. Consulte decisions.json y source_checks.jsonl: identifican qué fuente
se leyó y qué revisión fue sólo del expediente. No es revisión completa ni independiente humana.
{s['validation_issues']} incidencias de estructura/referencias/recuentos en la validación automática final.
La validación no acredita veracidad histórica, exhaustividad, independencia editorial ni elegibilidad.
{s['cross_month_flags']} cruces automáticos de claves entre meses; {len(notes)} notas manuales adicionales.
Toda coincidencia espera comparación de fuentes; no dispara fusión de eventos.
{s['approved_official_observations']} observaciones aprobadas o anexadas al dataset oficial. No se abrió PR.

DECISIONES Y RIESGOS CONCRETOS
- Myanmar enero: dos acciones con aproximadamente 50 pasan a pending_threshold en el dictamen
  del coordinador; las propuestas originales se conservan para auditoría.
- Nigeria enero: una estimación puntual de aproximadamente 70 se distingue de límites exactos;
  el consolidado conserva agent_participants_min/max y participants_estimate.
- Enero/febrero: un artículo posterior puede añadir alegaciones o contradecir cifras previas;
  IMN enero requiere corroboración de muertes y coordinación de actos, sin trasplantar a febrero.
- Myanmar febrero: muerte posterior al disparo no fecha el final del acto; bajas de combate y
  violencia que motivó una protesta no se codifican como respuesta estatal a esa protesta.
- Caravanas: vehículos, afectados, plantillas y detenidos acumulados no son asistencia simultánea.
- Convocatorias: pistas pending_evidence no se cuentan como actos realizados.
- Algunos candidatos nacionales/locales se superponen; no sumar filas como eventos únicos.
- Filtros de buscador fallaron y una URL de AAPP cambió de contenido; buscar versiones de archivo.

BLOQUEOS ANTES DE COMPATIBILIDAD OFICIAL
Metadatos DOI recuperados en baseline/baseline_status.json: versión registrada 5.1,
CC0 y periodo 1990-01-01–2020-03-31. La descarga y lista de versiones actuales de
Dataverse siguen bloqueadas; universo, esquema y condiciones de los últimos archivos
todavía requieren comparación directa. Abril–diciembre de 2020 exige reconciliación.
Faltan hemeroteca equivalente, protocolo adicional de autores, calibración con casos históricos,
revisión independiente y lingüística. Las diferencias de unknown/ignore, finales y umbrales están
declaradas en protocol/deviations_from_original.txt. Ningún silencio se convierte automáticamente en 0.

COLA Y SIGUIENTE TRABAJO
La matriz asigna un nombre de tarea previsto y rango de cola a todas las combinaciones, pero sólo
agent_task conserva la procedencia de una delegación; no prueba que un proceso siga activo.
Se continúa con los países restantes de enero de 2021 y después por mes en queue_order,
según la capacidad real. La cola está en planning/next_units.csv. El universo y periodo son provisionales.
La franja abril 2019–diciembre 2020 es reconciliación de la copia local, no hueco oficial demostrado.
No hay ejecución futura programada ni búsqueda que continúe automáticamente después de esta entrega.

REPRODUCCIÓN
Desde la raíz: python3 mass_mobilization_extension/scripts/consolidate.py
python3 mass_mobilization_extension/scripts/write_status_report.py
python3 mass_mobilization_extension/scripts/build_delivery.py --output releases/AAAA-MM-DD_HHMM
Sólo biblioteca estándar de Python. Usar una marca temporal real.
Esto reconstruye archivos de investigación existentes; no repite búsquedas web ni aprueba candidatos.
El manifiesto lista archivos y hashes. El ZIP contiene fichas, enlaces, paráfrasis y código; no artículos
completos ni copias privadas del manual. README.txt enlaza la documentación original.
'''
(r/'review/coordinator_review.txt').write_text(txt)
(r.parent/'STATUS.txt').write_text(txt)
stats={'executed_queries':s['queries'],'distinct_query_texts_within_units':uniqueq,'coordinator_decisions':len(d),'source_checks':sum(bool(line.strip()) for line in (r/'review/source_checks.jsonl').read_text().split('\n')),'coverage_fraction':s['researched_country_months']/s['planned_country_months'],'automatic_validation':s['validation_issues'],'independent_human_review':False,'future_execution_scheduled':False}
temporary=r/'review/review_summary.json.tmp';temporary.write_text(json.dumps(stats,ensure_ascii=False,indent=2));temporary.replace(r/'review/review_summary.json')
print(json.dumps(stats,ensure_ascii=False))
