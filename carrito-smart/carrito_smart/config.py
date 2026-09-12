"""Configuración central de la aplicación."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True, slots=True)
class AppConfig:
    data_dir: Path
    log_dir: Path
    database_path: Path
    camera_index: int
    yolo_model: str
    fallback_yolo_model: str
    camera_width: int
    camera_height: int
    camera_fps: float
    inference_fps: float
    ui_update_fps: float
    detection_threshold: float
    retention_threshold: float
    confirmation_count: int
    detection_hold_ms: int
    confidence_ema_alpha: float
    inference_image_size: int
    rfid_enabled: bool = True
    rfid_port: str = "AUTO"
    rfid_baud_rate: int = 9600
    rfid_reconnect_ms: int = 2000
    vision_auto_cart_enabled: bool = True
    vision_bottle_sku: str = "CS-001"
    vision_soda_can_sku: str = "CS-002"
    yoloe_water_bottle_prompt: str = "plastic water bottle"
    yoloe_soda_can_prompt: str = "aluminum soda can"
    yoloe_detection_threshold: float = 0.45
    yoloe_retention_threshold: float = 0.25
    secondary_fallback_yolo_model: str = "yolo11n.pt"
    vision_chocolate_bar_sku: str = "CS-006"
    yoloe_chocolate_bar_prompt: str = "packet of chocolate"
    yoloe_chocolate_detection_threshold: float = 0.30
    yoloe_chocolate_retention_threshold: float = 0.25
    fusion_window_ms: int = 3000
    # Compatibilidad con configuraciones anteriores; ya no controlan salidas.
    crossing_top_ratio: float = 0.25
    crossing_hysteresis_ratio: float = 0.10
    crossing_edge_ratio: float = 0.06
    crossing_match_distance: float = 0.25
    vision_stale_ms: int = 2500

    def __post_init__(self) -> None:
        if self.fusion_window_ms <= self.detection_hold_ms:
            raise ValueError("fusion_window_ms debe superar detection_hold_ms")
        if not (0 < self.crossing_edge_ratio < self.crossing_top_ratio < 1):
            raise ValueError("Cruce: 0 < edge_ratio < top_ratio < 1")
        if not 0 < self.crossing_hysteresis_ratio < 1 - self.crossing_top_ratio:
            raise ValueError("crossing_hysteresis_ratio fuera de rango")
        if not 0 < self.crossing_match_distance < 1:
            raise ValueError("crossing_match_distance fuera de rango")
        if self.vision_stale_ms < 500:
            raise ValueError("vision_stale_ms debe ser al menos 500")
        if min(self.camera_fps, self.inference_fps, self.ui_update_fps) <= 0:
            raise ValueError("Las frecuencias deben ser mayores que cero")
        if not 0 <= self.retention_threshold <= self.detection_threshold <= 1:
            raise ValueError(
                "Los umbrales deben cumplir 0 <= retention <= detection <= 1"
            )
        if self.confirmation_count < 1:
            raise ValueError("confirmation_count debe ser al menos 1")
        if self.detection_hold_ms < 0:
            raise ValueError("detection_hold_ms no puede ser negativo")
        if not 0 < self.confidence_ema_alpha <= 1:
            raise ValueError("confidence_ema_alpha debe estar entre 0 y 1")
        if self.rfid_baud_rate <= 0:
            raise ValueError("rfid_baud_rate debe ser mayor que cero")
        if self.rfid_reconnect_ms < 100:
            raise ValueError("rfid_reconnect_ms debe ser al menos 100")
        prompts = tuple(prompt.strip() for prompt in self.yoloe_prompts)
        if not all(prompts):
            raise ValueError("Los textos de búsqueda de YOLOE no pueden estar vacíos")
        if len({prompt.casefold() for prompt in prompts}) != len(prompts):
            raise ValueError("Los textos de búsqueda de YOLOE deben ser distintos")
        if not (
            0
            <= self.yoloe_retention_threshold
            <= self.yoloe_detection_threshold
            <= 1
        ):
            raise ValueError(
                "Los umbrales YOLOE deben cumplir 0 <= retention <= detection <= 1"
            )
        if not (
            0
            <= self.yoloe_chocolate_retention_threshold
            <= self.yoloe_chocolate_detection_threshold
            <= 1
        ):
            raise ValueError(
                "Los umbrales de chocolate deben cumplir "
                "0 <= retention <= detection <= 1"
            )

    @classmethod
    def from_env(cls) -> "AppConfig":
        data_dir = Path(os.getenv("CARRITO_SMART_DATA_DIR", PROJECT_ROOT / "data"))
        log_dir = Path(os.getenv("CARRITO_SMART_LOG_DIR", PROJECT_ROOT / "logs"))
        return cls(
            data_dir=data_dir,
            log_dir=log_dir,
            database_path=data_dir / "carrito_smart.db",
            camera_index=int(os.getenv("CARRITO_SMART_CAMERA", "1")),
            yolo_model=os.getenv(
                "CARRITO_SMART_YOLO_MODEL", "yoloe-26n-seg.pt"
            ),
            fallback_yolo_model=os.getenv(
                "CARRITO_SMART_FALLBACK_MODEL", "yolo26n.pt"
            ),
            camera_width=int(os.getenv("CARRITO_SMART_CAMERA_WIDTH", "1280")),
            camera_height=int(os.getenv("CARRITO_SMART_CAMERA_HEIGHT", "720")),
            camera_fps=float(os.getenv("CARRITO_SMART_CAMERA_FPS", "30")),
            inference_fps=float(os.getenv("CARRITO_SMART_INFERENCE_FPS", "8")),
            ui_update_fps=float(os.getenv("CARRITO_SMART_UI_UPDATE_FPS", "4")),
            detection_threshold=float(
                os.getenv(
                    "CARRITO_SMART_DETECTION_THRESHOLD",
                    os.getenv("CARRITO_SMART_CONFIDENCE", "0.60"),
                )
            ),
            retention_threshold=float(
                os.getenv("CARRITO_SMART_RETENTION_THRESHOLD", "0.45")
            ),
            confirmation_count=int(
                os.getenv("CARRITO_SMART_CONFIRMATION_COUNT", "3")
            ),
            detection_hold_ms=int(
                os.getenv("CARRITO_SMART_DETECTION_HOLD_MS", "700")
            ),
            confidence_ema_alpha=float(
                os.getenv("CARRITO_SMART_CONFIDENCE_EMA_ALPHA", "0.30")
            ),
            inference_image_size=int(
                os.getenv("CARRITO_SMART_INFERENCE_IMAGE_SIZE", "640")
            ),
            rfid_enabled=os.getenv("CARRITO_SMART_RFID_ENABLED", "1").strip().lower()
            not in {"0", "false", "no", "off"},
            rfid_port=os.getenv("CARRITO_SMART_RFID_PORT", "AUTO"),
            rfid_baud_rate=int(os.getenv("CARRITO_SMART_RFID_BAUD_RATE", "9600")),
            rfid_reconnect_ms=int(
                os.getenv("CARRITO_SMART_RFID_RECONNECT_MS", "2000")
            ),
            vision_auto_cart_enabled=os.getenv(
                "CARRITO_SMART_VISION_AUTO_CART", "1"
            ).strip().lower()
            not in {"0", "false", "no", "off"},
            vision_bottle_sku=os.getenv(
                "CARRITO_SMART_VISION_BOTTLE_SKU", "CS-001"
            ),
            vision_soda_can_sku=os.getenv(
                "CARRITO_SMART_VISION_SODA_CAN_SKU", "CS-002"
            ),
            vision_chocolate_bar_sku=os.getenv(
                "CARRITO_SMART_VISION_CHOCOLATE_BAR_SKU", "CS-006"
            ),
            yoloe_water_bottle_prompt=os.getenv(
                "CARRITO_SMART_YOLOE_WATER_BOTTLE_PROMPT",
                "plastic water bottle",
            ),
            yoloe_soda_can_prompt=os.getenv(
                "CARRITO_SMART_YOLOE_SODA_CAN_PROMPT",
                "aluminum soda can",
            ),
            yoloe_chocolate_bar_prompt=os.getenv(
                "CARRITO_SMART_YOLOE_CHOCOLATE_BAR_PROMPT", "packet of chocolate"
            ),
            yoloe_detection_threshold=float(
                os.getenv("CARRITO_SMART_YOLOE_DETECTION_THRESHOLD", "0.45")
            ),
            yoloe_retention_threshold=float(
                os.getenv("CARRITO_SMART_YOLOE_RETENTION_THRESHOLD", "0.25")
            ),
            yoloe_chocolate_detection_threshold=float(
                os.getenv("CARRITO_SMART_YOLOE_CHOCOLATE_DETECTION_THRESHOLD", "0.30")
            ),
            yoloe_chocolate_retention_threshold=float(
                os.getenv("CARRITO_SMART_YOLOE_CHOCOLATE_RETENTION_THRESHOLD", "0.25")
            ),
            secondary_fallback_yolo_model=os.getenv(
                "CARRITO_SMART_SECONDARY_FALLBACK_MODEL", "yolo11n.pt"
            ),
            fusion_window_ms=int(os.getenv("CARRITO_SMART_FUSION_WINDOW_MS", "3000")),
            crossing_top_ratio=float(os.getenv("CARRITO_SMART_CROSSING_TOP_RATIO", "0.25")),
            crossing_hysteresis_ratio=float(os.getenv("CARRITO_SMART_CROSSING_HYSTERESIS_RATIO", "0.10")),
            crossing_edge_ratio=float(os.getenv("CARRITO_SMART_CROSSING_EDGE_RATIO", "0.06")),
            crossing_match_distance=float(os.getenv("CARRITO_SMART_CROSSING_MATCH_DISTANCE", "0.25")),
            vision_stale_ms=int(os.getenv("CARRITO_SMART_VISION_STALE_MS", "2500")),
        )

    @property
    def yoloe_prompts(self) -> tuple[str, ...]:
        """Clases abiertas que YOLOE buscará en la cámara."""
        return (
            self.yoloe_water_bottle_prompt.strip(),
            self.yoloe_soda_can_prompt.strip(),
            self.yoloe_chocolate_bar_prompt.strip(),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
