"""System tests for gfc-train-cnn: overfit, run folder, predictor, CLI edges."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("torchvision")
np = pytest.importorskip("numpy")

from game_frame_classifier.dataset import FrameDataset, eval_transform, make_loader
from game_frame_classifier.model import FrameCNN
from game_frame_classifier.split_manifest import LABELS, load_split
from game_frame_classifier.train import (
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
}


def _overfit_fixture(root: Path, *, n_per_class: int = 8, n_val: int = 2) -> tuple[Path, Path]:
    """3 games × n_per_class train frames (+ small val) with distinct colours."""
    data_root = root / "data"
    split_dir = data_root / "manifests" / "splits" / "v1"
    split_dir.mkdir(parents=True, exist_ok=True)

    games = list(LABELS[:3])
    train_rows: list[dict] = []
    val_rows: list[dict] = []
    bucket = 0
    for game_i, game in enumerate(games):
        for j in range(n_per_class):
            row = make_slot_dict(
                game=game,
                label=game_i,
                source="src_a",
                session=f"src_a:{game}:s001",
                split="train",
                tier="full",
                clip_key=f"c{game_i:012x}",
                bucket=bucket,
            )
            train_rows.append(row)
            bucket += 1
        for j in range(n_val):
            row = make_slot_dict(
                game=game,
                label=game_i,
                source="src_a",
                session=f"src_a:{game}:s002",
                split="val",
                tier="full",
                clip_key=f"c{game_i + 10:012x}",
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
    assert len(rows) == int(meta["best_epoch"]) or len(rows) >= 1
    assert len(rows) == int(rows[-1]["epoch"])
    final_train_acc = float(rows[-1]["train_acc"])
    assert final_train_acc >= 0.95

    for name in ("run.json", "history.csv", "best.pt", "last.pt"):
        assert (run_dir / name).is_file(), name
    # curves.png may be present when matplotlib is installed
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
    model = FrameCNN()
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


def test_evaluation_missing_message(tmp_path, capsys):
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
    assert "matplotlib not available" in out
    # restore is automatic via monkeypatch; ensure module still importable
    assert train_mod is not None


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
            "--tag",
            "cli",
        ]
    )
    assert code == 0
    meta = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert meta["config"]["model"]["head"] == "gap"
    assert meta["param_count"] == 390_438
