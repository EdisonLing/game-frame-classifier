# Official data layout

Canonical folder scheme for gameplay clips and derived frames.  
Raw media stays **local** (`data/raw/`, `data/frames/`, `data/manifests/` are gitignored).

## Top level

```text
data/
  README.md          # short pointer (tracked)
  raw/               # source videos/clips (local only) — collect here
  clip_links/        # link lists as received and the Medal uploader file (local only, permanent)
  received_originals/  # files sent outside the kit (zips of original videos), kept as received; backup only
  incoming_clips/    # gfc-fetch-clips downloads (local only), then gfc-sort-clips
  sorting/           # clip sorter sessions (sheets cache, decisions, apply reports)
  frame_sources/     # native-res stills per clip (local only) — D26; from gfc-ingest-pack / gfc-make-sources
  frames/            # 256×144 model-size frames derived from frame_sources (local only)
  manifests/         # index tables and split manifests (local only)
  runs/              # training runs and evaluation output (local only)
```

How the folders feed each other: [training-pipeline.md](training-pipeline.md).

## Received originals (`data/received_originals/`)

Files people sent in a non-standard form (for example zips of original videos), kept exactly as received after their contents were extracted into `data/raw/`. No tool reads this folder; it exists only so `data/raw/` can be rebuilt. Never committed.

```text
data/received_originals/
  <person>/
    <file as received>.zip
```

Kit packs are not kept here; they go in `data/contributor_packs/`.

## Clip links (`data/clip_links/`)

What people shared as links, kept so downloads can be rebuilt (`gfc-fetch-clips data/clip_links` skips clips already fetched). Tools never change the link lists. Never committed.

```text
data/clip_links/
  <YYYY-MM-DD>_<label>.txt   # one link per line, one file per batch as received
  medal_users.csv            # Medal uploader -> source and permission (gfc-fetch-clips)
```

## Incoming clips (`data/incoming_clips/`)

Downloads from contributor Medal links (`gfc-fetch-clips`), before labelling with the clip sorter.

```text
data/incoming_clips/
  fetch_log.csv        # one row per attempt (all sources); file is <source>/<name>
  hints.csv            # file,game,other_name for gfc-sort-clips (file relative to incoming_clips/)
  <source>/
    <slug>__<YYYY-MM-DD>__<HH-MM-SS>__<clip_id>.mp4
```

## Frame sources (`data/frame_sources/`)

Native-resolution JPEG stills used as the shared source of truth for personal and friend footage (D26). Layout and ingest rules: [tools/ingest-pack.md](roadmap/tools/ingest-pack.md).

```text
data/frame_sources/
  <Game>/contributor_<handle>/<clip_key>/<tier>/*.jpg   # from gfc-ingest-pack
  <Game>/<source>/<clip_key>/<tier>/*.jpg               # my clips, from gfc-make-sources
  _other/<other_name>/<source>/<clip_key>/<tier>/*.jpg  # personal Other footage
  _personal/<run_id>/                                   # make-sources run records
  _other/<other_name>/contributor_<handle>/<clip_key>/...
  _packs/<pack_id>/          # verbatim contributor pack manifests
  _index/by_sha256.json      # dedupe index
  _stats/handoff_sizes.jsonl # local size tracking (D25)
```

## Raw clips — collection layout (`data/raw/`)

**Game first, then source.** Fill one game at a time; friends who only play one title drop into that game’s folder. **Do not rename files.**

```text
data/raw/
  <Game>/
    <source>/
      anything.mp4
      another_clip.mkv
  _other/
    <other_name>/
      <source>/
        anything.mp4
```

### Exact game folder names (top level under `raw/`)

- `Valorant`
- `League_of_Legends`
- `CS2`
- `Minecraft`
- `Overwatch_2`
- `Marvel_Rivals`

### Examples

```text
data/raw/
  League_of_Legends/
    edison/
      ranked_01.mp4
    friend_alex/
      customs_01.mp4
  Overwatch_2/
    edison/
      qp_01.mp4
  Marvel_Rivals/
    edison/
      qp_02.mp4
    friend_alex/
      ranked_03.mp4
  Valorant/
    edison/
      VALORANT_replay_....mp4
```

`<source>` ≈ channel for the ~1/15 cap (you, a friend, a streamer name, etc.). Friends' clips placed by `gfc-sort-clips` use a `friend_<handle>` source name (for example `friend_alex`); derive and the splitter treat `friend_*` as `contributor`. Pair a friend's raw source with their kit packs through `source_groups` in `config/split.json`.

### Clip sorter sessions (`data/sorting/`)

```text
data/sorting/<session>/
  decisions.csv
  sheets/<quick_id>.jpg
  apply_report.json
  apply_report.csv
```

`<session>` defaults to `<folder name>_<source>`. Contact sheets and decisions live here; apply copies labelled clips into `data/raw/` and moves trash into `<input folder>/_archive/`.

### Collection rules

| Rule | Detail |
|---|---|
| Path | `data/raw/<Game>/<source>/<file>` |
| Other path | `data/raw/_other/<other_name>/<source>/<file>`; `<other_name>` is normalised content metadata, not a class |
| Rename files? | **No** — keep original names |
| Labels | Game = `<Game>` folder; source/channel = `<source>` folder |
| Files | Prefer `.mp4`; other common containers OK |
| Priority | Fill **League_of_Legends**, **Overwatch_2**, **Marvel_Rivals** first |
| Holdout | Later, some sources are frozen as personal test — don’t use them for tuning |

### Later: normalize script (not built yet)

A future script can walk `data/raw/**`, read game + source from the **filepath**, and **copy** videos into whatever tooling layout we want. Collection stays drag-and-drop; normalization is a separate step.

Batch extract reads game + source from the catalog (paths under `raw/`) and writes under `frames/<Game>/<source>/<stem>/`. Single-clip extract still accepts `--game` by hand.

## Derived frames (`data/frames/`)

Training frames, written by `gfc-derive-frames` ([spec](roadmap/tools/derive-frames.md)), mirror `frame_sources/`:

```text
data/frames/
  <Game>/<source>/<clip_key>/full/<clip_key>_full_b000012.jpg
  <Game>/<source>/<clip_key>/crf45/<clip_key>_crf45_b000012.jpg
  _other/<other_name>/<source>/<clip_key>/full/<clip_key>_full_b000012.jpg
```

Outputs of the single-clip debugging tools (extract / clean / quality) use this pattern:

```text
data/frames/
  <run_or_video_id>/                 # extractor output + frames_manifest.*
  <run_or_video_id>_cleaned/         # cleaner kept/ + rejects
  <run_or_video_id>_quality/         # quality encoder (D04)
    full/                            # ops
    low/                             # ops = CRF 45
    medium/                          # optional; docs/reference CRF 38 only
```

Batch runs can mirror game/source:

```text
data/frames/
  League_of_Legends/
    edison/
      ranked_01/
        ...
```

## Manifests (`data/manifests/`)

CSV + JSON side by side; paths inside are relative to `data/`.

```text
data/manifests/
  clips.csv / clips.json            # gfc-catalog-clips (interim path)
  clips_index.csv                   # gfc-derive-frames: one row per clip
  slots.csv                         # gfc-derive-frames: one row per slot
  quarantine.csv                    # optional hand list of slots to drop
  slots_clean.csv                   # gfc-clean-frames --slots
  clean_summary.json
  splits/<split_id>/
    train.csv  val.csv  test_session.csv  test_source.csv
    ledger.csv  sessions.csv  counts.csv  sources.csv
    unused.csv  reassigned.csv  summary.json  freeze.json
    licenses.json  licenses.md      # public sources used by this split
    report/                         # gfc-evaluate --data-report
```

## Runs (`data/runs/`)

```text
data/runs/
  baseline/<run_id>/                # gfc-train-baseline
  cnn/<run_id>/                     # gfc-train-cnn
    eval/<split>/                   # gfc-evaluate
  compare/<runA>__<runB>/
  holdout_access.jsonl              # every evaluation of a test split
```

## Game name ↔ `--game` flag

| Folder | `--game` value |
|---|---|
| `Valorant` | `Valorant` |
| `League_of_Legends` | `League_of_Legends` |
| `CS2` | `CS2` |
| `Minecraft` | `Minecraft` |
| `Overwatch_2` | `Overwatch_2` |
| `Marvel_Rivals` | `Marvel_Rivals` |

## Volume reminder

Target ~**2,000–3,000 frames/game** @ 1 frame / 5 s ≈ **~3–5 hours** of footage per game after cleaning buffer. Cap any one `<source>` at ~**1/15** of that game’s frames.
