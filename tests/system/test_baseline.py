"""System tests for gfc-train-baseline on synthetic splits."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("sklearn")
pytest.importorskip("joblib")

from game_frame_classifier.baseline import load_baseline_predictor, load_config, main, train_baseline
from game_frame_classifier.split_manifest import load_split
from game_frame_classifier.sourcing.labels import GAMES
from tests.helpers.loader_fixtures import (
    make_slot_dict,
    write_frame_jpeg,
    write_split_csv,
    write_summary,
)

# Three clearly different palettes standing in for three games.
_COLOURS = {
    "Valorant": (220, 30, 30),
    "Minecraft": (30, 200, 40),
    "CS2": (40, 40, 210),
}
_GAMES3 = tuple(_COLOURS.keys())


def _build_colour_split(root: Path, *, n_per_game: int = 8) -> tuple[Path, Path]:
    data_root = Path(root) / "data"
    split_dir = data_root / "manifests" / "splits" / "v1"
    split_dir.mkdir(parents=True, exist_ok=True)
    by_split: dict[str, list[dict]] = {"train": [], "val": []}
    bucket = 0
    for split in ("train", "val"):
        for game in _GAMES3:
            label = GAMES.index(game)
            for j in range(n_per_game):
                tier = "full" if (bucket % 2) == 0 else "crf45"
                row = make_slot_dict(
                    game=game,
                    label=label,
                    source="src_a",
                    session=f"src_a:{game}:s001",
                    split=split,
                    tier=tier,
                    clip_key=f"c{label:012x}",
                    bucket=bucket,
                    target_time_s=float(bucket),
                )
                colour = _COLOURS[game]
                for rel in (row["path_full"], row["path_low"]):
                    write_frame_jpeg(data_root / Path(*rel.split("/")), colour=colour)
                by_split[split].append(row)
                bucket += 1
    for name, rows in by_split.items():
        write_split_csv(split_dir / f"{name}.csv", rows)
    write_summary(split_dir)
    return data_root, split_dir


def _required_run_files(run_dir: Path) -> list[Path]:
    return [
        run_dir / "run.json",
        run_dir / "model.joblib",
        run_dir / "c_search.csv",
        run_dir / "features_train.npy",
        run_dir / "features_val.npy",
    ]


def test_cli_beats_chance_and_writes_run_folder(tmp_path):
    data_root, split_dir = _build_colour_split(tmp_path, n_per_game=8)
    run_dir = tmp_path / "runs" / "baseline" / "smoke1"
    code = main(
        [
            "--split-dir",
            str(split_dir),
            "--data-root",
            str(data_root),
            "--config",
            "config/baseline.json",
            "--out",
            str(run_dir),
        ]
    )
    assert code == 0
    for path in _required_run_files(run_dir):
        assert path.is_file(), path
    meta = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    assert meta["model_type"] == "baseline"
    assert meta["labels"] == list(GAMES)
    assert Path(meta["split_dir"]) == split_dir.resolve()
    assert meta["split_id"] == "v1"
    assert "train" in meta["split_hashes"]
    assert "chosen_C" in meta
    assert meta["val_accuracy"] > 1.0 / 3.0
    assert meta["val_macro_f1"] > 1.0 / 6.0

    predictor = load_baseline_predictor(run_dir)
    val_rows = load_split(split_dir, "val")
    proba = predictor.predict_proba(val_rows, data_root)
    assert proba.shape == (len(val_rows), 6)
    preds = proba.argmax(axis=1)
    y = np.asarray([r.label for r in val_rows])
    assert float(np.mean(preds == y)) == pytest.approx(meta["val_accuracy"], abs=1e-6)


def test_same_seed_identical_c_search(tmp_path):
    data_root, split_dir = _build_colour_split(tmp_path, n_per_game=6)
    config = load_config(Path("config/baseline.json"))
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    train_baseline(split_dir=split_dir, data_root=data_root, config=config, run_dir=run_a)
    train_baseline(split_dir=split_dir, data_root=data_root, config=config, run_dir=run_b)
    assert (run_a / "c_search.csv").read_text(encoding="utf-8") == (
        run_b / "c_search.csv"
    ).read_text(encoding="utf-8")


def test_evaluation_missing_exits_zero(tmp_path, capsys):
    data_root, split_dir = _build_colour_split(tmp_path, n_per_game=4)
    run_dir = tmp_path / "run_eval_msg"
    code = main(
        [
            "--split-dir",
            str(split_dir),
            "--data-root",
            str(data_root),
            "--config",
            "config/baseline.json",
            "--out",
            str(run_dir),
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "evaluation not available yet" in out
