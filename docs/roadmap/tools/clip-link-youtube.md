# YouTube links and channel listing (`gfc-fetch-clips` 1.2)

**Stage:** 1 — Collection  
**Status:** specified  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [clip link downloader](clip-link-downloader.md) · [automatic sources](clip-link-auto-source.md)

## What it does

Adds YouTube video links to `gfc-fetch-clips`, and a command that lists every video of a YouTube channel into a links file once the channel owner has given permission. Each channel becomes its own source, like a Medal uploader. A YouTube channel is never downloaded without a recorded permission.

## Rules

- **Permission first.** A YouTube channel's videos are downloaded only when its row in the uploader file has `allowed = yes`. New YouTube channels are never accepted automatically (unlike Medal uploaders): they are added as pending and their links are logged `pending_permission` (exit 4). Permission is recorded by `--list-channel ... --permission "<note>"` or by editing the file.
- **No account access** (as for Medal): no cookies or logins; only public or unlisted videos.
- Other sites stay refused.

## Behaviour

1. **Links.** Accepted forms: `youtube.com/watch?v=<id>`, `youtu.be/<id>`, `youtube.com/shorts/<id>`, with or without `www.`/`m.`; `LinkInfo(site="youtube", clip_id=<11-char id>, slug="")`. A links-file line may carry a game after a comma: `<url>,<Game>` (one of `CLASSES`; `Other` as `Other:<name>`). Without it the video has no game hint and is labelled in the sorter page.
2. **Uploader.** From metadata: `channel_id` (else `uploader_id`) and `channel` (else `uploader`). Stored in the same uploader file (`data/clip_links/medal_users.csv`) with `uploader_id = "yt:<channel_id>"`, so Medal and YouTube ids cannot clash. Proposed source `yt_<normalize_handle(channel)>`.
3. **Download.** Video at most 720p (`bestvideo[height<=720]+bestaudio/best[height<=720]`), merged to MP4. Videos longer than `--max-minutes` (default 60) are logged `skipped_long` and not downloaded. File name `<game or "youtube">__<YYYY-MM-DD>__<HH-MM-SS>__<id>.mp4` from the upload date (time `00-00-00` when only a date is known). `hints.csv` gets the game only when the links-file line gave one.
4. **Channel listing.** `gfc-fetch-clips --list-channel <channel URL> --permission "<who agreed, when, how>" [--game <Game>] [--out <file>]`:
   - Lists the channel's videos with flat extraction (no download), newest first, skipping live streams that are still live.
   - Writes `data/clip_links/<YYYY-MM-DD>_yt_<handle>.txt` (or `--out`): a header of `#` lines (channel name, channel id, listing date, permission note, video count), then one `<url>[,<Game>]` per line.
   - Appends (or adds a new row for) the channel in the uploader file with `allowed = yes`, the proposed source and `note = permission: <note>`; an existing row is never changed (the new row wins, as before).
   - Refuses without `--permission` (exit 2). Downloads nothing; the person then runs `gfc-fetch-clips <that file>`.
5. **Log** as in 1.1, with `site = youtube`.

## Usage

```text
gfc-fetch-clips --list-channel https://www.youtube.com/@<handle> --permission "<note>" --game Overwatch_2
gfc-fetch-clips data/clip_links/2026-11-19_yt_<handle>.txt --max-minutes 30
gfc-fetch-clips data/clip_links                        # Medal and YouTube lines together
```

## Testing

Unit, with fake metadata, listing and download functions (no network): link forms and the `,Game` suffix; YouTube new channel stays pending and is not downloaded; allowed channel downloads into its source; `skipped_long`; 720p format string; file name from date only; channel listing writes the header and lines, records permission, refuses without `--permission`; other sites still refused; every Medal test still passes.

## Acceptance checks

- [ ] YouTube links download into one source per channel, only with recorded permission
- [ ] `--list-channel` writes a links file and records the permission
- [ ] Long videos are skipped; downloads are at most 720p
- [ ] Spec status and [clip-link-downloader.md](clip-link-downloader.md) scope updated (Medal and YouTube supported; other sites refused)

## Build instructions

Written for an agent that builds exactly this and decides nothing; ask the user if anything is unclear.

1. `clip_fetch/links.py`: YouTube parsing; `read_links` keeps the optional `,Game` part (return `(url, game, other_name)` from a new `read_link_entries`; `read_link_files` keeps its URL-only behaviour for callers that need it); update `UNSUPPORTED_SITE_ERROR` to "unsupported site: only Medal and YouTube links are supported".
2. `clip_fetch/users.py`: `decide(..., site)` never auto-accepts `site == "youtube"`; `proposed_source` takes a prefix (`friend_` Medal, `yt_` YouTube).
3. `clip_fetch/download.py`: YouTube metadata fields, format string, `--max-minutes`, naming, hints from the links-file game; site-aware uploader ids.
4. `clip_fetch/channel.py` (new): `list_channel(url, *, permission, game, out, users_path, lister=ytdlp_flat_list, now)`.
5. `clip_fetch/cli.py`: `--list-channel`, `--permission`, `--game` (listing only), `--out`, `--max-minutes`; `__version__ = "1.2.0"`.
6. Docs: this spec's status; `clip-link-downloader.md` scope and "Later: other sites"; `docs/data-layout.md` (`yt_` sources, listing files in `data/clip_links/`).
7. Tests as above.
