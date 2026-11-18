# Clip link downloader (`gfc-fetch-clips`)

**Stage:** 1 — Data intake  
**Status:** specified  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [clip sorter](clip-sorter.md) · [make-sources](make-sources.md)

## What it does (high level)

Downloads the clips a contributor shared as links (Medal clip links), one by one, into a local folder, names each file with its game and upload time, and writes a hints file so the [clip sorter](clip-sorter.md) shows the game as the suggested label. It uses only the links the contributor gave, with no account login.

## Why we need it

Some contributors keep clips only in Medal's cloud. They have given permission to use them, but downloading each by hand and finding the game is slow. A Medal clip link already names the game (`medal.tv/games/<game>/clips/<id>`), so the label comes with the link.

## Scope and limits

- **Medal clip links only.** Other links (Insights.gg and others) are attempted through yt-dlp's generic handling and reported as failed if that does not work; those clips are downloaded by hand or exported by the contributor.
- **No account access.** No logins, cookies or auth tokens; only clips that can be viewed through their link. Profile-wide downloads are out of scope.
- **Permission is per contributor.** The link list is what the contributor shared; the tool does not discover other clips.
- **Polite.** One download at a time, a pause between downloads, and a stop on rate limiting (HTTP 429).

## Spike results (2026-11-18, yt-dlp 2026.10.26, three permitted Medal links)

- Download works through the link alone, no login: 21 MB in about 6 s for a 58 s clip.
- **Quality is Medal's cloud copy, not the original recording:** formats offered were an HLS stream at 720p and an `http-source` file; the downloaded file was H.264 1280×720 at 60 fps, about 2.4 Mbit/s. Cloud clips are therefore 720p re-encodes, unlike local recordings (1080p to 4K). That is enough for 256×144 model input, but it is a recording property that lines up with these sources: the log records it, and run reports check it as a possible shortcut (`run-report`, recording properties per class).
- `timestamp` (upload time, seconds) and `upload_date` were present for all three; the file-name time works as specified.
- Clip titles contain emoji. File names use the slug, time and id (never the title), and console output must not fail on such text: set `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` in the CLI and write the log as UTF-8.

## Connections

| | |
|---|---|
| **Reads** | A text file of links from one contributor |
| **Writes** | `data/incoming_clips/<source>/` (videos, `fetch_log.csv`, `hints.csv`) |
| **Then** | `gfc-sort-clips data/incoming_clips/<source> --source <source> --hints data/incoming_clips/<source>/hints.csv` |
| **Needs** | yt-dlp (optional dependency group `fetch`) and ffmpeg (already used by the project) |

## Usage

```text
gfc-fetch-clips <links.txt> --source friend_alex
gfc-fetch-clips <links.txt> --source friend_alex --dry-run     # parse and label the links only
python -m game_frame_classifier.clip_fetch ...
```

| Flag | Meaning |
|---|---|
| `<links.txt>` | One link per line; blank lines and lines starting with `#` are ignored; duplicates are removed |
| `--source` | Source name (normalised with `normalize_handle`); output folder `data/incoming_clips/<source>/`. Must not start with `contributor_` |
| `--data-root` | Data root (default `data`) |
| `--pause-s` | Seconds between downloads (default 3) |
| `--limit N` | Stop after N new downloads |
| `--dry-run` | Parse links, show the game for each and what would be downloaded; no network |

Exit codes: `0` all done (including nothing new), `1` at least one link failed, `2` usage error or yt-dlp missing, `3` stopped by rate limiting (rerun later; finished links are skipped).

## Behaviour

1. **Read links.** Strip, drop blanks and `#` lines, de-duplicate keeping order.
2. **Parse each link.** `parse_link(url) -> LinkInfo(url, site, clip_id, slug)`. Medal: host `medal.tv` or `www.medal.tv`, path `/games/<slug>/clips/<clip_id>` (an optional trailing path or query is ignored). Older form `/clips/<clip_id>`: slug empty, and it is not downloaded (status `failed`, error "old Medal link form; ask for the full medal.tv/games/... link"): yt-dlp 2026.10.26's Medal extractor only matches `/games/<slug>/clips/<id>` (checked 2026-11-18). Other hosts: `site = "other"`.
3. **Game from the slug.** `game_for_slug(slug) -> (game, other_name)`: the table below first; otherwise `label_hints(slug with "-" replaced by " ")` when it gives exactly one game; otherwise Other with `other_name = normalize_other_name(slug)` (empty slug: no suggestion).

   | Slug | Game |
   |---|---|
   | `valorant` | Valorant |
   | `league-of-legends` | League_of_Legends |
   | `counter-strike-2`, `cs2`, `counter-strike-global-offensive`, `csgo`, `counter-strike` | CS2 |
   | `minecraft` | Minecraft |
   | `overwatch-2`, `overwatch` | Overwatch_2 |
   | `marvel-rivals` | Marvel_Rivals |

   CS:GO counts as CS2 and Overwatch 1 as Overwatch 2 (decisions log, 2026-11-18).
4. **Skip finished links.** A link whose `clip_id` (or URL for non-Medal links) has `status = ok` in `fetch_log.csv` and whose file still exists is skipped.
5. **Download** with the yt-dlp Python API (`yt_dlp.YoutubeDL`), one link at a time, options: `format: "bestvideo*+bestaudio/best"`, `merge_output_format: "mp4"`, `noplaylist: True`, `retries: 3`, `outtmpl` to a temporary name in the output folder, `quiet: True`. Read from the returned info: `timestamp` (or `upload_date`), `title`, `duration`, `id`. Any HTTP 429 stops the run with exit 3.
6. **Name the file** `<slug or site>__<YYYY-MM-DD>__<HH-MM-SS>__<clip_id>.mp4`, the time being the upload time in local time (from `timestamp`; from `upload_date` at 00-00-00 if only the date is known; from the download time if neither, marked in the log). `sourcing.timeinfo` reads `YYYY-MM-DD__HH-MM-SS` from file names, so recording sessions (D30) come out close to right. Also set the file's modification time to the upload time. The upload time is not the recording time; for Medal clips uploaded automatically they are minutes apart.
7. **Log** every link in `fetch_log.csv` (append one line per attempt, UTF-8): `utc, url, site, clip_id, slug, game, other_name, status (ok | failed | skipped | rate_limited), file, bytes, sha256, upload_time, time_source (timestamp | upload_date | download), width, height, fps, format_id, error`. Errors are one line, with local paths removed.
8. **Hints.** After the run, rewrite `hints.csv` from the log (`file,game,other_name`, one line per `ok` file with a game or Other), for `gfc-sort-clips --hints`.
9. **Summary**: counts by status and by game.

## Never

- Never use cookies, logins or tokens, and never download anything that is not in the links file.
- Never run downloads in parallel or without the pause.
- Never write outside `data/incoming_clips/<source>/`.

## Testing

No test touches the network: the downloader is called through a small wrapper that tests replace.

| Kind | Cases |
|---|---|
| **Unit: links** | Medal link with game path, with query and trailing slash, old `/clips/` form, other host; blank and `#` lines; duplicates |
| **Unit: game** | Every slug in the table; `label_hints` fallback; unknown slug → Other with a normalised name; empty slug → none |
| **Unit: naming** | Timestamp, date only, neither; file name parses back through `sourcing.timeinfo.parse_filename_time` to the same time |
| **Unit: run** | Fake downloader writing a small file: log lines, skip on rerun, failed link logged and exit 1, 429 stops with exit 3, `--limit`, `--dry-run` does no download; `hints.csv` content |
| **Unit: missing yt-dlp** | yt-dlp not importable → message to install the `fetch` extra, exit 2; `--dry-run` still works |

## Acceptance checks

- [ ] A links file of Medal clips downloads into `data/incoming_clips/<source>/` with game and time in each file name
- [ ] `hints.csv` gives the sorter a suggestion for every Medal clip with a game in its link
- [ ] Rerun skips finished links; rate limiting stops cleanly
- [ ] No network in tests; no credentials anywhere
- [ ] CLI entry `gfc-fetch-clips` in `pyproject.toml`; `fetch` optional dependency group

## Build instructions

Written for an agent that builds exactly this and decides nothing. Ask the user if anything below is unclear or wrong. Do not install packages without asking the user; tests must pass without yt-dlp installed.

1. **Package** `src/game_frame_classifier/clip_fetch/` with `__init__.py` (`__version__ = "1.0.0"`), `__main__.py`, `links.py`, `naming.py`, `download.py`, `cli.py`.
2. **`links.py`**: `@dataclass(frozen=True) LinkInfo(url, site, clip_id, slug)`; `read_links(path) -> list[str]` (Behaviour 1); `parse_link(url) -> LinkInfo` with `urllib.parse` (Behaviour 2); `SLUG_GAMES` dict from the table; `game_for_slug(slug) -> tuple[str, str]` returning `(game, other_name)` with `game` in `sourcing.labels.CLASSES` or `("", "")`.
3. **`naming.py`**: `clip_file_name(info: LinkInfo, upload: datetime | None, upload_date: str | None, now: datetime) -> tuple[str, datetime, str]` returning the file name, the time used and `time_source` (Behaviour 6). Use local time for the name.
4. **`download.py`**: `class RateLimited(Exception)`; `def ytdlp_download(url, out_dir, temp_name) -> dict` (imports `yt_dlp` inside the function; raises `RateLimited` when the error text contains `HTTP Error 429`); `run(links, source_dir, *, downloader=ytdlp_download, pause_s, limit, dry_run, sleep=time.sleep, now=datetime.now) -> Summary` implementing Behaviour 4–9; the log written with `open(..., "a")` one line per attempt; SHA-256 with `sourcing.hashing.sha256_file`; `os.utime` for the modification time.
5. **`cli.py`**: `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` first; argparse as in Usage; normalise `--source`, refuse `contributor_` prefix (exit 2); check `importlib.util.find_spec("yt_dlp")` unless `--dry-run` (missing → message "install the fetch extra: pip install yt-dlp", exit 2); output dir `data_root / "incoming_clips" / source`; map the summary to the exit codes.
6. **`pyproject.toml`**: optional dependency group `fetch = ["yt-dlp"]`; script `gfc-fetch-clips = "game_frame_classifier.clip_fetch.cli:main"`. **`.gitignore`**: `data/incoming_clips/`. **`docs/data-layout.md`**: the folder and its files.
7. **Tests**: `tests/unit/test_clip_fetch.py` with the cases in the Testing table, a fake `downloader` that writes a few bytes to the requested file and returns `{"timestamp": ..., "id": ..., "title": ...}`, and a fake `sleep`.
8. Set this spec's status to `implemented` and tick the acceptance checks.
