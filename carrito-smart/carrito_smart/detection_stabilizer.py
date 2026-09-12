"""Estabilización temporal de detecciones, independiente de UI y modelo."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass


BoundingBox = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class RawDetection:
    class_name: str
    confidence: float
    bbox: BoundingBox


@dataclass(frozen=True, slots=True)
class StableDetection:
    class_name: str
    confidence: float
    bbox: BoundingBox
    held: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "class_name": self.class_name,
            "confidence": self.confidence,
            "bbox": self.bbox,
            "held": self.held,
        }


@dataclass(frozen=True, slots=True)
class DetectionDecision:
    class_name: str
    decision: str
    reason: str
    raw_confidence: float | None
    smoothed_confidence: float | None


@dataclass(slots=True)
class _Track:
    class_name: str
    smoothed_confidence: float
    bbox: BoundingBox
    consecutive_count: int
    confirmed: bool
    last_seen_at: float
    held: bool = False


class TemporalDetectionStabilizer:
    """Confirma por clase, suaviza confianza y tolera pérdidas breves."""

    def __init__(
        self,
        *,
        detection_threshold: float,
        retention_threshold: float,
        confirmation_count: int,
        detection_hold_ms: int,
        confidence_ema_alpha: float,
        class_thresholds: Mapping[str, tuple[float, float]] | None = None,
    ) -> None:
        self.detection_threshold = detection_threshold
        self.retention_threshold = retention_threshold
        self.confirmation_count = confirmation_count
        self.detection_hold_seconds = detection_hold_ms / 1000
        self.confidence_ema_alpha = confidence_ema_alpha
        self.class_thresholds = dict(class_thresholds or {})
        for accept, retain in self.class_thresholds.values():
            if not 0 <= retain <= accept <= 1:
                raise ValueError("Umbrales por clase: 0 <= retention <= detection <= 1")
        self._tracks: dict[str, _Track] = {}

    def update(
        self,
        detections: list[RawDetection],
        *,
        now: float | None = None,
    ) -> tuple[list[StableDetection], list[DetectionDecision]]:
        timestamp = time.monotonic() if now is None else now
        best_by_class: dict[str, RawDetection] = {}
        for detection in detections:
            previous = best_by_class.get(detection.class_name)
            if previous is None or detection.confidence > previous.confidence:
                best_by_class[detection.class_name] = detection

        decisions: list[DetectionDecision] = []
        accepted_classes: set[str] = set()

        for class_name, detection in best_by_class.items():
            acceptance, retention = self._thresholds(class_name)
            track = self._tracks.get(class_name)
            if track is None:
                self._start_candidate(detection, timestamp, decisions)
                if class_name in self._tracks:
                    accepted_classes.add(class_name)
                continue

            if track.confirmed:
                if detection.confidence >= retention:
                    track.smoothed_confidence = self._ema(
                        detection.confidence, track.smoothed_confidence
                    )
                    track.bbox = detection.bbox
                    track.last_seen_at = timestamp
                    track.held = False
                    accepted_classes.add(class_name)
                    decisions.append(
                        DetectionDecision(
                            class_name,
                            "maintained",
                            f"confianza sobre el umbral de retención ({retention:.2f})",
                            detection.confidence,
                            track.smoothed_confidence,
                        )
                    )
                else:
                    track.held = True
                    decisions.append(
                        DetectionDecision(
                            class_name,
                            "held",
                            f"confianza bajo retención ({retention:.2f}); "
                            "se conserva dentro de tolerancia",
                            detection.confidence,
                            track.smoothed_confidence,
                        )
                    )
                continue

            if detection.confidence >= acceptance:
                track.consecutive_count += 1
                track.smoothed_confidence = self._ema(
                    detection.confidence, track.smoothed_confidence
                )
                track.bbox = detection.bbox
                track.last_seen_at = timestamp
                accepted_classes.add(class_name)
                if track.consecutive_count >= self.confirmation_count:
                    track.confirmed = True
                    track.held = False
                    decision = "confirmed"
                    reason = (
                        f"{track.consecutive_count} detecciones consecutivas "
                        f"sobre aceptación ({acceptance:.2f})"
                    )
                else:
                    decision = "candidate"
                    reason = (
                        f"confirmación {track.consecutive_count}/"
                        f"{self.confirmation_count}; aceptación={acceptance:.2f}"
                    )
                decisions.append(
                    DetectionDecision(
                        class_name,
                        decision,
                        reason,
                        detection.confidence,
                        track.smoothed_confidence,
                    )
                )
            else:
                del self._tracks[class_name]
                decisions.append(
                    DetectionDecision(
                        class_name,
                        "discarded",
                        f"candidato bajo el umbral de aceptación ({acceptance:.2f})",
                        detection.confidence,
                        track.smoothed_confidence,
                    )
                )

        for class_name, track in list(self._tracks.items()):
            if class_name in accepted_classes:
                continue
            if not track.confirmed:
                del self._tracks[class_name]
                decisions.append(
                    DetectionDecision(
                        class_name,
                        "discarded",
                        "se interrumpió la secuencia de confirmación",
                        None,
                        track.smoothed_confidence,
                    )
                )
                continue
            elapsed = timestamp - track.last_seen_at
            if elapsed > self.detection_hold_seconds:
                del self._tracks[class_name]
                decisions.append(
                    DetectionDecision(
                        class_name,
                        "expired",
                        f"sin detección durante {elapsed * 1000:.0f} ms",
                        None,
                        track.smoothed_confidence,
                    )
                )
            else:
                track.held = True
                if class_name not in best_by_class:
                    decisions.append(
                        DetectionDecision(
                            class_name,
                            "held",
                            f"pérdida temporal durante {elapsed * 1000:.0f} ms",
                            None,
                            track.smoothed_confidence,
                        )
                    )

        stable = [
            StableDetection(
                class_name=track.class_name,
                confidence=track.smoothed_confidence,
                bbox=track.bbox,
                held=track.held,
            )
            for track in self._tracks.values()
            if track.confirmed
        ]
        stable.sort(key=lambda item: item.class_name)
        return stable, decisions

    def _start_candidate(
        self,
        detection: RawDetection,
        timestamp: float,
        decisions: list[DetectionDecision],
    ) -> None:
        acceptance, _ = self._thresholds(detection.class_name)
        if detection.confidence < acceptance:
            decisions.append(
                DetectionDecision(
                    detection.class_name,
                    "discarded",
                    f"nueva detección bajo el umbral de aceptación ({acceptance:.2f})",
                    detection.confidence,
                    None,
                )
            )
            return
        confirmed = self.confirmation_count == 1
        self._tracks[detection.class_name] = _Track(
            class_name=detection.class_name,
            smoothed_confidence=detection.confidence,
            bbox=detection.bbox,
            consecutive_count=1,
            confirmed=confirmed,
            last_seen_at=timestamp,
        )
        decisions.append(
            DetectionDecision(
                detection.class_name,
                "confirmed" if confirmed else "candidate",
                (
                    f"confirmación inmediata; aceptación={acceptance:.2f}"
                    if confirmed
                    else f"confirmación 1/{self.confirmation_count}; "
                    f"aceptación={acceptance:.2f}"
                ),
                detection.confidence,
                detection.confidence,
            )
        )

    def _thresholds(self, class_name: str) -> tuple[float, float]:
        return self.class_thresholds.get(
            class_name, (self.detection_threshold, self.retention_threshold)
        )

    def _ema(self, raw: float, previous: float) -> float:
        alpha = self.confidence_ema_alpha
        return alpha * raw + (1 - alpha) * previous
