"""Unit tests for evaluation metrics and guards."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from game_frame_classifier.evaluation import (
    LOOKALIKE,
    _bootstrap_comparison,
    _lookalike_metrics,
    _threshold_at_false_alarm,
    compute_classification_metrics,
    compute_open_set_metrics,
    compute_six_game_metrics,
    evaluate_run,
    register_predictor_loader,
    clear_predictor_registry,
)
from game_frame_classifier.split_manifest import LABELS, SlotRow
from tests.helpers.loader_fixtures import (
    build_split_fixture,
    make_slot_dict,
    materialise_frames,
)


@pytest.fixture(autouse=True)
def _clear_registry():
    clear_predictor_registry()
    yield
    clear_predictor_registry()


def test_class_never_predicted_counts_as_zero_f1():
    # Class 1 has rows but is never predicted: F1 0, included in macro-F1 (not dropped).
    y_true = np.asarray([0, 0, 1, 1], dtype=np.int64)
    y_pred = np.asarray([0, 0, 0, 0], dtype=np.int64)
    m = compute_classification_metrics(y_true, y_pred, labels=LABELS)
    assert m["per_class"][LABELS[1]] == {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 2}
    f1_0 = 2 * 0.5 * 1.0 / 1.5
    assert m["macro_f1"] == pytest.approx((f1_0 + 0.0) / 2)


def test_metrics_hand_built_three_class():
    # 3 classes using first three labels; rest have zero support.
    y_true = np.asarray([0, 0, 1, 1, 2, 2], dtype=np.int64)
    y_pred = np.asarray([0, 1, 1, 1, 2, 0], dtype=np.int64)
    m = compute_classification_metrics(y_true, y_pred, labels=LABELS)
    assert m["n"] == 6
    assert m["accuracy"] == pytest.approx(4 / 6)
    # class 0: tp=1, fp=1 (from true2), fn=1 → P=0.5 R=0.5 F1=0.5
    assert m["per_class"]["Valorant"]["precision"] == pytest.approx(0.5)
    assert m["per_class"]["Valorant"]["recall"] == pytest.approx(0.5)
    assert m["per_class"]["Valorant"]["f1"] == pytest.approx(0.5)
    assert m["per_class"]["Valorant"]["support"] == 2
    # class 1: tp=2, fp=1, fn=0 → P=2/3 R=1 F1=0.8
    assert m["per_class"]["League_of_Legends"]["f1"] == pytest.approx(0.8)
    # zero-support classes are null and excluded from macro-F1
    for g in LABELS[3:]:
        assert m["per_class"][g]["f1"] is None
        assert m["per_class"][g]["support"] == 0
    f1s = [
        m["per_class"][LABELS[0]]["f1"],
        m["per_class"][LABELS[1]]["f1"],
        m["per_class"][LABELS[2]]["f1"],
    ]
    assert m["macro_f1"] == pytest.approx(float(np.mean(f1s)))
    assert m["confusion"][0][0] == 1
    assert m["confusion"][0][1] == 1
    assert m["zero_support_note"]


def test_lookalike_from_known_matrix():
    conf = [[0] * len(LABELS) for _ in range(len(LABELS))]
    i = LABELS.index("Overwatch_2")
    j = LABELS.index("Marvel_Rivals")
    conf[i][i] = 7
    conf[i][j] = 3  # 30% OW→MR
    conf[j][j] = 8
    conf[j][i] = 2  # 20% MR→OW
    look = _lookalike_metrics(conf, LABELS)
    assert look["pair"] == list(LOOKALIKE)
    assert look["Overwatch_2_to_Marvel_Rivals"] == pytest.approx(0.3)
    assert look["Marvel_Rivals_to_Overwatch_2"] == pytest.approx(0.2)
    assert look["mean_f1"] is not None


def test_group_breakdowns_by_tier_source_clip(tmp_path):
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=2, splits=("val",))
    from game_frame_classifier.split_manifest import load_split
    from game_frame_classifier.evaluation import build_metrics

    rows = load_split(split_dir, "val")
    # Predict always correct
    probs = np.zeros((len(rows), len(LABELS)), dtype=np.float64)
    for i, r in enumerate(rows):
        probs[i, r.label] = 1.0
    run = {
        "run_id": "20260101-000000",
        "model_type": "fake",
        "labels": list(LABELS),
        "split_dir": str(split_dir),
        "split_id": "v1",
        "split_hashes": {
            "train": "a" * 64,
            "val": "b" * 64,
            "test_session": "c" * 64,
            "test_source": "d" * 64,
        },
    }
    metrics = build_metrics(
        rows,
        probs,
        run=run,
        split="val",
        split_dir=split_dir,
        data_root=data_root,
        hash_changed=False,
    )
    assert set(metrics["by_tier"]) <= {"full", "crf45"}
    for tier_stats in metrics["by_tier"].values():
        assert tier_stats["accuracy"] == 1.0
    assert metrics["by_source"]["src_a"]["accuracy"] == 1.0
    assert metrics["by_source"]["src_a"]["source_kind"] == "personal"
    assert metrics["by_clip"]
    assert metrics["by_clip"][0]["accuracy"] == 1.0


def _metric_row(index: int, game: str, label: int, clip_key: str) -> SlotRow:
    return SlotRow(
        slot_id=f"{clip_key}:b{index:06d}",
        clip_key=clip_key,
        game=game,
        label=label,
        source="src",
        source_kind="personal",
        session=f"src:{game}:s001",
        split="val",
        tier="full",
        path="frames/x.jpg",
        path_full="frames/x.jpg",
        path_low="frames/y.jpg",
        bucket=index,
        target_time_s=float(index),
        public_examples_ok=False,
        other_name="desktop" if game == "Other" else "",
    )


def test_six_game_and_open_set_metrics_on_known_probabilities():
    rows = [
        _metric_row(i, LABELS[i % 6], i % 6, f"cg{i // 2}")
        for i in range(20)
    ]
    rows.extend([
        _metric_row(20, "Other", 6, "co1"),
        _metric_row(21, "Other", 6, "co2"),
    ])
    scores = np.asarray([i / 100 for i in range(20)] + [0.9, 0.8])
    probs = np.zeros((len(rows), 7), dtype=np.float64)
    for i, row in enumerate(rows):
        probs[i, row.label if row.label < 6 else 0] = 1.0 - scores[i]
        probs[i, 6] = scores[i]
    tau = _threshold_at_false_alarm(scores[:20])
    assert tau == pytest.approx(0.18)
    opened = compute_open_set_metrics(rows, probs, tau=tau, seven_way=True)
    assert opened["false_alarm_rate"] == pytest.approx(0.05)
    assert opened["other_detection_rate"] == 1.0
    assert opened["auroc"] == 1.0
    assert opened["coverage"] == pytest.approx(0.95)
    assert opened["accuracy_on_covered"] == 1.0
    assert opened["argmax_other_rate"] == 1.0

    pred = probs.argmax(axis=1)
    pred[0] = 6
    six = compute_six_game_metrics(rows, pred)
    assert six["n"] == 20
    assert six["accuracy"] == pytest.approx(19 / 20)


def test_paired_bootstrap_is_reproducible_over_clips():
    a: list[dict[str, str]] = []
    b: list[dict[str, str]] = []
    specs = [
        ("g1", 0, 0.1, 0.1, 0, 0),
        ("g2", 1, 0.2, 0.2, 1, 1),
        ("o1", 6, 0.4, 0.8, 0, 6),
        ("o2", 6, 0.6, 0.9, 0, 6),
    ]
    for i, (clip, label, score_a, score_b, pred_a, pred_b) in enumerate(specs):
        common = {"slot_id": f"s{i}", "clip_key": clip, "label": str(label)}
        a.append({**common, "pred": str(pred_a), "open_score": str(score_a)})
        b.append({**common, "pred": str(pred_b), "open_score": str(score_b)})
    first = _bootstrap_comparison(a, b, 0.5, 0.5)
    second = _bootstrap_comparison(a, b, 0.5, 0.5)
    assert first == second
    assert first["unit"] == "clip_key"
    assert first["resamples"] == 1000
    for result in first["metrics"].values():
        if result["difference_b_minus_a"] is not None:
            assert result["ci_low"] <= result["difference_b_minus_a"] <= result["ci_high"]


class _AlwaysRight:
    labels = LABELS

    def predict_proba(self, rows, data_root, tier_mode="assigned"):
        out = np.zeros((len(rows), len(LABELS)), dtype=np.float64)
        for i, r in enumerate(rows):
            out[i, r.label] = 1.0
        return out


def _write_run(run_dir: Path, split_dir: Path, *, model_type: str = "fake") -> None:
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


def test_guards_test_without_freeze(tmp_path):
    data_root, split_dir = build_split_fixture(
        tmp_path, n_per_game=1, splits=("val", "test_session")
    )
    run_dir = tmp_path / "runs" / "fake" / "r1"
    _write_run(run_dir, split_dir)
    register_predictor_loader("fake", lambda _p: _AlwaysRight())
    with pytest.raises(PermissionError, match="freeze"):
        evaluate_run(run_dir, "test_session", data_root=data_root, reason="final")


def test_guards_test_without_reason(tmp_path):
    data_root, split_dir = build_split_fixture(
        tmp_path, n_per_game=1, splits=("val", "test_session")
    )
    (split_dir / "freeze.json").write_text(
        json.dumps({"time": "t", "git_commit": "abc", "test_design": "B"}),
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "fake" / "r1"
    _write_run(run_dir, split_dir)
    register_predictor_loader("fake", lambda _p: _AlwaysRight())
    with pytest.raises(PermissionError, match="reason"):
        evaluate_run(run_dir, "test_session", data_root=data_root, reason=None)


def test_guards_accepted_appends_one_log_line(tmp_path):
    data_root, split_dir = build_split_fixture(
        tmp_path, n_per_game=1, splits=("val", "test_session")
    )
    (split_dir / "freeze.json").write_text(
        json.dumps({"time": "t", "git_commit": "abc", "test_design": "B"}),
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "fake" / "r1"
    _write_run(run_dir, split_dir)
    register_predictor_loader("fake", lambda _p: _AlwaysRight())
    evaluate_run(run_dir, "val", data_root=data_root)
    evaluate_run(
        run_dir,
        "test_session",
        data_root=data_root,
        reason="final report",
    )
    log_path = data_root / "runs" / "holdout_access.jsonl"
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["split"] == "test_session"
    assert entry["reason"] == "final report"
    assert entry["run"] == "r1"
    assert "utc" in entry and "git_commit" in entry


def test_test_split_refuses_before_val_threshold_exists(tmp_path):
    data_root, split_dir = build_split_fixture(
        tmp_path, n_per_game=1, splits=("test_session",),
    )
    (split_dir / "freeze.json").write_text(
        json.dumps({"time": "t", "git_commit": "abc", "test_design": "B"}),
        encoding="utf-8",
    )
    run_dir = tmp_path / "runs" / "fake" / "r1"
    _write_run(run_dir, split_dir)
    register_predictor_loader("fake", lambda _p: _AlwaysRight())
    with pytest.raises(PermissionError, match="score val first"):
        evaluate_run(
            run_dir,
            "test_session",
            data_root=data_root,
            reason="final report",
        )


def test_label_order_mismatch_refused(tmp_path):
    data_root, split_dir = build_split_fixture(tmp_path, n_per_game=1, splits=("val",))
    run_dir = tmp_path / "runs" / "fake" / "r1"
    _write_run(run_dir, split_dir)
    payload = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    payload["labels"] = list(reversed(LABELS))
    (run_dir / "run.json").write_text(json.dumps(payload), encoding="utf-8")
    register_predictor_loader("fake", lambda _p: _AlwaysRight())
    with pytest.raises(ValueError, match="labels"):
        evaluate_run(run_dir, "val", data_root=data_root)


def test_examples_exclude_non_consent(tmp_path):
    pytest.importorskip("matplotlib")
    from game_frame_classifier.evaluation import write_examples_png

    data_root = tmp_path / "data"
    rows_dicts = [
        make_slot_dict(
            game="Valorant",
            label=0,
            clip_key="c000000000001",
            bucket=0,
            public_examples_ok=False,
            source="friend_a",
        ),
        make_slot_dict(
            game="CS2",
            label=2,
            clip_key="c000000000002",
            bucket=1,
            public_examples_ok=True,
            source="tester",
        ),
    ]
    materialise_frames(data_root, rows_dicts)
    rows = [
        SlotRow(
            slot_id=d["slot_id"],
            clip_key=d["clip_key"],
            game=d["game"],
            label=d["label"],
            source=d["source"],
            source_kind=d["source_kind"],
            session=d["session"],
            split=d["split"],
            tier=d["tier"],
            path=d["path"],
            path_full=d["path_full"],
            path_low=d["path_low"],
            bucket=d["bucket"],
            target_time_s=d["target_time_s"],
            public_examples_ok=d["public_examples_ok"],
        )
        for d in rows_dicts
    ]
    probs = np.eye(len(LABELS), dtype=np.float64)[[0, 2]]
    # make first wrong so it would be preferred if consent were ignored
    probs[0] = 0.0
    probs[0, 1] = 1.0
    out = tmp_path / "examples.png"
    assert write_examples_png(out, rows, probs, data_root, examples=8)
    assert out.is_file() and out.stat().st_size > 0
