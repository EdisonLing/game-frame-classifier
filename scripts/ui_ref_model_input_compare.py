"""Downscale UI-ref quality ladders to 256x144 and compare tiers at each size.

Same-resolution metrics only (medium/low vs full at 1080p, then again at 256x144).
Default stem: action_buyphase_barrier (README example).
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from game_frame_classifier.quality_encoder import TIER_CRF

ROOT = Path(__file__).resolve().parents[1]
QUAL = ROOT / "docs" / "examples-library" / "ui-reference" / "qualities"
OUT = QUAL / "model_input_256x144"
PUBLISH = ROOT / "docs" / "examples" / "quality-ladder"
MED_CRF = TIER_CRF["medium"]
LOW_CRF = TIER_CRF["low"]


def load_rgb(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.float64)


def downscale(arr: np.ndarray, size: tuple[int, int] = (256, 144)) -> np.ndarray:
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return np.asarray(img.resize(size, Image.Resampling.BILINEAR), dtype=np.float64)


def mae(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a - b)))


def psnr(a: np.ndarray, b: np.ndarray, max_val: float = 255.0) -> float:
    mse = float(np.mean((a - b) ** 2))
    if mse == 0:
        return math.inf
    return 20.0 * math.log10(max_val) - 10.0 * math.log10(mse)


def ssim_global_gray(a: np.ndarray, b: np.ndarray) -> float:
    """Global grayscale SSIM (not windowed). Fine for a README table, not a paper."""
    ag = 0.299 * a[:, :, 0] + 0.587 * a[:, :, 1] + 0.114 * a[:, :, 2]
    bg = 0.299 * b[:, :, 0] + 0.587 * b[:, :, 1] + 0.114 * b[:, :, 2]
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mu_a, mu_b = float(ag.mean()), float(bg.mean())
    sig_a, sig_b = float(ag.var()), float(bg.var())
    sig_ab = float(((ag - mu_a) * (bg - mu_b)).mean())
    return float(
        ((2 * mu_a * mu_b + c1) * (2 * sig_ab + c2))
        / ((mu_a**2 + mu_b**2 + c1) * (sig_a + sig_b + c2))
    )


def pair_metrics(ref: np.ndarray, other: np.ndarray) -> dict[str, float]:
    return {
        "mae": mae(other, ref),
        "psnr_db": psnr(other, ref),
        "ssim": ssim_global_gray(other, ref),
    }


def process_stem(stem: str) -> dict:
    paths = {
        "full": QUAL / f"{stem}__full.jpg",
        "medium": QUAL / f"{stem}__medium_crf{MED_CRF}.jpg",
        "low": QUAL / f"{stem}__low_crf{LOW_CRF}.jpg",
    }
    for p in paths.values():
        if not p.is_file():
            raise FileNotFoundError(p)

    full = {k: load_rgb(p) for k, p in paths.items()}
    OUT.mkdir(parents=True, exist_ok=True)
    # Drop superseded 28/38 model-input names.
    for old in OUT.glob("*__medium_crf28_256x144.jpg"):
        old.unlink()
    for old in OUT.glob("*__low_crf38_256x144.jpg"):
        old.unlink()

    small: dict[str, np.ndarray] = {}
    out_names = {
        "full": f"{stem}__full_256x144.jpg",
        "medium": f"{stem}__medium_crf{MED_CRF}_256x144.jpg",
        "low": f"{stem}__low_crf{LOW_CRF}_256x144.jpg",
    }
    for k, arr in full.items():
        s = downscale(arr)
        small[k] = s
        Image.fromarray(s.astype(np.uint8)).save(OUT / out_names[k], quality=95)

    metrics = {
        "stem": stem,
        "tiers_crf": {"full": 0, "medium": MED_CRF, "low": LOW_CRF},
        "note": (
            "Same-resolution comparisons vs full tier (not cross-resolution). "
            "SSIM is global grayscale, not windowed."
        ),
        "resize": "PIL bilinear to 256x144",
        "1080p": {
            "medium_vs_full": pair_metrics(full["full"], full["medium"]),
            "low_vs_full": pair_metrics(full["full"], full["low"]),
        },
        "256x144": {
            "medium_vs_full": pair_metrics(small["full"], small["medium"]),
            "low_vs_full": pair_metrics(small["full"], small["low"]),
        },
        "files_256x144": out_names,
    }
    (OUT / f"{stem}_metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )
    return metrics


def promote_readme_ladder(stem: str) -> None:
    """Copy the six README-linked files into the published examples folder."""
    PUBLISH.mkdir(parents=True, exist_ok=True)
    (PUBLISH / "model_input_256x144").mkdir(parents=True, exist_ok=True)
    for old in PUBLISH.glob("*__medium_crf28.jpg"):
        old.unlink()
    for old in PUBLISH.glob("*__low_crf38.jpg"):
        old.unlink()
    for old in (PUBLISH / "model_input_256x144").glob("*__medium_crf28_256x144.jpg"):
        old.unlink()
    for old in (PUBLISH / "model_input_256x144").glob("*__low_crf38_256x144.jpg"):
        old.unlink()

    mapping = [
        (QUAL / f"{stem}__full.jpg", PUBLISH / f"{stem}__full.jpg"),
        (
            QUAL / f"{stem}__medium_crf{MED_CRF}.jpg",
            PUBLISH / f"{stem}__medium_crf{MED_CRF}.jpg",
        ),
        (
            QUAL / f"{stem}__low_crf{LOW_CRF}.jpg",
            PUBLISH / f"{stem}__low_crf{LOW_CRF}.jpg",
        ),
        (
            OUT / f"{stem}__full_256x144.jpg",
            PUBLISH / "model_input_256x144" / f"{stem}__full_256x144.jpg",
        ),
        (
            OUT / f"{stem}__medium_crf{MED_CRF}_256x144.jpg",
            PUBLISH / "model_input_256x144" / f"{stem}__medium_crf{MED_CRF}_256x144.jpg",
        ),
        (
            OUT / f"{stem}__low_crf{LOW_CRF}_256x144.jpg",
            PUBLISH / "model_input_256x144" / f"{stem}__low_crf{LOW_CRF}_256x144.jpg",
        ),
    ]
    for src, dest in mapping:
        shutil.copy2(src, dest)
        print(f"published {dest.relative_to(ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stem", default="action_buyphase_barrier")
    ap.add_argument(
        "--publish",
        action="store_true",
        help="Also copy this stem's six README files into docs/examples/quality-ladder/",
    )
    args = ap.parse_args()
    metrics = process_stem(args.stem)
    print(json.dumps(metrics, indent=2))
    if args.publish:
        promote_readme_ladder(args.stem)


if __name__ == "__main__":
    main()
