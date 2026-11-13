# game-frame-classifier
CNN that identifies which game a gameplay frame is from, intended use cases include auto-tagging clips and giving % breakdown of games played in longer clips or VODs.

## Quick start (frame extractor)

```bash
pip install -e ".[dev]"
gfc-extract-frames path\to\clip.mp4 -o data/frames/my_clip --game Valorant
gfc-clean-frames data/frames/my_clip/frames_manifest.csv -o data/frames/my_clip_cleaned
# audit pipeline:
gfc-extract-frames path\to\clip.mp4 -o data/frames/my_clip --game Valorant --debug
gfc-clean-frames data/frames/my_clip/frames_manifest.csv -o data/frames/my_clip_cleaned --debug
pytest -m "not personal"   # CI-safe
pytest -m personal         # local clip / GFC_TEST_VIDEO smokes
```

Tools are chained by **manifests** (extract → clean). A pipeline manager is optional later — not required yet.

## Docs
- [Docs index](docs/INDEX.md)
- [Project roadmap](docs/roadmap/ROADMAP.md) — stages, tools, progress plan
- [Design decisions](docs/design-decisions.md) — incremental adopt/reject log
