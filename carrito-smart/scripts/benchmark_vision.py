"""Compara modelos YOLO con la misma webcam y parámetros de Carrito Smart."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from carrito_smart.config import AppConfig
from carrito_smart.detection_stabilizer import TemporalDetectionStabilizer
from carrito_smart.vision import LatestFrameBuffer, extract_detections


@dataclass(slots=True)
class BenchmarkResult:
    model: str
    duration_seconds: float
    camera_index: int
    requested_resolution: str
    actual_resolution: str
    target_camera_fps: float
    target_inference_fps: float
    target_ui_update_fps: float
    detection_threshold: float
    retention_threshold: float
    device: str
    capture_fps: float
    inference_fps: float
    average_latency_ms: float
    p95_latency_ms: float
    raw_detection_count: int
    confirmed_ui_updates: int
    ui_signature_changes: int
    ui_stability_percent: float
    errors: list[str]


class CaptureProducer(threading.Thread):
    def __init__(self, config: AppConfig, frames: LatestFrameBuffer) -> None:
        super().__init__(daemon=True)
        self.config = config
        self.frames = frames
        self.stop_event = threading.Event()
        self.ready = threading.Event()
        self.frame_count = 0
        self.actual_width = 0
        self.actual_height = 0
        self.errors: list[str] = []

    def run(self) -> None:
        capture = cv2.VideoCapture(self.config.camera_index)
        try:
            if not capture.isOpened():
                self.errors.append(
                    f"No se pudo abrir la webcam {self.config.camera_index}"
                )
                self.ready.set()
                return
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.camera_width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.camera_height)
            capture.set(cv2.CAP_PROP_FPS, self.config.camera_fps)
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            self.actual_width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.actual_height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            period = 1 / self.config.camera_fps
            next_capture_at = time.monotonic()
            sequence = 0
            while not self.stop_event.is_set():
                delay = next_capture_at - time.monotonic()
                if delay > 0 and self.stop_event.wait(delay):
                    break
                ok, frame = capture.read()
                captured_at = time.monotonic()
                next_capture_at = max(next_capture_at + period, captured_at)
                if not ok:
                    self.errors.append("La webcam no entregó un frame")
                    self.ready.set()
                    return
                sequence += 1
                self.frame_count += 1
                self.frames.update(frame, sequence, captured_at)
                self.ready.set()
        finally:
            capture.release()


def percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]


def benchmark_model(
    model_name: str,
    config: AppConfig,
    duration: float,
    warmup_inferences: int,
) -> BenchmarkResult:
    model = YOLO(model_name)
    device: str | int = 0 if torch.cuda.is_available() else "cpu"
    device_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
    synthetic = np.zeros(
        (config.camera_height, config.camera_width, 3), dtype=np.uint8
    )
    for _ in range(warmup_inferences):
        model.predict(
            synthetic,
            conf=config.retention_threshold,
            imgsz=config.inference_image_size,
            device=device,
            verbose=False,
        )

    frames = LatestFrameBuffer()
    producer = CaptureProducer(config, frames)
    producer.start()
    producer.ready.wait(timeout=8)
    errors = list(producer.errors)
    if frames.latest() is None:
        producer.stop_event.set()
        producer.join(timeout=3)
        return BenchmarkResult(
            model=model_name,
            duration_seconds=0,
            camera_index=config.camera_index,
            requested_resolution=f"{config.camera_width}x{config.camera_height}",
            actual_resolution="unavailable",
            target_camera_fps=config.camera_fps,
            target_inference_fps=config.inference_fps,
            target_ui_update_fps=config.ui_update_fps,
            detection_threshold=config.detection_threshold,
            retention_threshold=config.retention_threshold,
            device=device_name,
            capture_fps=0,
            inference_fps=0,
            average_latency_ms=0,
            p95_latency_ms=0,
            raw_detection_count=0,
            confirmed_ui_updates=0,
            ui_signature_changes=0,
            ui_stability_percent=0,
            errors=errors or ["No se recibió el primer frame"],
        )

    stabilizer = TemporalDetectionStabilizer(
        detection_threshold=config.detection_threshold,
        retention_threshold=config.retention_threshold,
        confirmation_count=config.confirmation_count,
        detection_hold_ms=config.detection_hold_ms,
        confidence_ema_alpha=config.confidence_ema_alpha,
    )
    inference_period = 1 / config.inference_fps
    ui_period = 1 / config.ui_update_fps
    started_at = time.monotonic()
    finish_at = started_at + duration
    next_inference_at = started_at
    next_ui_at = started_at
    initial_capture_count = producer.frame_count
    inference_count = 0
    raw_detection_count = 0
    latencies: list[float] = []
    ui_signatures: list[tuple[str, ...]] = []
    latest_stable = []

    try:
        while time.monotonic() < finish_at:
            delay = next_inference_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            snapshot = frames.latest()
            if snapshot is None:
                errors.append("Se perdió el buffer de captura")
                break
            inference_started = time.perf_counter()
            result = model.predict(
                snapshot.frame,
                conf=config.retention_threshold,
                imgsz=config.inference_image_size,
                device=device,
                verbose=False,
            )[0]
            completed_at = time.monotonic()
            latencies.append((time.perf_counter() - inference_started) * 1000)
            inference_count += 1
            raw = extract_detections(result)
            raw_detection_count += len(raw)
            latest_stable, _ = stabilizer.update(raw, now=completed_at)
            if completed_at >= next_ui_at:
                ui_signatures.append(
                    tuple(detection.class_name for detection in latest_stable)
                )
                next_ui_at = completed_at + ui_period
            next_inference_at = max(
                next_inference_at + inference_period, completed_at
            )
    except Exception as error:
        errors.append(f"{type(error).__name__}: {error}")
    finally:
        producer.stop_event.set()
        producer.join(timeout=5)
        errors.extend(producer.errors)

    elapsed = max(0.001, min(time.monotonic(), finish_at) - started_at)
    signature_changes = sum(
        current != previous
        for previous, current in zip(ui_signatures, ui_signatures[1:])
    )
    comparison_count = max(0, len(ui_signatures) - 1)
    stability = (
        100 * (1 - signature_changes / comparison_count)
        if comparison_count
        else 0
    )
    return BenchmarkResult(
        model=model_name,
        duration_seconds=elapsed,
        camera_index=config.camera_index,
        requested_resolution=f"{config.camera_width}x{config.camera_height}",
        actual_resolution=f"{producer.actual_width}x{producer.actual_height}",
        target_camera_fps=config.camera_fps,
        target_inference_fps=config.inference_fps,
        target_ui_update_fps=config.ui_update_fps,
        detection_threshold=config.detection_threshold,
        retention_threshold=config.retention_threshold,
        device=device_name,
        capture_fps=(producer.frame_count - initial_capture_count) / elapsed,
        inference_fps=inference_count / elapsed,
        average_latency_ms=fmean(latencies) if latencies else 0,
        p95_latency_ms=percentile_95(latencies),
        raw_detection_count=raw_detection_count,
        confirmed_ui_updates=sum(bool(signature) for signature in ui_signatures),
        ui_signature_changes=signature_changes,
        ui_stability_percent=stability,
        errors=sorted(set(errors)),
    )


def write_report(results: list[BenchmarkResult], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps([asdict(result) for result in results], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    markdown = output.with_suffix(".md")
    lines = [
        "# Comparación de visión",
        "",
        "| Modelo | Captura FPS | Inferencia FPS | Latencia media | P95 | Dispositivo | Estabilidad UI | Errores |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: | --- |",
    ]
    for result in results:
        lines.append(
            f"| {result.model} | {result.capture_fps:.2f} | "
            f"{result.inference_fps:.2f} | {result.average_latency_ms:.1f} ms | "
            f"{result.p95_latency_ms:.1f} ms | {result.device} | "
            f"{result.ui_stability_percent:.1f}% | "
            f"{'<br>'.join(result.errors) if result.errors else 'Ninguno'} |"
        )
    lines.extend(
        [
            "",
            "La estabilidad es el porcentaje de actualizaciones de texto consecutivas "
            "que conservaron el mismo conjunto de clases confirmadas. Debe interpretarse "
            "junto con `confirmed_ui_updates`; una escena sin detecciones no compara calidad.",
        ]
    )
    markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=30)
    parser.add_argument("--warmup-inferences", type=int, default=3)
    parser.add_argument(
        "--models", nargs="+", default=["yolo11n.pt", "yolo26n.pt"]
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = AppConfig.from_env()
    config.ensure_directories()
    os.environ.setdefault(
        "YOLO_CONFIG_DIR", str(config.data_dir / "ultralytics")
    )
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = args.output or config.log_dir / "benchmarks" / f"vision_{timestamp}.json"
    results = []
    for model_name in args.models:
        print(f"Comparando {model_name} durante {args.duration:.0f} s…", flush=True)
        result = benchmark_model(
            model_name, config, args.duration, args.warmup_inferences
        )
        results.append(result)
        print(json.dumps(asdict(result), indent=2, ensure_ascii=False), flush=True)
    write_report(results, output)
    print(f"Resultados: {output}")
    return 0 if all(not result.errors for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
