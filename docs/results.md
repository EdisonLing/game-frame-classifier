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

## 2026-11-18 — Baseline and CNN, 6-way vs 7-way (a fourth contributor; Other)

**Question.** With a fourth contributor (P4: five games and Other footage), how do the baseline and the CNN do on more varied data, and does a trained Other class (7-way) detect non-target content better than a 6-way model with a confidence threshold, at what cost to the six games (D24)?

**Data.** Split `v1`, extended (the ledger kept every earlier assignment): train 4,166 / val 1,250 / test_session 1,252 slots, about 3.3 times the first run. League of Legends now comes from three people (it was one), so the earlier recording-setup concern for that class can be checked. Other (67 videos) comes from one person, P4, under a single content name. Overwatch 2 and Marvel Rivals have one video each (train only; not in val or test); Minecraft has none. The train cap (1/15 with the median fallback from three groups up) left out 1,590 train slots, almost all P4's Valorant and CS2.

| Game | train slots | val slots | Videos | Footage (min) |
|---|---:|---:|---:|---:|
| CS2 | 517 | 303 | 74 | 193 |
| League_of_Legends | 1173 | 251 | 65 | 179 |
| Marvel_Rivals | 55 | 0 | 1 | 5 |
| Other | 902 | 197 | 58 | 146 |
| Overwatch_2 | 40 | 0 | 1 | 5 |
| Valorant | 1479 | 499 | 96 | 268 |

- Native resolutions (videos): CS2: 1280x720 22, 1280x960 3, 1920x1080 39, 3840x2160 3, 960x720 7; League_of_Legends: 1280x720 33, 1920x1080 28, 3840x2160 4; Marvel_Rivals: 1920x1080 1; Other: 1280x720 26, 1920x1024 1, 1920x1032 1, 1920x1080 29, 800x600 1; Overwatch_2: 1280x720 1; Valorant: 1280x720 26, 1920x1080 35, 2560x1440 28, 3620x2036 2, 3840x2160 5
- Video codecs: CS2: av1 3, h264 71; League_of_Legends: av1 9, h264 56; Marvel_Rivals: h264 1; Other: h264 58; Overwatch_2: h264 1; Valorant: av1 5, h264 91
- Frame rate: CS2: constant 42, variable 32; League_of_Legends: constant 56, variable 9; Marvel_Rivals: constant 1; Other: constant 58; Overwatch_2: constant 1; Valorant: constant 33, variable 63
- Low-tier encoder (D28): CS2: h264_d3d12va 47, libx264 27; League_of_Legends: h264_d3d12va 65; Marvel_Rivals: h264_d3d12va 1; Other: h264_d3d12va 58; Overwatch_2: h264_d3d12va 1; Valorant: h264_d3d12va 38, libx264 58
- Recording time taken from: CS2: container 27, filename 47; League_of_Legends: filename 65; Marvel_Rivals: filename 1; Other: filename 58; Overwatch_2: filename 1; Valorant: container 58, filename 38 (mtime is low trust)
- Derive: pad16x9_bicubic_256x144_q2
- Extraction recipe `2026-11-17b`: one sample per 5 s bucket, low tier CRF/QP 45, low-tier encode window 1.0 s
- Cleaning (all frames at the time of the split): kept 8258 of 11528; rejected by reason {'blur': 100, 'duplicate': 3170}; by game CS2 1912 kept / 859 rejected, League_of_Legends 1717 kept / 868 rejected, Marvel_Rivals 55 kept / 5 rejected, Other 1293 kept / 919 rejected, Overwatch_2 40 kept / 21 rejected, Valorant 3241 kept / 598 rejected; by person P1-a 615 / 159, P2-a 780 / 117, P2-b 12 / 0, P3 939 / 83, P4 5912 / 2911
- Cleaning rules: black if mean < 8.0 and std < 4.0; blurred if Laplacian variance < 400.0; near-duplicate if the 8x8 aHash is within 6 bits of an earlier kept frame of the same source; slots on the hand quarantine list

**Possible shortcuts.** League of Legends low-tier copies are all GPU-encoded and P1-a's League videos are AV1; Valorant and CS2 have both encoders (`by_encoder` below). Other is entirely P4's footage, so a model could in principle learn "P4's recording setup → Other"; but P4 also contributes 2,000+ train frames of four games recorded the same way, which pushes the model away from that shortcut. A held-out Other source would settle it.

**By person and source** (train and val; slots / videos / sessions):

| Person / source | Kind | Game | train slots / videos / sessions | val slots / videos / sessions | Left out (cap) |
|---|---|---|---:|---:|---:|
| P1-a | personal | CS2 | 65 / 2 / 2 | 5 / 1 / 1 | 0 |
| P1-a | personal | League_of_Legends | 191 / 7 / 7 | 50 / 2 / 2 | 0 |
| P1-a | personal | Valorant | 141 / 4 / 4 | 37 / 1 / 1 | 0 |
| P2-a | contributor | CS2 | 226 / 22 / 19 | 56 / 5 / 5 | 0 |
| P2-a | contributor | Valorant | 358 / 25 / 23 | 44 / 4 / 4 | 0 |
| P3 | contributor | Valorant | 490 / 22 / 19 | 174 / 7 / 6 | 132 |
| P4 | contributor | CS2 | 226 / 38 / 38 | 242 / 6 / 6 | 798 |
| P4 | contributor | League_of_Legends | 982 / 49 / 49 | 201 / 7 / 7 | 0 |
| P4 | contributor | Marvel_Rivals | 55 / 1 / 1 | – | 0 |
| P4 | contributor | Other | 902 / 47 / 47 | 197 / 11 / 11 | 0 |
| P4 | contributor | Overwatch_2 | 40 / 1 / 1 | – | 0 |
| P4 | contributor | Valorant | 490 / 27 / 19 | 244 / 6 / 4 | 660 |
| **All** | | | **4166 / 245 / 229** | **1250 / 50 / 47** | **1590** |

- P1-a: Person 1 (the author), current PC, own recordings
- P2-a: Person 2, Frame Export Kit packs
- P3: Person 3, Frame Export Kit packs
- P4: Person 4, Frame Export Kit packs (mixed-game folder: six games plus Other)

**Method.** Same configs as the earlier runs (`config/baseline.json`, `config/train_cnn.json`, seed 360), once with `label_set = "six"` (Other frames left out of training and val) and once with `"seven"` (default). CNNs on the RX 9070 XT: about 15 s per epoch (6-way) and 19 s (7-way). Commands: `gfc-train-baseline --split-dir data/manifests/splits/v1 --tag p4-six --config <six>` and `--tag p4-seven`; `.venv-rocm` `-m game_frame_classifier.train --split-dir data/manifests/splits/v1 --set label_set=six --tag p4-six` and `--tag p4-seven`; then `gfc-evaluate --compare`. Commit `9bc09b9`.

**Results on val** (development numbers: val chose the best epoch or `C`).

| Run | Best | Six-game accuracy | Six-game macro-F1 | Other flagged at 5 % false alarms | AUROC (Other vs six games) |
|---|---|---:|---:|---:|---:|
| Baseline 6-way | C = 10 | 0.681 | 0.704 | 0.046 | 0.443 |
| Baseline 7-way | C = 1 | 0.626 | 0.679 | 0.325 | 0.706 |
| CNN 6-way | epoch 3 of 9 | 0.979 | 0.986 | 0.508 | 0.927 |
| CNN 7-way | epoch 14 of 20 | 0.959 | 0.977 | **0.904** | **0.984** |

Per game F1 (CNN 6-way / 7-way): Valorant 0.99 / 0.97, League of Legends 1.00 / 0.99, CS2 0.98 / 0.95, Other – / 0.86. Baseline 6-way: Valorant 0.73, League of Legends 0.84, CS2 0.53.

**6-way vs 7-way CNN** (`gfc-evaluate --compare`, paired bootstrap over 1,000 resamples of videos, 95 % intervals):

| Difference (7-way − 6-way) | Value | 95 % interval |
|---|---:|---:|
| Other flagged at 5 % false alarms | +0.396 | [+0.275, +0.564] |
| AUROC | +0.057 | [+0.033, +0.093] |
| Six-game macro-F1 | −0.008 | [−0.025, +0.003] |

**Baseline vs CNN, 6-way:** six-game macro-F1 +0.282 [+0.236, +0.360]; Other detection +0.462 [+0.198, +0.592].

- The trained Other class roughly doubles the share of non-target frames caught at the same false-alarm rate (51 % to 90 %), with a small, not clearly different cost on the six games. Against the D24 rule, the detection gain is clearly above zero, but the six-game interval reaches −0.025, just past the −0.02 limit, so the rule is not met yet; more val footage narrows it, and the rule is meant for a frozen, held-out test.
- This reading is optimistic for 7-way: val Other is the same person and the same content name as train Other (different sessions). Held-out Other content (`holdout_other`) is the real test.
- The CNN's six-game scores stay near the ceiling on three distinct games; the baseline still confuses Valorant and CS2 (CS2 F1 0.53).
- Tiers: CNN 6-way full and CRF 45 both 0.979; 7-way 0.952 / 0.941. Encoders: CNN 6-way 0.985 CPU-encoded vs 0.977 GPU-encoded low tier.

**Integrity.**

| Pair | Shared clips | Shared sessions | Shared slots |
|---|---:|---:|---:|
| train / val | 0 | 0 | 0 |

| Pair | Frames compared | aHash ≤ 6 (duplicate) | Smallest distance | Distance > 10 |
|---|---:|---:|---:|---:|
| val vs train | 1250 | 0 | 7 | 766 |

- `test_session.csv` matches the hash stored at training time
- `test_source.csv` matches the hash stored at training time
- `train.csv` matches the hash stored at training time
- `val.csv` matches the hash stored at training time
- Held-out access for this run: none

**Challenges.** A Windows GPU timeout (driver reset, recovered) occurred once, at the hand-over between the 6-way and 7-way CNN runs; both runs completed and no second timeout occurred. 28 % of frames were near-duplicates (mostly overlapping saves in one contributor's clips) and were removed before splitting.

**Limits and next.** Overwatch 2 and Marvel Rivals (one video each) and Minecraft (none) cannot be evaluated; Other from one person and one content name; no held-out test yet. Next: footage for the missing games, Other from more people and more content names, held-out Other names and the frozen split (G1), then the D24 rule on `test_source`.

**Archive.** `data/archive/2026-11-18_p4_six_vs_seven/` (local): the four runs, both comparisons, the split, manifests, data figures.

## 2026-11-19 — Baseline and CNN with seven more people; development check with whole people held out

**Question.** (1) How do the baseline and the CNN (7-way) change after adding seven people: one who sent original videos (P5: CS2, Minecraft, Overwatch 2, Other) and six who shared Valorant clips through Medal links (P6–P11)? (2) Does the CNN recognise games on people it never saw in training, or does its accuracy come from learning each person's recording artifacts?

**Data.** Split `v1`, extended again (the ledger kept every earlier assignment): train 3,323 / val 1,377 / test_session 1,365 slots from 420 clips of 12 sources (11 people). New: P5's original videos (placed in `data/raw/`, extracted by `gfc-make-sources --budget-hours 0.5`), and 40 Medal clips from six uploaders, downloaded with `gfc-fetch-clips` (one source per uploader) and labelled by their Medal game tag (`gfc-sort-clips --accept-hints`). Medal clips are the service's cloud copies: 34 at 1280×720 60 fps, 5 at 1920×1080, one 640×360. Minecraft now has 3 videos and Overwatch 2 has 8, each class from one or two people; Marvel Rivals still has one video.

| Game | train slots | val slots | test_session slots | Videos | Footage (min) |
|---|---:|---:|---:|---:|---:|
| CS2 | 431 | 303 | 294 | 91 | 226 |
| League_of_Legends | 1173 | 251 | 293 | 81 | 210 |
| Marvel_Rivals | 55 | 0 | 0 | 1 | 5 |
| Minecraft | 29 | 0 | 0 | 3 | 3 |
| Other | 911 | 197 | 227 | 74 | 183 |
| Overwatch_2 | 40 | 65 | 0 | 8 | 11 |
| Valorant | 684 | 561 | 551 | 152 | 335 |

- Native resolutions (videos): CS2: 1280x720 24, 1280x960 3, 1920x1080 50, 3840x2160 6, 960x720 8; League_of_Legends: 1280x720 37, 1920x1080 37, 3840x2160 7; Marvel_Rivals: 1920x1080 1; Minecraft: 1920x1080 3; Other: 1280x720 33, 1920x1024 1, 1920x1032 1, 1920x1080 38, 800x600 1; Overwatch_2: 1280x720 1, 1920x1080 7; Valorant: 1280x720 61, 1920x1080 50, 2560x1440 33, 3620x2036 2, 3840x2160 5, 640x360 1
- Video codecs: CS2: av1 6, h264 85; League_of_Legends: av1 12, h264 69; Marvel_Rivals: h264 1; Minecraft: h264 3; Other: h264 74; Overwatch_2: h264 8; Valorant: av1 5, h264 147
- Frame rate: CS2: constant 45, variable 46; League_of_Legends: constant 68, variable 13; Marvel_Rivals: constant 1; Minecraft: variable 3; Other: constant 69, variable 5; Overwatch_2: constant 1, variable 7; Valorant: constant 75, variable 77
- Low-tier encoder (D28): CS2: h264_d3d12va 63, libx264 28; League_of_Legends: h264_d3d12va 81; Marvel_Rivals: h264_d3d12va 1; Minecraft: h264_d3d12va 2, libx264 1; Other: h264_d3d12va 74; Overwatch_2: h264_d3d12va 8; Valorant: h264_d3d12va 81, libx264 71
- Recording time taken from: CS2: container 27, filename 52, mtime 12; League_of_Legends: filename 81; Marvel_Rivals: filename 1; Minecraft: mtime 3; Other: filename 69, mtime 5; Overwatch_2: filename 1, mtime 7; Valorant: container 71, filename 81 (mtime is low trust). P5's file names were not parsed, so each of P5's games is one session.
- Derive: pad16x9_bicubic_256x144_q2. Extraction recipe `2026-11-17b`: one sample per 5 s bucket, low tier CRF/QP 45, low-tier encode window 1.0 s.
- Cleaning (all frames at the time of the split): kept 8,900 of 12,212; rejected {'blur': 101, 'duplicate': 3211}; rules as before (black mean < 8 and std < 4; Laplacian variance < 400; aHash within 6 bits of an earlier kept frame of the same source); no hand quarantine.
- **Train cap.** With twelve sources the 1/15 cap per source (D33) binds harder: it left out 2,835 train slots (1,590 before), mostly from the large Valorant and CS2 sources. Valorant train fell from 1,479 to 684 slots and CS2 from 517 to 431, although more footage exists.

**Possible shortcuts.** Overwatch 2 train is one video from P4; val Overwatch 2 is entirely P5's, so in `v1` that class is already an unseen-person test. Other is still almost entirely P4 (902 of 911 train slots). Minecraft (one person, 29 slots) and Marvel Rivals (one video) cannot be evaluated. The Medal clips are all 720p/1080p cloud re-encodes and all Valorant; the check below holds one Medal uploader out.

**By person and source, split `v1`** (slots / videos / sessions):

| Person / source | Kind | Game | train | val | test_session | Left out (cap) |
|---|---|---|---:|---:|---:|---:|
| P1-a | personal | CS2 | 65 / 2 / 2 | 5 / 1 / 1 | 95 / 3 / 1 | 0 |
| P1-a | personal | League_of_Legends | 191 / 7 / 7 | 50 / 2 / 2 | 31 / 3 / 3 | 0 |
| P1-a | personal | Valorant | 100 / 4 / 4 | 37 / 1 / 1 | – | 41 |
| P2-a | contributor | CS2 | 148 / 22 / 19 | 56 / 5 / 5 | – | 78 |
| P2-a | contributor | Valorant | 100 / 25 / 23 | 44 / 4 / 4 | 96 / 8 / 7 | 258 |
| P2-b | personal | League_of_Legends | – | – | 12 / 1 / 1 | 0 |
| P3 | contributor | Valorant | 100 / 22 / 19 | 174 / 7 / 6 | 143 / 5 / 3 | 522 |
| P4 | contributor | CS2 | 148 / 33 / 33 | 242 / 6 / 6 | 199 / 7 / 7 | 876 |
| P4 | contributor | League_of_Legends | 982 / 49 / 49 | 201 / 7 / 7 | 250 / 12 / 12 | 0 |
| P4 | contributor | Marvel_Rivals | 55 / 1 / 1 | – | – | 0 |
| P4 | contributor | Other | 902 / 47 / 47 | 197 / 11 / 11 | 194 / 10 / 10 | 0 |
| P4 | contributor | Overwatch_2 | 40 / 1 / 1 | – | – | 0 |
| P4 | contributor | Valorant | 100 / 25 / 19 | 244 / 6 / 4 | 232 / 6 / 4 | 1050 |
| P5 | contributor | CS2 | 70 / 12 / 1 | – | – | 0 |
| P5 | contributor | Minecraft | 29 / 3 / 1 | – | – | 0 |
| P5 | contributor | Other | – | – | 33 / 5 / 1 | 0 |
| P5 | contributor | Overwatch_2 | – | 65 / 7 / 1 | – | 0 |
| P6 | contributor | Valorant | 100 / 10 / 9 | 12 / 1 / 1 | 13 / 1 / 1 | 10 |
| P7 | contributor | Valorant | 18 / 3 / 3 | 17 / 1 / 1 | 42 / 5 / 5 | 0 |
| P8 | contributor | Valorant | 90 / 6 / 4 | 19 / 2 / 1 | – | 0 |
| P9 | contributor | Other | 9 / 1 / 1 | – | – | 0 |
| P9 | contributor | Valorant | 20 / 2 / 2 | – | 25 / 2 / 2 | 0 |
| P10 | contributor | Valorant | 5 / 1 / 1 | – | – | 0 |
| P11 | contributor | Valorant | 51 / 3 / 3 | 14 / 2 / 2 | – | 0 |
| **All** | | | **3323 / 279 / 249** | **1377 / 63 / 53** | **1365 / 68 / 57** | **2835** |

- P1-a: Person 1 (the author), current PC, own recordings
- P2-a / P2-b: Person 2, Frame Export Kit packs / one raw video
- P3: Person 3, Frame Export Kit packs
- P4: Person 4, Frame Export Kit packs (six games plus Other)
- P5: Person 5, original videos sent as zips
- P6–P11: Persons 6–11, Medal clip links (one source per uploader), Medal cloud copies

**Method.** Unchanged configs (`config/baseline.json`, `config/train_cnn.json`, 7-way, seed 360); CNN on the RX 9070 XT (`.venv-rocm`), about 13–15 s per epoch. Commands: `gfc-make-sources --budget-hours 0.5`, `gfc-derive-frames`, `gfc-clean-frames --slots data/manifests/slots.csv`, `gfc-split`; `gfc-train-baseline --split-dir data/manifests/splits/v1 --tag medal-seven`; `.venv-rocm` `-m game_frame_classifier.train --split-dir data/manifests/splits/v1 --tag medal-seven`. Commit `65708e6`.

**Results on val, split `v1`** (development numbers: val chose the best epoch or `C`).

| Run | Best | Accuracy | Macro-F1 | Other flagged at 5 % false alarms | AUROC (Other vs games) |
|---|---|---:|---:|---:|---:|
| Baseline 7-way | C = 0.1 | 0.533 | 0.440 | 0.355 | 0.688 |
| CNN 7-way | epoch 13 of 19 | 0.866 | 0.781 | 0.680 | 0.942 |

Per game F1, CNN (baseline): Valorant 0.96 (0.65), League of Legends 0.91 (0.74), CS2 0.89 (0.35), Overwatch 2 0.46 (0.00), Other 0.68 (0.45). By person, the CNN is at 0.92–1.00 on every person/game with more than 20 val slots except P4's CS2 (0.84), P4's Other (0.64) and P5's Overwatch 2 (0.37, the unseen-person class). Main confusions: Other called League of Legends (37), CS2 called Other (25), Overwatch 2 called Marvel Rivals (24).

- Lower than the previous run (CNN 0.946 on val), for three reasons visible in the tables: val now contains a class from an unseen person (P5's Overwatch 2, trained on one video of P4); the stronger train cap cut Valorant and CS2 training data by more than half; and val Other moved (P4 only) against a larger, more mixed set of games. The val sets differ, so the two numbers are not a paired comparison.
- The baseline stays near the majority share; colour statistics do not separate the games once more people and settings are mixed.

**Development check `dev-srcout-2`: whole people held out.** A separate development split (own ledger, frozen only so the held-out set can be scored; not the report's test design, G1 still open) holds out every game of three people as `test_source`: P2 (CS2, Valorant, and League of Legends as P2-b), P5 (CS2, Overwatch 2, Other) and one Medal uploader, P6 (Valorant). P5's Minecraft stays in training because Minecraft has no other person. Each game with two or more people keeps at least one person on each side. Both models were trained with their default configs on this split and scored once on `test_source`; the access is logged.

| Person / source | Game | train | val | test_session | test_source | Left out (cap) |
|---|---|---:|---:|---:|---:|---:|
| P1-a | CS2 | 134 / 5 / 3 | – | 31 / 1 / 1 | – | 0 |
| P1-a | League_of_Legends | 183 / 8 / 8 | 58 / 2 / 2 | 31 / 2 / 2 | – | 0 |
| P1-a | Valorant | 81 / 5 / 5 | – | – | – | 97 |
| P2-a | CS2 | – | – | – | 282 / 27 / 24 | 0 |
| P2-a | Valorant | – | – | – | 498 / 37 / 34 | 0 |
| P2-b | League_of_Legends | – | – | – | 12 / 1 / 1 | 0 |
| P3 | Valorant | 81 / 20 / 16 | 144 / 5 / 4 | 167 / 6 / 5 | – | 547 |
| P4 | CS2 | 979 / 36 / 36 | 238 / 7 / 7 | 248 / 8 / 8 | – | 0 |
| P4 | League_of_Legends | 966 / 49 / 49 | 220 / 10 / 10 | 247 / 9 / 9 | – | 0 |
| P4 | Marvel_Rivals | 55 / 1 / 1 | – | – | – | 0 |
| P4 | Other | 906 / 48 / 48 | 191 / 9 / 9 | 196 / 11 / 11 | – | 0 |
| P4 | Overwatch_2 | 40 / 1 / 1 | – | – | – | 0 |
| P4 | Valorant | 81 / 21 / 17 | 320 / 6 / 5 | 253 / 6 / 4 | – | 972 |
| P5 | CS2 | – | – | – | 70 / 12 / 1 | 0 |
| P5 | Minecraft | 29 / 3 / 1 | – | – | – | 0 |
| P5 | Other | – | – | – | 33 / 5 / 1 | 0 |
| P5 | Overwatch_2 | – | – | – | 65 / 7 / 1 | 0 |
| P6 | Valorant | – | – | – | 135 / 12 / 11 | 0 |
| P7 | Valorant | 77 / 9 / 9 | – | – | – | 0 |
| P8 | Valorant | 81 / 6 / 3 | – | 24 / 2 / 2 | – | 4 |
| P9 | Other | – | 9 / 1 / 1 | – | – | 0 |
| P9 | Valorant | 32 / 3 / 3 | – | 13 / 1 / 1 | – | 0 |
| P10 | Valorant | 5 / 1 / 1 | – | – | – | 0 |
| P11 | Valorant | 65 / 5 / 5 | – | – | – | 0 |
| **All** | | **3795 / 221 / 206** | **1180 / 40 / 38** | **1210 / 46 / 43** | **1095 / 101 / 73** | **1620** |

| | Val accuracy (people seen in training) | Unseen people accuracy / macro-F1 (1,095 frames) | CS2 (352) | Valorant (633) | League of Legends (12) | Overwatch 2 (65) | Other (33) |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 0.538 | 0.419 / 0.279 | 0.236 | 0.569 | 1.000 | 0.000 | 0.121 |
| CNN (best epoch 8 of 14) | 0.962 | **0.900** / 0.679 | 0.923 | 0.981 | 1.000 | 0.062 | 0.697 |

Unseen people by person (CNN): P2-a CS2 0.908 (282), P2-a Valorant 0.990 (498), P2-b League of Legends 1.000 (12), P5 CS2 0.986 (70), P5 Other 0.697 (33), P5 Overwatch 2 0.062 (65), P6 Valorant (a Medal uploader) 0.948 (135). Errors: Overwatch 2 called Other (34), CS2 (14) or Marvel Rivals (11); CS2 called Other (14) or Valorant (11).

- **Games with several people in training generalise to new people.** On CS2 and Valorant, which have 3–8 people in training, the CNN keeps 0.92 and 0.98 on three people it never saw, including a different recording route (P5's original files, P6's Medal cloud copies). A model that had learned per-person recording artifacts would fail here; it does not.
- **Games with one person in training do not.** Overwatch 2 is trained on one video of one person and drops to 0.06 on a new person; Other, almost all from one person, drops to 0.70. For these classes the model has not learned the game in general, which is the expected result with one source, and it is where more people are needed.
- The 6-point drop from seen people (0.962) to unseen people (0.900) is almost all Overwatch 2 and Other. Excluding those two classes, unseen-people accuracy is 0.962 (958 of 997 frames).
- The baseline falls from 0.54 to 0.42, as on the first unseen-person check: colour statistics carry little game information across people.

**Integrity** (both splits): no clips, sessions or slots shared between any splits; no non-train frame within aHash 6 of a train frame of the same source (smallest distance 7). `v1`: 946 of 1,312 val frames above distance 10. `dev-srcout-2`: test_source shares no source with train. All split files match the hashes stored at training time. Held-out access: `v1` runs none; `dev-srcout-2` runs one `test_source` access each, with the reason "development check: whole people held out of training (dev-srcout-2), learning games vs recording artifacts; not the report's test".

**Challenges.** P5's files came as zips of original videos in a non-standard layout; they were placed under `data/raw/<Game>/<source>/` and `_other/rainbow_six_siege/`. Their file names carry the time in a form the timestamp parser does not read, so each of P5's games became one session (time from file modification). The Medal downloader fell back to a lower-quality copy for one clip (640×360).

**Limits and next.** Overwatch 2, Marvel Rivals and Minecraft need footage from more people before they can be learned or measured; Other needs more people and content names. The 1/15 cap now removes more than half of the large sources' train frames; a cap per person group (`source_groups`) or a higher limit is worth comparing on val. The report's held-out design (G1) can now hold out whole people in CS2 and Valorant. P5's Medal-style file names should be parsed for recording times.

**Archive.** `data/archive/2026-11-19_new_people_and_unseen_people/` (local): the four runs, both splits with the data figures, the development-split config, manifests, access log, README.

## 2026-11-19 — CNN with public datasets added; check of the public data on its game's own players

**Question.** (1) Does adding three licensed public datasets fill the two classes that had almost no data (Minecraft, Marvel Rivals)? (2) Does a model trained on the public data recognise those games when the people who recorded them are not in the public sets, or has it learned the datasets' capture setups?

**Data.** Three public datasets, each approved for local, non-commercial use, with the licence saved before download (`docs/THIRD_PARTY_DATA.md`, `docs/licenses/`):

| Alias | Dataset | Licence | Taken | Frames kept |
|---|---|---|---|---:|
| D1 | OpenAI VPT contractor demos (Minecraft) | MIT; Minecraft not licensed by OpenAI | 15 videos, 3 from each of the five contractor indexes, evenly spaced | 471 |
| D2 | BEDD / BASALT demos (Minecraft) | MIT | 16 videos, 4 per task (find cave, waterfall, animal pen, house) | 332 |
| D3 | MARVELRIVALSYOLO (Marvel Rivals) | Apache-2.0 packaging; no publisher grant | 300 full-screen 1920×1080 screenshots, grouped by 10-minute capture windows (14 groups) | 289 |

- D1 and D2 are 640×360 at 20 fps: lower resolution and frame rate than every other source, and the same capture setup as each other, so they count as one setup for any generalisation claim. D3 is an object-detection dataset; its character crops (odd sizes, not game frames) were excluded and only full-screen captures used; whether they are live play or replays is not verified.
- Public data is off in the default split (`v1` is unchanged). This run uses the preset `config/splits/public_permissive.json`, with its own split id and ledger: train 3,464 / val 1,581 / test_session 1,515 slots.

| Game | train slots | val slots | test_session slots | Videos | Footage (min) |
|---|---:|---:|---:|---:|---:|
| CS2 | 546 | 286 | 301 | 96 | 231 |
| League_of_Legends | 484 | 292 | 250 | 79 | 209 |
| Marvel_Rivals | 226 | 63 | 55 | 15 | 30 |
| Minecraft | 479 | 118 | 149 | 33 | 95 |
| Other | 931 | 204 | 200 | 74 | 183 |
| Overwatch_2 | 40 | 65 | 0 | 8 | 11 |
| Valorant | 758 | 553 | 560 | 149 | 338 |

- Recording properties: Minecraft videos are 1920x1080 3 (P5) and 640x360 30 (D1, D2); Marvel Rivals stills are 1920x1080. Cleaning kept 9,992 of 13,660 frames (rejected: 3,564 near-duplicates, 104 blurred).
- **Train cap in this preset.** The 1/15 cap applies once a game has three or more source groups (D33, option A). Here P2-b's one League of Legends video sits in train, which makes three groups, so P4's League of Legends is capped (691 slots left out); in `v1` the same video sits in test_session, League has two groups in train, and no cap applies. Train League of Legends is 484 slots here against 1,173 in `v1`.

**By person and source, split `public_permissive`** (slots / videos / sessions):

| Person / source | Kind | Game | train | val | test_session | Left out (cap) |
|---|---|---|---:|---:|---:|---:|
| D1 | public | Minecraft | 225 / 8 / 8 | 107 / 3 / 2 | 53 / 3 / 3 | 86 |
| D2 | public | Minecraft | 225 / 10 / 10 | 11 / 2 / 2 | 96 / 4 / 4 | 0 |
| D3 | public | Marvel_Rivals | 171 / 9 / 9 | 63 / 2 / 2 | 55 / 3 / 3 | 0 |
| P1-a | personal | CS2 | 134 / 5 / 3 | 31 / 1 / 1 | – | 0 |
| P1-a | personal | League_of_Legends | 236 / 9 / 9 | 3 / 1 / 1 | 33 / 2 / 2 | 0 |
| P1-a | personal | Valorant | 105 / 4 / 4 | 35 / 1 / 1 | – | 38 |
| P2-a | contributor | CS2 | 206 / 20 / 17 | 65 / 6 / 6 | 11 / 1 / 1 | 0 |
| P2-a | contributor | Valorant | 105 / 30 / 28 | 25 / 2 / 1 | 40 / 4 / 4 | 328 |
| P2-b | personal | League_of_Legends | 12 / 1 / 1 | – | – | 0 |
| P3 | contributor | Valorant | 105 / 22 / 19 | 174 / 6 / 4 | 144 / 5 / 4 | 516 |
| P4 | contributor | CS2 | 206 / 36 / 36 | 190 / 7 / 7 | 220 / 8 / 8 | 849 |
| P4 | contributor | League_of_Legends | 236 / 41 / 41 | 289 / 16 / 16 | 217 / 9 / 9 | 691 |
| P4 | contributor | Marvel_Rivals | 55 / 1 / 1 | – | – | 0 |
| P4 | contributor | Other | 898 / 46 / 46 | 195 / 14 / 14 | 200 / 8 / 8 | 0 |
| P4 | contributor | Overwatch_2 | 40 / 1 / 1 | – | – | 0 |
| P4 | contributor | Valorant | 105 / 23 / 18 | 269 / 6 / 4 | 352 / 7 / 4 | 900 |
| P5 | contributor | CS2 | – | – | 70 / 12 / 1 | 0 |
| P5 | contributor | Minecraft | 29 / 3 / 1 | – | – | 0 |
| P5 | contributor | Other | 33 / 5 / 1 | – | – | 0 |
| P5 | contributor | Overwatch_2 | – | 65 / 7 / 1 | – | 0 |
| P6 | contributor | Valorant | 105 / 10 / 10 | – | 6 / 2 / 1 | 24 |
| P7 | contributor | Valorant | 55 / 7 / 7 | 9 / 1 / 1 | 13 / 1 / 1 | 0 |
| P8 | contributor | Valorant | 81 / 5 / 3 | 28 / 3 / 2 | – | 0 |
| P9 | contributor | Other | – | 9 / 1 / 1 | – | 0 |
| P9 | contributor | Valorant | 32 / 3 / 3 | 13 / 1 / 1 | – | 0 |
| P10 | contributor | Valorant | 5 / 1 / 1 | – | – | 0 |
| P11 | contributor | Valorant | 60 / 4 / 4 | – | 5 / 1 / 1 | 0 |
| **All** | | | **3464 / 304 / 281** | **1581 / 80 / 67** | **1515 / 70 / 54** | **3432** |

- D1–D3: public datasets as in the table above; P1–P11 as in the previous entry.

**Method.** `config/train_cnn.json` unchanged (7-way, seed 360), RX 9070 XT, about 12 s per epoch. Commands: `scripts/fetch_public_samples.py vpt --per-index 3`, `bedd --per-task 4`, `marvelrivals --images 300`; `gfc-make-sources --game Minecraft --source <each> --budget-hours 1`; `gfc-ingest-stills` for the screenshots; derive, clean; `gfc-split --config config/splits/public_permissive.json`; `.venv-rocm` `-m game_frame_classifier.train --split-dir data/manifests/splits/public_permissive --tag public-permissive`. Commit `3bd8560`.

**Results on val** (val chose the best epoch, 14 of 20). The val set differs from `v1`'s, so the comparison shows direction only.

| | `v1` CNN (previous entry) | `public_permissive` CNN |
|---|---:|---:|
| Accuracy / macro-F1 | 0.866 / 0.781 (n = 1,377) | **0.926 / 0.852** (n = 1,581) |
| Minecraft F1 | not measurable (no val frames) | 0.96 (118, all D1/D2) |
| Marvel Rivals F1 | not measurable | 0.82 (63, all D3) |
| Valorant / League of Legends / CS2 F1 | 0.96 / 0.91 / 0.89 | 0.98 / 0.98 / 0.92 |
| Overwatch 2 F1 | 0.46 | 0.49 |
| Other F1 / flagged at 5 % false alarms | 0.68 / 0.680 | 0.81 / 0.907 |

Main confusions: Overwatch 2 called CS2 (18) or Marvel Rivals (17); Other called CS2 (17), Valorant (14) or Marvel Rivals (10).

**Development check `dev-pubout-1`: the public data scored on its game's own players.** Same preset with Minecraft and Marvel Rivals trained only on public data: P5's Minecraft (29 frames, 3 videos) and P4's Marvel Rivals (55 frames, 1 video) held out as `test_source` (own ledger, frozen only to score it; not the report's test design, G1 open). CNN best epoch 10 of 16; val 0.923; scored once on `test_source` (access logged).

| Game | Trained on | Val (same datasets) | Held-out player |
|---|---|---:|---:|
| Minecraft | D1 + D2 only | 0.991 (107) | **0.103** (29; 16 called Other, 7 Marvel Rivals) |
| Marvel Rivals | D3 only | 0.970 (33) | **0.745** (55; 11 called Other) |

- **The Minecraft datasets teach their capture setup, not Minecraft in general.** Trained on 640×360, 20 fps contractor footage, the model calls a player's own 1080p Minecraft "Other". The 0.96 Minecraft F1 above measures recognition of D1/D2-style footage only; it says little about Minecraft clips in general. More Minecraft footage from people, at ordinary resolutions, is needed before a Minecraft number means much.
- **The Marvel Rivals screenshots transfer partly** (0.745 on a player's video), so they carry real game appearance, but one held-out video is a small test.
- The run supports keeping public data opt-in and reporting public-only classes separately.

**Integrity.** `public_permissive`: no clips, sessions or slots shared between splits; no val or test_session frame within aHash 6 of a train frame of the same source (smallest distance 7; 1,116 of 1,507 val frames above 10); split files match the hashes stored at training time; held-out access none. `dev-pubout-1`: test_source shares no source with train; one logged access with the reason "development check: Minecraft and Marvel Rivals trained only on public data, scored on the people who recorded them (dev-pubout-1); not the report's test".

**Challenges.** Some files in the VPT index no longer exist on the host (HTTP 404); the fetch script skips to the next file in the same index. The Marvel Rivals dataset mixes character crops with full screenshots; the crops failed frame derivation and were dropped. The Overwatch dataset (Game-Intention) is gated and needs a manual access request.

**Limits and next.** Val Minecraft and Marvel Rivals come only from the public sets, so their val F1 is optimistic (shown by the held-out check). Overwatch 2 is still one person in training. Next: Minecraft, Overwatch 2 and Marvel Rivals clips from more people; the Game-Intention access request; decide whether public data enters the report's main model or stays a separate comparison.

**Archive.** `data/archive/2026-11-19_public_data/` (local): both runs, both splits with the data figures, the configs, access log, README.

## 2026-11-19 — CNN with more people (split `v1x`), three seeds, and a leave-one-person-out check on every person

**Question.** (1) Does the data added since the last entry (new people for Overwatch 2, CS2, League of Legends and Other, two YouTube channels whose owners agreed to be used, one more Medal contributor) improve the CNN on the same validation rows, once seed noise is accounted for? (2) How well does the CNN recognise a person it never saw, for every person and game where that can be measured?

**Data.** Default split policy (personal and contributor sources, no public datasets), 14 people (P1–P14), 15 sources, 683 clips, 14,996 extracted slots of which 11,055 were kept by cleaning (rejected: 3,836 near-duplicates, 104 blurred, 1 black). Split `v1x` is the `v1` ledger extended with the new data under its own id, so every earlier val and test_session slot stays where it was; `v1` itself is unchanged (split hashes identical). New people since `v1`: P12 and P13 (YouTube channels, contributors who agreed to be used, `friend_` sources), P14 (Medal clips). No source labelled as downloaded from the public web (`yt_`, kind `web`) is in this data yet.

| Split `v1x` | Slots | Videos | Sessions |
|---|---:|---:|---:|
| train | 2,526 | 402 | 278 |
| val | 1,510 | 82 | 63 |
| test_session | 1,498 | 94 | 68 |

| Game | train | val | test_session | Videos | Footage (min) |
|---|---:|---:|---:|---:|---:|
| Valorant | 830 | 588 | 602 | 246 | 359 |
| League of Legends | 1,168 | 353 | 353 | 147 | 275 |
| CS2 | 282 | 303 | 308 | 89 | 198 |
| Other | 105 | 201 | 227 | 69 | 144 |
| Overwatch 2 | 57 | 65 | 8 | 23 | 13 |
| Marvel Rivals | 55 | 0 | 0 | 1 | 5 |
| Minecraft | 29 | 0 | 0 | 3 | 3 |

Compared with `v1` (train 3,323 / val 1,377 / test_session 1,365): val and test_session each gained 133 slots and kept all earlier ones; train fell by 1,493 slots (the 1/15 source cap tightened as sources were added, mostly P4's Other and CS2: 902 to 48 and 148 to 70 train slots) and gained 696. Overwatch 2 went from 105 to 130 used slots and from 2 to 4 people (P4, P5, P12, P14). The per-person table by split and the left-out counts are in the archive (`tables_v1x.md`). Recording properties: 1,280×720 and 1,920×1,080 H.264 for most clips, AV1 for 43 videos (League of Legends 32, CS2 6, Valorant 5), mostly 3,840×2,160; recording times mostly from the file name. Cleaning rules: black below mean 8 and std 4, blurred below Laplacian variance 400, near-duplicate within 6 bits of the 8×8 aHash of an earlier kept frame of the same source. Marvel Rivals (one person) and Minecraft (one person) have no val or test slots in this policy.

**Method.** Unchanged configs (`config/baseline.json`, `config/train_cnn.json`, 7-way, seed 360; extra seeds 361 and 362 via `--set seed=`); CNN on the RX 9070 XT (`.venv-rocm`), about 10 s per epoch, early stopping with patience 6. Commands: `gfc-make-sources`, `gfc-derive-frames`, `gfc-clean-frames --slots data/manifests/slots.csv`, `gfc-split` with the `v1` ledger copied to `v1x`, `gfc-train-baseline` and `-m game_frame_classifier.train --split-dir data/manifests/splits/v1x --tag web-contrib`. Leave-one-person-out: for each person a split `lopo-p<n>` (same policy, that person's footage held out as `test_source` in every game where at least two other people have 15 or more kept slots), frozen as a development check, both models trained on it and scored once on the held-out footage with a logged reason. Commit `e8802f0`.

**Results on val** (development numbers: val chose the best epoch or `C`). Scored on the 1,377 val slots that `v1` and `v1x` share:

| Seed | Split | Accuracy | Macro-F1 | Overwatch 2 F1 | League of Legends F1 | Other F1 |
|---|---|---:|---:|---:|---:|---:|
| 360 | `v1` | 0.866 | 0.781 | 0.46 | 0.91 | 0.68 |
| 361 | `v1` | 0.882 | 0.785 | 0.40 | 0.98 | 0.71 |
| 362 | `v1` | 0.897 | 0.820 | 0.54 | 0.95 | 0.71 |
| 360 | `v1x` | 0.891 | 0.859 | 0.74 | 0.98 | 0.72 |
| 361 | `v1x` | 0.882 | 0.844 | 0.70 | 0.96 | 0.71 |
| 362 | `v1x` | 0.880 | 0.834 | 0.66 | 0.98 | 0.68 |

Over three seeds, accuracy is about the same (mean 0.882 on `v1`, 0.885 on `v1x`, ranges overlap). Macro-F1 is higher on `v1x` (mean 0.795 to 0.845; the ranges 0.781–0.820 and 0.834–0.859 do not overlap), and almost all of it is Overwatch 2 F1 (mean 0.47 to 0.70, ranges 0.40–0.54 and 0.66–0.74). The single seed-360 comparison suggested a 0.025 accuracy gain; the other seeds show that part was noise. Baseline (own val, no seed): accuracy 0.533 / macro-F1 0.440 on `v1`, 0.530 / 0.460 on `v1x`. The two changes happen together (new people added, source cap tightened), so the gain cannot be assigned to the new data alone.

**Unseen people** (CNN, `test_source`, 9,879 frames from 14 people, each person held out once; development check, not the report's test design):

| Held-out person | Valorant | League of Legends | CS2 | Overwatch 2 | Other | All frames |
|---|---:|---:|---:|---:|---:|---:|
| P1 | 176/178 | 727/746 | 155/165 | - | - | 1058/1089 (0.97) |
| P2 | 489/498 | 12/12 | 274/282 | - | - | 775/792 (0.98) |
| P3 | 928/939 | - | - | - | - | 928/939 (0.99) |
| P4 | 1499/1626 | 1271/1433 | 1083/1465 | 35/40 | 690/1293 | 4578/5857 (0.78) |
| P5 | - | - | 70/70 | 36/65 | 20/33 | 126/168 (0.75) |
| P6 | 129/135 | - | - | - | - | 129/135 (0.96) |
| P7 | 77/77 | - | - | - | - | 77/77 (1.00) |
| P8 | 106/109 | - | - | - | - | 106/109 (0.97) |
| P9 | 42/45 | - | - | - | 2/9 | 44/54 (0.81) |
| P10 | 4/5 | - | - | - | - | 4/5 (0.80) |
| P11 | 59/65 | - | - | - | - | 59/65 (0.91) |
| P12 | 257/276 | 144/144 | 7/7 | 16/21 | 16/52 | 440/500 (0.88) |
| P13 | 50/52 | - | 14/14 | - | - | 64/66 (0.97) |
| P14 | - | - | - | 15/23 | - | 15/23 (0.65) |

Pooled over all held-out frames: CNN accuracy 0.851, macro-F1 0.725 over the five games that can be evaluated; mean accuracy per person 0.887. Per game (recall / precision): Valorant 0.95 / 0.96 (12 people), League of Legends 0.92 / 0.96 (4), CS2 0.80 / 0.93 (6), Overwatch 2 0.68 / 0.21 (4), Other 0.52 / 0.57 (4). Baseline: accuracy 0.397, macro-F1 0.319, Overwatch 2 recall 0.09. Marvel Rivals and Minecraft each have one person, so no unseen-person score exists for them.

**Confusion.** Overwatch 2 has low precision because Other is read as Overwatch 2: 344 held-out Other frames (335 of them P4's) were predicted Overwatch 2, with only 105 Other train slots left after the cap. Other is also read as Valorant (100) and CS2 (65). The weakest person-and-game cells are P4 in CS2 (0.74) and Other (0.53), P5 in Overwatch 2 (0.55), P12 in Other (0.31) and P14 in Overwatch 2 (0.65, 23 frames).

**Integrity.** No clip, session or slot is shared between train, val and test_session in `v1x`; no val or test_session frame is within 6 bits of a train frame (smallest distance 7). The split files match the hashes stored at training time. Held-out access: each leave-one-person-out scoring is in `data/runs/holdout_access.jsonl` with its reason ("development check: leave-one-person-out, held-out person P<n>"); `test_session` and the report's held-out design are not touched.

**Challenges.** The dataset is dominated by one person (P4: 5,857 of 9,879 held-out frames) and by Valorant, so pooled numbers lean on them; the source cap changes how much each person contributes whenever a source is added. Overwatch 2 rests on four people and 130 used slots, and Other on a handful of people, which also makes the Overwatch 2 versus Other confusion. One seed per fold in the leave-one-person-out check.

**Limits and next.** This does not show performance on the report's held-out test design, on Marvel Rivals or Minecraft players (one person each), or on people from channels that never agreed to be used. Next: more people for Overwatch 2, Marvel Rivals and Minecraft (public YouTube channels with continuous gameplay, labelled as web sources), a larger and more varied Other class, then repeat this check; consider source-balanced sampling and a pretrained backbone.

**Archive.** `data/archive/2026-11-19_v1x_seeds_and_lopo/` (local): split `v1x`, the seed runs, the leave-one-person-out run metrics and predictions, the data tables, the access log, README.
