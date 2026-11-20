# YouTube links, channel listing and content types (`gfc-fetch-clips` 1.2.1, `gfc-sort-clips` 1.2.2)

**Stage:** 1 — Collection  
**Status:** implemented  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [clip link downloader](clip-link-downloader.md) · [automatic sources](clip-link-auto-source.md) · [clip sorter](clip-sorter.md)

## What it does

- `gfc-fetch-clips` accepts YouTube video links. Each channel becomes its own source, like a Medal uploader.
- `--list-channel` writes every video link of a channel into a links file.
- Videos with no game given are flagged **unlabelled**; the sorter can open just those.
- Every clip can optionally carry a **content type** (esports VOD, pure gameplay, gameplay with streamer overlay), set in the links file, for a whole channel, or in the sorter. It travels with the clip into `clips_index` for analysis.

## Rules

- **Permission is assumed.** A link or channel given to the tool means permission was obtained. New YouTube channels are accepted automatically, as Medal uploaders are (decided 2026-11-19).
- **No account access**: no cookies or logins; public or unlisted videos only. Other sites stay refused.
- **Two kinds of YouTube source, told apart by the source name** (decided 2026-11-19). `yt_<handle>` is the **web** label: downloaded from the public web, no licence granted or checked, used for educational research only, never redistributed (`source_kind` `web`, `public_examples_ok` false). It is a statement of where the clips came from, not a licence. A channel whose owner agreed to be used is a contributor: its source is `friend_<handle>` (`source_kind` `contributor`, handled like any contributor's clips). Download a contributor's links with `--source friend_<handle>`, or type that name when `--ask` offers a source; the uploader file's newest row for the channel decides later downloads. Default splits include `web` sources; a split can leave them out with `exclude_source_kinds: ["web"]`.

## Content types

| Value | Meaning | Sorter key |
|---|---|---|
| `esports_vod` | Esports broadcast: tournament overlay and frames other than gameplay (casters, replays, desk) | `Q` |
| `gameplay` | Pure gameplay, no overlay beyond the game's own HUD | `W` |
| `streamer_overlay` | Gameplay with a streamer overlay (facecam, chat, alerts) | `E` |
| `mixed` | Flag: clip mixes kinds / needs scene splitting later (can combine with a kind, e.g. `gameplay,mixed`) | `R` |

Empty means not marked. Values outside the table are refused (exit 2 in the CLI, 400 in the page). Content type is **in addition to** the game label (both can be set). Keys are `Q`/`W`/`E`/`R` on the row under `1`–`4` for speed; the page legend lists them; `U` undoes the last content-type or label row if the wrong key was hit.

**Channel tag.** An uploader (YouTube channel or Medal uploader) can carry a content type meaning "most of this channel's videos are this kind". Its videos inherit it unless a video's own line or the sorter says otherwise. Every clip records where its type came from in `content_type_origin`: `video` (its own line), `channel` (inherited from the channel tag), `sorter` (set or changed in the page), or empty.

## Behaviour

1. **Links.** Accepted YouTube forms: `youtube.com/watch?v=<id>`, `youtu.be/<id>`, `youtube.com/shorts/<id>`, with or without `www.` / `m.`; `LinkInfo(site="youtube", clip_id=<id>, slug="")`. A links-file line is `<url>[,<Game>[,<content_type>]]`; `<Game>` is one of `CLASSES`, `Other:<name>` for Other, or empty (`<url>,,gameplay`). This applies to Medal lines too (a Medal game from the link is used when the line gives none).
2. **Uploader.** From metadata `channel_id` (else `uploader_id`) and `channel` (else `uploader`); stored in the uploader file (`data/clip_links/medal_users.csv`) as `uploader_id = "yt:<channel_id>"`; new channels saved `allowed = yes`, source `yt_<normalize_handle(channel)>`, note `auto`. `allowed = no` still blocks a channel. `--ask` asks for YouTube as for Medal. The uploader file gains a `content_type` column (the channel tag; empty by default); as before, rows are only appended and an uploader's newest row counts, so re-tagging a channel adds a row. `--tag-uploader <uploader_id or source> --content-type <value>` appends such a row without downloading.
3. **Download.** At most 720p (`bestvideo[height<=720]+bestaudio/best[height<=720]`), merged to MP4. Longer than `--max-minutes` (default 60): logged `skipped_long`, not downloaded. File name `<game slug or "unlabelled">__<YYYY-MM-DD>__<HH-MM-SS>__<id>.mp4` (time `00-00-00` when only a date is known).
4. **Unlabelled.** A video with no game (no game in the line and none from a Medal link) is logged with `game` empty and counted as unlabelled in the summary. `hints.csv` gains `content_type` and `content_type_origin` columns and keeps one row per downloaded file, with `game` empty for unlabelled ones. The type is the line's own (`video`), else the channel tag (`channel`), else empty.
5. **Channel listing.** `gfc-fetch-clips --list-channel <channel URL> [--game <Game>] [--content-type <value>] [--note "<text>"] [--out <file>]` lists the channel's videos with flat extraction (no download), newest first, skipping videos that are live now; writes `data/clip_links/<YYYY-MM-DD>_yt_<handle>.txt` (or `--out`) with a `#` header (channel, channel id, date, note, count) and one `<url>,<Game>,<content_type>` line per video (empty fields where not given); adds the channel to the uploader file as in step 2 if it is not there, and with `--content-type` also tags the channel (appends a row with that `content_type`). Downloads nothing.
6. **Sorter.**
   - `--unlabelled`: the page shows only clips with no game hint and no label, disabled or trash decision. Other flags work with it.
   - Keys `Q` / `W` / `E` set one content kind (press again to clear); `R` toggles **mixed** additively (e.g. gameplay+mixed → stored `gameplay,mixed`). Origin `sorter`. Pressing the selected game again unselects it (keeps content type). `S` skip and `C` reset clear game and content types (fresh for later); skip advances, reset stays. Content type does not count as deciding the clip; `U` undoes the newest row. A labelled clip whose type includes `mixed` is still copied on apply (shelved in `data/raw`).
   - `decisions.csv` gains a `content_type` column and decision values `content`, `unlabel`, `reset`.
   - `--accept-hints` also takes the hint's content type.
   - Apply writes `data/raw/<Game>/<source>/content_types.csv` (`file, content_type, content_type_origin`; Other: under `_other/<name>/<source>/`), adding or replacing that file's row, for every copied clip with a content type.
7. **Into the pipeline.** `gfc-make-sources` reads `content_types.csv` beside the videos and writes `content_type` and `content_type_origin` into each `clip.json` (empty when absent). Files whose type includes `mixed` (alone or with a kind) are skipped (`status_detail=mixed_content_type`) and never enter `frame_sources` until a scene splitter can produce accurately labelled segments. `gfc-derive-frames` adds both columns to `clips_index` (empty for clips without them). Other tools do not filter on content type yet; run reports can break results down by it.

## Usage

```text
gfc-fetch-clips --list-channel https://www.youtube.com/@<handle> --game Overwatch_2 --content-type streamer_overlay
gfc-fetch-clips --tag-uploader yt_<handle> --content-type esports_vod     # tag a channel already known
gfc-fetch-clips data/clip_links --max-minutes 30
gfc-fetch-clips data/clip_links --sort                 # after downloads, open the sorter page
gfc-fetch-clips data/clip_links --no-sort              # scripts: print next command, never prompt
gfc-sort-clips data/incoming_clips --accept-hints      # tagged clips straight into data/raw
gfc-sort-clips data/incoming_clips --unlabelled        # page with only the unlabelled ones
```

After new downloads, fetch always prints the `gfc-sort-clips …` next step. In a terminal it also asks `Open sorter now? [y/N]` unless `--sort` or `--no-sort`. The sorter is a local browser page with contact sheets (no file-explorer browsing).

## Testing

Unit, with fake metadata, listing and download functions (no network): YouTube link forms; `,Game,content_type` parsing incl. empty game and `Other:<name>`; new channel auto-accepted into `yt_<handle>`; `allowed = no` blocks; `skipped_long`; 720p format string; `unlabelled` file name and summary count; hints with content type; channel listing file, uploader row and channel tag; `--tag-uploader` appends a row; videos inherit the channel tag with origin `channel` and a line's own type wins with origin `video`; invalid content type refused; sorter `--unlabelled` filter; `Q`/`W`/`E`/`R` set, toggle and undo; content row does not count as a decision; `--accept-hints` carries content type; apply writes and updates `content_types.csv` (including `mixed`); make-sources skips `mixed` (`mixed_content_type`, not over_budget, not indexed) while other content types still extract; system path sorter-apply-mixed → make-sources skips; derive carries both columns; every existing Medal and sorter test still passes.

## Acceptance checks

- [x] YouTube links and channels download into one source per channel without asking
- [x] Unlabelled videos are flagged and the sorter can show only them
- [x] Content type can be set per video (links file or sorter) or as a channel tag that its videos inherit, and reaches `clips_index` with its origin
- [x] Long videos skipped; at most 720p
- [x] Docs updated: this spec, [clip-link-downloader.md](clip-link-downloader.md) scope (Medal and YouTube), [clip-sorter.md](clip-sorter.md) keys and flags, `docs/data-layout.md`

## Build instructions

Written for an agent that builds exactly this and decides nothing; ask the user if anything is unclear.

1. `clip_fetch/links.py`: YouTube parsing; `read_link_entries(paths) -> list[LinkEntry(url, game, other_name, content_type)]` (folders as in 1.1, de-duplicated by URL keeping the first); `CONTENT_TYPES = ("esports_vod", "gameplay", "streamer_overlay", "mixed")`; `UNSUPPORTED_SITE_ERROR` = "unsupported site: only Medal and YouTube links are supported".
2. `clip_fetch/users.py`: `content_type` in `USER_COLUMNS` (old files without it read as empty); `proposed_source(name, prefix)` (`friend_` Medal, `yt_` YouTube); site-aware ids; `tag_uploader(users_path, key, content_type)` (key matches `uploader_id` or `source`; exit 2 if neither matches).
3. `clip_fetch/download.py`: YouTube metadata fields, format string, `--max-minutes`, naming, unlabelled count, `hints.csv` with `content_type`; `run` takes `LinkEntry` items.
4. `clip_fetch/channel.py` (new): `ytdlp_flat_list(url)` using `extract_flat="in_playlist"` on `<url>/videos` for a channel root (`@<handle>` or `/channel/<id>`); `list_channel(url, *, game, content_type, note, out, users_path, lister=ytdlp_flat_list, now)`.
5. `clip_fetch/cli.py`: `--list-channel`, `--tag-uploader`, `--game`, `--content-type`, `--note`, `--out`, `--max-minutes`; `__version__ = "1.2.0"`.
6. `clip_sorter/`: `scan` reads the hint's content type; `store` (`content_type` column, `content` decision, replay keeps label state and content type apart, undo removes the clip's newest row); `server` / `page.html` (`Q`/`W`/`E`/`R`, display); `cli` (`--unlabelled`); `apply` (`content_types.csv`, `accept_hints` content type); `__version__ = "1.2.1"`.
7. `make_sources.py`: read `content_types.csv`; `content_type`, `content_type_origin` in `clip.json`. `derive_frames.py`: both in `CLIPS_INDEX_COLUMNS` (after `other_name`) and in `build_clip_row`.
8. Docs as in the acceptance checks; tests as above.
