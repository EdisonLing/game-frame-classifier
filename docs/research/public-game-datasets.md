# Public gameplay datasets (research)

Decision support for whether free public data can **supplement** local, non-commercial training for Minecraft, Overwatch 2 and Marvel Rivals. **Research only:** no media downloaded, no source registered, **D12 left open**.

Accessed **2026-11-18**. Rights labels:

| Label | Meaning |
|---|---|
| `confirmed candidate` | Stated terms clearly cover the gameplay media for this intended local non-commercial use |
| `research-only/non-commercial candidate` | Dataset terms allow NC research packaging, but publisher game-IP clearance for training is incomplete or self-asserted |
| `unclear/not suitable` | Public media exists, but license/provenance does not clear training use (or conflicts) |
| `not found` | No serious public frame/video corpus located |

A public download page or paper is **not** permission. Prefer official project pages over Kaggle/Drive mirrors.

**Related:** [use plan / justification draft](public-dataset-use-plan.md) · [source acquisition](../roadmap/tools/source-acquisition.md) · [data layout](../data-layout.md) · [D12](../design-decisions.md#d12--confirmed-sources-for-lol-overwatch-2-marvel-rivals) · [results](../results.md)

---

## Executive summary

- **No `confirmed candidate`** was found for Minecraft, Overwatch 2 or Marvel Rivals that clears both dataset redistributor terms **and** publisher audiovisual rights for local ML training.
- **Minecraft** has the strongest *research* shortlist: **MineRL** (treat as NC; GitHub CC BY-NC-SA 4.0 vs Zenodo MIT conflict), **OpenAI VPT contractor demos** (MIT code + explicit Mojang IP disclaimer), **BEDD/BASALT** (MIT claim), **PAWA** (CC BY-NC 4.0 + Usage Guidelines). None document systematic **shaders** or **Bedrock**; MineRL alone documents **texture-pack / resolution** variants.
- **Gameplay Images** (proposal fallback) and **Gamed** (Valorant/CS2 fallback) are YouTube-derived stills with CC BY packaging — useful shape for experiments, **not** clean media rights. Gameplay Images also lacks clip IDs (leakage risk under D01/D02).
- **Overwatch 2** and **Marvel Rivals:** **not found** as confirmed free frame corpora. HF/Roboflow/Ultralytics dumps exist; cards either disclaim publisher licenses, license annotations only, or assert packaging licenses without clearing Blizzard/NetEase/Marvel IP.
- **Conservative fallback (operational, not clearance):** keep filling `data/raw/<Game>/<source>/` and contributor packs with self/friends captures; do not treat public VOD dumps as approved sources. Any later public acquisition needs an explicit terms note + date (per source-acquisition acceptance checks) and a user decision on D12.

---

## Candidate table

### Minecraft

| Name | Official sources | Format / scale | Stated license / terms | Rights confidence | Access | Pipeline fit | Recommendation |
|---|---|---|---|---|---|---|---|
| MineRL (v0 / human demos) | [GitHub](https://github.com/minerllabs/minerl/), [docs](https://minerl.readthedocs.io/), [arXiv:1907.13440](https://arxiv.org/abs/1907.13440), [Zenodo backup](https://zenodo.org/records/12659939) | POV H.264 MP4 + JSON actions; 500+ h / 60M+ pairs per render; 64×64–192×256 (API also documents higher) | Repo `LICENSE`: **CC BY-NC-SA 4.0**; Zenodo 2019 backup labeled **MIT** (conflict); Mojang [Usage Guidelines](https://www.minecraft.net/en-us/usage-guidelines) overlay | `research-only/non-commercial candidate` (treat NC until conflict resolved) | Zenodo / historical downloader (primary mirrors down) | Strong: contiguous trajectories → clip/session splits; Java 1.11.2 / 1.16.5; HUD/GUI present; **weak** in-the-wild diversity | Shortlist for Minecraft volume **after** license confirmation; keep as own `<source>`; do not merge with VPT bytes |
| OpenAI VPT contractor demos | [Video-Pre-Training](https://github.com/openai/Video-Pre-Training/), [OpenAI VPT](https://openai.com/index/vpt/) | `.mp4` + `.jsonl`; 720p windowed → 360p @ 20 Hz; large multi-version contractor set | Repo **MIT** + README: OpenAI **does not license Minecraft IP** | `research-only/non-commercial candidate` / rights cloudy on Mojang IP | Azure blob via official index JSON | Strong session identity; fixed capture look; Java modified client | Prefer official indexes over HF rehosts; separate `<source>` from MineRL |
| BEDD / BASALT demos | [basalt-benchmark](https://github.com/minerllabs/basalt-benchmark), [arXiv:2312.02405](https://arxiv.org/html/2312.02405), [Zenodo eval](https://zenodo.org/records/8021960) | MP4 + JSONL; ~361 h demos / ~26M pairs; eval on Zenodo | Datasheet/Zenodo: **MIT** claim; Mojang overlay | `research-only/non-commercial candidate` | OpenAI host + Zenodo | Same visual family as MineRL/VPT | Overlap risk with VPT/MineRL ecosystem — provenance must stay separate |
| PAWA | [HF YOUSIKI/pawa-dataset](https://huggingface.co/datasets/YOUSIKI/pawa-dataset) | POV 640×360 + panorama; TB-scale; Fabric + ReplayMod | **CC BY-NC 4.0** + Minecraft Usage Guidelines | `research-only/non-commercial candidate` | Gated HF | Session episodes; documented mod-loader stack | NC only; confirm version string before use |
| Gameplay Images | [Kaggle](https://www.kaggle.com/datasets/aditmagotra/gameplay-images), HF mirror [Bingsu/Gameplay_Images](https://huggingface.co/datasets/Bingsu/Gameplay_Images) | 1k Minecraft PNGs @ 640×360 (of 10k / 10 games) | Packaging **CC BY 4.0**; frames from “famous gameplay videos on YouTube” | `unclear/not suitable` | Kaggle / HF | Class labels only; **no published clip IDs** → D01/D02 leakage risk | Do **not** treat as cleared Minecraft fallback; proposal name only |
| MineDojo YouTube DB | [MineDojo](https://github.com/MineDojo/MineDojo), [Zenodo](https://doi.org/10.5281/zenodo.6693792) | Metadata/links for 730K+ videos (not shipped pixels) | **CC BY 4.0** on metadata product | `unclear/not suitable` as training media | Zenodo JSON | Video IDs exist; media = YouTube | Metadata OK for discovery; downloading YT for training fails the source rule unless rights are explicit |

### Overwatch 2

| Name | Official sources | Format / scale | Stated license / terms | Rights confidence | Access | Pipeline fit | Recommendation |
|---|---|---|---|---|---|---|---|
| *(none confirmed)* | — | — | — | `not found` | — | — | No free confirmed OW2 frame corpus |
| Game-Intention (OW subset) | [HF GameIntention/Game-Intention](https://huggingface.co/datasets/GameIntention/Game-Intention) | Video pairs; OW ~1.4k verified pairs; large total repo | HF tag **CC BY-NC 4.0** | `research-only/non-commercial candidate` (packaging); media clearance **needs confirmation** | Public HF / large LFS | Likely HUD-on video; clip structure unknown without inventory | Do not acquire until publisher + author terms reviewed |
| GamingDatasets 25hr pilot | [HF GamingDatasets/25hr…](https://huggingface.co/datasets/GamingDatasets/25hr-gameplay-with-actions) | OW2 ~2 h @ 1080p30 + actions among 18 games | `other`; card: owns recordings, **no publisher license** | `unclear/not suitable` | Gated HF | Session-like recordings | Explicitly unsuitable as “free publisher-cleared” data |
| OW2 killfeed crops | [HF tnguyen2002/overwatch2-killfeed-rows](https://huggingface.co/datasets/tnguyen2002/overwatch2-killfeed-rows) | 453 killfeed-band crops | CC BY 4.0 on **annotations**; Blizzard art not licensed | `unclear/not suitable` | Public HF | Killfeed-only — poor full-frame identity | Skip |
| Roboflow / Ultralytics OW2 OD sets | e.g. [Roboflow OW2 character detection](https://universe.roboflow.com/appliedrobotics-uihpz/overwatch-2-character-detection) | Still dumps (thousands–100k+ images) | “Open Source Dataset” style cards; no Blizzard grant found | `unclear/not suitable` | Platform download | Shuffled stills / OD labels; weak session splits | Skip as training source |
| EgoEsportsQA (OW2 among titles) | [arXiv:2604.12320](https://arxiv.org/abs/2604.12320) | QA over ~7.5 h clips (CS2/Valorant/OW2) | Authors: YT CC + NC research claim; public clip dump URL not found | `unclear/not suitable` / needs confirmation | Paper only (clips not located) | Clip-level possible if released | Watch for release; not usable now |

**Publisher note (not a dataset grant):** [Blizzard EULA](https://blizzard.com/eula) asserts ownership of recordings/replays; [Video Policy](https://www.blizzard.com/en-us/legal/2068564f-f427-4c1c-8664-c107c90b34d5/blizzard-video-policy) allows limited non-commercial community video — **not** an ML dataset license. StarCraft II’s AI/ML license is a **different product**, not OW2 clearance.

### Marvel Rivals

| Name | Official sources | Format / scale | Stated license / terms | Rights confidence | Access | Pipeline fit | Recommendation |
|---|---|---|---|---|---|---|---|
| *(none confirmed)* | — | — | — | `not found` | — | — | No free confirmed Rivals frame corpus |
| MARVELRIVALSYOLO | [HF Chappieut/MARVELRIVALSYOLO](https://huggingface.co/datasets/Chappieut/MARVELRIVALSYOLO) | ~2051 replay-viewer screenshots (~5.7 GB) | HF tag **Apache-2.0** (packaging); no NetEase/Marvel grant quoted | `unclear/not suitable` | Public HF | Stills; no session IDs | Skip |
| Luel gaming samples | [HF Luel-ai/luel-gaming-samples](https://huggingface.co/datasets/Luel-ai/luel-gaming-samples) | Few Rivals clips | `luel-internal` — not for redistribution | `unclear/not suitable` | Restricted | Tiny | Skip |
| Tournament / Twitch / YouTube VODs | e.g. [Ignite rules PDF](https://www.marvelrivals.com/Marvel_Rivals_Ignite_2026_Rules_Preseason_%26_Stage1_2026.3.13_V1.0.pdf) | Broadcast footage | Rights granted **to** NetEase/partners, not to third-party trainers | `unclear/not suitable` | Platforms | Would need per-VOD rights | Do not treat as free dataset |

**Publisher note:** [NetEase Games Terms](https://protocol.unisdk.easebar.com/release/latest_v557.html) — personal/internal license; restrict derivative works / commercial use. Region-specific client EULA equivalence **needs confirmation**.

### Named proposal fallbacks (other games — context only)

| Name | Games of the six | Stated terms | Rights confidence | Notes |
|---|---|---|---|---|
| Gamed ([HF ybashir/…](https://huggingface.co/datasets/ybashir/gamed-game-classification-dataset)) | Valorant, CS2 | CC BY 4.0 on derived frames; publishers retain footage | `unclear/not suitable` as cleared media; shape is useful | Preserves `video_id` (split on video, not frame); YouTube-sourced |
| Gameplay Images | Minecraft only | CC BY 4.0 packaging; YouTube-sourced | `unclear/not suitable` | See Minecraft table |

---

## Minecraft visual-variation matrix

| Axis | MineRL | VPT contractor / BEDD | PAWA | Gameplay Images | MineDojo YT metadata |
|---|---|---|---|---|---|
| Texture / resource packs | **Documented / controllable:** default vs simplified (`texture_pack` 0\|1) | Absent / unknown (vanilla-looking) | Unknown (ReplayMod re-render possible) | Unknown | Varied in wild (undocumented) |
| Mods / modpacks | Absent as diversity axis | Modified logging client, not content packs | **Documented:** Fabric + ReplayMod | Unknown | Varied / undocumented |
| Shaders | Absent / unknown | Absent / unknown | Absent / unknown | Unknown | Unknown |
| Version / edition | Java **1.11.2** / **1.16.5**; Bedrock absent | Java modified client; Bedrock absent | Fabric (Java); exact MC version needs confirmation | Unknown | Varied / unknown |
| UI / HUD | Present in POV; GUI state annotated | Likely present (windowed human play) | POV UI + world panorama | Unknown (YT overlays possible) | Varied |
| Viewpoint | First-person; platform claims re-render options | First-person screen capture | POV + equirectangular | Assumed POV stills | Varied |
| Graphics settings | Resolution + texture variants released | Fixed 720p→360p @ 20 Hz | Fixed release resolutions | Fixed 640×360 | Source-dependent |

**What matters for this classifier**

- **Identity-critical:** Java vs Bedrock UI chrome, major version art, third-party **resource packs**, **shaders**, non-default HUD/FOV, stream overlays, menu vs world frames (menus stay valid per D06).
- **Robustness / synthetic:** lighting, biome, camera pitch, resolution, mild texture simplification (MineRL), compression (already covered by CRF tiers in-pipeline).
- **Gap:** no serious public corpus labels pack/shader/edition per frame. A MineRL/VPT-trained Minecraft class can look “Minecraft” only for **vanilla-ish Java POV**, not packed/shader/Bedrock clients.

---

## Recommended acquisition order

Research recommendation only — **does not approve a source** or close D12.

1. **Continue personal + contributor captures** for Overwatch 2 and Marvel Rivals (and Minecraft if local clips appear). Keep `data/raw/<Game>/<source>/` and Frame Export Kit provenance (D19, D26). Cap/reporting per D33.
2. **If Minecraft public volume is needed later:** shortlist **MineRL** (resolve CC BY-NC-SA vs Zenodo MIT in writing) then **VPT contractor** (official Azure indexes only), each as its own `<source>`, session/clip splits only. Confirm Mojang Usage Guidelines fit for *local NC research* with the user before any download.
3. **Do not** acquire Gameplay Images, Gamed, Roboflow/Ultralytics dumps, MARVELRIVALSYOLO, or YouTube/Twitch/esports VODs as “free” training sets under current evidence.
4. **Optional discovery only:** MineDojo YouTube **metadata** to find channels — still requires per-video rights before any extract.

### Conservative fallback (no confirmed free set)

| Game | Fallback |
|---|---|
| Minecraft | Local / friends only until MineRL/VPT terms are confirmed; do not use Gameplay Images as cleared |
| Overwatch 2 | Local / friends only; no public confirmed alternative |
| Marvel Rivals | Local / friends only; no public confirmed alternative |

Operational tip from source-acquisition / D12 (not a rights clearance): prioritize personal clips for the three games without a public fallback.

---

## Gaps and contacts before use

| Gap | Who / what to ask |
|---|---|
| MineRL: which license governs which bytes (GitHub NC-SA vs Zenodo MIT)? | MineRL maintainers / Zenodo record authors; get a single written statement |
| VPT: does MIT cover contractor **MP4** media or only code/docs? | OpenAI / VPT maintainers; also confirm Mojang Usage Guidelines for local NC training |
| Mojang/Microsoft: is local non-commercial frame-classifier training on research dumps allowed? | Minecraft Usage Guidelines contact / Microsoft gaming IP channel — **needs confirmation** |
| OW2: any Blizzard path for NC research frame datasets? | Blizzard legal / Video Policy clarification — current text does not grant it |
| Marvel Rivals: any NetEase/Marvel research dataset license? | NetEase / Marvel licensing — current Terms restrict derivatives |
| Game-Intention OW clips: publisher clearance + clip IDs? | Dataset authors + Blizzard |
| EgoEsportsQA: public clip release + media license file? | Paper authors |
| PAWA exact Minecraft version / gated access terms | Dataset card maintainers |

---

## Evidence ledger

| Date | Source | What it supports |
|---|---|---|
| 2026-11-18 | [minerllabs/minerl LICENSE](https://github.com/minerllabs/minerl/blob/dev/LICENSE) | MineRL repo = CC BY-NC-SA 4.0 |
| 2026-11-18 | [Zenodo 12659939](https://zenodo.org/records/12659939) | MineRL 2019 backup labeled MIT |
| 2026-11-18 | [MineRL paper](https://arxiv.org/abs/1907.13440) / [PDF](https://arxiv.org/pdf/1907.13440) | Scale, MP4+JSON, texture/resolution variants |
| 2026-11-18 | [MineRL versions](https://minerl.readthedocs.io/en/latest/notes/versions.html) | Java 1.11.2 / 1.16.5 |
| 2026-11-18 | [MineRL data API](https://minerl.readthedocs.io/en/v0.4.4/api/data.html) | `texture_pack` / resolution knobs |
| 2026-11-18 | [Minecraft Usage Guidelines](https://www.minecraft.net/en-us/usage-guidelines) | Screenshots/videos = assets; commercial use restricted |
| 2026-11-18 | [openai/Video-Pre-Training](https://github.com/openai/Video-Pre-Training/) | VPT MIT + Mojang IP disclaimer; 720p→360p capture |
| 2026-11-18 | [BEDD / BASALT](https://arxiv.org/html/2312.02405), [Zenodo 8021960](https://zenodo.org/records/8021960) | MIT claim; demo scale |
| 2026-11-18 | [PAWA HF](https://huggingface.co/datasets/YOUSIKI/pawa-dataset) | CC BY-NC 4.0 + Usage Guidelines |
| 2026-11-18 | [Kaggle Gameplay Images](https://www.kaggle.com/datasets/aditmagotra/gameplay-images), [HF mirror](https://huggingface.co/datasets/Bingsu/Gameplay_Images) | CC BY packaging; YouTube provenance; 1k Minecraft |
| 2026-11-18 | [MineDojo](https://github.com/MineDojo/MineDojo), [Zenodo 6693792](https://doi.org/10.5281/zenodo.6693792) | YT DB = metadata under CC BY 4.0 |
| 2026-11-18 | [Gamed HF](https://huggingface.co/datasets/ybashir/gamed-game-classification-dataset) | Valorant/CS2 YouTube frames; CC BY + publisher residual; `video_id` |
| 2026-11-18 | [Game-Intention HF](https://huggingface.co/datasets/GameIntention/Game-Intention) | OW subset; CC BY-NC packaging |
| 2026-11-18 | [GamingDatasets 25hr](https://huggingface.co/datasets/GamingDatasets/25hr-gameplay-with-actions) | Explicitly no publisher license |
| 2026-11-18 | [OW2 killfeed HF](https://huggingface.co/datasets/tnguyen2002/overwatch2-killfeed-rows) | Annotation CC BY ≠ media clearance |
| 2026-11-18 | [MARVELRIVALSYOLO HF](https://huggingface.co/datasets/Chappieut/MARVELRIVALSYOLO) | Apache-2.0 packaging; replay screenshots |
| 2026-11-18 | [Blizzard EULA](https://blizzard.com/eula), [Video Policy](https://www.blizzard.com/en-us/legal/2068564f-f427-4c1c-8664-c107c90b34d5/blizzard-video-policy) | Recordings owned; NC community video ≠ dataset grant |
| 2026-11-18 | [NetEase Terms](https://protocol.unisdk.easebar.com/release/latest_v557.html) | Personal use; derivative-work limits |
| 2026-11-18 | [Marvel Rivals Ignite rules](https://www.marvelrivals.com/Marvel_Rivals_Ignite_2026_Rules_Preseason_%26_Stage1_2026.3.13_V1.0.pdf) | Event footage rights to organizer, not researchers |

Scratch notes used while drafting (not committed): `research_notes/Public gameplay dataset options/`.

---

## What this does *not* change

- **D12** remains **open** (no named confirmed source for LoL / OW2 / Marvel Rivals).
- [source-acquisition.md](../roadmap/tools/source-acquisition.md) is unchanged; any update to named fallbacks after this research is a **user approval** item.
- No files under `data/`; no catalog rows; no downloads.
