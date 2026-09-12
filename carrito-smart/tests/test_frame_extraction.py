from __future__ import annotations

import cv2
import numpy as np

from scripts.extract_training_frames import (
    VALID_CLASSES,
    VALID_SPLITS,
    average_hash,
    discover_videos,
    ensure_video_layout,
    hash_distance,
    is_sharp,
)


def test_image_helpers_identify_similarity_and_blur():
    sharp = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.rectangle(sharp, (20, 20), (140, 100), (255, 255, 255), 3)
    blurry = cv2.GaussianBlur(sharp, (31, 31), 0)

    assert hash_distance(average_hash(sharp), average_hash(sharp.copy())) == 0
    assert is_sharp(sharp, 65)
    assert not is_sharp(blurry, 65)


def test_discover_videos_uses_expected_structure(tmp_path):
    video = tmp_path / "train" / "pepsi_lata" / "sesion.mp4"
    video.parent.mkdir(parents=True)
    video.touch()
    ignored = video.parent / "notas.txt"
    ignored.touch()

    assert discover_videos(tmp_path) == [("train", "pepsi_lata", video)]


def test_ensure_video_layout_creates_all_expected_directories(tmp_path):
    ensure_video_layout(tmp_path)

    for split in VALID_SPLITS:
        for class_name in VALID_CLASSES:
            assert (tmp_path / split / class_name).is_dir()
