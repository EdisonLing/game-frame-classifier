# Official data layout

Canonical folder scheme for gameplay clips and derived frames.  
Raw media stays **local** (`data/raw/`, `data/frames/`, `data/manifests/` are gitignored).

## Top level

```text
data/
  README.md          # short pointer (tracked)
  raw/               # source videos/clips (local only)
  frames/            # extracted / cleaned / quality copies (local only)
  manifests/         # optional shared catalogs & split lists (local only)
```

## Raw clips — collection layout (use this now)

**Goal:** drag-and-drop. No renaming of video files.

```text
data/raw/
  <Game>/
    <source>/          # one folder per person, friend, channel, or dump bucket
      original_name.mp4
      Recording 003.mp4
      ...
```

### Game folder names (exact)

```text
data/raw/
  Valorant/
  League_of_Legends/
  CS2/
  Minecraft/
  Overwatch_2/
  Marvel_Rivals/
```

### Source folders

- **One folder per source** (you, a friend, a streamer, “medal_exports”, etc.).
- Name it whatever is easy (`edison`, `alex`, `twitch_caps`) — **no** required `person__session` spelling while collecting.
- **Keep original filenames.** Drop files straight in.

Examples:

```text
data/raw/League_of_Legends/
  edison/
    VALORANT_replay_....mp4          # wrong game? don't — put under the right Game/
    clip from medal.mp4
  friend_alex/
    Desktop 2026.11.10 - 21.03.mp4
data/raw/Overwatch_2/
  edison/
    overwatch_session.mp4
```

**Rules (collection)**

| Rule | Detail |
|---|---|
| Game folder | Must be one of the six names above → becomes the label |
| Source folder | One per origin; used later for ~1/15 caps and splits |
| Files | Keep original names; prefer `.mp4` |
| Priority | Fill **League_of_Legends**, **Overwatch_2**, **Marvel_Rivals** first |

### Flat game folder (temporary)

OK only for a quick dump; move into `<source>/` before mid-project splits:

```text
data/raw/Valorant/
  clip1.mp4
```

## Raw clips — canonical layout (later)

A **future normalize script** will walk `data/raw/<Game>/<source>/...`, read the filepath, and **copy** (not destroy) into a stricter tree for training IDs, e.g.:

```text
data/raw_canonical/
  <Game>/
    <source>__<session_or_stem>/
      <stable_name>.mp4
```

Until that script exists, **collect only in the collection layout above.** Extract/clean can still run on collection paths.

## Derived frames (`data/frames/`)

```text
data/frames/
  <run_or_video_id>/                 # extractor output + frames_manifest.*
  <run_or_video_id>_cleaned/         # cleaner kept/ + rejects
  <run_or_video_id>_quality/         # quality encoder
    full/ | medium/ | low/
```

Or group by game/source to mirror raw:

```text
data/frames/
  League_of_Legends/
    friend_alex/
      ...
```

## Manifests (`data/manifests/`)

```text
data/manifests/
  clips.csv                 # future catalog (path → game, source, …)
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

Target ~**2,000–3,000 frames/game** @ 1 frame / 5 s ≈ **~3–5 hours** of footage per game after cleaning buffer. Cap any one **source** folder at ~**1/15** of that game’s frames.
