# Query and retrieval log

All retrieval timestamps are UTC (clock tool). Search was via the managed web search/open interface. Search-result references and open-result references are retained as provided by the tool. Search snippets may be incomplete or stale; opened pages were used for the main candidates where accessible.

## Search calls

### Batch 1 — 2026-10-11 03:02:57 UTC

Queries, in order:

1. `Angola protest OR demonstration OR march "October" "2026"`
2. `Angola protesto manifestação marcha "outubro" 2026`
3. `Angola greve protesto outubro 2026 manifestação`
4. `site:facebook.com Angola protesto manifestação "outubro" 2026`

No Angola-specific event candidate was returned. Output included unrelated Brazil/France results and background pages. Search refs shown included `turn6search*`, `turn6news*`; excluded as irrelevant or outside the event date window.

### Batch 2 — 2026-10-11 03:03:05 UTC

Queries, in order:

1. `site:angop.ao outubro 2026 protesto manifestação Angola`
2. `Angola "6 de outubro de 2026" protesto OR manifestação`
3. `Angola "5 de outubro de 2026" protesto OR manifestação`
4. `Angola "outubro 2026" greve trabalhadores manifestação estudantes Luanda`

First effective Angola-specific query: query 1. It returned ANGOP daily summaries dated Oct 2 (`turn10search0`, https://angop.ao/noticias/resumos/j6yxunwzblsr/) and Oct 6 (`turn10search12`, https://www.angop.ao/es/noticias/resumos/dgyt69/), and the ANGOP society index (`turn10search24`, https://www.angop.ao/angola/noticias/?vtab=sociedade&vtabid=1170). The returned excerpt for the Oct 6 summary did not identify a protest/mass event. Query 2–4 produced no matching Oct 1–7 event; prominent results were old events, non-Angola results, or unrelated.

ANGOP opens attempted 2026-10-11 03:03:07 UTC (`turn14view0` through `turn14view4` for the five returned ANGOP pages/indexes) failed with 502 Bad Gateway. This is an access/fetch failure, not evidence that no event was covered.

### Batch 3 — 2026-10-11 03:03:19 UTC

Queries, in order:

1. `Angola manifestação OR protesto OR greve "outubro" "2026" Luanda 1 2 3 4 5 6 7`
2. `Angola protest demonstration strike rally 2026 October 1 2 3 4 5 6 7`
3. `site:dw.com/pt-002 Angola protesto OR manifestação outubro 2026`
4. `site:club-k.net Angola manifestação protesto outubro 2026`

This batch returned no confirmed event. `dw.com/pt-002` was blocked by robots.txt (tool output; no bypass attempted). Search refs included `turn15search1` (HRW historical/background report) and `turn15search4` (2025 Reuters event), both outside event window.

### Batch 4 — 2026-10-11 03:03:19 UTC

Queries, in order:

1. `Angola "7 de Outubro de 2026" protesto OR manifestação OR greve`
2. `Angola "3 de Outubro de 2026" protesto OR manifestação OR greve`
3. `site:angop.ao/noticias "Outubro de 2026" (manifestação OR protesto OR greve OR concentração)`
4. `site:angola24horas.com Angola 2026 October protest OR strike OR demonstration`

Promising results: `turn18search1` Caminhada Outubro Rosa (Luanda, Oct 3); `turn18search5` Calumbo planned protest (Oct 3; occurrence unverified); `turn18search0` Movimento Cívico TODOS forum (held Oct 6); `turn18search6` possible Malanje protest associated with a visit scheduled Oct 8–9; `turn18search12` Angola24Horas Oct 7 archive excerpt about the forum. The October 8–9 Malanje visit is outside the event window. Search also returned campaign/party stories; see scope note in `README.md`.

### Batch 5 — 2026-10-11 03:03:34 UTC

Queries, in order:

1. `"INGOMBOTA VESTE-SE DE ROSA" "15 MIL" Luanda outubro 2026`
2. `"manifestação" "3 de Outubro" "Calumbo" 2026 realizou`
3. `"Cidadão" "06/10/26" Movimento Cívico TODOS Fórum protesto Luanda`
4. `site:club-k.net Malanje manifestação outubro 2026 governador`

Query 1 returned the detailed PRESSdigi report `turn23search0`, https://press.digi.ao/artigo/ingombota-veste-se-de-rosa-e-reune-mais-de-15-mil-participantes-em-caminhada-pela-prevencao-do-cancro-da-mama/. Query 2 did not surface a post-event report confirming the planned Calumbo demonstration. Query 3 did not surface a protest; forum references persisted. Query 4 did not establish a Malanje event within the window.

### Batch 6 — 2026-10-11 03:03:44 UTC

Queries, in order:

1. `site:gov.ao "15 mil" "Caminhada Rosa" Ingombota 3 Outubro 2026`
2. `site:gov.ao "Caminhada Rosa" Luanda "3 de Outubro" 2026`
3. `site:rna.ao Caminhada Rosa Ingombota 2026 3 outubro`
4. `"Ingombota" "Caminhada Rosa" "3 de Outubro de 2026"`

The first two did not surface an accessible direct Government of Luanda page in the returned results. Queries 3–4 surfaced independent confirmation by Rádio Nacional de Angola: `turn27search16`, https://rna.ao/rna.ao/2026/10/04/marcha-a-favor-da-prevencao-e-diagnostico-precoce-do-cancro-mama-mobiliza-milhares-de-pessoas-em-luanda/ and `turn27search25`, https://www.rna.ao/pages/new.php?uid=233694.

### Batch 7 — 2026-10-11 03:03:54 UTC

Queries, in order:

1. `site:press.digi.ao/artigo "Stop Rixa" Kilamba 3 Outubro 2026`
2. `site:press.digi.ao/artigo "ANGOLA CHAMA POR TI" "3 de Outubro" 2026 Luanda`
3. `site:press.digi.ao/artigo BASTA mobilização porta-a-porta Bengo Outubro 2026`

This call produced the public campaign result `turn29search7` for Angola Chama Por Ti's nationwide electoral-record update program (official government page, program running from June 15, 2026 to March 31, 2027); this is continuing administrative mobilization, not an event confined to Oct 1–7. `turn29search1` was an inaccessible Facebook event video concerning an Oct 3 Luanda campaign. `turn29view1` came from a related-page click rather than a search result: PRESSdigi's Oct 5 Vila Flor walk report.

### Batch 8 — 2026-10-11 03:04:01 UTC

No new queries. Opened `turn29view0` (RNA), `turn29view1` (Vila Flor walk), `turn27search25` (RNA alternate URL), `turn29search7` (official electoral-record campaign page), and `turn29search1` (Facebook video). Full accessible page references are `turn31view0`, `turn31view1`, and `turn31view3`. Facebook open (`turn31view4`) failed because online fetch was throttled; no workaround attempted.

## Open attempts and limitations

- ANGOP Oct 2/Oct 6 digests and indexes: five opens failed with 502 on 2026-10-11 03:03:07 UTC (`turn14view0`–`turn14view4`).
- DW Portuguese search was blocked by robots.txt at search time; no bypass attempted.
- Angola24Horas Oct 2026 archive `https://www.angola24horas.com/angola-24-horas-noticias/itemlist/date?start=10` returned 403 on open at 2026-10-11 03:03:41 UTC (`turn25view2`). Search-result snippet `turn18search12` was still visible, but full archive could not be reviewed.
- Facebook campaign video fetch was throttled on 2026-10-11 03:04:01 UTC (`turn31view4`).
- Search failure or restricted fetching only limits this pass; neither establishes that no relevant events occurred.

