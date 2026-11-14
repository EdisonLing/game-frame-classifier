# Source acquisition

**Stage:** 3 — Scale volume  
**Status:** planned (after Stage 1–2 tools work on personal clips)  
**Back to:** [ROADMAP.md](../ROADMAP.md)

## What it does (high level)

Collects additional gameplay video from terms-permitted public sources (and named fallback datasets), registers them in the [clip catalog](clip-catalog.md), then reuses extract → clean → split.

## Why we need it

Personal clips are perfect for **building** the pipeline, but the progress report wants **all or most** of the data, and the proposal targets **~2,000–3,000 frames per game** with **15+ channels** and per-channel caps. Volume is a separate stage so we don’t collect thousands of files before the tools work.

## Inputs / outputs

| | |
|---|---|
| **In** | Source list (URLs / dataset ids) + permission notes |
| **Out** | Files under `data/raw/<Game>/...` per [data-layout.md](../../data-layout.md); later catalog rows |

**Filing:** follow [docs/data-layout.md](../../data-layout.md) — `data/raw/<Game>/<source>/` (drag-and-drop; no rename).

## Known design choices (from proposal)

- Primary: personal + friends’ clips; public Twitch/YouTube/etc. **only where terms permit**
- Fallbacks: **Gamed** (Valorant, CS2), **Gameplay Images** / **MineRL** (Minecraft)
- LoL / OW2 / Marvel Rivals: no full public frame dataset found → esports / popular streamers where allowed
- Cap any one channel (incl. pro or personal) at ≈ **1/15** of that game’s frames
- Frames local, non-commercial, never redistributed
- Facecams / usernames / chat never used as labels

## Undecided / blank

- **Stack / download tooling:** —
- **Exact channel list per game**
- **Confirmed sources for LoL / OW2 / Marvel Rivals:** tracked as **D12** in [design-decisions.md](../../design-decisions.md) (TA deduction; name concrete sources)
- **How to document terms checks** for the report
- **Architecture:** —

**Collection priority (TA tip, operational):** personal clips first for the three games with no public fallback — still an open item under D12, not a locked source list.

## Implementation notes

- Prefer recording *source → terms note → date accessed* in the catalog for the ethics / data section

## Acceptance checks

- [ ] New sources flow through existing extract/clean tools unchanged
- [ ] Per-game and per-channel counts reportable
- [ ] Channel caps enforceable (or at least measurable)
- [ ] Written plan for final never-seen test videos (rubric requirement)

## Testing

| Kind | Cases |
|---|---|
| **Unit** | Channel-cap math: given counts, which clips would violate ≈1/15; catalog row built from a source record has required ethics fields (source, terms note, date) |
| **System** | Optional: dry-run register of a **local** file as if acquired → appears in catalog and extractable; do **not** hit network in CI |
| **Manual / process** | Checklist: named source for LoL/OW2/Rivals (D12); per-game frames/videos/channels table for progress report |

**How to run:** `pytest tests/unit/test_source_acquisition.py` (system tests stay offline)

## Ties to proposal

Data Processing — Sources; Ethical Considerations — copyright / platform terms / privacy.
