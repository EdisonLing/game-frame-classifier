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

**Next.** A larger histogram run once more footage is in; footage for Minecraft, Overwatch 2 and Marvel Rivals.

## 2026-11-18 — CNN, same data as the baseline above

**Data.** Exactly the baseline's train and val: the same split files (identical SHA-256), 1,258 train and 366 val slots over Valorant, League of Legends and CS2, half full and half CRF 45.

**Run.** `gfc-train-cnn` with the default config (D16, D37):

| | |
|---|---|
| Model | FrameCNN: four blocks of 3×3 conv (no bias), batch norm, ReLU, 2×2 max pool (32, 64, 128, 256 channels); flatten (256×9×16 = 36,864 features), FC 256, ReLU, dropout 0.5, FC 6. 9,827,878 parameters, random initialisation |
| Training | Adam, lr 1e-3, weight decay 1e-4, batch 64, cross-entropy with class weights from train (D34); augmentation on train only: zoom 0.85–1.15 and shift up to 2 % on half the frames, colour jitter on 80 %, no flips (D35) |
| Selection | Best val macro-F1, early stop after 6 epochs without improvement; seed 360 |
| Hardware | AMD RX 9070 XT, ROCm build of PyTorch 2.14; 30 s for the first epoch (kernel warm-up), 4.6 s for each later one, about 76 s in total |

**Training history.**

| Epoch | Train loss | Train acc | Val loss | Val acc | Val macro-F1 | Seconds |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4.466 | 0.668 | 6.458 | 0.536 | 0.369 | 30.1 |
| 2 | 0.961 | 0.910 | 0.591 | 0.883 | 0.799 | 4.6 |
| 3 | 0.320 | 0.948 | 0.007 | 0.997 | 0.997 | 4.6 |
| 4 | 0.167 | 0.970 | 0.007 | 0.995 | 0.993 | 4.6 |
| **5** | 0.087 | 0.979 | 0.001 | **1.000** | **1.000** | 4.8 |
| 6 | 0.059 | 0.981 | 0.001 | 1.000 | 1.000 | 4.6 |
| 7 | 0.057 | 0.979 | 0.003 | 0.997 | 0.997 | 4.6 |
| 8 | 0.039 | 0.987 | 0.033 | 0.981 | 0.977 | 4.6 |
| 9 | 0.029 | 0.985 | 0.001 | 1.000 | 1.000 | 4.6 |
| 10 | 0.044 | 0.990 | 0.022 | 0.986 | 0.981 | 4.6 |
| 11 | 0.059 | 0.984 | 0.062 | 0.992 | 0.987 | 4.6 |

Best epoch 5 (first to reach 1.000); stopped after epoch 11. Train accuracy stays below val because augmentation applies to train only; the two curves converge by epoch 3 and do not separate later, so there is no sign of overfitting.

**Val results.** Accuracy 1.000 and macro-F1 1.000 (366 of 366); every game F1 1.00; full and CRF 45 tiers both 1.000. Against the baseline on the same rows: accuracy +0.268, macro-F1 +0.303, CS2 F1 +0.47 (`gfc-evaluate --compare`, same split hash).

**Why 1.000 is not a leak.** Checked after the run:

| Check | Result |
|---|---|
| Test splits opened | No; the held-out access log did not exist |
| Val used in training | No; only train frames produce gradients. Val picks the best epoch and the stopping point only, and every epoch from 3 to 11 scores 0.98–1.00, so the choice adds almost no optimism |
| Clips, sessions or slots shared between splits | 0 for every pair of train, val and test_session |
| Near-duplicate frames across train and val | None: the closest train frame of the same source is at aHash distance 7 or more for every val frame (duplicates are ≤ 6); 247 of 366 are above 10 |

**How to read it.** Three games with very different screen layouts (a top-down MOBA and two shooters with distinct HUDs) are an easy task for a model that sees layout; the CNN fixes exactly the cases the colour histogram could not separate. Val shares people with train (different sessions), and League of Legends has a single source, so this run does not show generalisation to new people or the hard pair (Overwatch 2 and Marvel Rivals). The next entry tests the first point.

## 2026-11-18 — Development check: an unseen person (Valorant)

**Question.** Does the CNN recognise a game when the player, setup and recordings were never seen in training, or has it learned each person's recording setup?

**Setup.** A separate development split (`dev-srcout-1`, own ledger, frozen only so the held-out set can be scored; the report's held-out design, G1, is still open). One contributor's Valorant footage was held out completely as `test_source`: 939 slots from 34 videos in 28 sessions. Training data: Valorant from the two other sources, League of Legends and CS2 as before (679 train slots after the source cap, 230 val). Both models were trained with their default configs on this split and scored once on the held-out person; the access is logged.

**Results.**

| | Val accuracy / macro-F1 | Held-out person accuracy (939 Valorant frames) | Called CS2 | Called League of Legends |
|---|---:|---:|---:|---:|
| Baseline (colour histogram) | 0.717 / 0.724 | 0.570 | 315 | 89 |
| CNN | 0.996 / 0.996 | **0.970** | 25 | 3 |

- The CNN keeps 97 % on a person it never saw (best epoch 9 of 15); errors are mostly Valorant called CS2, the other shooter. Full and CRF 45 frames score the same (0.970 / 0.971). The weakest held-out videos are at 0.89–0.93; one single-frame video is wrong.
- The baseline drops from 0.72 on val to 0.57 on the unseen person: palette depends more on a person's settings and maps than layout does.
- One held-out person and one game: evidence against "it learned the recording setup", not yet a general result. The report's held-out test (G1) should hold out sources in several games, with source groups so one person cannot sit on both sides.
