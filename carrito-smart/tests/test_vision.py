from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
import numpy as np
import time

from carrito_smart.config import AppConfig
from carrito_smart.vision import (
    InferenceWorker,
    LatestFrameBuffer,
    StableDetectionBuffer,
    extract_detections,
)


class FakeScalar:
    def __init__(self, value):
        self.value = value

    def item(self):
        return self.value


class FakeScalarList:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return self.values


class FakeBox:
    cls = [FakeScalar(1)]
    conf = [FakeScalar(0.875)]
    xyxy = [FakeScalarList([10.2, 20.4, 110.6, 220.8])]


class FakeResult:
    boxes = [FakeBox()]
    names = {1: "bicycle"}


def test_extract_detections_returns_simple_values():
    detections = extract_detections(FakeResult())

    assert len(detections) == 1
    assert detections[0].class_name == "bicycle"
    assert detections[0].confidence == 0.875
    assert detections[0].bbox == (10, 20, 111, 221)


class FakeYolo:
    loaded: list[str] = []

    def __init__(self, model_name):
        self.model_name = model_name
        self.loaded.append(model_name)


class FakeYoloE(FakeYolo):
    prompts: list[str] = []

    def set_classes(self, prompts):
        type(self).prompts = prompts


def test_loader_configures_yoloe_with_three_product_prompts(tmp_path):
    config = AppConfig.from_env()
    values = {
        field: getattr(config, field)
        for field in config.__dataclass_fields__
    }
    values.update(
        data_dir=tmp_path,
        log_dir=tmp_path,
        database_path=tmp_path / "test.db",
    )
    worker = InferenceWorker(
        AppConfig(**values), LatestFrameBuffer(), StableDetectionBuffer()
    )

    model, name = worker._load_model(FakeYolo, FakeYoloE)

    assert isinstance(model, FakeYoloE)
    assert name == "yoloe-26n-seg.pt"
    assert FakeYoloE.prompts == [
        "plastic water bottle", "aluminum soda can", "packet of chocolate"
    ]


def test_loader_falls_back_to_standard_yolo_when_yoloe_fails(tmp_path):
    class BrokenYoloE:
        def __init__(self, model_name):
            raise RuntimeError("download unavailable")

    config = AppConfig.from_env()
    values = {
        field: getattr(config, field)
        for field in config.__dataclass_fields__
    }
    values.update(
        data_dir=tmp_path,
        log_dir=tmp_path,
        database_path=tmp_path / "test.db",
    )
    worker = InferenceWorker(
        AppConfig(**values), LatestFrameBuffer(), StableDetectionBuffer()
    )

    model, name = worker._load_model(FakeYolo, BrokenYoloE)

    assert isinstance(model, FakeYolo)
    assert name == "yolo26n.pt"


def test_yoloe_and_coco_models_use_separate_thresholds(tmp_path):
    config = AppConfig.from_env()
    values = {
        field: getattr(config, field)
        for field in config.__dataclass_fields__
    }
    values.update(
        data_dir=tmp_path,
        log_dir=tmp_path,
        database_path=tmp_path / "test.db",
    )
    worker = InferenceWorker(
        AppConfig(**values), LatestFrameBuffer(), StableDetectionBuffer()
    )

    assert worker._thresholds_for_model("yoloe-26n-seg.pt") == (0.45, 0.25)
    assert worker._thresholds_for_model("yolo26n.pt") == (0.60, 0.45)
    assert worker._class_thresholds_for_model("yoloe-26n-seg.pt") == {
        "packet of chocolate": (0.30, 0.25)
    }
    assert worker._class_thresholds_for_model("yolo26n.pt") == {}
    assert worker._class_thresholds_for_model("yolo11n.pt") == {}


def test_chocolate_threshold_uses_named_prompt_not_position(monkeypatch, tmp_path):
    config = replace(
        AppConfig.from_env(), data_dir=tmp_path,
        yoloe_chocolate_bar_prompt="  custom wrapped chocolate  ",
    )
    # Una futura reordenación no debe transferir el umbral a otro producto.
    monkeypatch.setattr(AppConfig, "yoloe_prompts", property(lambda self: (
        self.yoloe_chocolate_bar_prompt.strip(),
        self.yoloe_water_bottle_prompt.strip(),
        self.yoloe_soda_can_prompt.strip(),
    )))
    worker = InferenceWorker(config, LatestFrameBuffer(), StableDetectionBuffer())

    assert worker._class_thresholds_for_model("yoloe-26n-seg.pt") == {
        "custom wrapped chocolate": (0.30, 0.25)
    }
    assert worker._class_thresholds_for_model("yolo26n.pt") == {}


def test_worker_applies_chocolate_override_and_lowest_prediction_floor(monkeypatch, tmp_path):
    import sys

    config = replace(
        AppConfig.from_env(), data_dir=tmp_path,
        yoloe_chocolate_bar_prompt="custom chocolate prompt",
        yoloe_chocolate_retention_threshold=0.20,
        inference_fps=1000, ui_update_fps=1000,
    )
    frames = LatestFrameBuffer()
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    frames.update(frame, sequence=1, captured_at=time.monotonic())
    recorded = []
    buffer = StableDetectionBuffer()
    monkeypatch.setattr(buffer, "update", lambda stable: recorded.append(stable))
    worker = InferenceWorker(config, frames, buffer)
    calls = []

    class FakeModel:
        def predict(self, **kwargs):
            calls.append(kwargs)
            frames.update(frame, sequence=len(calls) + 1, captured_at=time.monotonic())
            if len(calls) == 3:
                worker.request_stop()
            box = FakeBox()
            box.conf = [FakeScalar(0.32)]
            return [SimpleNamespace(boxes=[box], names={1: "custom chocolate prompt"})]

    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=None, YOLOE=None))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setattr(worker, "_load_model", lambda *_: (FakeModel(), "yoloe-26n-seg.pt"))
    worker.run()

    assert len(calls) == 3
    assert all(call["conf"] == 0.20 for call in calls)
    assert recorded[0] == recorded[1] == []
    assert len(recorded[2]) == 1
    assert recorded[2][0].class_name == "custom chocolate prompt"
    assert recorded[2][0].confidence == pytest.approx(0.32)
    assert recorded[-1] == []  # Limpieza al detener el worker.


def test_crossing_signal_is_not_limited_by_ui_refresh(monkeypatch, tmp_path):
    import sys
    config = replace(AppConfig.from_env(), data_dir=tmp_path, inference_fps=1000, ui_update_fps=.01)
    frames = LatestFrameBuffer()
    frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
    frames.update(frame, 1, 0)
    worker = InferenceWorker(config, frames, StableDetectionBuffer())
    calls, crossings, displayed = [], [], []
    worker.crossings_ready.connect(lambda batch: crossings.extend(batch))
    worker.detections_ready.connect(lambda batch: displayed.append(batch))

    class FakeModel:
        def predict(self, **kwargs):
            y = [100, 200, 380][len(calls)]
            calls.append(kwargs)
            frames.update(frame, len(calls) + 1, len(calls) * .125)
            if len(calls) == 3:
                worker.request_stop()
            box = FakeBox()
            box.xyxy = [FakeScalarList([450, y - 50, 550, y + 50])]
            return [SimpleNamespace(boxes=[box], names={1: "bottle"})]

    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=None, YOLOE=None))
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False)))
    monkeypatch.setattr(worker, "_load_model", lambda *_: (FakeModel(), "yolo26n.pt"))
    worker.run()
    assert len(calls) == 3
    assert len(displayed) == 1 and displayed[0] == []
    assert len(crossings) == 1 and crossings[0].action.value == "ENTRADA"


def test_sensor_policy_overlay_has_no_exit_lines():
    from carrito_smart.vision import draw_sensor_policy
    canvas = np.zeros((720, 1280, 3), dtype=np.uint8)
    draw_sensor_policy(canvas)
    assert np.any(canvas[:40])  # Solo el texto de la política de sensores.
    assert not np.any(canvas[40:])  # Sin líneas de salida al 25% / 35%.
