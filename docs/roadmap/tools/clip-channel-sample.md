# Channel sampling for `gfc-fetch-clips` (version 1.3)

**Stage:** 1 — Collection  
**Status:** specified  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [YouTube links and channel listing](clip-link-youtube.md) · [clip link downloader](clip-link-downloader.md) · [clip sorter](clip-sorter.md)

## What it does

Given a YouTube channel (not a single video), download a chosen number of its videos, picked at random with a lean towards recent uploads, so no one person's whole channel is taken and the sample spreads over time. Two modes:

- **`new`**: download N videos from the channel that have not been downloaded before.
- **`total`**: make the number of the channel's videos held in the dataset equal N: download more when below N, and set aside the surplus when above N.

## Rules

- **Channels only.** A single video link, a playlist or a search URL is refused (exit 2). Same permission, source naming and web / contributor labels as the [YouTube spec](clip-link-youtube.md): a new channel is accepted as `yt_<handle>`; an existing uploader row (for example a contributor's `friend_<handle>` source) decides the source.
- **No account access**, public or unlisted videos only, 720p cap and `--max-minutes` (default 60) as in 1.2.
- **Nothing is deleted.** Shrinking moves files to an archive folder; it never deletes and never touches files already placed in `data/raw/` or processed (proposed, see Decisions).
- **Reproducible.** The pick is recorded in a links file with its seed.

## Usage

```text
gfc-fetch-clips --channel https://www.youtube.com/@<handle> --count 20                       # 20 new videos (mode new)
gfc-fetch-clips --channel https://www.youtube.com/@<handle> --count 30 --mode total          # bring this channel's total to 30
gfc-fetch-clips --channel <url> --count 15 --recency-bias 3 --seed 7 --game Overwatch_2 --content-type gameplay
gfc-fetch-clips --channel <url> --count 30 --mode total --dry-run                            # print the plan, change nothing
```

| Flag | Meaning |
|---|---|
| `--channel URL` | The channel (`@handle`, `/channel/<id>`, with or without `/videos`). Needs `--count` |
| `--count N` | Positive integer: videos to download (`new`) or the target total (`total`) |
| `--mode new\|total` | Default `new` |
| `--recency-bias B` | Float >= 0, default 2.0. 0 = uniform; larger = stronger lean to recent uploads |
| `--seed S` | Integer; default random. The seed used is always printed and written to the picks file |
| `--dry-run` | Print the plan (picks, downloads, removals) and write nothing |
| `--game`, `--content-type`, `--note`, `--max-minutes`, `--sort` / `--no-sort`, `--out` | As in 1.2 (`--out` is the picks file) |

`--channel` cannot be combined with links files, `--list-channel` or `--tag-uploader` (exit 2).

## Behaviour

1. **List.** Flat-list the channel with `clip_fetch.channel.ytdlp_flat_list` (newest first; each entry has `id`, `duration`, `title`, `live_status`). Drop live videos and entries with no URL, as `list_channel` does. Drop videos longer than `--max-minutes` when `duration` is known. Rank the rest by listing order: newest = rank 0.
2. **Weights.** With `n` candidates, rank `i` (0 = newest): `w_i = exp(-B * i / max(n - 1, 1))`. `B = 0` gives equal weights; at the default `B = 2` the newest video is about 7.4 times as likely as the oldest.
3. **Weighted pick without replacement** (Efraimidis–Spirakis): for each candidate draw `u` uniform in (0, 1) from `random.Random(seed)` and use key `u ** (1 / w_i)`; take candidates in descending key order. The ordered list is the pick order; it is fixed by the seed.
4. **Held videos.** A video of this channel is *held* when its id is in the fetch log with `status = ok` for this channel (`uploader_id = yt:<channel_id>`) and a file whose name ends in `__<id>.mp4` exists under `data/incoming_clips/<source>/` or under `data/raw/**/<source>/`. The id is the last `__`-separated token of the file name stem.
5. **Mode `new`.** Candidates exclude every video id the fetch log already lists with `status = ok` for this channel (even if the file is gone, so a video the user removed is not fetched again). Take picks in order and download each; a pick that ends `skipped_long`, `failed` or unavailable is replaced by the next pick, until N videos are downloaded or the candidates run out (report the shortfall; exit 0).
6. **Mode `total`.** Let `held` be the count from step 4.
   - `held < N`: behave as mode `new` with count `N - held`.
   - `held == N`: do nothing and say so.
   - `held > N`: remove `held - N` videos. Only files still in `data/incoming_clips/<source>/` are removable. Choose which with the same weighted method using weights `w'_i = 1 / w_i` (leaning to the **oldest** videos), over the removable held videos ranked by the channel's listing order (a held video no longer in the listing ranks as oldest). Move each chosen file to `data/incoming_clips/_archive/<source>/<relative name>` (the sorter's trash folder) and append a fetch-log row with `status = removed`. Held videos in `data/raw/` or processed are never touched; if there are fewer removable videos than needed, remove what is possible and report the remainder.
7. **Picks file.** Write `data/clip_links/<YYYY-MM-DD>_yt_<handle>_sample.txt` (or `--out`) with a `#` header (channel, channel id, date, mode, count, seed, recency bias, held before, picks, removals) and one `<url>,<Game>,<content_type>` line per downloaded pick (empty fields where not given). Removals are listed as `# removed: <file name>` lines.
8. **Download** through the existing `clip_fetch.download.run` with `LinkEntry` items, so uploader rows, naming (`unlabelled__<date>__<time>__<id>.mp4` or the game slug), hints and the fetch log work as before. Print the sample summary after the normal summary: mode, picks, downloaded, replaced, removed, shortfall, seed.
9. **`--dry-run`** performs steps 1–6 using only the listing and local files and prints the plan; it writes no file and moves none.
10. **Errors.** Not a channel URL, `--count` below 1, `--recency-bias` below 0, a mode other than `new` / `total`, or flags combined as above: exit 2 with a one-line message. A listing or network failure: exit 1.

## Decisions

- Weighted random pick towards recent uploads, two modes `new` and `total` (user, 2026-11-19).
- Proposed, to confirm with the user before building:
  1. **Shrinking** moves surplus videos to `data/incoming_clips/_archive/<source>/` and only from `data/incoming_clips/`; it never deletes and never touches `data/raw/` or later stages. Alternative: allow removing from `data/raw/` too (needs the frame-source and index cleanup that `gfc-make-sources --rebuild` does).
  2. **Which videos shrink first:** weighted towards the oldest (inverse of the pick weights). Alternative: uniform random.
  3. **Default recency bias 2.0** (newest about 7.4 times as likely as the oldest).

## Testing

Unit tests with a fake lister and fake downloader (no network), in `tests/unit/test_clip_channel_sample.py`:

- weights: `B = 0` equal; `B > 0` strictly decreasing with rank; a single candidate works.
- pick: same seed gives the same order; different seeds differ; over 2,000 seeds with `B = 3` the newest quarter is picked first more often than the oldest quarter; with `B = 0` the counts are within a loose tolerance of equal.
- mode `new`: ids already `ok` in the fetch log (file present or gone) are never picked; N larger than the candidates downloads all and reports the shortfall; a `skipped_long` or failed pick is replaced.
- mode `total`: below N downloads the difference; equal does nothing; above N archives exactly `held - N` files, only from `data/incoming_clips/`, with `removed` rows in the log; held files in `data/raw/` are never moved and the remainder is reported.
- held detection: the id is read from the last `__` token; files of another channel's source are not counted.
- picks file content and header; `--dry-run` changes nothing (no file, no move, no log row).
- CLI: a video URL, a playlist URL, `--count 0`, a bad mode, and `--channel` with a links file all exit 2.
- Every existing `clip_fetch` test still passes.

Smoke (real network, no download): `gfc-fetch-clips --channel <small channel URL> --count 3 --dry-run` prints three picks and writes nothing.

## Acceptance checks

- [ ] `--channel` with `--count` downloads that many new videos, weighted to recent, and records the seed
- [ ] `--mode total` adds when below, does nothing when equal and archives the surplus when above, never deleting
- [ ] Skipped, failed and over-long videos are replaced until the count is met or the channel runs out
- [ ] `--dry-run` writes and moves nothing
- [ ] Docs updated: this spec (status `implemented`), [clip-link-youtube.md](clip-link-youtube.md) (see-also line), ROADMAP row 4e.3

## Build instructions

Written for an agent that builds exactly this and decides nothing; ask the user if anything is unclear.

1. `clip_fetch/sample.py` (new): `recency_weights(n, bias) -> list[float]`; `weighted_order(weights, seed) -> list[int]` (Efraimidis–Spirakis with `random.Random(seed)`); `held_videos(data_root, source, channel_id) -> dict[str, Path]` (video id to file, from the fetch log and the two folders); `plan_sample(entries, held, mode, count, bias, seed, max_minutes) -> Plan` with `picks`, `removals`, `held_before`, `shortfall`; keep it pure so tests need no files beyond fixtures.
2. `clip_fetch/sample.py`: `run_sample(...)`: list with the injected lister, build the plan, write the picks file, download through `download.run` with the injected downloader and replace failed or skipped picks from the remaining order, then apply removals (move to `_archive`, append `removed` rows to the fetch log with the same columns).
3. `clip_fetch/cli.py`: flags `--channel`, `--count`, `--mode`, `--recency-bias`, `--seed`, `--dry-run`; validation and exit codes as in Behaviour 10; `__version__ = "1.3.0"`. Reuse `parse_game_field`, `parse_content_type` and `validate_source` as the 1.2 flags do.
4. Tests as in Testing; docs as in the acceptance checks; the `docs/readme-drafts` entry is not needed.
