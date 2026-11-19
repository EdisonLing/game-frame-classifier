# Automatic sources for clip links (`gfc-fetch-clips` 1.1, `gfc-sort-clips` 1.1)

**Stage:** 1 — Collection  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [clip link downloader](clip-link-downloader.md) · [clip sorter](clip-sorter.md) · [data layout](../../data-layout.md)

## What it does (high level)

One links file can hold Medal clips from many people. The downloader reads each clip's uploader from Medal's metadata and puts the clip under a source for that uploader, so different people are separate sources without sorting the links by hand. A local uploader file maps each Medal account to a source name and records whether its clips may be used; the first time an uploader appears, the downloader asks. The clip sorter then labels the whole download folder at once and keeps each clip's source. Automatic sources are the default; `--source` stays as an override that puts every link under one source.

## Why we need it

Sources are what the splitter caps (D33) and groups (`source_groups`), and what run reports break results down by. With one `--source` per run, a mixed list from a clip-sharing group either lands under one wrong source or has to be split by person first. Medal's metadata already names the uploader (spike, 2026-11-18: `uploader`, `uploader_id`, `uploader_url` present for every clip).

## Where the files live

| Path | Holds | Written by | Kept |
|---|---|---|---|
| `data/clip_links/<YYYY-MM-DD>_<label>.txt` | Link lists as received, one per batch | The person collecting | Permanent; tools never change them |
| `data/clip_links/medal_users.csv` | Uploader → source and permission | The downloader (new rows), the person (edits) | Permanent |
| `data/incoming_clips/<source>/` | Downloaded videos | The downloader | Working copy; the source of truth for frames until sorted |
| `data/incoming_clips/fetch_log.csv`, `hints.csv` | One log and one hints file for all sources | The downloader | Permanent with the videos |
| `data/raw/<Game>/<source>/` | Labelled clips | The sorter (copies) | Permanent |

`data/clip_links/` sits beside `data/contributor_packs/`: both hold what people gave us, read again to rebuild. Both are git-ignored; link lists and uploader names never go into git. To rebuild the downloads: `gfc-fetch-clips data/clip_links` (already-fetched clips are skipped).

## Connections

| | |
|---|---|
| **Reads** | Links files or a folder of them; `data/clip_links/medal_users.csv`; Medal metadata |
| **Writes** | `data/incoming_clips/<source>/`, `data/incoming_clips/fetch_log.csv`, `data/incoming_clips/hints.csv`; rows of `medal_users.csv` |
| **Then** | `gfc-sort-clips data/incoming_clips` (sources from the folders, hints found automatically) |

## Usage

```text
gfc-fetch-clips data/clip_links/2026-11-18_medal.txt           # automatic sources (default)
gfc-fetch-clips data/clip_links                                # every .txt in the folder, in name order
gfc-fetch-clips <links.txt> --source friend_alex               # override: all links to one source
gfc-fetch-clips <links.txt> --no-prompt                        # never ask; new uploaders wait (exit 4)
gfc-fetch-clips data/clip_links --refetch-missing              # download again clips whose file is gone
gfc-sort-clips data/incoming_clips                             # sources from folders (default)
gfc-sort-clips <folder> --source tester                        # override, as before
```

| Flag (fetch) | Meaning |
|---|---|
| `links` | One or more links files or folders (a folder means its `*.txt`, sorted by name) |
| `--source` | Override: every link goes to this source; uploaders are still logged, no permission check |
| `--no-prompt` | Do not ask about new uploaders; add them as pending and skip their links |
| `--refetch-missing` | Download again clips logged `ok` whose file is no longer anywhere under `data/incoming_clips/` |
| `--users` | Uploader file (default `data/clip_links/medal_users.csv`) |
| `--data-root`, `--pause-s`, `--limit`, `--dry-run` | As in 1.0 |

Exit codes: `0`, `1`, `2`, `3` as in 1.0; `4` some links wait for an uploader decision (pending or `--no-prompt`).

## Behaviour (fetch)

1. **Read links** from every file given (folders expanded to their `*.txt` in name order), as in 1.0, de-duplicated across files keeping first order.
2. **Skip finished clips.** A clip whose `clip_id` has any `ok` row in `fetch_log.csv` is skipped, whether or not its file still exists (sorted or trashed clips are never fetched again). With `--refetch-missing`, an `ok` clip is fetched again only when no file ending in `__<clip_id>.mp4` exists anywhere under `data/incoming_clips/` (including `_archive/`).
3. **Metadata pass** (automatic mode only). For each link not skipped, read metadata without downloading (`extract_info(download=False)`), pausing `--pause-s` between requests. Take `uploader_id` (string) and `uploader` (display name). A clip without `uploader_id` is logged `failed` with error `no uploader in metadata; use --source`. HTTP 429 stops the run as in 1.0 (exit 3).
4. **Uploader decisions.** Look up each `uploader_id` in `medal_users.csv` (`uploader_id, uploader, source, allowed, first_seen, note`):
   - `allowed = yes`: use its `source`.
   - `allowed = no`: log the link `not_allowed`; do not download.
   - Not in the file, or `allowed` empty: ask, one uploader at a time, in order of first appearance, showing the display name, how many links in this run and the proposed source `friend_<normalize_handle(uploader)>`:
     `Uploader "<name>" (<n> clips). Use as source friend_<x>? [y = yes / n = no / or type a source name]`.
     `y` saves `allowed = yes` with the proposed source; `n` saves `allowed = no`; any other answer is normalised with `normalize_handle` and saved with `allowed = yes` (refused and asked again if empty, starting with `contributor_` or `_`). Several uploaders may share one source (one person, two accounts).
   - With `--no-prompt`, or when stdin is not a terminal: a new uploader is saved with `allowed` empty, and its links are logged `pending_permission`.
   New rows are appended immediately (`first_seen` = today, UTC); existing rows are never changed by the tool.
5. **Download** as in 1.0 into `data/incoming_clips/<source>/`, then log `ok`.
6. **Log.** One `data/incoming_clips/fetch_log.csv` for all sources: the 1.0 columns plus `source`, `uploader_id`, `uploader`; `file` is relative to `data/incoming_clips/` (`<source>/<file name>`).
7. **Hints.** One `data/incoming_clips/hints.csv` (`file, game, other_name`), `file` relative to `data/incoming_clips/`, rebuilt from `ok` rows after each run.
8. **Summary** adds counts by source and the pending uploaders.

## Behaviour (sorter)

1. **Automatic sources** when `--source` is not given: each clip's source is the first folder of its path under the scanned folder. That folder name must equal its `normalize_handle` form and must not start with `contributor_` or `_`; otherwise the clip is shown with problem `no_source` and apply reports it as a conflict. Clips directly in the scanned folder have problem `no_source` (message: "put clips in a <source>/ folder or give --source").
2. **Destination** `data/raw/<Game>/<source>/<path below the source folder>` (Other: `data/raw/_other/<other_name>/<source>/...`).
3. **Hints** default to `<folder>/hints.csv` when `--hints` is not given and that file exists.
4. **Session name** defaults to `<folder name>_auto` in automatic mode.
5. The page shows each clip's source beside its file name.
6. `--source` behaves exactly as in 1.0.

## Never

- Never download a clip whose uploader is `no` or still pending.
- Never write uploader names, ids or links into tracked files, test data or commit messages; tests use made-up uploaders.
- Never change or delete a link list in `data/clip_links/`, or an existing row of `medal_users.csv`.
- Never use cookies or logins (as in 1.0).

## Testing

| Kind | Cases |
|---|---|
| **Unit: links** | Several files and a folder; cross-file duplicates |
| **Unit: skip** | `ok` with file gone is skipped; `--refetch-missing` fetches only when no `__<clip_id>.mp4` remains, including `_archive/` |
| **Unit: users** | Known yes/no; new uploader with answers `y`, `n`, a typed name, an invalid name then `y`; `--no-prompt` and non-terminal give pending; rows appended once; two uploaders one source |
| **Unit: log/hints** | Global log with `source`, `uploader_id`, `uploader`; `file` relative to `incoming_clips`; hints rebuilt |
| **Unit: override** | `--source` sends everything to one source, no metadata pass, no prompts |
| **Unit: sorter** | Source from folder; `no_source` for root clips and bad folder names; destination strips the source folder; default hints; session name |
| **System** | Fake metadata and downloader: mixed list of two allowed, one denied, one new uploader → folders, log, hints, exit code; then the sorter's apply plan on `data/incoming_clips` puts each clip under its source in `data/raw/` |

## Acceptance checks

- [x] A mixed links file lands in one folder per uploader, with no `--source`
- [x] New uploaders are asked once and remembered in `data/clip_links/medal_users.csv`
- [x] Denied and pending uploaders are never downloaded
- [x] Sorted or trashed clips are not downloaded again
- [x] `gfc-sort-clips data/incoming_clips` copies each clip under its own source

## Build instructions

Written for an agent that builds exactly this and decides nothing; ask the user if anything is unclear. No data exists yet under `data/incoming_clips/`, so the 1.0 per-source log and hints files need no migration.

1. **`clip_fetch/__init__.py`**: `__version__ = "1.1.0"`.
2. **`clip_fetch/links.py`**: `read_link_files(paths: list[Path]) -> list[str]` (Behaviour 1; folders expand to `sorted(p.glob("*.txt"))`).
3. **`clip_fetch/users.py`** (new): `USER_COLUMNS`; `load_users(path) -> dict[str, dict]`; `append_user(path, row)`; `proposed_source(uploader) -> str`; `validate_source(text) -> str` (returns `""` when refused); `decide(new_uploaders: list[tuple[id, name, count]], ask: Callable[[str], str] | None) -> dict[id, row]` where `ask=None` means no prompts (Behaviour 4).
4. **`clip_fetch/download.py`**: `ytdlp_metadata(url) -> dict` (`extract_info(download=False)`, same 429 handling); `run(...)` takes `incoming_dir`, `source_override: str | None`, `users_path`, `ask`, `refetch_missing`, `metadata=ytdlp_metadata`; log and hints at `incoming_dir` (Behaviour 2–8); `LOG_COLUMNS` gains `source, uploader_id, uploader`; statuses gain `not_allowed`, `pending_permission`; `Summary` gains `by_source`, `pending` and exit code 4 (after 3, before 1).
5. **`clip_fetch/cli.py`**: `links` with `nargs="+"`; `--source` optional; `--no-prompt`, `--refetch-missing`, `--users`; `ask = input if sys.stdin.isatty() and not args.no_prompt else None`.
6. **`clip_sorter/scan.py`**: `Clip` gains `source`; `scan(..., source: str | None)` fills it (Behaviour 1).
7. **`clip_sorter/apply.py`**: destination from `clip.source` and the path below the source folder (Behaviour 2); `no_source` → conflict.
8. **`clip_sorter/cli.py`**, **`server.py`**, **`page.html`**: `--source` optional; default hints and session name; source shown on the page.
9. **`.gitignore`**: `data/clip_links/` (already added with this spec). **`docs/data-layout.md`**: the incoming folder section (one log and hints at the top). Update [clip-link-downloader.md](clip-link-downloader.md) and [clip-sorter.md](clip-sorter.md) usage to the 1.1 defaults and this spec's status.
10. **Tests** as in the Testing table, in `tests/unit/test_clip_fetch.py`, `tests/unit/test_clip_sorter.py` and a new `tests/system/test_clip_auto_source.py`, with a fake `metadata` and fake downloader (no network).
