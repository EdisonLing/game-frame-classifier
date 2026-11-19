# Scene splitter (`gfc-split-scenes`)

**Stage:** 2 — Data quality  
**Status:** planned (outline; to be specified before building)  
**Back to:** [ROADMAP.md](../ROADMAP.md) · [clip sorter](clip-sorter.md) · [label review](label-review.md) · [YouTube links and content types](clip-link-youtube.md)

## What it would do

Today the clip sorter labels a whole video with one game. Esports VODs and stream recordings mix real gameplay with parts that are not the game: caster desk, player cams, sponsor reads, "be right back" screens, other games. This tool would split such a video into time sections, propose which sections are the game and which are Other, let a person confirm them in a page, and pass the result to the pipeline so each 5-second frame gets the right label (or is left out).

## What stays the game's class

Menus, lobbies, loading screens, scoreboards and the game's own replays stay the game's class (D06): they are frames of that game. "Not the game" means content that is not the game at all, such as broadcast desk, camera shots of people, ads and other games' footage.

## Planned approach

1. **Candidate cuts.** Shot boundaries with ffmpeg's scene score (`select='gt(scene,T)'`) or PySceneDetect, plus long static stretches, on the source video. A section is the span between two cuts, rounded to the 5-second frame buckets the pipeline already uses.
2. **Proposal.** Score every 5-second frame of the video with the trained CNN (as label review does) and average per section: sections whose frames are mostly Other, or mostly low-confidence, are proposed as Other; the rest as the clip's game. Before a model exists for a game, every section starts as the clip's game.
3. **Review page.** An extension of the sorter page: the clip's frames as a timeline strip with the proposed sections coloured; keys to mark a section as the game, Other (with a content name such as `esports_desk`, `player_cam`, `ad`), or unusable; split or merge sections at a frame.
4. **Output.** `data/raw/<Game>/<source>/segments/<file>.csv` with `start_s, end_s, label, other_name, origin` (`proposed` / `confirmed`).
5. **Into the pipeline.** Make-sources records the segment of each frame bucket; derive gives frames in Other sections `game = Other` with the section's content name and leaves unusable ones out. The clip stays one unit for splitting, so its game and Other frames always land in the same split (no leakage).

## Why it matters

- Esports and stream VODs become usable training data without throwing away whole videos or teaching the model that a caster desk is Valorant.
- It gives Other varied, real non-game content (desks, cams, ads) from many people, the gap noted in the results.
- Its confirmed sections are a hand-labelled sample for measuring how often the model calls non-game content a game.

## Depends on

- [Label review](label-review.md) (scoring frames with a trained model, review page patterns).
- [YouTube links and content types](clip-link-youtube.md) (`esports_vod` and `streamer_overlay` clips are the first candidates).

## Open before specifying

- Whether non-game sections train the Other class (with content names) or are only left out.
- Which cut detector, and its threshold, measured on a few labelled VODs.
- Whether short Other sections (under 10 s) are merged into their neighbours.
- How the page handles videos longer than an hour (load the timeline in chunks).
