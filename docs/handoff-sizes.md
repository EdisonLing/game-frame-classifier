# Friend pack: size and time by resolution

How much a friend pack weighs compared to the recordings it replaces, and how long it takes to make. Recipe: [friend-pack.md](roadmap/tools/friend-pack.md) (1 sampled moment every 5 s; tiers **full** + **CRF 45**; JPEG q2; native resolution).

A **usable frame** is one sampled moment. In a pack that is 2 JPEGs (full + CRF 45). In a video it is the 5 s of footage it stands for.

## Size

| Resolution | Pack per usable frame | Recording per 5 s (NVIDIA "High", 60 fps) | Pack / recording | Pack per footage min | Recording per footage min |
|---|---:|---:|---:|---:|---:|
| 1080p | **466 KiB** (280 full + 187 CRF 45) | 9.7 MiB (16.2 Mbps) | **4.7 %** (21× smaller) | **5.5 MiB** | 116 MiB |
| 1440p | **716 KiB** (413 + 303) | 17.2 MiB (28.8 Mbps) | **4.1 %** (25×) | **8.4 MiB** | 206 MiB |
| 2160p | **1,295 KiB** (699 + 596) | 29.8 MiB (50 Mbps) | **4.2 %** (24×) | **15.2 MiB** | 358 MiB |
| Compact 256×144 | **25 KiB** (12.5 + 12.3) | vs 1080p: 9.7 MiB | **0.25 %** (≈ 400×) | **0.3 MiB** | — |

Per hour of footage: about 0.3 GiB (1080p), 0.5 GiB (1440p), 0.9 GiB (2160p), 17 MiB (compact), versus 6.8 / 12.1 / 21 GiB of recording.

My own 4K masters (AV1, 30.6 Mbps measured) are 18.3 MiB per 5 s, so a 2160p pack is **6.9 %** of them (14× smaller). Recordings made with OBS quality-based settings vary with the scene (roughly 10–20 Mbps at 1080p60), which puts a 1080p pack at 4–8 % of the recording.

Zip ≈ unzipped (JPEGs don't compress; packs use stored zip entries). The CRF 45 tier is 40–46 % of each pack.

Spread of a single full-tier still (10th–90th percentile): 1080p 226–340 KiB, 1440p 335–502 KiB, 2160p 567–854 KiB.

## Time

Wall time to process one minute of footage, whole recipe (hash, full extract, CRF 45 re-encode, CRF 45 extract):

| Resolution | Per footage min | Per footage hour | Share in the CRF 45 re-encode |
|---|---:|---:|---:|
| 1080p | **12 s** | **12 min** | 75 % |
| 1440p | **22 s** | **22 min** | 75 % |
| 2160p | **51 s** | **51 min** | 78 % |

Measured on a fast 8-core desktop (Ryzen 7 7800X3D, 16 threads), machine otherwise idle, 60 fps H.264 sources. The time is almost all libx264 software encoding, so it scales with CPU cores and frame count:

- **Estimate for a friend:** footage minutes × (12 s at 1080p, 22 s at 1440p, 51 s at 4K), then **about 2×** on a typical 6-core gaming PC and **3× or more** on an older 4-core laptop. These multipliers are not measured.
- 120 fps recordings take about twice as long (twice the frames to re-encode). HEVC and AV1 sources decode more slowly than H.264.
- Compact mode takes the same time (the downscale at the end is negligible).

## How this was measured (2026-11-16)

Footage: five 3-minute Valorant replays (15 min total), 3840×2160 AV1 at 30.6 Mbps, variable frame rate around 120 fps, recorded with my own setup. ffmpeg 8.1 (gyan.dev essentials build), libx264 `veryfast`, on the machine above.

**Sizes** (`scripts/measure_handoff_sizes.py`, all 15 min, 185 usable frames per resolution):

1. Decode each master once; split into 2160p (native), 1440p and 1080p (lanczos downscale).
2. Each resolution: full tier = bucket sampler (one frame per 5 s on the real timestamps, `select` + `-fps_mode passthrough`) → JPEG `-q:v 2`. CRF 45 tier = libx264 `-preset veryfast -crf 45 -pix_fmt yuv420p -fps_mode passthrough` re-encode, then the same sampler.
3. Compact = 1080p stills scaled to 256×144 (bicubic), JPEG q2.
4. File sizes from disk; tier counts checked equal. Results: `data/bench_handoff/full_2026-11-16/results.json` (local).

Downscaling a 4K master gives cleaner pixels than a real 1080p/1440p recording, so these sizes lean high. A cross-check on the simulated recordings below came out 3–4 % smaller (1080p 447 KiB, 1440p 692 KiB, 2160p 1,251 KiB per usable frame).

**Recording sizes:** bitrate × 5 s ÷ 8. NVIDIA App "High" preset at 60 fps: 1080p 16.2 Mbps (NVIDIA support article on video capture bitrates), 1440p 28.8 Mbps (NVIDIA forum report of the preset values), 2160p 50 Mbps (community guides; NVIDIA computes defaults from resolution, frame rate and codec, so this one is the least certain). My masters: real file sizes.

**Time** (`scripts/time_handoff_by_resolution.py`):

1. `make-sources`: from each master, cut 60–120 s and re-encode as a typical recording at each resolution: 60 fps, libx264 at the NVIDIA "High" bitrates above (5 min of footage per resolution, measured 15.5 / 27.7 / 48.6 Mbps).
2. `time`: run the four recipe steps one resolution at a time on an idle machine; sum the wall time and divide by footage minutes. Results: `data/bench_handoff/sim_recordings/timing_results.json` (local).

Re-run both scripts after switching to the pinned friend-pack ffmpeg build, and on a friend's PC during the canary run, to replace the unmeasured multipliers.
