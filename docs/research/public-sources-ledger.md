# Public sources ledger

Tracks third-party **labelled still / labelled video** datasets that may enter training. Personal and contributor sources are not listed here.

**Status:** `planned` (approved shape, not on disk) · `active` (in `data/frame_sources` / training) · `retired` (removed; attribution dropped)

Filter rule (2026-11-18): only datasets that ship **labelled still frames** or **labelled videos** with a game (or class) label. Metadata-only, annotations-without-media, and non-gameplay crops are out — see [public-dataset-use-plan.md](public-dataset-use-plan.md).

Source folder names must start with `public_` so `gfc-derive-frames` / `gfc-split` mark `source_kind=public`.

| source_id | status | games | dataset_name | official_url | license_spdx | commercial_ok | attribution_text | date_accessed | date_activated | date_retired | notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `public_gamed` | active | Valorant, CS2 | Gamed game-classification | https://huggingface.co/datasets/ybashir/gamed-game-classification-dataset | CC-BY-4.0 | review | Frames from the Gamed dataset (ybashir), CC BY 4.0; underlying footage remains with uploaders and publishers. | 2026-11-18 | 2026-11-18 | | Prototype: eval zip → 1 Valorant + 1 CS2 clip (150 frames each); derived OK; cleaner kept 6/300 (rest near-dupes at 224² — expect sparse keep from this dump). |
| `public_gameplay_images` | active | Minecraft | Gameplay Images | https://www.kaggle.com/datasets/aditmagotra/gameplay-images | CC-BY-4.0 | review | Minecraft stills from Gameplay Images (Adit Magotra), CC BY 4.0. | 2026-11-18 | 2026-11-18 | | Prototype: 30 stills → 3 synthetic clips (10 frames each) via HF `Bingsu/Gameplay_Images`; derived with `gfc-derive-frames --source public_gameplay_images`. |
| `public_vpt_contractor` | planned | Minecraft | OpenAI VPT contractor demos | https://github.com/openai/Video-Pre-Training/ | MIT | review | OpenAI Video Pre-Training contractor demonstrations (MIT); Minecraft © Microsoft/Mojang. | 2026-11-18 | | | Labelled task videos (`.mp4` + `.jsonl`). |
| `public_bedd_basalt` | planned | Minecraft | BEDD / BASALT demos | https://arxiv.org/html/2312.02405 | MIT | review | BEDD/BASALT demonstration videos (MIT as stated on datasheet/Zenodo). | 2026-11-18 | | | Labelled trajectory videos. |
| `public_minerl` | planned | Minecraft | MineRL human demos | https://github.com/minerllabs/minerl/ | CC-BY-NC-SA-4.0 | no | MineRL human gameplay demos (CC BY-NC-SA 4.0; Zenodo backup also labeled MIT — treat as NC until resolved). | 2026-11-18 | | | Labelled POV MP4 + actions. |
| `public_pawa` | planned | Minecraft | PAWA | https://huggingface.co/datasets/YOUSIKI/pawa-dataset | CC-BY-NC-4.0 | no | PAWA Minecraft dataset (CC BY-NC 4.0), subject to Minecraft Usage Guidelines. | 2026-11-18 | | | Labelled episodes; large. |
| `public_game_intention_ow` | planned | Overwatch_2 | Game-Intention (OW subset) | https://huggingface.co/datasets/GameIntention/Game-Intention | CC-BY-NC-4.0 | no | Overwatch videos from Game-Intention (CC BY-NC 4.0). | 2026-11-18 | | | Labelled video pairs; confirm HUD coverage before volume use. |
| `public_marvelrivals_yolo` | planned | Marvel_Rivals | MARVELRIVALSYOLO | https://huggingface.co/datasets/Chappieut/MARVELRIVALSYOLO | Apache-2.0 | review | Marvel Rivals replay screenshots from MARVELRIVALSYOLO (Apache-2.0 packaging). | 2026-11-18 | | | Labelled stills (detection labels); game label = Marvel_Rivals. |

## Filtered out (no labelled stills/videos for this pipeline)

| Name | Why excluded |
|---|---|
| MineDojo YouTube DB | Metadata / links only — no shipped labelled frames |
| LoL-V2T | Captions/annotations only — raw video withheld |
| OW2 killfeed-rows | Labelled crops of killfeed UI only — not full gameplay frames |
| Overwatch / Rivals match stats (Kaggle/Zenodo) | Tables, not frames |
| Tournament / Twitch / YouTube VODs without a dataset card | No creator-labelled still/video package |
| GamingDatasets 25hr pilot | Has video, but gated + card disclaims usable grant; not first prototype |

## Active attribution blurb

Regenerate for reports from rows with `status=active` only. None active until a prototype is activated.

