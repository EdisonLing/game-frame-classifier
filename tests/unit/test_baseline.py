"""Unit tests for the colour-histogram baseline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("sklearn")
pytest.importorskip("joblib")

from game_frame_classifier.baseline import (
    histogram_features,
    load_baseline_predictor,
    load_config,
    main,
    train_baseline,
)
from game_frame_classifier.split_manifest import LABELS, load_split
from game_frame_classifier.sourcing.labels import GAMES
from tests.helpers.loader_fixtures import build_split_fixture


def _solid(colour: tuple[int, int, int]) -> np.ndarray:
    return np.full((144, 256, 3), colour, dtype=np.uint8)


def test_histogram_length_and_channel_sums():
    feats = histogram_features(_solid((10, 20, 30)), bins=16)
    assert feats.shape == (48,)
    assert feats.dtype == np.float32
    assert abs(feats[0:16].sum() - 1.0) < 1e-6
    assert abs(feats[16:32].sum() - 1.0) < 1e-6
    assert abs(feats[32:48].sum() - 1.0) < 1e-6


def test_solid_colour_mass_in_expected_bin():
    # Bin width 16: value 40 -> bin 2; 80 -> bin 5; 120 -> bin 7.
    feats = histogram_features(_solid((40, 80, 120)), bins=16)
    assert feats[2] == pytest.approx(1.0)
    assert feats[16 + 5] == pytest.approx(1.0)
    assert feats[32 + 7] == pytest.approx(1.0)


def test_value_255_in_last_bin():
    feats = histogram_features(_solid((255, 255, 255)), bins=16)
    assert feats[15] == pytest.approx(1.0)
    assert feats[31] == pytest.approx(1.0)
    assert feats[47] == pytest.approx(1.0)


def test_predict_proba_shape_and_row_sums(tmp_path):
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=2, splits=("train", "val"))
    config = load_config(Path("config/baseline.json"))
    run_dir = tmp_path / "run"
    train_baseline(
        split_dir=split_dir,
        data_root=data_root,
        config=config,
        run_dir=run_dir,
    )
    predictor = load_baseline_predictor(run_dir)
    rows = load_split(split_dir, "val")
    proba = predictor.predict_proba(rows, data_root)
    assert proba.shape == (len(rows), 6)
    assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-6)
    assert predictor.labels == LABELS == GAMES


def test_load_baseline_predictor_round_trip(tmp_path):
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=2, splits=("train", "val"))
    config = load_config(Path("config/baseline.json"))
    run_dir = tmp_path / "run_rt"
    train_baseline(
        split_dir=split_dir,
        data_root=data_root,
        config=config,
        run_dir=run_dir,
    )
    rows = load_split(split_dir, "val")
    import joblib

    pipe = joblib.load(run_dir / "model.joblib")
    from game_frame_classifier.baseline import _features_for_rows

    x = _features_for_rows(rows, data_root, int(config["bins"]))
    expected = pipe.predict_proba(x)
    loaded = load_baseline_predictor(run_dir)
    got = loaded.predict_proba(rows, data_root)
    # When all six classes appear in train, columns match LABELS order.
    assert np.allclose(got, expected, atol=1e-6)


def test_tag_in_run_id(tmp_path, capsys, monkeypatch):
    import sys

    # Simulate a checkout without evaluation.py: training still succeeds and says what to run.
    monkeypatch.setitem(sys.modules, "game_frame_classifier.evaluation", None)
    import game_frame_classifier

    monkeypatch.delattr(game_frame_classifier, "evaluation", raising=False)
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=1, splits=("train", "val"))
    out = tmp_path / "runs" / "baseline" / "placeholder"
    code = main(
        [
            "--split-dir",
            str(split_dir),
            "--data-root",
            str(data_root),
            "--config",
            "config/baseline.json",
            "--tag",
            "bins16",
            "--out",
            str(tmp_path / "runs" / "baseline" / "20260101-000000_bins16"),
        ]
    )
    assert code == 0
    meta = json.loads(
        (tmp_path / "runs" / "baseline" / "20260101-000000_bins16" / "run.json").read_text(
            encoding="utf-8"
        )
    )
    assert meta["run_id"].endswith("_bins16")
    assert meta["tag"] == "bins16"
    assert "evaluation not available yet" in capsys.readouterr().out


def test_c_tie_picks_smaller(tmp_path):
    """When every C scores the same, the smallest C is kept."""
    from game_frame_classifier.baseline import _search_c

    # Two well-separated points; any C that fits will get perfect val F1.
    x_train = np.array([[0.0] * 48, [1.0] * 48], dtype=np.float32)
    y_train = np.array([0, 1], dtype=np.int64)
    x_val = x_train.copy()
    y_val = y_train.copy()
    chosen, rows, _ = _search_c(
        x_train,
        y_train,
        x_val,
        y_val,
        [10.0, 0.01, 1.0],
        max_iter=2000,
        class_weight="balanced",
        seed=360,
    )
    assert chosen == 0.01
    assert [r["C"] for r in rows] == [0.01, 1.0, 10.0]


def test_never_opens_test_split(tmp_path, monkeypatch):
    data_root, split_dir = build_split_fixture(
        tmp_path, n_per_game=1, splits=("train", "val", "test_session", "test_source")
    )
    config = load_config(Path("config/baseline.json"))
    opened: list[str] = []
    real_load = __import__(
        "game_frame_classifier.split_manifest", fromlist=["load_split"]
    ).load_split

    def tracking_load(split_dir_arg, name, *, allow_test=False):
        opened.append(name)
        return real_load(split_dir_arg, name, allow_test=allow_test)

    monkeypatch.setattr("game_frame_classifier.baseline.load_split", tracking_load)
    train_baseline(
        split_dir=split_dir,
        data_root=data_root,
        config=config,
        run_dir=tmp_path / "run_no_test",
    )
    assert "test_session" not in opened
    assert "test_source" not in opened
    assert opened == ["train", "val"]


def test_end_of_training_evaluation_writes_val_results(tmp_path):
    pytest.importorskip("matplotlib")
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=2, splits=("train", "val"))
    run_dir = tmp_path / "runs" / "baseline" / "r"
    code = main(["--split-dir", str(split_dir), "--data-root", str(data_root),
                 "--config", "config/baseline.json", "--out", str(run_dir)])
    assert code == 0
    metrics = json.loads((run_dir / "eval" / "val" / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["provenance"]["model_type"] == "baseline"
    assert (run_dir / "eval" / "val" / "predictions.csv").is_file()


def test_single_game_train_is_a_clear_error(tmp_path, capsys):
    import csv

    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=2, splits=("train", "val"))
    path = split_dir / "train.csv"
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    keep = [row for row in rows if row["game"] == "Valorant"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(keep)
    code = main(["--split-dir", str(split_dir), "--data-root", str(data_root),
                 "--config", "config/baseline.json", "--out", str(tmp_path / "run")])
    assert code == 2
    assert "at least two games" in capsys.readouterr().err
