# Season 1 release pins — 7 September 2026

`RELEASE_MANIFEST.json` records SHA-256 hashes for the exact public files in this release,
including the scorers, datasets, schemas, tool definitions and measured reference summary. The
manifest excludes itself to avoid a circular hash; Git binds the manifest to the root commit.
The review receipt separately records the amended root commit and Git tree.

| Component | Fixed material |
|---|---|
| Harbour | 180 public cases, seed, policy, starter, canonical goal scorer and 14 tool schemas |
| Production contract | Ten items, four deterministic regressions, gateway, exact-price table and collector |
| OP-02 | 180 measured retiring decisions; fixed roles in MODELS.md |
| OP-04 | 480 development / 240 unlabelled held-out trajectories, split by case; 360 private trajectories retained separately |
| OP-05 | 34 documents / 391 passages; 146 development / 272 held-out questions; corpus source hashes and freshness interface |
| OP-06 | 20,000 train / 2,000 dev / 300 noisy / 9 hostile; source-byte hashes in its manifest; private test inputs retained separately |
| Reference attempts | CALIBRATION.md and references/calibration-2026-09-06.json, including hashes of independently retained evidence |
| Model roles and prices | MODELS.md; exact gateway snapshot IDs verified 6 September 2026 |

Private input and evidence hashes are retained in the maintainer release receipt. They are not
candidate-visible labels. The published corpus manifests preserve upstream content hashes even
where the source URL tracks a branch; the hash, not a mutable branch name, identifies the bytes.

The seed values and synthetic servicing clock are fixture constants. They are not season dates;
changing them would invalidate case goals and historical trajectories. The launch window is
7 September–7 December 2026. See RELEASE_STATUS.md for the open submission route and release status.
