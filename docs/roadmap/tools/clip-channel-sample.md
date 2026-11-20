# Channel sampling for `gfc-fetch-clips` (version 1.3)

**Stage:** 1 — Collection  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [YouTube links and channel listing](clip-link-youtube.md) · [clip link downloader](clip-link-downloader.md) · [clip sorter](clip-sorter.md)

## What it does

Given a YouTube channel (not a single video), download footage until a time budget is met, picking videos at random with a lean towards recent uploads. Two modes:

- **`new`**: download until about `--max-time` hours of *new* videos from the channel (not downloaded before) are obtained.
- **`total`**: ensure the channel has at least `--max-time` hours *held* locally: download more when below; do nothing when already at or above. Never removes or archives.

Before download, a local preview page shows thumbnails and titles so non-gameplay can be toggled off.

## Rules

- **Channels only.** A single video link, a playlist or a search URL is refused (exit 2). Same permission, source naming and web / contributor labels as the [YouTube spec](clip-link-youtube.md): a new channel is accepted as `yt_<handle>`; an existing uploader row (for example a contributor's `friend_<handle>` source) decides the source.
- **No account access**, public or unlisted videos only, 720p cap as in 1.2.
- **No per-video length cap** in `--channel` mode (`--max-minutes` does not apply). Budget is total time, not clip length.
- **Nothing is deleted or archived.** `total` never shrinks the set.
- **Reproducible.** The pick is recorded in a links file with its seed.

## Usage

```text
gfc-fetch-clips --channel https://www.youtube.com/@<handle>                                    # ~3 h new (mode new)
gfc-fetch-clips --channel https://www.youtube.com/@<handle> --max-time 2 --mode total           # at least 2 h held
gfc-fetch-clips --channel <url> --max-time 3 --recency-bias 3 --seed 7 --game Minecraft --content-type gameplay
gfc-fetch-clips --channel <url> --dry-run                                                      # print the plan, change nothing
gfc-fetch-clips --channel <url> --no-preview                                                   # skip the keep/skip page
```

| Flag | Meaning |
|---|---|
| `--channel URL` | The channel (`@handle`, `/channel/<id>`, with or without `/videos`) |
| `--max-time H` | Hours (float > 0); default **3.0** (same as the contributor footage budget). Target for `new` / minimum for `total` |
| `--mode new\|total` | Default `new` |
| `--recency-bias B` | Float >= 0, default 2.0. 0 = uniform; larger = stronger lean to recent uploads |
| `--seed S` | Integer; default random. The seed used is always printed and written to the picks file |
| `--dry-run` | Print the plan (picks) and write nothing |
| `--preview` / `--no-preview` | Open the keep/skip page before download (default: preview on in a TTY, off otherwise). `--dry-run` never opens it |
| `--game`, `--content-type`, `--note`, `--sort` / `--no-sort`, `--out` | As in 1.2 (`--out` is the picks file) |

`--channel` cannot be combined with links files, `--list-channel` or `--tag-uploader` (exit 2).

## Behaviour

1. **List.** Flat-list the channel with `clip_fetch.channel.ytdlp_flat_list` (newest first; each entry has `id`, `duration`, `title`, `live_status`). Drop live videos and entries with no URL, as `list_channel` does. Rank the rest by listing order: newest = rank 0. Unknown duration is allowed (treated as 0 s for budget maths; still eligible).
2. **Weights.** With `n` candidates, rank `i` (0 = newest): `w_i = exp(-B * i / max(n - 1, 1))`. `B = 0` gives equal weights; at the default `B = 2` the newest video is about 7.4 times as likely as the oldest.
3. **Weighted pick without replacement** (Efraimidis–Spirakis): for each candidate draw `u` uniform in (0, 1) from `random.Random(seed)` and use key `u ** (1 / w_i)`; take candidates in descending key order. The ordered list is the pick order; it is fixed by the seed.
4. **Held videos.** A video of this channel is *held* when its id is in the fetch log with `status = ok` for this channel (`uploader_id = yt:<channel_id>`) and a file whose name ends in `__<id>.mp4` exists under `data/incoming_clips/<source>/` or under `data/raw/**/<source>/`. The id is the last `__`-separated token of the file name stem. Held duration sums listing `duration` for those ids (0 when unknown).
5. **Time budget and overshoot.** Let `T` be `--max-time` in seconds. The hard ceiling for a fill is `T * 1.2` (20 % overshoot). Walk candidates in pick order: take a video if adding its duration keeps accrued time ≤ ceiling; if it would exceed the ceiling, **skip it** and try the next. If none of the remaining fit, **stop under budget** (do not keep searching for a shorter clip outside the prepared pool). Whole videos only; never cut a file.
6. **Preview buffer.** Before the keep/skip page, take a prefix of the pick order whose cumulative duration is about **2 × T** (or the rest of the channel). That pool is shown in the preview.
7. **Preview page.** Local browser page: each item shows the YouTube thumbnail (`https://i.ytimg.com/vi/<id>/hqdefault.jpg`), title, duration and index. All start **on**. Digit keys `1`–`9` and `0` (tenth) toggle items on the current page of ten; `[` / `]` change page; Enter submits. Toggled-off items are dropped. Remaining items stay in pick order and then the time-budget walk (step 5) selects what to download.
8. **Mode `new`.** Candidates exclude every video id the fetch log already lists with `status = ok` for this channel (even if the file is gone). Accrued starts at 0; fill until about `T` of new downloads (with overshoot rules). A pick that ends `skipped_long`, `failed` or unavailable is replaced by the next remaining candidate under the same budget rules, until the budget is met or candidates run out (report the shortfall; exit 0).
9. **Mode `total`.** Let `held_s` be held duration from step 4.
   - `held_s >= T`: do nothing and say so.
   - `held_s < T`: behave as mode `new` with target remaining `T - held_s`, but the overshoot ceiling is absolute: `held_s + new_s ≤ T * 1.2`.
10. **Picks file.** Write `data/clip_links/<YYYY-MM-DD>_yt_<handle>_sample.txt` (or `--out`) with a `#` header (channel, channel id, date, mode, max_time_h, seed, recency bias, held_s before, picks, downloaded_s, shortfall_s) and one `<url>,<Game>,<content_type>` line per downloaded pick (empty fields where not given). Rejected preview items are listed as `# skipped_preview: <id> <title>` lines.
11. **Download** through the existing `clip_fetch.download.run` with `LinkEntry` items, so uploader rows, naming, hints and the fetch log work as before. Print the sample summary after the normal summary: mode, picks, downloaded_s, replaced, shortfall_s, seed.
12. **`--dry-run`** performs steps 1–6 and 8–9 using only the listing and local files and prints the plan; it writes no file and opens no preview.
13. **Errors.** Not a channel URL, `--max-time` ≤ 0, `--recency-bias` below 0, a mode other than `new` / `total`, or flags combined as above: exit 2 with a one-line message. A listing or network failure: exit 1.

## Decisions

- Weighted random pick towards recent uploads, two modes `new` and `total` (user, 2026-11-19).
- **Budget is time, not video count:** `--max-time` hours, default **3.0**, matching the contributor footage budget (user, 2026-11-19).
- **`total` is a minimum only:** add when below; never archive or delete (user, 2026-11-19).
- **No per-video length cap** in channel sampling (user, 2026-11-19).
- **Overshoot cap 20 % of `--max-time`:** skip a candidate that would exceed `T * 1.2`; if none of the remaining pool fit, stop under budget (user, 2026-11-19).
- **Preview before download:** multi-item local page; on by default; digits toggle off; Enter submits; buffer ~2× time so rejects have replacements already picked (user, 2026-11-19).
- **Default recency bias 2.0.**

## Testing

Unit tests with a fake lister and fake downloader (no network), in `tests/unit/test_clip_channel_sample.py`:

- weights: `B = 0` equal; `B > 0` strictly decreasing with rank; a single candidate works.
- pick: same seed gives the same order; different seeds differ; over 2,000 seeds with `B = 3` the newest quarter is picked first more often than the oldest quarter; with `B = 0` the counts are within a loose tolerance of equal.
- fill / overshoot: a candidate past `T * 1.2` is skipped; if nothing else fits, result stays under `T`; last video may land between `T` and `T * 1.2`.
- mode `new`: ids already `ok` in the fetch log (file present or gone) are never picked; shortfall when the channel runs out.
- mode `total`: below T downloads toward T; equal or above does nothing; never moves or deletes files.
- held detection: the id is read from the last `__` token; files of another channel's source are not counted.
- preview filter: toggling ids off removes them; remaining still respect the budget walk.
- picks file content and header; `--dry-run` changes nothing (no file, no log row).
- CLI: a video URL, a playlist URL, `--max-time 0`, a bad mode, and `--channel` with a links file all exit 2.
- Every existing `clip_fetch` test still passes.

Smoke (real network, no download): `gfc-fetch-clips --channel <small channel URL> --max-time 0.1 --dry-run` prints picks and writes nothing.

## Acceptance checks

- [x] `--channel` with `--max-time` downloads toward that many hours of new video, weighted to recent, and records the seed
- [x] `--mode total` adds when below and does nothing when at or above; never deletes or archives
- [x] Overshoot stays within 20 %; otherwise stops under budget
- [x] Preview can toggle items off; buffer supplies replacements
- [x] `--dry-run` writes nothing
- [x] Docs updated: this spec (status `implemented`), [clip-link-youtube.md](clip-link-youtube.md) (see-also line), ROADMAP row 4e.3 (reviewer at merge)

## Build instructions

Written for an agent that builds exactly this and decides nothing; ask the user if anything is unclear.

1. `clip_fetch/sample.py` (new): `recency_weights(n, bias) -> list[float]`; `weighted_order(weights, seed) -> list[int]`; `held_videos(...)`; `fill_to_budget(...)`; `plan_sample(...)` → `Plan` with `preview_pool`, `picks`, `held_before_s`, `shortfall_s`; pure where possible.
2. `clip_fetch/preview.py` + `preview.html` (new): local page for the buffer; digit toggles; Enter returns kept ids.
3. `clip_fetch/sample.py`: `run_sample(...)`: list, plan, optional preview, write picks file, download through `download.run` with replacement from remaining order under the budget rules.
4. `clip_fetch/cli.py`: flags `--channel`, `--max-time`, `--mode`, `--recency-bias`, `--seed`, `--dry-run`, `--preview` / `--no-preview`; validation and exit codes as in Behaviour 13; `__version__ = "1.3.0"`.
5. Tests as in Testing; docs as in the acceptance checks; no README draft.
