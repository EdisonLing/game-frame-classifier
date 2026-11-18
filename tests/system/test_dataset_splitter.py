"""System tests for the dataset splitter command and written manifests."""

from __future__ import annotations

import csv
import json

from game_frame_classifier.dataset_splitter import main
from tests.helpers.splitter_fixtures import write_split_config, write_split_inputs


def test_cli_writes_disjoint_manifests_counts_and_quick_tiers(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [
        {"source": "a", "recorded_start_utc": f"2026-01-{day:02d}T00:00:00Z"}
        for day in range(1, 7)
    ]
    write_split_inputs(data, clips, slots_per_clip=3)
    slots_path = data / "manifests" / "slots_clean.csv"
    rows = list(csv.DictReader(slots_path.open(encoding="utf-8")))
    rows[0]["path_low"] = ""
    with slots_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    config = write_split_config(tmp_path / "split.json")
    assert main(["--data-root", str(data), "--config", str(config)]) == 0
    output = data / "manifests" / "splits" / "v1"
    split_rows = {}
    for split in ("train", "val", "test_session", "test_source"):
        with (output / f"{split}.csv").open(encoding="utf-8") as file:
            split_rows[split] = list(csv.DictReader(file))
        assert len(json.loads((output / f"{split}.json").read_text(encoding="utf-8"))) == len(split_rows[split])
    used = [row for rows in split_rows.values() for row in rows]
    assert len({row["slot_id"] for row in used}) == len(used)
    assert len({(row["clip_key"], row["split"]) for row in used}) == len({row["clip_key"] for row in used})
    assert all(row["path"] == (row["path_low"] if row["tier"] == "crf45" else row["path_full"]) for row in used)
    assert next(row for row in used if not row["path_low"])["tier"] == "full"
    counts = list(csv.DictReader((output / "counts.csv").open(encoding="utf-8")))
    total = next(row for row in counts if row["game"] == "ALL" and row["split"] == "ALL")
    assert int(total["slots"]) == len(used)
    assert int(total["slots_quick"]) == 1
    assert main(["--data-root", str(data), "--config", str(config), "--freeze"]) == 1
    write_split_config(config, test_design="held-out sources will be selected before reporting")
    assert main(["--data-root", str(data), "--config", str(config), "--freeze"]) == 0
    assert (output / "freeze.json").is_file()
    assert main(["--data-root", str(data), "--config", str(config), "--plan"]) == 0


def test_cli_source_groups_cap_and_ledger_stable(tmp_path) -> None:
    data = tmp_path / "data"
    clips = [
        {"source": src, "recorded_start_utc": f"2026-01-{day:02d}T00:00:00Z"}
        for src, days in (("tester", range(1, 9)), ("tester_oldpc", range(1, 9)), ("friend", range(1, 5)))
        for day in days
    ]
    write_split_inputs(data, clips, slots_per_clip=4)
    config = write_split_config(
        tmp_path / "split.json",
        max_source_share=0.5,
        source_groups={"person_a": ["tester", "tester_oldpc"]},
    )
    assert main(["--data-root", str(data), "--config", str(config)]) == 0
    output = data / "manifests" / "splits" / "v1"
    train = list(csv.DictReader((output / "train.csv").open(encoding="utf-8")))
    person_a = sum(row["source"] in {"tester", "tester_oldpc"} for row in train)
    friend = sum(row["source"] == "friend" for row in train)
    assert person_a <= friend or person_a / max(len(train), 1) <= 0.5 + 1e-9
    ledger_before = (output / "ledger.csv").read_text(encoding="utf-8")
    assert main(["--data-root", str(data), "--config", str(config)]) == 0
    assert (output / "ledger.csv").read_text(encoding="utf-8") == ledger_before
    sources = list(csv.DictReader((output / "sources.csv").open(encoding="utf-8")))
    assert {row["group"] for row in sources if row["source"] in {"tester", "tester_oldpc"}} == {"person_a"}
    counts = list(csv.DictReader((output / "counts.csv").open(encoding="utf-8")))
    assert "groups" in counts[0]
