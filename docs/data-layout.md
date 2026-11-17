# Official data layout

Canonical folder scheme for gameplay clips and derived frames.  
Raw media stays **local** (`data/raw/`, `data/frames/`, `data/manifests/` are gitignored).

## Top level

```text
data/
  README.md          # short pointer (tracked)
  raw/               # source videos/clips (local only) — collect here
  frame_sources/     # native-res stills per clip (local only) — D26; from gfc-ingest-pack / future gfc-make-sources
  frames/            # derived / cleaned / quality copies (local only)
  manifests/         # optional shared catalogs & split lists (local only)
```

## Frame sources (`data/frame_sources/`)

Native-resolution JPEG stills used as the shared source of truth for personal and friend footage (D26). Layout and ingest rules: [tools/ingest-pack.md](roadmap/tools/ingest-pack.md).

```text
data/frame_sources/
  <Game>/contributor_<handle>/<clip_key>/<tier>/*.jpg
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

`<source>` ≈ channel for the ~1/15 cap (you, a friend, a streamer name, etc.).

### Collection rules

| Rule | Detail |
|---|---|
| Path | `data/raw/<Game>/<source>/<file>` |
| Rename files? | **No** — keep original names |
| Labels | Game = `<Game>` folder; source/channel = `<source>` folder |
| Files | Prefer `.mp4`; other common containers OK |
| Priority | Fill **League_of_Legends**, **Overwatch_2**, **Marvel_Rivals** first |
| Holdout | Later, some sources are frozen as personal test — don’t use them for tuning |

### Later: normalize script (not built yet)

A future script can walk `data/raw/**`, read game + source from the **filepath**, and **copy** videos into whatever tooling layout we want. Collection stays drag-and-drop; normalization is a separate step.

Batch extract reads game + source from the catalog (paths under `raw/`) and writes under `frames/<Game>/<source>/<stem>/`. Single-clip extract still accepts `--game` by hand.

## Derived frames (`data/frames/`)

Outputs from extract / clean / quality tools. Suggested pattern:

```text
data/frames/
  <run_or_video_id>/                 # extractor output + frames_manifest.*
  <run_or_video_id>_cleaned/         # cleaner kept/ + rejects
  <run_or_video_id>_quality/         # quality encoder
    full/
    medium/
    low/
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

Optional shared tables (clip catalog, train/val/test lists):

```text
data/manifests/
  clips.csv                 # from gfc-catalog-clips (also clips.json)
  clips.json
  splits/
    train.csv
    val.csv
    test.csv
    personal_holdout.csv
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
