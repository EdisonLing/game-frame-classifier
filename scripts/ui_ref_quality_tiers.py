"""Build full / medium / low 1080p stills for UI reference frames.

Uses D22 method: short 1080p proxy around the provenance timestamp, then
video CRF re-encode, then still extract. Full = still from the proxy (CRF18);
medium/low = re-encode that proxy at TIER_CRF then still.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from game_frame_classifier.frame_extractor import require_ffmpeg
from game_frame_classifier.quality_encoder import TIER_CRF, reencode_video_crf

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANIFEST = ROOT / "docs" / "examples-library" / "ui-reference" / "manifest.json"
OUT = ROOT / "docs" / "examples-library" / "ui-reference" / "qualities"

PROXY_CRF = 18
SLICE_PAD_BEFORE_S = 1.0
SLICE_PAD_AFTER_S = 2.0
WIDTH = 1920
HEIGHT = 1080
JPEG_QV = 2
MED_CRF = TIER_CRF["medium"]
LOW_CRF = TIER_CRF["low"]


def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "cmd failed\n"
            f"{' '.join(cmd)}\n"
            f"{proc.stderr.strip()}"
        )


def extract_still(video: Path, dest: Path, *, timestamp_s: float) -> Path:
    ffmpeg = require_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{timestamp_s:g}",
            "-i",
            str(video),
            "-vf",
            f"scale={WIDTH}:{HEIGHT}:flags=bicubic",
            "-frames:v",
            "1",
            "-q:v",
            str(JPEG_QV),
            str(dest),
        ]
    )
    return dest


def make_proxy(
    src: Path,
    dest: Path,
    *,
    seek_s: float,
    duration_s: float,
) -> Path:
    ffmpeg = require_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{seek_s:g}",
            "-t",
            f"{duration_s:g}",
            "-i",
            str(src),
            "-vf",
            f"scale={WIDTH}:{HEIGHT}:flags=bicubic",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(PROXY_CRF),
            "-pix_fmt",
            "yuv420p",
            str(dest),
        ]
    )
    return dest


def main() -> None:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    frames = data["frames"]
    OUT.mkdir(parents=True, exist_ok=True)

    # Drop superseded filename patterns from older 28/38 ladders.
    for old in OUT.glob("*__medium_crf28.jpg"):
        old.unlink()
    for old in OUT.glob("*__low_crf38.jpg"):
        old.unlink()

    out_manifest: dict = {
        "note": (
            "Three quality stills per UI reference frame (D22): "
            f"full = 1080p proxy CRF{PROXY_CRF}; "
            f"medium/low = video CRF {MED_CRF}/{LOW_CRF} then still. "
            "Paths relative to docs/examples-library/ui-reference/qualities/."
        ),
        "method": {
            "width": WIDTH,
            "height": HEIGHT,
            "proxy_crf": PROXY_CRF,
            "slice_pad_before_s": SLICE_PAD_BEFORE_S,
            "slice_pad_after_s": SLICE_PAD_AFTER_S,
            "jpeg_qv": JPEG_QV,
            "tiers": {
                "full": f"proxy CRF{PROXY_CRF}",
                "medium": f"proxy re-encoded CRF{MED_CRF}",
                "low": f"proxy re-encoded CRF{LOW_CRF}",
            },
        },
        "frames": [],
    }

    with tempfile.TemporaryDirectory(prefix="ui_ref_q_") as tmp_s:
        tmp = Path(tmp_s)
        for entry in frames:
            stem = Path(entry["file"]).stem
            rel_video = entry["source_video"]
            t = float(entry["timestamp_s"])
            src = RAW / rel_video
            if not src.is_file():
                raise FileNotFoundError(src)

            seek_s = max(0.0, t - SLICE_PAD_BEFORE_S)
            offset_s = t - seek_s
            duration_s = offset_s + SLICE_PAD_AFTER_S

            print(f"{stem}: {src.name} @ {t:g}s (seek {seek_s:g}, offset {offset_s:g})")

            proxy = tmp / f"{stem}_proxy.mp4"
            med_v = tmp / f"{stem}_crf{MED_CRF}.mp4"
            low_v = tmp / f"{stem}_crf{LOW_CRF}.mp4"
            make_proxy(src, proxy, seek_s=seek_s, duration_s=duration_s)
            reencode_video_crf(proxy, med_v, crf=MED_CRF, preset="veryfast")
            reencode_video_crf(proxy, low_v, crf=LOW_CRF, preset="veryfast")

            files = {
                "full": f"{stem}__full.jpg",
                f"medium_crf{MED_CRF}": f"{stem}__medium_crf{MED_CRF}.jpg",
                f"low_crf{LOW_CRF}": f"{stem}__low_crf{LOW_CRF}.jpg",
            }
            extract_still(proxy, OUT / files["full"], timestamp_s=offset_s)
            extract_still(
                med_v, OUT / files[f"medium_crf{MED_CRF}"], timestamp_s=offset_s
            )
            extract_still(
                low_v, OUT / files[f"low_crf{LOW_CRF}"], timestamp_s=offset_s
            )

            sizes = {
                k: round((OUT / name).stat().st_size / 1024, 1)
                for k, name in files.items()
            }
            out_manifest["frames"].append(
                {
                    "stem": stem,
                    "label": entry.get("label", stem),
                    "source_video": rel_video,
                    "timestamp_s": t,
                    "seek_s": seek_s,
                    "frame_offset_s": offset_s,
                    "files": files,
                    "sizes_kb": sizes,
                }
            )
            print(f"  sizes_kb={sizes}")

    man_path = OUT / "manifest.json"
    man_path.write_text(json.dumps(out_manifest, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {man_path}")


if __name__ == "__main__":
    main()
