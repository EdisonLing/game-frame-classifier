# Quality encoder

**Stage:** 1 — Personal-clip data tools  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

Builds **full / medium / low** frame sets from one source video by re-encoding the **video** at controlled H.264 CRF, then extracting and downscaling (same sample rate / size as the extractor).

## Why we need it

1. **Ops storage** — produce **full** + **low (CRF 45)** stills (D04)  
2. **Train** — for each example, pick **full or low at random** (not both; avoids ~2× data given small Δ). Probability TBD (default lean ~0.5 / 0.5 or slight full bias).  
3. **Eval** — score **full** and **low** as separate conditions (report both).  
4. **Friend handoff** — zip **full + low** so I can sample/eval either way (D25)  
5. **Docs** — optional **medium (CRF 38)** for README only  

## Method (D22)

```text
original video ──extract──► full/     (256×144 @ 1/5s)
       │
       └─ re-encode CRF 45 ──extract──► low/     ← ops / eval / friend default

optional (docs / reference only):
       └─ re-encode CRF 38 ──extract──► medium/
```

**Not** CRF on already-downscaled JPEGs (that was the early proxy; rejected).

## Tier map (current)

| Tier | CRF | Role |
|---|---:|---|
| **full** | 0 (original timeline) | Ops + eval |
| **medium** | **38** | **Docs / reference only** (not required for train/eval/friend packs) |
| **low** | **45** | Ops + eval: one hard degraded setting |

Code: `TIER_CRF` / `AUGMENT_CRF_*` in `quality_encoder.py` (may still expose medium until the CLI is trimmed to match D04).

## Why full + low=45 (D04)

The classifier sees **256×144**, not 1080p. Downscale removes a lot of visible bitrate damage, so a multi-step “good / ok / bad” eval ladder overstates what the model gets.

**Finding (one scene, README figures):** buy-phase barrier, Δ vs full = mean |RGB diff| / 255.

| | Full | Medium 38 (docs) | Low 45 (ops) |
|---|---:|---:|---:|
| 1080p | 0% | 2.9% | 4.9% |
| 256×144 | 0% | 1.8% | **3.5%** |

Even a harsh encode is only a few percent at model size. **Ops = full + CRF 45.** Medium=38 stays in docs so that gap is visible. Spot-check another game later if needed; do not assume identical %, but the same mechanism applies.

Photos: root README Quality levels, or `docs/examples/quality-ladder/`. Rebuild: `python scripts/ui_ref_model_input_compare.py --publish`.

## Inputs / outputs

| | |
|---|---|
| **In** | Source video + `--game` |
| **Out** | `output_dir/<tier>/` images + manifests; `quality_summary.json` |

## CLI

```bash
gfc-encode-quality path\to\clip.mp4 -o data/frames/my_clip_quality --game Valorant
gfc-encode-quality path\to\clip.mp4 -o out --game Valorant --max-duration 20
gfc-encode-quality path\to\clip.mp4 -o out --game Valorant --keep-proxies
```

## Acceptance checks

- [x] Tier → CRF map: full=0 (original), medium=38, low=45  
- [x] Medium/low re-encode video then extract  
- [x] Output frames are 256×144  
- [x] Manifests store `quality_tier` + `crf`  
- [x] Tier CRFs chosen so 256×144 same-res distance vs full is material (not 28-as-medium)

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Tier → CRF map; validate_crf bounds |
| **System** | Synthetic video → three tiers + summary; bad tier rejected |
| **Personal** | Optional short slice of a `data/raw` clip |

```bash
pytest tests/unit/test_quality_encoder.py tests/system/test_quality_encoder.py
```

## Ties to proposal

Evaluation at three compression levels (values revised after model-input analysis; see above). Augmentation samples a low-bitrate CRF band aligned with medium→low.
