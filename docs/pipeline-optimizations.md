# Pipeline optimizations

Special speed / resource wins that beat the straightforward approach for this project’s data tools.

**Rules**

- Agents must **ask for approval and review** before adding or changing any entry (see skill `pipeline-optimizations`).
- Record only optimizations that are **non-obvious and significant** — not “we used the normal efficient path.”
- Prefer measured gains (wall time, memory, disk) over guesses.
- Newest entry first within each section.

**Not an optimization (example):** single-pass ffmpeg `fps=1/5` + scale for extract. That is the default-correct streaming path, not a special trick.

---

## Extract / batch

Applies to the shared extraction (`sourcing/extract.py`) used by the Frame Export Kit and `gfc-make-sources`. Test machine: 8-core / 16-thread desktop CPU, RX 9070 XT, Windows 11. Clips: 3 minutes, keyframe every 1 s; 1080p60 and 1440p60 H.264 test recordings (15.5 / 27.7 Mbps) and a 4K120 AV1 replay. Raw numbers: `data/bench_handoff/extract_profile_2026-11-17.json` and `window_verify_2026-11-17.json` (local).

### 2026-11-17 — Full tier by one seek per sample

| | |
|---|---|
| **Stage / tool** | extract, full tier |
| **Straightforward baseline** | One pass over the whole video with the `bucket_v1` select filter, decoding every frame |
| **Optimization** | One accurate seek per 5 s bucket (`-ss` before `-i`, `-frames:v 1`), so ffmpeg decodes only from the keyframe before each sample. The seek targets the exact frame the sampler picks, found in the packet list (`ffprobe` packet times and keyframe flags, no decoding), because recorders often put a keyframe there and a seek just before it decodes the previous group of pictures |
| **Why it qualifies** | Decode work drops from the whole clip to at most one keyframe interval per sample, with the same frames and identical pixels |
| **Gain** | Full tier, 3-min clips, single pass → seeks: 1080p60 6.4 → 4.2 s; 1440p60 10.6 → 6.1 s; 4K120 AV1 147 → 13.5 s (plain seeks without the packet list: 40.8 s, because each landed just before a keyframe). Packet list: 0.2 to 0.4 s |
| **How to verify** | `pytest tests/system/test_sourcing_extract.py -k seek_tier` (CFR, VFR with gap and offset, odd size, HDR, AV1, cover art); on real 1080p60, 1440p60 and 4K120 AV1 clips the images and timestamps were identical to the single pass |
| **Tradeoffs** | One ffmpeg launch per sample; recorded times within 1 ms of the single pass; a mismatched exact seek is redone with the plain seek; sources with keyframes more than 10 s apart use the single pass |
| **Code / docs** | `sourcing/extract.py` (`grab_still`, `seek_tier`); frame-export-kit spec §5.4 |

### 2026-11-17 — Low tier from 1 s encoded windows

| | |
|---|---|
| **Stage / tool** | extract, degraded (CRF 45) tier |
| **Straightforward baseline** | Re-encode the whole video, then sample the copy |
| **Optimization** | For each sample, encode only the `low_window_s` (1 s) before it, starting with a fresh keyframe, and keep its last frame |
| **Why it qualifies** | About a fifth of the frames are encoded at a 5 s interval, and the source is decoded only around the samples |
| **Gain** | End to end per 3-min clip, GPU / x264: 1080p60 24.4 → 19.4 s / 33.5 → 18.5 s; 1440p60 37.8 → 26.6 s / 61.2 → 28.9 s; 4K120 AV1 102.6 vs 208.4 s / 115.3 vs 258.5 s (before exact-frame seeks); low tier alone at 4K: 53 s from windows against 146 s for the whole-video encode |
| **How to verify** | Verify script comparing windows with `low_window_s: 0` on the same clips; `pytest tests/system/test_sourcing_extract.py -k "window or whole_video"` |
| **Tradeoffs** | Changes how the low tier is made (recipe `2026-11-17b`): stills come out 0.5 to 1.0 dB lower PSNR against the full tier than from a whole-video encode with the same 2 s keyframe interval (1080p GPU 26.8 vs 27.4 dB, x264 25.5 vs 26.3 dB; 4K GPU 28.3 vs 29.1 dB), so slightly harsher, because every sample sits 1 s after a keyframe. `low_window_s: 0` restores the whole-video encode |
| **Code / docs** | `sourcing/extract.py` (`window_tier`); D22; frame-export-kit spec §5.5 |

### 2026-11-17 — GPU decode only when it is faster

| | |
|---|---|
| **Stage / tool** | extract, decode |
| **Straightforward baseline** | Use GPU decode whenever the GPU can decode the format |
| **Optimization** | Per format and resolution, time GPU and CPU decode of 30 frames and use the GPU only when its output is identical and at least 10 % faster; always decode the intermediate low-tier file on the CPU |
| **Why it qualifies** | Counter-intuitive: copying decoded frames back from the GPU usually costs more than the decode saves; only heavy footage (4K120 AV1) gains |
| **Gain** | 1080p60, whole-video path: 38 → 26 s; intermediate file at 4K120: 47 → 18 s; 4K120 AV1 full decode: 256 s CPU vs 149 s GPU, so the GPU is kept there |
| **How to verify** | `pytest tests/system/test_sourcing_gpu_checks.py`; the run record's `encoder.decode` shows the choice and timings per format |
| **Tradeoffs** | About 1 s per new format and resolution for the check |
| **Code / docs** | `sourcing/gpu.py` (`DecodeCheck`, `DECODE_MIN_SPEEDUP`); D28 |

### 2026-11-17 — GPU encoder for the low tier

| | |
|---|---|
| **Stage / tool** | extract, degraded tier encode |
| **Straightforward baseline** | libx264 on the CPU |
| **Optimization** | Direct3D 12 hardware H.264 (`h264_d3d12va`) at constant QP 51, libx264 as the fallback |
| **Why it qualifies** | Moves the heaviest step off the CPU, so a contributor's PC stays usable |
| **Gain** | No wall-time gain on a fast 8-core CPU at 1080p (40 s clip: 9.0 s vs 8.8 s); modest at 1440p and up. CPU load and weaker PCs not measured yet |
| **How to verify** | `pytest tests/system/test_frame_export_cli.py -k gpu`; pack manifest `encoder` block |
| **Tradeoffs** | Vendor-specific artifacts (accepted, recorded per frame); self-test, picture check and stall timeout guard it |
| **Code / docs** | `sourcing/gpu.py`, `sourcing/extract.py`; D28 |

## Clean

*(none yet)*

## Quality encode

*(none yet)*

## Catalog / other

*(none yet)*

---

## Related

- [pipeline-timing.md](pipeline-timing.md) — measured rates for estimates
- [pipeline-status.md](pipeline-status.md) — what’s built
- Skill: `pipeline-optimizations` (under edutil project skills)
