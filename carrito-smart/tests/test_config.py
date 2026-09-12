from __future__ import annotations

import pytest
from dataclasses import replace

from carrito_smart.config import AppConfig


def test_vision_defaults_are_centralized(monkeypatch, tmp_path):
    variables = (
        "CARRITO_SMART_CAMERA",
        "CARRITO_SMART_CAMERA_FPS",
        "CARRITO_SMART_INFERENCE_FPS",
        "CARRITO_SMART_UI_UPDATE_FPS",
        "CARRITO_SMART_DETECTION_THRESHOLD",
        "CARRITO_SMART_RETENTION_THRESHOLD",
        "CARRITO_SMART_CONFIRMATION_COUNT",
        "CARRITO_SMART_DETECTION_HOLD_MS",
        "CARRITO_SMART_CONFIDENCE_EMA_ALPHA",
        "CARRITO_SMART_CONFIDENCE",
        "CARRITO_SMART_YOLO_MODEL",
        "CARRITO_SMART_FALLBACK_MODEL",
        "CARRITO_SMART_SECONDARY_FALLBACK_MODEL",
        "CARRITO_SMART_VISION_SODA_CAN_SKU",
        "CARRITO_SMART_VISION_CHOCOLATE_BAR_SKU",
        "CARRITO_SMART_YOLOE_WATER_BOTTLE_PROMPT",
        "CARRITO_SMART_YOLOE_SODA_CAN_PROMPT",
        "CARRITO_SMART_YOLOE_CHOCOLATE_BAR_PROMPT",
        "CARRITO_SMART_YOLOE_DETECTION_THRESHOLD",
        "CARRITO_SMART_YOLOE_RETENTION_THRESHOLD",
        "CARRITO_SMART_YOLOE_CHOCOLATE_DETECTION_THRESHOLD",
        "CARRITO_SMART_YOLOE_CHOCOLATE_RETENTION_THRESHOLD",
    )
    for variable in variables:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("CARRITO_SMART_DATA_DIR", str(tmp_path))

    config = AppConfig.from_env()

    assert config.camera_index == 1
    assert config.camera_fps == 30
    assert config.inference_fps == 8
    assert config.ui_update_fps == 4
    assert config.detection_threshold == 0.60
    assert config.retention_threshold == 0.45
    assert config.confirmation_count == 3
    assert config.detection_hold_ms == 700
    assert config.confidence_ema_alpha == 0.30
    assert config.yolo_model == "yoloe-26n-seg.pt"
    assert config.fallback_yolo_model == "yolo26n.pt"
    assert config.secondary_fallback_yolo_model == "yolo11n.pt"
    assert config.rfid_enabled
    assert config.rfid_port == "AUTO"
    assert config.rfid_baud_rate == 9600
    assert config.rfid_reconnect_ms == 2000
    assert config.vision_auto_cart_enabled
    assert config.vision_bottle_sku == "CS-001"
    assert config.vision_soda_can_sku == "CS-002"
    assert config.vision_chocolate_bar_sku == "CS-006"
    assert config.yoloe_prompts == (
        "plastic water bottle",
        "aluminum soda can",
        "packet of chocolate",
    )
    assert config.yoloe_detection_threshold == 0.45
    assert config.yoloe_retention_threshold == 0.25
    assert config.yoloe_chocolate_detection_threshold == 0.30
    assert config.yoloe_chocolate_retention_threshold == 0.25


def test_chocolate_thresholds_are_configurable_and_independent(monkeypatch):
    monkeypatch.setenv("CARRITO_SMART_YOLOE_CHOCOLATE_DETECTION_THRESHOLD", "0.35")
    monkeypatch.setenv("CARRITO_SMART_YOLOE_CHOCOLATE_RETENTION_THRESHOLD", "0.20")
    config = AppConfig.from_env()
    assert config.yoloe_chocolate_detection_threshold == 0.35
    assert config.yoloe_chocolate_retention_threshold == 0.20
    assert config.yoloe_detection_threshold == 0.45
    assert config.yoloe_retention_threshold == 0.25


@pytest.mark.parametrize("accept,retain", [(0.2, 0.3), (1.1, 0.25), (0.3, -0.1)])
def test_invalid_chocolate_thresholds_are_rejected(accept, retain):
    with pytest.raises(ValueError, match="umbrales de chocolate"):
        replace(
            AppConfig.from_env(), yoloe_chocolate_detection_threshold=accept,
            yoloe_chocolate_retention_threshold=retain,
        )


def test_crossing_and_fusion_settings_are_configurable(monkeypatch):
    monkeypatch.setenv("CARRITO_SMART_FUSION_WINDOW_MS", "4000")
    monkeypatch.setenv("CARRITO_SMART_CROSSING_TOP_RATIO", ".20")
    monkeypatch.setenv("CARRITO_SMART_CROSSING_HYSTERESIS_RATIO", ".12")
    monkeypatch.setenv("CARRITO_SMART_CROSSING_EDGE_RATIO", ".04")
    monkeypatch.setenv("CARRITO_SMART_CROSSING_MATCH_DISTANCE", ".30")
    monkeypatch.setenv("CARRITO_SMART_VISION_STALE_MS", "2000")
    config = AppConfig.from_env()
    assert config.fusion_window_ms == 4000
    assert config.crossing_top_ratio == .20
    assert config.crossing_hysteresis_ratio == .12
    assert config.crossing_edge_ratio == .04
    assert config.crossing_match_distance == .30
    assert config.vision_stale_ms == 2000


@pytest.mark.parametrize("values", [
    {"fusion_window_ms": 500}, {"crossing_top_ratio": 1},
    {"crossing_hysteresis_ratio": -.1}, {"crossing_edge_ratio": .3},
    {"crossing_match_distance": 0}, {"vision_stale_ms": 100},
])
def test_invalid_fusion_config_is_rejected(values):
    with pytest.raises(ValueError):
        replace(AppConfig.from_env(), **values)


def test_invalid_hysteresis_is_rejected(tmp_path):
    config = AppConfig.from_env()
    values = {
        field: getattr(config, field)
        for field in config.__dataclass_fields__
    }
    values["data_dir"] = tmp_path
    values["database_path"] = tmp_path / "test.db"
    values["retention_threshold"] = 0.70
    values["detection_threshold"] = 0.60

    with pytest.raises(ValueError, match="retention"):
        AppConfig(**values)


def test_duplicate_yoloe_prompts_are_rejected(tmp_path):
    config = AppConfig.from_env()
    values = {
        field: getattr(config, field)
        for field in config.__dataclass_fields__
    }
    values["data_dir"] = tmp_path
    values["database_path"] = tmp_path / "test.db"
    values["yoloe_water_bottle_prompt"] = "same product"
    values["yoloe_soda_can_prompt"] = "SAME PRODUCT"

    with pytest.raises(ValueError, match="distintos"):
        AppConfig(**values)


def test_invalid_yoloe_hysteresis_is_rejected(tmp_path):
    config = AppConfig.from_env()
    values = {
        field: getattr(config, field)
        for field in config.__dataclass_fields__
    }
    values["data_dir"] = tmp_path
    values["database_path"] = tmp_path / "test.db"
    values["yoloe_detection_threshold"] = 0.30
    values["yoloe_retention_threshold"] = 0.40

    with pytest.raises(ValueError, match="umbrales YOLOE"):
        AppConfig(**values)
