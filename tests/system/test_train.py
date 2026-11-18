"""System tests for gfc-train-cnn: overfit, run folder, predictor, CLI edges."""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
import types
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torchvision")
np = pytest.importorskip("numpy")

from game_frame_classifier.dataset import FrameDataset, eval_transform, make_loader
from game_frame_classifier.model import FrameCNN
from game_frame_classifier.split_manifest import LABELS, load_split
from game_frame_classifier.train import (
    TrainError,
    load_cnn_predictor,
    load_config,
    main,
    train_run,
)
from tests.helpers.loader_fixtures import (
    make_slot_dict,
    write_frame_jpeg,
    write_split_csv,
    write_summary,
)

# Highly separable solid colours so a tiny CNN overfits quickly.
_CLASS_COLOURS = {
    0: (220, 30, 30),
    1: (30, 220, 30),
    2: (30, 30, 220),
    6: (180, 180, 30),
}


def _overfit_fixture(
    root: Path,
    *,
    n_per_class: int = 8,
    n_val: int = 2,
    include_other: bool = False,
) -> tuple[Path, Path]:
    """3 games × n_per_class train frames (+ small val) with distinct colours."""
    data_root = root / "data"
    split_dir = data_root / "manifests" / "splits" / "v1"
    split_dir.mkdir(parents=True, exist_ok=True)

    games = list(LABELS[:3]) + ([LABELS[6]] if include_other else [])
    train_rows: list[dict] = []
    val_rows: list[dict] = []
    bucket = 0
    for game_i, game in enumerate(games):
        label = 6 if game == "Other" else game_i
        for j in range(n_per_class):
            row = make_slot_dict(
                game=game,
                label=label,
                source="src_a",
                session=f"src_a:{game}:s001",
                split="train",
                tier="full",
                clip_key=f"c{label:012x}",
                other_name="desktop" if game == "Other" else "",
                bucket=bucket,
            )
            train_rows.append(row)
            bucket += 1
        for j in range(n_val):
            row = make_slot_dict(
                game=game,
                label=label,
                source="src_a",
                session=f"src_a:{game}:s002",
                split="val",
                tier="full",
                clip_key=f"c{label + 10:012x}",
                other_name="desktop" if game == "Other" else "",
                bucket=bucket,
            )
            val_rows.append(row)
            bucket += 1

    all_rows = train_rows + val_rows
    for row in all_rows:
        colour = _CLASS_COLOURS[row["label"]]
        for rel in (row["path_full"], row["path_low"]):
            write_frame_jpeg(data_root / Path(*rel.split("/")), colour=colour)

    write_split_csv(split_dir / "train.csv", train_rows)
    write_split_csv(split_dir / "val.csv", val_rows)
    write_summary(split_dir)
    return data_root, split_dir


def _no_aug_config(config_path: Path) -> dict:
    cfg = load_config(config_path)
    cfg["label_set"] = "six"
    cfg["device"] = "cpu"
    cfg["epochs"] = 30
    cfg["batch_size"] = 8
    cfg["early_stop_patience"] = 30
    cfg["cache"] = "ram"
    cfg["num_workers"] = 0
    cfg["augment"]["affine_p"] = 0.0
    cfg["augment"]["jitter_p"] = 0.0
    return cfg


def test_overfit_and_run_folder(tmp_path):
    data_root, split_dir = _overfit_fixture(tmp_path)
    config = _no_aug_config(Path("config/train_cnn.json"))
    run_dir = tmp_path / "run"
    meta = train_run(
        split_dir=split_dir,
        data_root=data_root,
        config=config,
        run_dir=run_dir,
        run_id="test-overfit",
    )

    # Train accuracy of the final epoch should be high
    with (run_dir / "history.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert 1 <= int(meta["best_epoch"]) <= len(rows)
    assert len(rows) == int(rows[-1]["epoch"])
    final_train_acc = float(rows[-1]["train_acc"])
    assert final_train_acc >= 0.95

    for name in ("run.json", "history.csv", "best.pt", "last.pt"):
        assert (run_dir / name).is_file(), name
    if importlib.util.find_spec("matplotlib") is not None:
        assert (run_dir / "curves.png").is_file()
    assert meta["model_type"] == "cnn"
    assert meta["param_count"] == 9_827_878
    assert Path(meta["split_dir"]).is_absolute()

    # Predictor matches a fresh forward from best.pt
    predictor = load_cnn_predictor(run_dir)
    val_rows = load_split(split_dir, "val")
    probs = predictor.predict_proba(val_rows, data_root)
    assert probs.shape == (len(val_rows), 6)
    assert np.allclose(probs.sum(axis=1), 1.0, atol=1e-5)

    ckpt = torch.load(run_dir / "best.pt", map_location="cpu", weights_only=True)
    model = FrameCNN(num_classes=6)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    ds = FrameDataset(val_rows, data_root, transform=eval_transform(), cache="none")
    loader = make_loader(ds, batch_size=8, shuffle=False, seed=0, num_workers=0)
    manual = []
    order = []
    with torch.no_grad():
        for images, _labels, indices in loader:
            logits = model(images)
            manual.append(torch.softmax(logits, dim=1).numpy())
            order.extend(int(i) for i in indices.tolist())
    stacked = np.concatenate(manual, axis=0)
    expected = np.zeros_like(stacked)
    for pos, row_i in enumerate(order):
        expected[row_i] = stacked[pos]
    assert np.allclose(probs, expected, atol=1e-5)


def test_same_seed_same_first_epoch_loss(tmp_path):
    data_root, split_dir = _overfit_fixture(tmp_path, n_per_class=4, n_val=1)
    config = _no_aug_config(Path("config/train_cnn.json"))
    config["epochs"] = 1
    losses = []
    for i in range(2):
        run_dir = tmp_path / f"run{i}"
        meta = train_run(
            split_dir=split_dir,
            data_root=data_root,
            config=config,
            run_dir=run_dir,
            run_id=f"seed-{i}",
        )
        losses.append(meta["first_epoch_train_loss"])
    assert losses[0] == pytest.approx(losses[1], rel=0, abs=1e-8)


def test_limit_flag(tmp_path):
    data_root, split_dir = _overfit_fixture(tmp_path, n_per_class=8, n_val=4)
    config = _no_aug_config(Path("config/train_cnn.json"))
    config["epochs"] = 1
    run_dir = tmp_path / "run-limit"
    meta = train_run(
        split_dir=split_dir,
        data_root=data_root,
        config=config,
        run_dir=run_dir,
        run_id="limit",
        limit=5,
    )
    assert meta["n_train"] == 5
    assert meta["n_val"] == 5


def test_evaluation_missing_message(tmp_path, capsys, monkeypatch):
    import game_frame_classifier.train as train_mod

    module_name = "game_frame_classifier.evaluation"

    def _missing_evaluation(name):
        assert name == module_name
        raise ModuleNotFoundError(
            f"No module named {module_name!r}",
            name=module_name,
        )

    monkeypatch.setattr(train_mod.importlib, "import_module", _missing_evaluation)
    data_root, split_dir = _overfit_fixture(tmp_path, n_per_class=4, n_val=1)
    config = _no_aug_config(Path("config/train_cnn.json"))
    config["epochs"] = 1
    train_run(
        split_dir=split_dir,
        data_root=data_root,
        config=config,
        run_dir=tmp_path / "run-eval",
        run_id="eval-msg",
    )
    out = capsys.readouterr().out
    assert "evaluation not available yet" in out


def test_curves_skipped_without_matplotlib(tmp_path, monkeypatch, capsys):
    import game_frame_classifier.train as train_mod

    real_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "matplotlib" or name.startswith("matplotlib."):
            raise ImportError("blocked for test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    data_root, split_dir = _overfit_fixture(tmp_path, n_per_class=4, n_val=1)
    config = _no_aug_config(Path("config/train_cnn.json"))
    config["epochs"] = 1
    run_dir = tmp_path / "run-nompl"
    train_run(
        split_dir=split_dir,
        data_root=data_root,
        config=config,
        run_dir=run_dir,
        run_id="nompl",
    )
    assert not (run_dir / "curves.png").exists()
    assert (run_dir / "history.csv").is_file()
    out = capsys.readouterr().out
    assert "skipping figure" in out
    # restore is automatic via monkeypatch; ensure module still importable
    assert train_mod is not None


def test_history_is_appended_before_later_epoch_failure(tmp_path, monkeypatch):
    import game_frame_classifier.train as train_mod

    data_root, split_dir = _overfit_fixture(tmp_path, n_per_class=4, n_val=1)
    config = _no_aug_config(Path("config/train_cnn.json"))
    config["epochs"] = 2
    run_dir = tmp_path / "run-interrupted"
    eval_calls = 0

    monkeypatch.setattr(
        train_mod,
        "_run_train_epoch",
        lambda *_args, **_kwargs: (1.25, 0.5),
    )

    def _eval_then_fail(*_args, **_kwargs):
        nonlocal eval_calls
        eval_calls += 1
        if eval_calls == 2:
            raise RuntimeError("simulated epoch failure")
        empty = np.array([], dtype=np.int64)
        return 1.0, 0.5, 0.5, empty, empty

    monkeypatch.setattr(train_mod, "_run_eval", _eval_then_fail)
    with pytest.raises(RuntimeError, match="simulated epoch failure"):
        train_run(
            split_dir=split_dir,
            data_root=data_root,
            config=config,
            run_dir=run_dir,
            run_id="interrupted",
        )

    with (run_dir / "history.csv").open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["epoch"] == "1"


def test_best_checkpoint_keeps_selected_epoch_weights(tmp_path, monkeypatch):
    import game_frame_classifier.train as train_mod

    data_root, split_dir = _overfit_fixture(tmp_path, n_per_class=2, n_val=1)
    config = _no_aug_config(Path("config/train_cnn.json"))
    config["epochs"] = 5
    config["early_stop_patience"] = 2
    f1_values = iter((0.8, 0.3, 0.2))

    def _mutate_model(model, *_args, **_kwargs):
        with torch.no_grad():
            next(model.parameters()).add_(1.0)
        return 1.0, 0.5

    def _controlled_eval(*_args, **_kwargs):
        empty = np.array([], dtype=np.int64)
        return 1.0, 0.5, next(f1_values), empty, empty

    monkeypatch.setattr(train_mod, "_run_train_epoch", _mutate_model)
    monkeypatch.setattr(train_mod, "_run_eval", _controlled_eval)
    run_dir = tmp_path / "run-best"
    train_run(
        split_dir=split_dir,
        data_root=data_root,
        config=config,
        run_dir=run_dir,
        run_id="best",
    )

    best = torch.load(run_dir / "best.pt", map_location="cpu", weights_only=True)
    last = torch.load(run_dir / "last.pt", map_location="cpu", weights_only=True)
    assert best["epoch"] == 1
    assert last["epoch"] == 3
    first_key = next(iter(best["model_state"]))
    assert not torch.equal(
        best["model_state"][first_key],
        last["model_state"][first_key],
    )


def test_import_error_inside_evaluation_is_not_hidden(tmp_path, monkeypatch):
    data_root, split_dir = _overfit_fixture(tmp_path, n_per_class=4, n_val=1)
    config = _no_aug_config(Path("config/train_cnn.json"))
    config["epochs"] = 1

    fake = types.ModuleType("game_frame_classifier.evaluation")

    def _raise_import_error(*_args, **_kwargs):
        raise ImportError("evaluation dependency is broken")

    fake.evaluate_run = _raise_import_error
    monkeypatch.setitem(sys.modules, "game_frame_classifier.evaluation", fake)

    with pytest.raises(ImportError, match="evaluation dependency is broken"):
        train_run(
            split_dir=split_dir,
            data_root=data_root,
            config=config,
            run_dir=tmp_path / "run-broken-eval",
            run_id="broken-eval",
        )


def test_existing_run_folder_is_refused(tmp_path):
    data_root, split_dir = _overfit_fixture(tmp_path, n_per_class=2, n_val=1)
    config = _no_aug_config(Path("config/train_cnn.json"))
    config["epochs"] = 1
    run_dir = tmp_path / "existing-run"
    run_dir.mkdir()
    marker = run_dir / "keep.txt"
    marker.write_text("do not overwrite\n", encoding="utf-8")

    with pytest.raises(TrainError, match="run folder already exists"):
        train_run(
            split_dir=split_dir,
            data_root=data_root,
            config=config,
            run_dir=run_dir,
            run_id="existing",
        )
    assert marker.read_text(encoding="utf-8") == "do not overwrite\n"


def test_cli_set_gap_and_main(tmp_path):
    data_root, split_dir = _overfit_fixture(tmp_path, n_per_class=4, n_val=1)
    out = tmp_path / "cli-run"
    code = main(
        [
            "--split-dir",
            str(split_dir),
            "--data-root",
            str(data_root),
            "--out",
            str(out),
            "--device",
            "cpu",
            "--epochs",
            "1",
            "--set",
            "model.head=gap",
            "--set",
            "augment.affine_p=0",
            "--set",
            "augment.jitter_p=0",
            "--set",
            "batch_size=8",
            "--set",
            "label_set=six",
            "--tag",
            "cli",
        ]
    )
    assert code == 0
    meta = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert meta["config"]["model"]["head"] == "gap"
    assert meta["param_count"] == 390_438


def test_seven_way_cnn_records_labels_and_parameter_count(tmp_path):
    data_root, split_dir = _overfit_fixture(
        tmp_path, n_per_class=2, n_val=1, include_other=True,
    )
    config = _no_aug_config(Path("config/train_cnn.json"))
    config["label_set"] = "seven"
    config["epochs"] = 1
    meta = train_run(
        split_dir=split_dir,
        data_root=data_root,
        config=config,
        run_dir=tmp_path / "seven",
        run_id="seven",
    )
    assert meta["label_set"] == "seven"
    assert meta["labels"] == list(LABELS)
    assert meta["param_count"] == 9_828_135
    assert load_cnn_predictor(tmp_path / "seven").predict_proba(
        load_split(split_dir, "val"), data_root,
    ).shape[1] == 7


def test_seven_way_cnn_refuses_without_other(tmp_path):
    data_root, split_dir = _overfit_fixture(tmp_path, n_per_class=1, n_val=1)
    config = _no_aug_config(Path("config/train_cnn.json"))
    config["label_set"] = "seven"
    with pytest.raises(TrainError, match="no Other frames"):
        train_run(
            split_dir=split_dir,
            data_root=data_root,
            config=config,
            run_dir=tmp_path / "seven",
            run_id="seven",
        )
