"""Compara textos YOLOE sobre las mismas fotos, sin entrenar ni abrir la webcam."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import cv2

from carrito_smart.config import AppConfig


DEFAULT_PROMPTS = (
    "chocolate bar",
    "wrapped chocolate bar",
    "candy bar",
    "chocolate bar in a wrapper",
    "packaged chocolate bar",
    "chocolate packaging",
    "chocolate packet",
    "candy bar wrapper",
    "chocolate tablet",
    "packaged chocolate tablet",
    "chocolate bar in brown and turquoise packaging",
    "Tutto chocolate bar",
    "chocolate package",
    "packaged chocolate",
    "packet of chocolate",
    "chocolate bar packaging",
    "chocolate wrapper",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--prompts", nargs="+", default=DEFAULT_PROMPTS)
    parser.add_argument("--imgsz", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = AppConfig.from_env()
    os.environ.setdefault("YOLO_CONFIG_DIR", str(config.data_dir / "ultralytics"))
    os.environ.setdefault("YOLO_AUTOINSTALL", "false")
    from ultralytics import YOLOE
    import torch

    output = args.output or (
        config.log_dir / "prompt_comparisons" / datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    output.mkdir(parents=True, exist_ok=False)
    images = []
    for path in args.images:
        frame = cv2.imread(str(path))
        if frame is None:
            raise ValueError(f"No se pudo leer la foto: {path}")
        images.append((path, frame))
    fixed = list(config.yoloe_prompts[:2])
    prompts = list(dict.fromkeys(args.prompts))
    # Codificar una vez y recargar los pesos antes de cada comparación evita
    # reutilizar un predictor cuyo clasificador ya fue fusionado con otro texto.
    encoder = YOLOE(config.yolo_model)
    embeddings = encoder.get_text_pe(fixed + prompts)
    del encoder
    device = 0 if torch.cuda.is_available() else "cpu"
    image_size = args.imgsz or config.inference_image_size
    report = {
        "model": config.yolo_model,
        "device": device,
        "imgsz": image_size,
        "fixed_prompts": fixed,
        "diagnostic_confidence_floor": 0.05,
        "app_accept_threshold": config.yoloe_detection_threshold,
        "app_retain_threshold": config.yoloe_retention_threshold,
        "note": "Fotografías de diagnóstico; no mide precisión ni estabilidad en video.",
        "results": [],
    }
    for prompt_index, prompt in enumerate(prompts):
        model = YOLOE(config.yolo_model)
        indices = [0, 1, prompt_index + 2]
        model.set_classes(fixed + [prompt], embeddings=embeddings[:, indices, :].clone())
        for image_index, (path, frame) in enumerate(images):
            result = model.predict(
                frame, conf=0.05, imgsz=image_size, device=device,
                agnostic_nms=True, verbose=False,
            )[0]
            detections = []
            for box in result.boxes:
                confidence = float(box.conf[0])
                detections.append({
                    "class_name": result.names[int(box.cls[0])],
                    "confidence": confidence,
                    "bbox": box.xyxy[0].tolist(),
                    "above_accept_threshold": confidence >= config.yoloe_detection_threshold,
                })
            report["results"].append({
                "prompt": prompt,
                "image": str(path.resolve()),
                "shape": list(frame.shape),
                "detections": detections,
            })
            # Solo dibujar candidatos del producto investigado; las predicciones
            # de botella/lata se conservan en el JSON para revisar confusiones.
            target = result[result.boxes.cls == 2]
            if len(target.boxes):
                target.save(str(output / f"prompt-{prompt_index:02d}-image-{image_index:02d}.jpg"))
            print(json.dumps({
                "prompt": prompt, "image": path.name,
                "detections": detections,
            }, ensure_ascii=True), flush=True)
        del model
    report_path = output / "results.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"REPORT {report_path.resolve()}", flush=True)


if __name__ == "__main__":
    main()
