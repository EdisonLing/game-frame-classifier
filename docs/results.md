# Results

Model results in the order they were run. Each entry states the data snapshot in general terms (games, sources, frame counts), the run settings and the val numbers. Frames, run folders and per-person tables stay local; nothing here names a contributor.

**Related:** [training pipeline](training-pipeline.md) · [evaluation](roadmap/tools/evaluation.md) · [baseline](roadmap/tools/baseline.md)

---

## 2026-11-18 — Baseline, first real data (3 games)

**Data.** Valorant, League of Legends and CS2 only; the other three games had no footage yet. Three sources: my own clips (at most 30 minutes per game, spread across recording days) and two contributors' Frame Export Kit packs. 2,334 slots kept after cleaning (359 near-duplicates removed); 1,989 used after the train source cap (1/15 with the median fallback, D33), in 107 recording sessions.

| Split | Slots | Valorant | League of Legends | CS2 |
|---|---:|---:|---:|---:|
| train | 1,258 | 857 | 191 | 210 |
| val | 366 | 255 | 50 | 61 |
| test_session | 365 | not evaluated | | |

| Game | Videos | Recording sessions | Sources | Footage |
|---|---:|---:|---:|---:|
| Valorant | 76 | 67 | 3 (mine + 2 contributors) | about 141 min |
| League of Legends | 12 | 12 | 1 (mine) | about 30 min |
| CS2 | 33 | 28 | 2 (mine + 1 contributor) | about 45 min |

Tiers half full, half CRF 45 in every split (D04). Test splits not opened (split not frozen, D13).

**Run.** `gfc-train-baseline` with the default config: 16-bin RGB histograms, standardised, logistic regression, `C` picked on val (`C = 1.0`).

**Val results.**

| | Precision | Recall | F1 |
|---|---:|---:|---:|
| Valorant | 0.90 | 0.71 | 0.79 |
| League of Legends | 0.65 | 0.94 | 0.77 |
| CS2 | 0.44 | 0.67 | 0.53 |
| **Accuracy / macro-F1** | | | **0.732 / 0.697** |

- Valorant is 70 % of val, so accuracy alone is close to always answering Valorant (0.697); macro-F1 against 0.33 by chance is the fairer reading.
- League of Legends is separated by its palette. Valorant and CS2, two tactical shooters, are mostly confused with each other (53 Valorant frames called CS2, 17 CS2 frames called Valorant).
- Example errors: a dark CS2 buy menu called League of Legends; gold-tinted Valorant frames called CS2; sandy CS2 maps called Valorant. These are the cases a colour histogram cannot separate and spatial layout should.
- By tier: full 0.71, CRF 45 0.75 accuracy; the low tier does not hurt this model.

The run folder, the split snapshot, figures (confusion matrix, example grid, class counts, example frames) and per-source tables are archived locally for the reports; the figures contain gameplay frames and stay out of the repo until they are checked for personal details.

**Next.** A larger histogram run once more footage is in; footage for Minecraft, Overwatch 2 and Marvel Rivals; the CNN on the same split for the comparison.
