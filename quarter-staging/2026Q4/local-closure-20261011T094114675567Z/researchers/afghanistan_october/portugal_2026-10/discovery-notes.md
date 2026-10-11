# Portugal — bounded public discovery notes

Scope: 2026-10-01 through 2026-10-07 inclusive; timezone context America/Mexico_City. Discovery only; no completeness or validation claim; canonical kit pending.

## Search record

Searches were run 2026-10-11 UTC; exact individual managed-web request times were not exposed.

1. First set:
   - `Portugal protestos manifestação greve 1 2 3 4 5 6 7 outubro 2026`
   - `Portugal protest demonstration strike October 1 2 3 4 5 6 7 2026 Lisbon`
   - `site:publico.pt OR site:observador.pt OR site:rtp.pt protestos greve outubro 2026 Portugal`
   - `Portugal manifestação 7 outubro 2026 protesto Lisboa trabalhadores`
   
   Results `turn230search*`. The search response included a domain-denial notice for Publico due to robots.txt (non-retryable); no bypass/retry attempted. It returned no useful material in the first portion, but also surfaced a promising Observador result `turn230search6`: “Rubio. 300 pessoas protestam contra visita a Portugal,” dated Oct 7, and RTP/Lusa result `turn230search18`. These two outlets report the same event and may rely on the same Lusa reporting; they are retained as two public reports, not presumed independent eyewitness accounts. Unrelated French protests and out-of-scope events were excluded.

2. Follow-up searches:
   - `Portugal 7 outubro 2026 Lisboa protesto Rubio 300 pessoas manifestaram`
   - `site:rtp.pt/noticias "Rubio" Lisboa protestam 7 outubro 2026`
   - `"Não à presença de Marco Rubio em Portugal" "7 de outubro de 2026" manifestação`
   - `Portugal protestos greve outubro 2026 1 2 3 4 5 6 7 trabalhadores`
   
   Opened Observador result as `turn234view0`, lines 100–102: reports about 300 people gathered in Lisbon on Wednesday to protest Marco Rubio’s planned visit the next day; demonstration under the slogan “Não à presença de Marco Rubio em Portugal” began at 18:00 in Largo de São Domingos and was organized by Conselho Português para a Paz e Cooperação.
   
   Opened RTP result as `turn234view1`, lines 58–62: same-day report that about 300 gathered to protest the visit. No additional event surfaced in this follow-up. A planned housing demonstration for Oct 10 appeared in search results but is outside the inclusive Oct 1–7 window and was excluded.

## Candidate

**Lisbon — protest against Marco Rubio’s planned visit, 2026-10-07.** Publication/event date: Oct 7, 2026. Observador and RTP report about 300 participants at 18:00 at Largo de São Domingos, organized by CPPC; demands included opposing the visit and calls to end war, genocide of Palestinians, and aggression against Cuba (Observed page snippet for latter context in `turn230search6`). Sources:
- Observador: https://observador.pt/2026/10/07/cerca-de-300-pessoas-protestam-em-lisboa-contra-visita-de-rubio-a-portugal/ (`turn230search6`, open `turn234view0`)
- RTP (Lusa): https://www.rtp.pt/noticias/pais/cerca-de-300-pessoas-protestam-em-lisboa-contra-visita-de-rubio-a-portugal_n1770133 (`turn230search18`, open `turn234view1`)

This is a discovery candidate; formal dataset inclusion and criteria are pending the canonical scientific kit.

## Limits and access notes

Publico’s robots.txt block was returned by the managed search and remains binding. No retry or bypass attempted. Search results outside the window (including Oct 10) were excluded. Search no-hits do not establish absence.
