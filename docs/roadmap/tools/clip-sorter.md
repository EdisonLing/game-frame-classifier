# Clip sorter (`gfc-sort-clips`)

**Stage:** 1 — Data intake  
**Status:** specified  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [make-sources](make-sources.md) · [link downloader](clip-link-downloader.md)

## What it does (high level)

Shows every video in a folder as one picture (six frames from across the clip, tiled 3×2) in a local web page, so a person can label, disable or trash each clip with one key press, about one clip per second. Applying the decisions copies the labelled clips into the `data/raw/` layout that `gfc-make-sources` reads, and moves trashed clips into an archive folder. Nothing is uploaded.

## Why we need it

Clips arrive without a reliable game label: downloads from clip links, exports from recorders, folders of mixed content, footage to check before use. Scrubbing each video to find the game takes about a minute per clip; a prepared contact sheet makes it a glance. The same tool reviews any folder of videos, labelled or not, before they enter the pipeline.

## Connections

| | |
|---|---|
| **Reads** | A folder of videos (recursive); optional `hints.csv` from the [link downloader](clip-link-downloader.md); `data/frame_sources/_index/by_sha256.json` (to skip clips already in the pipeline) |
| **Writes** | `data/sorting/<session>/` (sheets cache, decisions, report); on apply: `data/raw/<Game>/<source>/` and `data/raw/_other/<name>/<source>/` (copies), `<input folder>/_archive/` (moved trash) |
| **Then** | `gfc-make-sources` on the new raw clips |

## Usage

```text
gfc-sort-clips <folder> --source <name>                 # start or resume a session, opens the page
gfc-sort-clips <folder> --source <name> --hints <csv>   # with suggested labels from the downloader
gfc-sort-clips <folder> --source <name> --apply         # copy labelled clips, archive trashed ones
gfc-sort-clips <folder> --source <name> --apply --dry-run
python -m game_frame_classifier.clip_sorter ...
```

| Flag | Meaning |
|---|---|
| `<folder>` | Folder of videos, searched recursively (the `_archive` subfolder is ignored) |
| `--source` | Source name for the copies, normalised with `normalize_handle` (for example `edison`, `friend_alex`). Must not start with `contributor_` (reserved for packs) |
| `--session` | Session name (default: `<folder name>_<source>`); the session folder is `data/sorting/<session>/` |
| `--hints` | CSV `file,game,other_name` (file relative to `<folder>`): suggested labels |
| `--data-root` | Data root (default `data`) |
| `--port` | Local port (default 8765; the next free port if taken). The server listens on 127.0.0.1 only |
| `--no-open` | Do not open the browser |
| `--apply` | Apply the decisions instead of starting the page |
| `--dry-run` | With `--apply`: print what would happen, change nothing |

## Decisions

Each clip gets one decision; the latest one counts, and every decision can be changed until apply.

| Key | Decision | On apply |
|---|---|---|
| `1`–`6` | One of the six games, in `sourcing.labels.GAMES` order (Valorant, League of Legends, CS2, Minecraft, Overwatch 2, Marvel Rivals) | Copied to `data/raw/<Game>/<source>/<relative path>` |
| `7` | Other; the page asks for the content name the first time (list of names used before, or a new one, normalised with `normalize_other_name`) | Copied to `data/raw/_other/<name>/<source>/<relative path>` |
| `D` | **Disabled**: not confident this clip should be used; kept for a later look | Nothing; stays listed as disabled in the report |
| `X` | **Trash**: confident it should not be used | Moved to `<folder>/_archive/<relative path>` |
| `S` | Skip for now (undecided) | Nothing |
| `Enter` | Accept the suggested label | As the label |
| `U` | Undo the last decision | — |
| `←` / `→` | Previous / next clip without deciding | — |
| `P` | Open the clip in the default video player (`os.startfile`) | — |
| `F` | Jump to the first undecided clip | — |

After a decision the page moves to the next clip.

## Behaviour

1. **Scan.** Walk `<folder>` recursively for files with an extension in the recipe's `video_extensions` (`config/recipe.json`), skipping `<folder>/_archive/`. For each: relative path, size, `quick_id` (`sourcing.hashing.quick_id`). Probe with `sourcing.probe.probe_file`; files that fail to probe or are shorter than the recipe's `min_duration_s` are listed with the reason and cannot be labelled (they can be trashed).
2. **Suggested label**, first match wins:
   1. a `--hints` row for the file;
   2. `sourcing.labels.classify_mixed_filename(file name)` when it gives a game or Other (Medal-style names);
   3. `sourcing.labels.label_hints(relative path)` when it gives exactly one game.
   Otherwise no suggestion. The page always shows where a suggestion came from.
3. **Contact sheets.** For each probed clip: six frames at `duration × (i − 0.5) / 6` for i = 1..6, each by one input seek (`ffmpeg -ss <t> -i <file> -frames:v 1 -vf scale=320:-2`), tiled 3×2 into `data/sorting/<session>/sheets/<quick_id>.jpg` (`ffmpeg -i f%d.jpg -vf tile=3x2`). A background worker (2 threads) makes sheets in clip order, starting at the current clip and running ahead, so the page rarely waits. Existing sheets are reused. Measured on 3-minute 4K clips: 1.7–5.3 s per sheet.
4. **Page.** One HTML page with inline CSS and JavaScript (no external files), served by the standard library (`http.server.ThreadingHTTPServer`) on 127.0.0.1. Shows the sheet large, the file name and relative path, duration and resolution, the suggested label and its origin, the current decision, progress (decided / total, clips per minute) and a key legend. A "sheet not ready" placeholder refreshes until the sheet exists.
5. **Saving.** Every decision appends one line to `data/sorting/<session>/decisions.csv` (`utc, quick_id, rel_path, decision, game, other_name`; `decision` is `label`, `disabled`, `trash`, `skip` or `undo`). The current state is the replay of that file, so closing the page or the program loses nothing, and restarting resumes at the first undecided clip.
6. **Apply** (`--apply`), per clip by its latest decision:
   - Label: compute the SHA-256; if it is already in `frame_sources/_index/by_sha256.json`, report `already_in_pipeline` and skip. Otherwise copy (`shutil.copy2`, keeps the file time) to the destination; an existing identical file is reported `already_copied`; an existing different file stops that clip with `conflict`.
   - Trash: move to `<folder>/_archive/<relative path>` (create folders; never overwrite: add `_1`, `_2` if needed).
   - Disabled, skip, undecided: untouched.
   - Write `data/sorting/<session>/apply_report.json` and `.csv` (`rel_path, decision, result, destination`) and print counts per game, Other name, disabled, trashed, skipped and conflicts.
   - `--dry-run` prints the same plan and writes nothing.
7. **Source kind.** Friends' clips placed in `data/raw/` by this tool use a `friend_<handle>` source name (for example `friend_alex`). `derive_frames.source_kind` and `dataset_splitter._source_kind` report `friend_*` as `contributor`. Pair a friend's raw source with their kit packs through `source_groups` in `config/split.json` (same person).

## Never

- Never delete a clip; trash is a move into `_archive/` inside the input folder.
- Never modify or move a labelled clip in the input folder; apply copies.
- Never listen on anything but 127.0.0.1, and never upload.
- Never write outside `data/` and `<folder>/_archive/`.

## Testing

| Kind | Cases |
|---|---|
| **Unit: scan** | Recursive find; `_archive` ignored; non-video and short files listed with reasons |
| **Unit: suggestions** | Hints file wins; Medal-style name; single folder hint; ambiguous gives none |
| **Unit: decisions** | Replay of `decisions.csv` (label, change, undo, skip); resume at first undecided |
| **Unit: apply** | Label copies to the right layout (games and `_other/<name>/`); already-in-pipeline and already-copied skipped; conflict stops that clip; trash moves without overwrite; disabled untouched; dry-run writes nothing |
| **Unit: source kind** | `friend_x` → contributor in derive and the splitter |
| **System** | Synthetic clips (`tests/helpers/ffmpeg_fixtures.make_testsrc_video`) → sheets made (3×2, 960×360 for 16:9 input) → HTTP API decide / undo through the running server (port 0) → apply → files in `data/raw/` and `_archive/` |

## Acceptance checks

- [ ] A folder of clips can be labelled with one key per clip, with sheets ready ahead of the cursor
- [ ] Disabled and trashed clips behave as in the table; nothing is deleted
- [ ] Apply copies into the `gfc-make-sources` layout and skips clips already in the pipeline
- [ ] Session resumes after closing
- [ ] CLI entry `gfc-sort-clips` in `pyproject.toml`

## Build instructions

Written for an agent that builds exactly this and decides nothing. Ask the user if anything below is unclear or wrong.

1. **Package** `src/game_frame_classifier/clip_sorter/` with `__init__.py` (`__version__ = "1.0.0"`), `__main__.py` (calls `cli.main`), `scan.py`, `sheets.py`, `store.py`, `server.py`, `apply.py`, `page.html`, `cli.py`. Standard library only, plus the existing `sourcing` package.
2. **`scan.py`**: `@dataclass Clip(rel_path: str, path: Path, size: int, quick_id: str, duration_s: float | None, width: int, height: int, problem: str, suggestion: str, other_name: str, suggestion_origin: str)`; `scan(folder: Path, recipe, tools, hints: dict[str, tuple[str, str]]) -> list[Clip]` sorted by `rel_path`; `read_hints(path) -> dict`; `suggest(rel_path, hints) -> (game, other_name, origin)` implementing Behaviour 2.
3. **`sheets.py`**: `sheet_path(session_dir, quick_id)`; `make_sheet(tools, clip, out_path)` implementing Behaviour 3 with a temp folder per clip and `ffbin.run_capture`; `class SheetWorker` (threads=2, `start(order: list[Clip], current_index)`, `prioritise(index)`, `stop()`), which skips clips with a problem or an existing sheet.
4. **`store.py`**: `DECISION_COLUMNS`; `append(session_dir, quick_id, rel_path, decision, game="", other_name="")` (open with `"a"`, write one CSV line, flush); `replay(session_dir) -> dict[quick_id, dict]` (latest decision per clip; `undo` removes the latest non-undo decision of that clip); `first_undecided(clips, state) -> int`; `other_names(state) -> list[str]`.
5. **`server.py`**: `serve(session, clips, worker, port, open_browser)` with `ThreadingHTTPServer(("127.0.0.1", port), Handler)`; endpoints, all JSON except the page and sheets:
   - `GET /` → `page.html`;
   - `GET /api/state` → `{clips: [{i, rel_path, duration_s, width, height, problem, suggestion, other_name, origin, decision, game, sheet_ready}], games: GAMES, other_names: [...], current: i}`;
   - `GET /sheet/<quick_id>.jpg` → the image or 404;
   - `POST /api/decide` `{i, decision, game, other_name}` → appends, returns the new state of that clip; `POST /api/undo` → undoes the last decision overall; `POST /api/open` `{i}` → `os.startfile` on Windows, `xdg-open` / `open` elsewhere; `POST /api/current` `{i}` → `worker.prioritise(i)`.
   Validate `decision` and `game` against the tables above; return 400 otherwise.
6. **`page.html`**: one file, inline CSS and JS: fetch state, show the current clip as in Behaviour 4, keyboard handler for every key in the Decisions table, a small dialog for Other names (pick from list or type), poll `/api/state` every 2 s while the sheet is not ready. Dark and light both readable; no external URLs.
7. **`apply.py`**: `plan(session_dir, folder, clips, source, data_root) -> list[Action]`; `run(actions, dry_run) -> report`; implementing Behaviour 6. SHA-256 with `sourcing.hashing.sha256_file`; index from `frame_sources/_index/by_sha256.json` (missing file → empty).
8. **`cli.py`**: argparse as in Usage; validate `--source` (normalise, refuse `contributor_` prefix, exit 2); session dir `data_root / "sorting" / session`; `--apply` → apply path; else scan, start worker, serve, open the browser unless `--no-open`; Ctrl+C stops cleanly.
9. **Source kind**: in `derive_frames.source_kind` and `dataset_splitter._source_kind`, `friend_` prefix → `"contributor"`; update `docs/roadmap/tools/derive-frames.md` and `dataset-splitter.md` with one line each.
10. **`pyproject.toml`**: `gfc-sort-clips = "game_frame_classifier.clip_sorter.cli:main"`. **`.gitignore`**: add `data/sorting/`. **`docs/data-layout.md`**: add `data/sorting/<session>/` and the `friend_<handle>` source naming.
11. **Tests** as in the Testing table: `tests/unit/test_clip_sorter.py`, `tests/system/test_clip_sorter.py`; reuse `tests/helpers/ffmpeg_fixtures.py`; the system test starts the server on port 0 in a thread and calls the API with `urllib.request`.
12. Set this spec's status to `implemented` and tick the acceptance checks.
