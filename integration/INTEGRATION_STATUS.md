# Integration and recovery status

As of 2026-10-12. This records a preservation/cataloguing integration; it does not make scientific acceptance decisions or restart research.

## Scope and reproducibility

- Inventory scope: 2020Q2–2026Q4, 160 inherited provisional country slugs, 12,640 country-month rows across 27 quarter rows. The 26 full quarters have 480 country-month rows each. 2026Q4 covers October 1–7 only and has 160 rows.
- The inherited country list is provisional and must be checked against the official project universe before a release.
- [`BRANCH_REGISTER.csv`](BRANCH_REGISTER.csv) identifies 20 fetched non-main remote heads. Each original tree is preserved at its registered path under `source-branches/`; source commit heads remain reachable in the integration history. After exact SHA, ancestry and archived-tree checks, all 20 non-main refs were deleted from the remote on 2026-10-12; `main` remains the default and only remote branch. See [`REMOTE_BRANCH_RETIREMENT.csv`](REMOTE_BRANCH_RETIREMENT.csv) for the retirements and before/after verification. No source tree, file version or duplicate was removed from the archive; only the remote refs were deleted.
- [`inventory/`](inventory/) records every mapped source-file occurrence with path, source ref, Git tree ID, byte count and SHA256; it also separates unit status observations, unit-level report facts, quarter aggregates, duplicate references, and file-absence observations.
- Run `python integration/scripts/build_inventory.py` to rebuild the catalogue. Run `python integration/scripts/verify_integration.py` to compare archived trees with registered source trees, check retained-file manifests and verify inventory dimensions.

## Recovery status

[`QUARTER_RECOVERY_STATUS.csv`](QUARTER_RECOVERY_STATUS.csv) gives one row per target quarter. In the fetched remote refs, 12 quarter-specific snapshots/closeouts were integrated. Exact declared closure commits are present for 2026Q2 and 2026Q4; eight other declared closure commits remain unavailable as Git objects:

- 2022Q4 `02f404d7bbec`
- 2023Q1 `540366f80d5b0bf50c267d5dcbcabc3c98423d97`
- 2023Q3 `1fa0e0b`
- 2024Q2 `2dc24d2db31aa92e9e29be89132cb41c30b178df`
- 2024Q4 `b41cbb674176`
- 2025Q1 `cc3d1b5492cee88609655690331c3dce5e7d7217`
- 2025Q4 `0082754761e6be6eadf8a5aeeefb84a8e8a49c72`
- 2026Q1 `29a70c692221fde2395f87d76dfe5ebd7005423d`

Owners reported local safe candidates for 2022Q4, 2025Q4 and 2026Q1, but those Git objects/trees are not available in this checkout, so they are not integrated. A safe 2021Q3 proxy export is blocked because its tree mixes partitions. 2025Q2 export is now reported blocked by `proxy:8080`; its safe branch was not published. For 2025Q4, Google Drive metadata confirms a restricted backup bundle (62,604,319 bytes), JSON manifest (1,183 bytes), TSV index (15,717,690 bytes) and sidecar (107 bytes). The official Drive fetch returned user-scoped file references, but no local workspace path was available. A later Library metadata search matched the user-provided backup reference and size. The official Library materialization returned a signed transfer, but its bundled transfer helper failed with a download error in this executor. No local bytes were obtained, so there is no local checksum, bundle verification, or secrets scan; no private backup IDs, hashes or contents were added, and Q4 remains unintegrated. The local work/safe-selection commit objects are absent from this checkout, and the reported public selection contains only README, PROGRESS and PUBLICATION_MANIFEST with no source evidence. Ten other quarters have no quarter-specific source branch among refs fetched on 2026-10-12; the recovery register records seven requests still queued, one draft-only delivery (2022Q2), and no visible publication for 2023Q3/Q4. These are delivery outcomes, not findings that research failed; their work state remains unknown, not empty. Annual snapshots and per-unit files are listed separately and are not allocated to quarters without exact IDs.

The Library reference `avance_trimestres_20261011.csv` was not materialized: the supported Library helper returned `hosted apps tools/list request failed: network`. The inventory was built from repository artifacts only; no alternate URL or access path was used.

For 2026Q1, an owner-authorized private Drive archive and manifest were reported. Read-only metadata and a file reference were obtained, and Library search confirmed the archive title and size against the user-provided reference. The official Library materialization returned a signed transfer, but its bundled transfer helper failed with a download error in this executor. No local bytes were obtained, so there is no local checksum or secrets scan. The archive contents remain private and were not added to this repository; the separate eight-file safe-package candidate is still not present as a Git object here.

## Interpretation and remaining work

Safety-filtered snapshots omit private evidence, raw/search ledgers and some source histories. Their absence is not evidence that research was not done. `firstpass`, dossier-shaped files, current-hash review, bounded acceptance, provisional candidacy and official approval remain separate. Saved reports record zero official approvals; the 2026Q2 closeout still has 480 units awaiting formal acceptance and no canonical validation. The 2026Q4 closeout contains 160 discovery notes but zero formal first passes or canonical integration, three integrity holds and two predecessor versions whose exact bytes are unrecoverable.

Outstanding work is to recover the unavailable closure Git objects/trees and safe selections from their original environments, obtain the blocked/in-process quarter exports, and retrieve private evidence only through an authorized, safe publication flow. No owner threads were awakened or research workers reactivated for this catalogue. Do not interpret this catalogue as an approved release or as evidence that missing work is complete.
