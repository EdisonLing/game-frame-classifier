# Official data layout

Canonical folder scheme for gameplay clips and derived frames.  
Raw media stays **local** (`data/raw/`, `data/frames/`, `data/manifests/` are gitignored).

## Top level

```text
data/
  README.md          # short pointer (tracked)
  raw/               # source videos/clips (local only) — collect here
  frames/            # extracted / cleaned / quality copies (local only)
  manifests/         # optional shared catalogs & split lists (local only)
```

## Raw clips — collection layout (`data/raw/`)

**Source first, then game.** Drag-and-drop friendly: make a folder for each person/channel, then drop clips into the right game subfolder. **Do not rename files.**

```text
data/raw/
  <source>/
    <Game>/
      anything.mp4
      another_clip.mkv
```

### Exact game folder names

Inside each source, use only these six names:

- `Valorant`
- `League_of_Legends`
- `CS2`
- `Minecraft`
- `Overwatch_2`
- `Marvel_Rivals`

### Examples

```text
data/raw/
  edison/
    League_of_Legends/
      VALORANT_replay_....mp4          # wait — wrong game folder; put Valorant clips under Valorant/
      ranked_01.mp4
    Overwatch_2/
      qp_01.mp4
    Marvel_Rivals/
      qp_02.mp4
  friend_alex/
    League_of_Legends/
      customs_01.mp4
    Marvel_Rivals/
      ranked_03.mp4
```

`<source>` ≈ channel for the ~1/15 cap (you, a friend, a streamer name, etc.).

### Collection rules

| Rule | Detail |
|---|---|
| Path | `data/raw/<source>/<Game>/<file>` |
| Rename files? | **No** — keep original names |
| Labels | Game = `<Game>` folder; source/channel = `<source>` folder |
| Files | Prefer `.mp4`; other common containers OK |
| Priority | Fill **League_of_Legends**, **Overwatch_2**, **Marvel_Rivals** first |
| Holdout | Later, some sources/sessions are frozen as personal test — don’t use them for tuning |

### Later: normalize script (not built yet)

A future script can walk `data/raw/**`, read game + source from the **filepath**, and **copy** (not destroy) videos into whatever tooling layout we want (e.g. flat per-run extract dirs, or `person__session` style). Collection stays messy-friendly; normalization is a separate step.

Until that exists, extract manually with `--game` matching the game folder name.

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

Batch runs can mirror source/game:

```text
data/frames/
  edison/
    League_of_Legends/
      ranked_01/
        ...
```

## Manifests (`data/manifests/`)

Optional shared tables (clip catalog, train/val/test lists):

```text
data/manifests/
  clips.csv                 # future catalog (paths encode source + game)
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
