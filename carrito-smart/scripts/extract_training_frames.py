"""Extrae frames variados y nítidos desde los videos de entrenamiento."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path

import cv2


PROJECT_ROOT = Path(__file__).resolve().parent.parent
VALID_SPLITS = ("train", "val", "test")
VALID_CLASSES = (
    "cocacola_lata",
    "pepsi_lata",
    "doritos_bolsa",
    "negativos",
)
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}


@dataclass(frozen=True, slots=True)
class ExtractionStats:
    video: Path
    candidates: int
    saved: int
    blurry: int
    duplicates: int


def average_hash(frame, hash_size: int = 16) -> int:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (hash_size, hash_size), interpolation=cv2.INTER_AREA)
    mean = float(resized.mean())
    bits = (resized >= mean).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hash_distance(first: int, second: int) -> int:
    return (first ^ second).bit_count()


def is_sharp(frame, threshold: float) -> bool:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var()) >= threshold


def extract_video(
    video_path: Path,
    output_dir: Path,
    *,
    samples_per_second: float,
    blur_threshold: float,
    duplicate_distance: int,
) -> ExtractionStats:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"No se pudo abrir {video_path}")

    source_fps = float(capture.get(cv2.CAP_PROP_FPS)) or 30.0
    sample_step = max(1, round(source_fps / samples_per_second))
    output_dir.mkdir(parents=True, exist_ok=True)
    source_id = hashlib.sha1(str(video_path.resolve()).encode()).hexdigest()[:8]
    previous_saved_hash: int | None = None
    frame_index = 0
    candidates = saved = blurry = duplicates = 0

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_index % sample_step != 0:
                frame_index += 1
                continue
            candidates += 1
            if not is_sharp(frame, blur_threshold):
                blurry += 1
                frame_index += 1
                continue
            current_hash = average_hash(frame)
            if (
                previous_saved_hash is not None
                and hash_distance(previous_saved_hash, current_hash)
                <= duplicate_distance
            ):
                duplicates += 1
                frame_index += 1
                continue
            output_path = output_dir / f"{video_path.stem}_{source_id}_{frame_index:07d}.jpg"
            if not cv2.imwrite(str(output_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 94]):
                raise RuntimeError(f"No se pudo guardar {output_path}")
            previous_saved_hash = current_hash
            saved += 1
            frame_index += 1
    finally:
        capture.release()

    return ExtractionStats(video_path, candidates, saved, blurry, duplicates)


def discover_videos(input_root: Path) -> list[tuple[str, str, Path]]:
    videos: list[tuple[str, str, Path]] = []
    for split in VALID_SPLITS:
        for class_name in VALID_CLASSES:
            class_dir = input_root / split / class_name
            if not class_dir.exists():
                continue
            for path in sorted(class_dir.iterdir()):
                if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
                    videos.append((split, class_name, path))
    return videos


def ensure_video_layout(input_root: Path) -> None:
    """Crea la estructura de entrada, incluso en un clon nuevo del repositorio."""
    for split in VALID_SPLITS:
        for class_name in VALID_CLASSES:
            (input_root / split / class_name).mkdir(parents=True, exist_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrae frames nítidos y no duplicados para tres productos"
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=PROJECT_ROOT / "training" / "videos",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "training" / "frames",
    )
    parser.add_argument("--samples-per-second", type=float, default=2.0)
    parser.add_argument("--blur-threshold", type=float, default=65.0)
    parser.add_argument("--duplicate-distance", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.samples_per_second <= 0:
        raise SystemExit("--samples-per-second debe ser mayor que cero")
    ensure_video_layout(args.input)
    videos = discover_videos(args.input)
    if not videos:
        print(f"No se encontraron videos en {args.input}")
        print("Revise training/README.md para ver la estructura esperada.")
        return 2

    total_saved = 0
    for split, class_name, video in videos:
        stats = extract_video(
            video,
            args.output / split / class_name,
            samples_per_second=args.samples_per_second,
            blur_threshold=args.blur_threshold,
            duplicate_distance=args.duplicate_distance,
        )
        total_saved += stats.saved
        print(
            f"[{split}/{class_name}] {video.name}: {stats.saved} guardados, "
            f"{stats.blurry} borrosos, {stats.duplicates} repetidos"
        )
    print(f"Total guardado: {total_saved} imágenes en {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
