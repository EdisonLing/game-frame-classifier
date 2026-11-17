# Quality ladder (README example)

One scene (buy-phase barrier) justifying **ops = full + low (CRF 45)**. Medium (CRF 38) is reference only.

| File | Role |
|---|---|
| `…__full.jpg` | 1080p full |
| `…__medium_crf38.jpg` | 1080p medium (docs / Δ reference) |
| `…__low_crf45.jpg` | 1080p low (ops) |
| `model_input_256x144/*` | Same at 256×144 |

Decision: [quality-encoder.md](../../roadmap/tools/quality-encoder.md) (D04). Rebuild: `python scripts/ui_ref_model_input_compare.py --publish`.
