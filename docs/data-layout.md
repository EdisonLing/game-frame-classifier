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

## Raw clips (`data/raw/`)

**One directory per game**, using these exact names:

```text
data/raw/
  Valorant/
  League_of_Legends/
  CS2/
  Minecraft/
  Overwatch_2/
  Marvel_Rivals/
```

### Recommended: person / session subfolders

Needed for channel caps (~1/15) and video/session-level splits:

```text
data/raw/<Game>/
  <person_or_channel>__<session_id>/
    clip_or_vod.mp4
    ...
```

Examples:

```text
data/raw/League_of_Legends/
  edison__2026-11-10/
    ranked_01.mp4
  friend_alex__session1/
    customs_01.mp4
data/raw/Overwatch_2/
  edison__2026-11-12/
    qp_01.mp4
```

**Rules**

| Rule | Detail |
|---|---|
| Game folder | Must match one of the six names above |
| Session folder | Use `person__session` (double underscore). Person ≈ “channel” for caps |
| Files | Prefer `.mp4`; other common containers OK |
| Labels | Game = parent game folder (no per-frame labelling) |
| Holdout | When splitting later, some `person__session` folders are frozen as personal test — don’t peek for tuning |
| Collection priority | Fill **League_of_Legends**, **Overwatch_2**, **Marvel_Rivals** first (no public fallback) |

### Minimal mode (OK while collecting)

If you’re still dumping files quickly, flat game folders are allowed:

```text
data/raw/Valorant/
  clip1.mp4
  clip2.mp4
```

Move into `person__session/` subfolders before the official split for the mid-project writeup.

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

Batch runs can group by game:

```text
data/frames/
  League_of_Legends/
    edison__2026-11-10/
      ...
```

## Manifests (`data/manifests/`)

Optional shared tables (clip catalog, train/val/test lists) when we outgrow per-run folders:

```text
data/manifests/
  clips.csv                 # future catalog
  splits/
    train.csv
    val.csv
    test.csv
    personal_holdout.csv
```

## Game name ↔ `--game` flag

Use the same spelling when calling tools:

| Folder | `--game` value |
|---|---|
| `Valorant` | `Valorant` |
| `League_of_Legends` | `League_of_Legends` |
| `CS2` | `CS2` |
| `Minecraft` | `Minecraft` |
| `Overwatch_2` | `Overwatch_2` |
| `Marvel_Rivals` | `Marvel_Rivals` |

## Volume reminder

Target ~**2,000–3,000 frames/game** @ 1 frame / 5 s ≈ **~3–5 hours** of footage per game after cleaning buffer. Cap any one `person__session` / channel at ~**1/15** of that game’s frames.
