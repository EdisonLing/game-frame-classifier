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

**By person and source** (train and val as used by this run and the CNN below; aliases, no names; slots / videos / sessions; "left out" = train slots removed by the source cap, kept on disk):

| Person / source | Kind | Game | train slots / videos / sessions | val slots / videos / sessions | Left out (cap) |
|---|---|---|---:|---:|---:|
| P1-a | personal | CS2 | 65 / 2 / 2 | 5 / 1 / 1 | 0 |
| P1-a | personal | League_of_Legends | 191 / 7 / 7 | 50 / 2 / 2 | 0 |
| P1-a | personal | Valorant | 141 / 4 / 4 | 37 / 1 / 1 | 0 |
| P2-a | contributor | CS2 | 145 / 22 / 19 | 56 / 5 / 5 | 81 |
| P2-a | contributor | Valorant | 358 / 25 / 23 | 44 / 4 / 4 | 0 |
| P3 | contributor | Valorant | 358 / 22 / 19 | 174 / 7 / 6 | 264 |
| **All** | | | **1258 / 82 / 74** | **366 / 20 / 19** | **345** |

- P1-a: Person 1 (the author), current PC, own recordings
- P2-a: Person 2, Frame Export Kit packs
- P3: Person 3, Frame Export Kit packs

**Extraction, recording properties and cleaning** (videos in train and val):

- Native resolutions (videos): CS2: 1920x1080 27, 3840x2160 3; League_of_Legends: 1920x1080 5, 3840x2160 4; Valorant: 1920x1080 28, 2560x1440 28, 3620x2036 2, 3840x2160 5
- Video codecs: CS2: av1 3, h264 27; League_of_Legends: av1 9; Valorant: av1 5, h264 58
- Frame rate: CS2: variable 30; League_of_Legends: variable 9; Valorant: variable 63
- Low-tier encoder (D28): CS2: h264_d3d12va 3, libx264 27; League_of_Legends: h264_d3d12va 9; Valorant: h264_d3d12va 5, libx264 58
- Recording time taken from: CS2: container 27, filename 3; League_of_Legends: filename 9; Valorant: container 58, filename 5 (mtime is low trust)
- Derive: pad16x9_bicubic_256x144_q2
- Extraction recipe `2026-11-17b`: one sample per 5 s bucket, low tier CRF/QP 45, low-tier encode window 1.0 s
- Cleaning (all frames at the time of the split): kept 2346 of 2705; rejected by reason {'duplicate': 359}; by game CS2 447 kept / 125 rejected, League_of_Legends 284 kept / 95 rejected, Valorant 1615 kept / 139 rejected; by person P1-a 615 / 159, P2-a 780 / 117, P2-b 12 / 0, P3 939 / 83
- Cleaning rules: black if mean < 8.0 and std < 4.0; blurred if Laplacian variance < 400.0; near-duplicate if the 8x8 aHash is within 6 bits of an earlier kept frame of the same source; slots on the hand quarantine list

**Possible shortcut.** Recording properties line up partly with the class: every League of Legends video is from P1-a (AV1, GPU-encoded low tier), while most Valorant and CS2 videos are contributor H.264 with a CPU-encoded low tier. A model could learn encoder or codec traces instead of the game. Checks: Valorant and CS2 each have both low-tier encoders, and `by_encoder` reports accuracy per encoder; the unseen-person check below uses a different person's recordings. League of Legends from another source is needed to rule it out for that class.

**Never-seen test data.** `test_session` (365 slots, held-out recording sessions) exists and was not opened. The report's held-out design (G1: held-out sessions and held-out people, with source groups) is open; footage recorded after the split and an older PC's recordings (P1-b) are the planned new data.

**Run.** `gfc-train-baseline` with the default config (`config/baseline.json`): 16-bin RGB histograms per channel (48 values, each channel summing to 1) of the 256×144 frame, standardised, multinomial logistic regression (lbfgs, `class_weight="balanced"`, max 2,000 iterations, seed 360), `C` picked on val from {0.01, 0.1, 1, 10} by macro-F1, ties to the smaller `C`.

| C | Val accuracy | Val macro-F1 |
|---:|---:|---:|
| 0.01 | 0.694 | 0.644 |
| 0.1 | 0.724 | 0.683 |
| **1.0** | **0.732** | **0.697** |
| 10 | 0.727 | 0.692 |

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
- By low-tier encoder: GPU-encoded 0.848 (46 slots, mostly League of Legends), CPU-encoded 0.721 (136); within Valorant both are 0.722, so the gap follows the game, not the encoder.

**Challenges.** One contributor pack was first refused at ingest (one video one frame short at its end; ingest now accepts this with a warning). Three games have no footage yet. Valorant is 70 % of val, which makes accuracy misleading on its own.

**Reproduce.** `gfc-make-sources --budget-hours 0.5`, `gfc-ingest-pack` for each pack, `gfc-derive-frames`, `gfc-clean-frames --slots data/manifests/slots.csv`, `gfc-split` (`config/split.json`, split `v1`), `gfc-train-baseline --split-dir data/manifests/splits/v1 --tag first3games` at commit `d2a997c` (scikit-learn 1.8.0, NumPy 2.3.5); evaluation runs at the end of training.

**Archive.** `data/archive/2026-11-18_baseline_first3games/` (local): run, split, manifests, figures (confusion matrix, example grid, class counts, example frames per class), README.

The run folder, the split snapshot, figures (confusion matrix, example grid, class counts, example frames) and per-source tables are archived locally for the reports; the figures contain gameplay frames and stay out of the repo until they are checked for personal details.

**Next.** A larger histogram run once more footage is in; footage for Minecraft, Overwatch 2 and Marvel Rivals.

## 2026-11-18 — CNN, same data as the baseline above

**Data.** Exactly the baseline's train and val: the same split files (identical SHA-256), 1,258 train and 366 val slots over Valorant, League of Legends and CS2, half full and half CRF 45.

**Run.** `gfc-train-cnn` with the default config (D16, D37):

| | |
|---|---|
| Model | FrameCNN, below; random initialisation (PyTorch defaults), no pretrained weights |
| Training | Adam, lr 1e-3, weight decay 1e-4, batch 64, cross-entropy with class weights from train (D34); augmentation on train only: zoom 0.85–1.15 and shift up to 2 % on half the frames, colour jitter on 80 %, no flips (D35) |
| Selection | Best val macro-F1, early stop after 6 epochs without improvement; seed 360 |
| Hardware | AMD RX 9070 XT, ROCm build of PyTorch 2.14; 30 s for the first epoch (kernel warm-up), 4.6 s for each later one, about 76 s in total |

| Layer | Output (C×H×W) | Parameters |
|---|---|---:|
| Input: RGB 256×144, scaled to [-1, 1] | 3×144×256 | 0 |
| Block 1: conv 3×3, 3→32 (no bias), batch norm, ReLU, max pool 2×2 | 32×72×128 | 928 |
| Block 2: conv 3×3, 32→64, batch norm, ReLU, max pool | 64×36×64 | 18,560 |
| Block 3: conv 3×3, 64→128, batch norm, ReLU, max pool | 128×18×32 | 73,984 |
| Block 4: conv 3×3, 128→256, batch norm, ReLU, max pool | 256×9×16 | 295,424 |
| Flatten (keeps where on screen each feature fired) | 36,864 | 0 |
| FC 36,864→256, ReLU, dropout 0.5 | 256 | 9,437,440 |
| FC 256→6 (logits; softmax for reporting only) | 6 | 1,542 |
| **Total** | | **9,827,878** |

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

**Encoder check.** By low-tier encoder: CPU-encoded 1.000 (136 slots), GPU-encoded 1.000 (46); Valorant and CS2 each score 1.000 with both encoders, so the encoder is not what separates them. League of Legends comes from one person and one recorder only (see the baseline entry), so for that class the check is still open.

**Why 1.000 is not a leak.** Checked after the run:

| Check | Result |
|---|---|
| Test splits opened | No; the held-out access log did not exist |
| Val used in training | No; only train frames produce gradients. Val picks the best epoch and the stopping point only, and every epoch from 3 to 11 scores 0.98–1.00, so the choice adds almost no optimism |
| Clips, sessions or slots shared between splits | 0 for every pair of train, val and test_session |
| Near-duplicate frames across train and val | None: the closest train frame of the same source is at aHash distance 7 or more for every val frame (duplicates are ≤ 6); 247 of 366 are above 10 |

**Challenges.** The first epoch takes 30 s for GPU kernel selection; a known MIOpen database warning on this GPU is harmless. A perfect val score had to be checked for leaks (table above) before it could be trusted.

**Reproduce.** `.venv-rocm` Python: `python -m game_frame_classifier.train --split-dir data/manifests/splits/v1 --tag first3games` (`config/train_cnn.json`, seed 360) at commit `b3d9259`; evaluation on val runs at the end; `gfc-evaluate --compare <baseline run> <cnn run> --split val`.

**Archive.** Same folder as the baseline: `cnn_run/` (run, history, curves, checkpoints, val evaluation) and `compare/`.

**How to read it.** Three games with very different screen layouts (a top-down MOBA and two shooters with distinct HUDs) are an easy task for a model that sees layout; the CNN fixes exactly the cases the colour histogram could not separate. Val shares people with train (different sessions), and League of Legends has a single source, so this run does not show generalisation to new people or the hard pair (Overwatch 2 and Marvel Rivals). The next entry tests the first point.

## 2026-11-18 — Development check: an unseen person (Valorant)

**Question.** Does the CNN recognise a game when the player, setup and recordings were never seen in training, or has it learned each person's recording setup?

**Setup.** A separate development split (`dev-srcout-1`, own ledger, frozen only so the held-out set can be scored; the report's held-out design, G1, is still open). One contributor's Valorant footage was held out completely as `test_source`: 939 slots from 34 videos in 28 sessions. Training data: Valorant from the two other sources, League of Legends and CS2 as before (679 train slots after the source cap, 230 val). Both models were trained with their default configs on this split and scored once on the held-out person; the access is logged.

**By person and source** (all splits of `dev-srcout-1`; slots / videos / sessions). P2-b, one raw video of person 2, is in train while P2-a (the same person's packs) has frames in val and test_session; the held-out person P3 appears only in `test_source`, so the unseen-person result is not affected:

| Person / source | Kind | Game | train slots / videos / sessions | val slots / videos / sessions | test_session slots / videos / sessions | test_source slots / videos / sessions | Left out (cap) |
|---|---|---|---:|---:|---:|---:|---:|
| P1-a | personal | CS2 | 65 / 2 / 2 | 5 / 1 / 1 | 95 / 3 / 1 | – | 0 |
| P1-a | personal | League_of_Legends | 87 / 6 / 6 | 50 / 2 / 2 | 59 / 4 / 4 | – | 76 |
| P1-a | personal | Valorant | 141 / 4 / 4 | 37 / 1 / 1 | – | – | 0 |
| P2-a | contributor | CS2 | 145 / 22 / 19 | 56 / 5 / 5 | – | – | 81 |
| P2-a | contributor | Valorant | 229 / 22 / 19 | 82 / 7 / 7 | 98 / 8 / 8 | – | 89 |
| P2-b | personal | League_of_Legends | 12 / 1 / 1 | – | – | – | 0 |
| P3 | contributor | Valorant | – | – | – | 939 / 34 / 28 | 0 |
| **All** | | | **679 / 57 / 51** | **230 / 16 / 16** | **252 / 15 / 13** | **939 / 34 / 28** | **246** |

- P1-a: Person 1 (the author), current PC, own recordings
- P2-a: Person 2, Frame Export Kit packs
- P2-b: Person 2, one raw video extracted by gfc-make-sources
- P3: Person 3, Frame Export Kit packs

**Integrity** (`dev-srcout-1`):

| Pair | Shared clips | Shared sessions | Shared slots |
|---|---:|---:|---:|
| train / val | 0 | 0 | 0 |
| train / test_session | 0 | 0 | 0 |
| train / test_source | 0 | 0 | 0 |
| val / test_session | 0 | 0 | 0 |
| val / test_source | 0 | 0 | 0 |
| test_session / test_source | 0 | 0 | 0 |

| Pair | Frames compared | aHash ≤ 6 (duplicate) | Smallest distance | Distance > 10 |
|---|---:|---:|---:|---:|
| val vs train | 230 | 0 | 7 | 156 |
| test_session vs train | 252 | 0 | 7 | 182 |
| test_source vs train | 0 (no frame shares a source with train) | – | – | – |

- `test_session.csv` matches the hash stored at training time
- `test_source.csv` matches the hash stored at training time
- `train.csv` matches the hash stored at training time
- `val.csv` matches the hash stored at training time
- Held-out access for this run: test_source (development check: unseen Valorant contributor (dev split, not the report test))

**Results.**

| | Val accuracy / macro-F1 | Held-out person accuracy (939 Valorant frames) | Called CS2 | Called League of Legends |
|---|---:|---:|---:|---:|
| Baseline (colour histogram) | 0.717 / 0.724 | 0.570 | 315 | 89 |
| CNN | 0.996 / 0.996 | **0.970** | 25 | 3 |

- The CNN keeps 97 % on a person it never saw (best epoch 9 of 15); errors are mostly Valorant called CS2, the other shooter. Full and CRF 45 frames score the same (0.970 / 0.971). The weakest held-out videos are at 0.89–0.93; one single-frame video is wrong.
- The baseline drops from 0.72 on val to 0.57 on the unseen person: palette depends more on a person's settings and maps than layout does.
- One held-out person and one game: evidence against "it learned the recording setup", not yet a general result. The report's held-out test (G1) should hold out sources in several games, with source groups so one person cannot sit on both sides.
- The held-out person's low tier is entirely CPU-encoded (475 slots, 0.971), the same encoder as most training Valorant, so this check does not separate encoder from person; it does show a different player, settings and recording hardware are handled.

**Reproduce.** `gfc-split --config <split config>` with `split_id = "dev-srcout-1"`, `holdout_sources = {"Valorant": [<P3's source>]}` and a `test_design` marking it as a development check, then `gfc-split --config ... --freeze`; train both models with `--split-dir data/manifests/splits/dev-srcout-1`; `gfc-evaluate --run <run> --split test_source --reason "development check: ..."`. Commit `b3d9259`.

**Archive.** `data/archive/2026-11-18_baseline_first3games/dev_srcout_1/` (local): split, config, both runs, access log.
