# Docs index

| Doc | What it is |
|---|---|
| [training-pipeline.md](training-pipeline.md) | How the tools connect from clips to model results: step order, files passed between them, shared conventions, open decisions |
| [results.md](results.md) | Model results by run: data snapshot in general terms, settings, val metrics |
| [amd-gpu-setup.md](amd-gpu-setup.md) | Training on a Radeon RX 9000 GPU under Windows: requirements, install, checks, troubleshooting |
| [pipeline-status.md](pipeline-status.md) | What’s done vs missing (interim batch vs D26 frame_sources) |
| [pipeline-timing.md](pipeline-timing.md) | Measured wall-time rates (extract sec per video-minute) |
| [handoff-sizes.md](handoff-sizes.md) | Contributor pack size vs recordings and processing time, by resolution |
| [pipeline-optimizations.md](pipeline-optimizations.md) | Special pipeline speedups (approval required to add) |
| [examples/](examples/) | **Published** doc figures only (e.g. README quality ladder) |
| `examples-library/` (local, gitignored) | Full UI-reference + CRF catalog; promote into `examples/` when a doc embeds a file |
| `readme-drafts/` (local, gitignored) | Per-section README scaffolds; short snippets go in root `README.md` until polished |
| [roadmap/ROADMAP.md](roadmap/ROADMAP.md) | Project stages, tool list, testing convention |
| [data-layout.md](data-layout.md) | Official `data/raw` / frames / `frame_sources` / manifests folder scheme |
| [design-decisions.md](design-decisions.md) | Incremental adopt/reject log |
| [research/public-game-datasets.md](research/public-game-datasets.md) | Public Minecraft / OW2 / Marvel Rivals dataset research (rights + pipeline fit; no acquisition) |
| [research/public-dataset-use-plan.md](research/public-dataset-use-plan.md) | Draft course-use justification, freeness ranking, attribution ledger / removal plan |
| [roadmap/tools/frame-export-kit.md](roadmap/tools/frame-export-kit.md) | Frame Export Kit (contributor clips → zip) |
| [roadmap/tools/ingest-pack.md](roadmap/tools/ingest-pack.md) | Ingest contributor zip → `frame_sources/` |
| [roadmap/tools/](roadmap/tools/) | One detail page per tool |
