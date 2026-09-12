"""Pipeline no bloqueante de cámara, inferencia y visualización estable."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from statistics import fmean
from typing import Any

import cv2
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QImage

from carrito_smart.config import AppConfig
from carrito_smart.vision_crossing import TopCrossingTracker
from carrito_smart.detection_stabilizer import (
    DetectionDecision,
    RawDetection,
    StableDetection,
)


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FrameSnapshot:
    frame: Any
    sequence: int
    captured_at: float


class LatestFrameBuffer:
    """Comparte solamente el frame más reciente; nunca crea una cola atrasada."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: FrameSnapshot | None = None

    def update(self, frame: Any, sequence: int, captured_at: float) -> None:
        with self._lock:
            self._snapshot = FrameSnapshot(frame, sequence, captured_at)

    def latest(self) -> FrameSnapshot | None:
        with self._lock:
            return self._snapshot


class StableDetectionBuffer:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._detections: tuple[StableDetection, ...] = ()

    def update(self, detections: list[StableDetection]) -> None:
        with self._lock:
            self._detections = tuple(detections)

    def latest(self) -> tuple[StableDetection, ...]:
        with self._lock:
            return self._detections


def extract_detections(result: Any) -> list[RawDetection]:
    """Convierte un resultado Ultralytics a valores simples e inmutables."""
    detections: list[RawDetection] = []
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return detections
    names = getattr(result, "names", {})
    for box in boxes:
        class_id = int(box.cls[0].item())
        confidence = float(box.conf[0].item())
        coordinates = box.xyxy[0].tolist()
        bbox = tuple(int(round(value)) for value in coordinates)
        detections.append(
            RawDetection(
                class_name=str(names.get(class_id, class_id)),
                confidence=confidence,
                bbox=bbox,
            )
        )
    return detections


class CameraWorker(QObject):
    """Captura a camera_fps y emite video fluido con el último overlay estable."""

    frame_ready = Signal(QImage)
    status_changed = Signal(str)
    metrics_ready = Signal(dict)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        config: AppConfig,
        frames: LatestFrameBuffer,
        stable_detections: StableDetectionBuffer,
    ) -> None:
        super().__init__()
        self.config = config
        self.frames = frames
        self.stable_detections = stable_detections
        self._stop_event = threading.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    @Slot()
    def run(self) -> None:
        capture = None
        try:
            self.status_changed.emit("Abriendo webcam…")
            capture = cv2.VideoCapture(self.config.camera_index)
            if not capture.isOpened():
                raise RuntimeError(
                    f"No se pudo abrir la webcam {self.config.camera_index}. "
                    "Compruebe permisos y que ninguna otra aplicación la esté usando."
                )
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.camera_width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera_height)
            capture.set(cv2.CAP_PROP_FPS, self.config.camera_fps)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            actual_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            actual_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self.status_changed.emit("Webcam activa; preparando YOLO…")
            LOGGER.info(
                "Captura iniciada: camera=%s requested=%sx%s@%.1f actual=%sx%s",
                self.config.camera_index,
                self.config.camera_width,
                self.config.camera_height,
                self.config.camera_fps,
                actual_width,
                actual_height,
            )

            period = 1 / self.config.camera_fps
            next_capture_at = time.monotonic()
            metrics_started_at = next_capture_at
            frames_since_metrics = 0
            sequence = 0
            failures = 0

            while not self._stop_event.is_set():
                delay = next_capture_at - time.monotonic()
                if delay > 0 and self._stop_event.wait(delay):
                    break
                ok, frame = capture.read()
                captured_at = time.monotonic()
                next_capture_at = max(next_capture_at + period, captured_at)
                if not ok:
                    failures += 1
                    if failures >= 20:
                        raise RuntimeError("La webcam dejó de entregar imágenes")
                    continue

                failures = 0
                sequence += 1
                frames_since_metrics += 1
                self.frames.update(frame, sequence, captured_at)
                annotated = draw_stable_detections(
                    frame, self.stable_detections.latest()
                )
                draw_sensor_policy(annotated)
                self.frame_ready.emit(frame_to_qimage(annotated))

                metrics_elapsed = captured_at - metrics_started_at
                if metrics_elapsed >= 1:
                    self.metrics_ready.emit(
                        {
                            "capture_fps": frames_since_metrics / metrics_elapsed,
                            "capture_resolution": f"{actual_width}x{actual_height}",
                        }
                    )
                    metrics_started_at = captured_at
                    frames_since_metrics = 0
        except Exception as error:
            message = str(error) or type(error).__name__
            LOGGER.exception("La captura se detuvo: %s", message)
            self.failed.emit(message)
        finally:
            if capture is not None:
                capture.release()
            LOGGER.info("Captura detenida")
            self.finished.emit()


class InferenceWorker(QObject):
    """Ejecuta YOLO con reloj propio y publica únicamente estado estabilizado."""

    detections_ready = Signal(list)
    crossings_ready = Signal(list)
    observation_ready = Signal(float)
    status_changed = Signal(str)
    metrics_ready = Signal(dict)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        config: AppConfig,
        frames: LatestFrameBuffer,
        stable_detections: StableDetectionBuffer,
    ) -> None:
        super().__init__()
        self.config = config
        self.frames = frames
        self.stable_detections = stable_detections
        self._stop_event = threading.Event()
        self._reset_crossings = threading.Event()

    def reset_crossings(self) -> None:
        self._reset_crossings.set()

    def request_stop(self) -> None:
        self._stop_event.set()

    @Slot()
    def run(self) -> None:
        try:
            yolo_config_dir = self.config.data_dir / "ultralytics"
            yolo_config_dir.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("YOLO_CONFIG_DIR", str(yolo_config_dir))
            from ultralytics import YOLO, YOLOE
            import torch

            model, model_name = self._load_model(YOLO, YOLOE)
            detection_threshold, retention_threshold = (
                self._thresholds_for_model(model_name)
            )
            class_thresholds = self._class_thresholds_for_model(model_name)
            # El filtro del modelo no debe eliminar lecturas válidas de una clase.
            prediction_threshold = min(
                [retention_threshold]
                + [retain for _, retain in class_thresholds.values()]
            )
            device: str | int = 0 if torch.cuda.is_available() else "cpu"
            device_name = (
                torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
            )
            self.status_changed.emit(
                f"Webcam y {model_name} activos · {device_name}"
            )
            LOGGER.info(
                "Inferencia iniciada: model=%s device=%s target_fps=%.1f "
                "imgsz=%s accept=%.2f retain=%.2f class_thresholds=%s predict_conf=%.2f",
                model_name,
                device_name,
                self.config.inference_fps,
                self.config.inference_image_size,
                detection_threshold,
                retention_threshold,
                class_thresholds,
                prediction_threshold,
            )

            stabilizer = TopCrossingTracker(
                detection_threshold=detection_threshold,
                retention_threshold=retention_threshold,
                confirmation_count=self.config.confirmation_count,
                detection_hold_ms=self.config.detection_hold_ms,
                confidence_ema_alpha=self.config.confidence_ema_alpha,
                class_thresholds=class_thresholds,
                match_distance=self.config.crossing_match_distance,
            )
            inference_period = 1 / self.config.inference_fps
            ui_period = 1 / self.config.ui_update_fps
            next_inference_at = time.monotonic()
            last_ui_emit_at = float("-inf")
            metrics_started_at = time.monotonic()
            inference_count = 0
            latencies_ms: list[float] = []
            last_sequence = -1

            while not self._stop_event.is_set():
                delay = next_inference_at - time.monotonic()
                if delay > 0 and self._stop_event.wait(delay):
                    break
                snapshot = self.frames.latest()
                if snapshot is None or snapshot.sequence == last_sequence:
                    next_inference_at = time.monotonic() + 0.02
                    continue
                last_sequence = snapshot.sequence
                if self._reset_crossings.is_set():
                    stabilizer.reset()
                    self._reset_crossings.clear()

                started_at = time.perf_counter()
                result = model.predict(
                    source=snapshot.frame,
                    conf=prediction_threshold,
                    imgsz=self.config.inference_image_size,
                    device=device,
                    agnostic_nms=True,
                    verbose=False,
                )[0]
                finished_at = time.monotonic()
                latency_ms = (time.perf_counter() - started_at) * 1000
                inference_count += 1
                latencies_ms.append(latency_ms)
                raw_detections = extract_detections(result)
                self._log_raw_detections(raw_detections)
                height, width = snapshot.frame.shape[:2]
                stable, crossings, decisions = stabilizer.update(
                    raw_detections, width=width, height=height, now=snapshot.captured_at,
                )
                self._log_decisions(decisions)
                self.stable_detections.update(stable)
                self.observation_ready.emit(snapshot.captured_at)
                if crossings:
                    for crossing in crossings:
                        LOGGER.info("Evento visual de entrada: %s", crossing)
                    self.crossings_ready.emit(crossings)

                if finished_at - last_ui_emit_at >= ui_period:
                    self.detections_ready.emit(
                        [detection.as_dict() for detection in stable]
                    )
                    last_ui_emit_at = finished_at

                metrics_elapsed = finished_at - metrics_started_at
                if metrics_elapsed >= 1:
                    self.metrics_ready.emit(
                        {
                            "inference_fps": inference_count / metrics_elapsed,
                            "latency_ms": fmean(latencies_ms),
                            "device": device_name,
                            "model": model_name,
                        }
                    )
                    metrics_started_at = finished_at
                    inference_count = 0
                    latencies_ms.clear()

                next_inference_at = max(
                    next_inference_at + inference_period, finished_at
                )
        except Exception as error:
            message = str(error) or type(error).__name__
            LOGGER.exception("La inferencia se detuvo: %s", message)
            self.failed.emit(message)
        finally:
            self.stable_detections.update([])
            LOGGER.info("Inferencia detenida")
            self.finished.emit()

    def _load_model(
        self, yolo_class: Any, yoloe_class: Any
    ) -> tuple[Any, str]:
        candidates = list(
            dict.fromkeys(
                (
                    self.config.yolo_model,
                    self.config.fallback_yolo_model,
                    self.config.secondary_fallback_yolo_model,
                )
            )
        )
        last_error: Exception | None = None
        for model_name in candidates:
            try:
                self.status_changed.emit(f"Cargando {model_name}…")
                if self._is_yoloe_model(model_name):
                    model = yoloe_class(model_name)
                    self.status_changed.emit("Preparando clases de productos…")
                    prompts = list(self.config.yoloe_prompts)
                    model.set_classes(prompts)
                    LOGGER.info(
                        "YOLOE configurado: model=%s prompts=%s",
                        model_name,
                        prompts,
                    )
                else:
                    model = yolo_class(model_name)
                return model, model_name
            except Exception as error:
                last_error = error
                LOGGER.exception("No se pudo cargar el modelo %s", model_name)
                if model_name != candidates[-1]:
                    LOGGER.warning(
                        "Intentando modelo fallback %s",
                        candidates[candidates.index(model_name) + 1],
                    )
        assert last_error is not None
        raise last_error

    @staticmethod
    def _is_yoloe_model(model_name: str) -> bool:
        normalized = os.path.basename(model_name).casefold()
        return normalized.startswith("yoloe-")

    def _thresholds_for_model(self, model_name: str) -> tuple[float, float]:
        """Usa umbrales calibrados para YOLOE sin alterar los fallbacks COCO."""
        if self._is_yoloe_model(model_name):
            return (
                self.config.yoloe_detection_threshold,
                self.config.yoloe_retention_threshold,
            )
        return (
            self.config.detection_threshold,
            self.config.retention_threshold,
        )

    def _class_thresholds_for_model(
        self, model_name: str
    ) -> dict[str, tuple[float, float]]:
        """Ajuste de chocolate separado de botella, lata y fallbacks COCO."""
        if not self._is_yoloe_model(model_name):
            return {}
        return {
            self.config.yoloe_prompts[2]: (
                self.config.yoloe_chocolate_detection_threshold,
                self.config.yoloe_chocolate_retention_threshold,
            )
        }

    @staticmethod
    def _log_raw_detections(detections: list[RawDetection]) -> None:
        if not detections:
            LOGGER.info("Detección cruda: ninguna")
            return
        for detection in detections:
            LOGGER.info(
                "Detección cruda: class=%s raw_confidence=%.3f bbox=%s",
                detection.class_name,
                detection.confidence,
                detection.bbox,
            )

    @staticmethod
    def _log_decisions(decisions: list[DetectionDecision]) -> None:
        for decision in decisions:
            LOGGER.info(
                "Estabilización: class=%s decision=%s raw=%s smoothed=%s reason=%s",
                decision.class_name,
                decision.decision,
                (
                    f"{decision.raw_confidence:.3f}"
                    if decision.raw_confidence is not None
                    else "none"
                ),
                (
                    f"{decision.smoothed_confidence:.3f}"
                    if decision.smoothed_confidence is not None
                    else "none"
                ),
                decision.reason,
            )


def draw_stable_detections(
    frame: Any, detections: tuple[StableDetection, ...]
) -> Any:
    canvas = frame.copy()
    height, width = canvas.shape[:2]
    for detection in detections:
        x1, y1, x2, y2 = detection.bbox
        x1, x2 = sorted((max(0, min(x1, width - 1)), max(0, min(x2, width - 1))))
        y1, y2 = sorted((max(0, min(y1, height - 1)), max(0, min(y2, height - 1))))
        color = (0, 180, 255) if detection.held else (50, 205, 50)
        state = " · retenida" if detection.held else ""
        label = f"{detection.class_name} {detection.confidence:.0%}{state}"
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        (text_width, text_height), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.58, 2
        )
        label_top = max(0, y1 - text_height - baseline - 8)
        cv2.rectangle(
            canvas,
            (x1, label_top),
            (min(width - 1, x1 + text_width + 8), y1),
            color,
            -1,
        )
        cv2.putText(
            canvas,
            label,
            (x1 + 4, max(text_height, y1 - baseline - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (15, 20, 25),
            2,
            cv2.LINE_AA,
        )
    return canvas


def draw_sensor_policy(canvas: Any) -> None:
    """Texto sobre una copia, sin zonas de salida ni cambios a la entrada de YOLO."""
    cv2.putText(canvas, "ENTRADA: aparicion + RFID | SALIDA: solo RFID",
                (10, 22), cv2.FONT_HERSHEY_SIMPLEX, .5, (255, 220, 50), 1, cv2.LINE_AA)


def frame_to_qimage(frame: Any) -> QImage:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, channels = rgb.shape
    return QImage(
        rgb.data,
        width,
        height,
        channels * width,
        QImage.Format.Format_RGB888,
    ).copy()
