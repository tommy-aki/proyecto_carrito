"""Prueba local acotada de webcam; no abre SQLite ni modifica el carrito."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from carrito_smart.config import AppConfig
from carrito_smart.detection_stabilizer import TemporalDetectionStabilizer
from carrito_smart.vision import (
    CameraWorker, InferenceWorker, LatestFrameBuffer, StableDetectionBuffer,
    draw_stable_detections, extract_detections,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=12)
    parser.add_argument("--label", default="chocolate")
    args = parser.parse_args()
    if not 0 < args.seconds <= 60:
        parser.error("La duración debe estar entre 0 y 60 segundos")

    config = AppConfig.from_env()
    os.environ.setdefault("YOLO_CONFIG_DIR", str(config.data_dir / "ultralytics"))
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    import cv2
    import torch
    from ultralytics import YOLO, YOLOE

    frames, stable_buffer = LatestFrameBuffer(), StableDetectionBuffer()
    loader = InferenceWorker(config, frames, stable_buffer)
    print("Cargando el modelo configurado...", flush=True)
    model, model_name = loader._load_model(YOLO, YOLOE)
    acceptance, retention = loader._thresholds_for_model(model_name)
    overrides = loader._class_thresholds_for_model(model_name)
    predictor_threshold = min([retention] + [pair[1] for pair in overrides.values()])
    stabilizer = TemporalDetectionStabilizer(
        detection_threshold=acceptance, retention_threshold=retention,
        confirmation_count=config.confirmation_count,
        detection_hold_ms=config.detection_hold_ms,
        confidence_ema_alpha=config.confidence_ema_alpha,
        class_thresholds=overrides,
    )
    device = 0 if torch.cuda.is_available() else "cpu"
    output = config.log_dir / "chocolate_webcam" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    output.mkdir(parents=True, exist_ok=False)
    camera = CameraWorker(config, frames, stable_buffer)
    thread = threading.Thread(target=camera.run, daemon=True)
    records = []
    best_confidence = -1.0
    last_sequence = -1
    print(f"Prueba de {args.seconds:g} s; evidencia: {output}", flush=True)
    thread.start()
    try:
        deadline = time.monotonic() + 8
        while frames.latest() is None:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("La webcam no entregó imágenes")
            time.sleep(0.02)
        # Permitir que la exposición automática se acomode antes de medir.
        time.sleep(1)
        started = time.monotonic()
        next_at = started
        while time.monotonic() - started < args.seconds:
            time.sleep(max(0, next_at - time.monotonic()))
            snapshot = frames.latest()
            if snapshot is None or snapshot.sequence == last_sequence:
                next_at = time.monotonic() + 0.01
                continue
            last_sequence = snapshot.sequence
            before = time.monotonic()
            result = model.predict(
                snapshot.frame, conf=predictor_threshold,
                imgsz=config.inference_image_size, device=device,
                agnostic_nms=True, verbose=False,
            )[0]
            finished = time.monotonic()
            raw = extract_detections(result)
            stable, decisions = stabilizer.update(raw, now=finished)
            stable_buffer.update(stable)
            records.append({
                "seconds": finished - started,
                "sequence": snapshot.sequence,
                "latency_ms": (finished - before) * 1000,
                "raw": [asdict(item) for item in raw],
                "stable": [asdict(item) for item in stable],
                "decisions": [asdict(item) for item in decisions],
            })
            if len(records) == 1:
                cv2.imwrite(str(output / "first.jpg"), snapshot.frame)
            chocolate_conf = max(
                (item.confidence for item in raw if item.class_name == config.yoloe_prompts[2]),
                default=0,
            )
            if chocolate_conf > best_confidence:
                best_confidence = chocolate_conf
                cv2.imwrite(str(output / "best-raw.jpg"), snapshot.frame)
                cv2.imwrite(str(output / "best-detections.jpg"), result.plot(masks=False))
            if stable and not (output / "confirmed.jpg").exists():
                cv2.imwrite(str(output / "confirmed.jpg"), draw_stable_detections(snapshot.frame, tuple(stable)))
            next_at = max(next_at + 1 / config.inference_fps, finished)
        elapsed = time.monotonic() - started
        summary = {
            "label": args.label, "model": model_name, "device": str(device),
            "camera": config.camera_index,
            "resolution": list(snapshot.frame.shape[1::-1]),
            "imgsz": config.inference_image_size,
            "target_inference_fps": config.inference_fps,
            "accept": acceptance, "retain": retention,
            "class_thresholds": overrides,
            "elapsed_seconds": elapsed, "inferences": len(records),
            "inference_fps": len(records) / elapsed,
            "mean_latency_ms": sum(row["latency_ms"] for row in records) / len(records),
            "best_chocolate_confidence": best_confidence,
            "chocolate_confirmed_frames": sum(
                any(item["class_name"] == config.yoloe_prompts[2] for item in row["stable"])
                for row in records
            ),
        }
        (output / "results.json").write_text(
            json.dumps({"summary": summary, "frames": records}, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary, indent=2), flush=True)
    finally:
        camera.request_stop()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
