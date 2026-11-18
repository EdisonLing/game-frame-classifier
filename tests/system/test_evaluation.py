"""System tests for gfc-evaluate with fake predictors."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from game_frame_classifier.evaluation import (
    LABELS,
    clear_predictor_registry,
    compare_runs,
    evaluate_run,
    main,
    register_predictor_loader,
    write_data_report,
)
from tests.helpers.loader_fixtures import build_split_fixture


@pytest.fixture(autouse=True)
def _clear_registry():
    clear_predictor_registry()
    yield
    clear_predictor_registry()


class AlwaysRight:
    labels = LABELS

    def predict_proba(self, rows, data_root, tier_mode="assigned"):
        out = np.zeros((len(rows), len(LABELS)), dtype=np.float64)
        for i, r in enumerate(rows):
            out[i, r.label] = 1.0
        return out


class AlwaysClass0:
    labels = LABELS

    def predict_proba(self, rows, data_root, tier_mode="assigned"):
        out = np.zeros((len(rows), len(LABELS)), dtype=np.float64)
        out[:, 0] = 1.0
        return out


class PathDependent:
    """Predicts class 0 on full tier, class 1 on low tier."""

    labels = LABELS

    def predict_proba(self, rows, data_root, tier_mode="assigned"):
        out = np.zeros((len(rows), len(LABELS)), dtype=np.float64)
        for i, r in enumerate(rows):
            if tier_mode == "full":
                out[i, 0] = 1.0
            elif tier_mode == "low":
                out[i, 1] = 1.0
            else:
                # assigned: follow row.tier
                out[i, 0 if r.tier == "full" else 1] = 1.0
        return out


def _write_run(run_dir: Path, split_dir: Path, *, model_type: str = "fake") -> dict:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_dir.name,
        "model_type": model_type,
        "labels": list(LABELS),
        "split_dir": str(split_dir.resolve()),
        "split_id": split_dir.name,
        "split_hashes": {
            "train": "a" * 64,
            "val": "b" * 64,
            "test_session": "c" * 64,
            "test_source": "d" * 64,
        },
    }
    (run_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _write_clips_index(data_root: Path, rows: list[dict], *, encoders: dict[str, str] | None = None) -> None:
    encoders = encoders or {}
    path = data_root / "manifests" / "clips_index.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({r["clip_key"] for r in rows})
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["clip_key", "game", "source", "low_encoder", "public_examples_ok"],
        )
        writer.writeheader()
        for key in keys:
            writer.writerow(
                {
                    "clip_key": key,
                    "game": "Valorant",
                    "source": "tester",
                    "low_encoder": encoders.get(key, "libx264"),
                    "public_examples_ok": "true",
                }
            )


def test_system_always_right_writes_files(tmp_path):
    pytest.importorskip("matplotlib")
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=1, splits=("val",))
    with open(split_dir / "val.csv", encoding="utf-8", newline="") as f:
        row_dicts = list(csv.DictReader(f))
    _write_clips_index(data_root, row_dicts)

    run_dir = tmp_path / "runs" / "fake" / "always_right"
    _write_run(run_dir, split_dir)
    register_predictor_loader("fake", lambda _p: AlwaysRight())
    out = evaluate_run(run_dir, "val", data_root=data_root, examples=4)
    assert (out / "predictions.csv").is_file()
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["accuracy"] == 1.0
    assert metrics["macro_f1"] == pytest.approx(1.0)
    assert metrics["n"] == 6
    conf = out / "confusion.png"
    ex = out / "examples.png"
    assert conf.is_file() and conf.stat().st_size > 0
    assert ex.is_file() and ex.stat().st_size > 0


def test_system_always_one_class(tmp_path):
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=1, splits=("val",))
    run_dir = tmp_path / "runs" / "fake" / "class0"
    _write_run(run_dir, split_dir)
    register_predictor_loader("fake", lambda _p: AlwaysClass0())
    out = evaluate_run(run_dir, "val", data_root=data_root)
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    # Only Valorant rows are correct (1 of 6)
    assert metrics["accuracy"] == pytest.approx(1 / 6)
    assert metrics["per_class"]["Valorant"]["recall"] == pytest.approx(1.0)


def test_tier_diagnostic_flip_rate(tmp_path):
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=1, splits=("val",))
    run_dir = tmp_path / "runs" / "fake" / "pathdep"
    _write_run(run_dir, split_dir)
    register_predictor_loader("fake", lambda _p: PathDependent())
    out = evaluate_run(
        run_dir, "val", data_root=data_root, tier_diagnostic=True
    )
    diag = json.loads((out / "tier_diagnostic.json").read_text(encoding="utf-8"))
    assert diag["n_paired"] == 6
    assert diag["n_skipped_quick"] == 0
    assert diag["flip_rate"] == pytest.approx(1.0)


def test_compare_two_runs(tmp_path):
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=1, splits=("val",))
    run_a = tmp_path / "runs" / "fake" / "runA"
    run_b = tmp_path / "runs" / "fake" / "runB"
    _write_run(run_a, split_dir)
    _write_run(run_b, split_dir)
    register_predictor_loader("fake", lambda p: AlwaysRight() if p.name == "runA" else AlwaysClass0())
    evaluate_run(run_a, "val", data_root=data_root)
    evaluate_run(run_b, "val", data_root=data_root)
    out = compare_runs(run_a, run_b, "val", data_root=data_root)
    assert (out / "val.csv").is_file()
    assert (out / "val.md").is_file()
    text = (out / "val.md").read_text(encoding="utf-8")
    assert "accuracy" in text
    assert "runA" in text or "runB" in str(out)


def test_data_report_writes_figures(tmp_path):
    pytest.importorskip("matplotlib")
    data_root, split_dir = build_split_fixture(
        tmp_path, n_per_game=1, splits=("train", "val")
    )
    # counts.csv as splitter writes
    counts_path = split_dir / "counts.csv"
    with open(counts_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "game",
                "split",
                "slots",
                "slots_full",
                "slots_low",
                "slots_quick",
                "clips",
                "sessions",
                "sources",
            ],
        )
        writer.writeheader()
        for game in LABELS:
            for split in ("train", "val"):
                writer.writerow(
                    {
                        "game": game,
                        "split": split,
                        "slots": 1,
                        "slots_full": 1,
                        "slots_low": 0,
                        "slots_quick": 0,
                        "clips": 1,
                        "sessions": 1,
                        "sources": 1,
                    }
                )
    out = write_data_report(split_dir, data_root=data_root)
    assert (out / "class_counts.png").is_file()
    assert (out / "class_counts.png").stat().st_size > 0
    assert (out / "example_frames.png").is_file()
    assert (out / "example_frames.png").stat().st_size > 0


def test_cli_evaluate(tmp_path):
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=1, splits=("val",))
    run_dir = tmp_path / "runs" / "fake" / "cli"
    _write_run(run_dir, split_dir)
    register_predictor_loader("fake", lambda _p: AlwaysRight())
    rc = main(
        [
            "--run",
            str(run_dir),
            "--split",
            "val",
            "--data-root",
            str(data_root),
        ]
    )
    assert rc == 0
    assert (run_dir / "eval" / "val" / "metrics.json").is_file()
