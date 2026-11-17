# Pipeline optimizations

Special speed / resource wins that beat the straightforward approach for this project’s data tools.

**Rules**

- Agents must **ask for approval and review** before adding or changing any entry (see skill `pipeline-optimizations`).
- Record only optimizations that are **non-obvious and significant** — not “we used the normal efficient path.”
- Prefer measured gains (wall time, memory, disk) over guesses.
- Newest entry first within each section.

**Not an optimization (example):** single-pass ffmpeg `fps=1/5` + scale for extract. That is the default-correct streaming path, not a special trick.

---

## Extract / batch

*(none yet)*

## Clean

*(none yet)*

## Quality encode

*(none yet)*

## Catalog / other

*(none yet)*

---

## Related

- [pipeline-timing.md](pipeline-timing.md) — measured rates for estimates
- [pipeline-status.md](pipeline-status.md) — what’s built
- Skill: `pipeline-optimizations` (under edutil project skills)
