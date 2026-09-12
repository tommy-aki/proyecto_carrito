"""Apariciones nuevas confirmadas, con seguimiento local por instancia.

No conoce el carrito ni los UID. Perder una trayectoria nunca genera una baja:
las salidas del carrito se reciben exclusivamente por RFID.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import logging
import uuid

from carrito_smart.detection_stabilizer import (
    RawDetection, StableDetection, TemporalDetectionStabilizer,
)
from carrito_smart.rfid import RfidAction

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VisualCrossing:
    event_id: str
    action: RfidAction
    class_name: str
    track_id: int
    observed_at: float
    visible_count: int = 1


@dataclass(slots=True)
class _ObjectTrack:
    track_id: int
    class_name: str
    box: tuple[float, float, float, float]
    last_seen: float
    stabilizer: TemporalDetectionStabilizer
    entry_sent: bool = False


class TopCrossingTracker:
    """Nombre/argumentos geométricos conservados por compatibilidad.

    Ya no evalúa cruces ni emite SALIDA; solo confirma apariciones y suaviza cajas.
    """
    def __init__(
        self, *, detection_threshold: float, retention_threshold: float,
        confirmation_count: int, detection_hold_ms: int, confidence_ema_alpha: float,
        class_thresholds: dict[str, tuple[float, float]] | None = None,
        top_ratio: float = 0.25, hysteresis_ratio: float = 0.10,
        edge_ratio: float = 0.06, match_distance: float = 0.25,
    ) -> None:
        self.match_distance = match_distance
        self.hold_seconds = detection_hold_ms / 1000
        self.thresholds = (detection_threshold, retention_threshold)
        self.class_thresholds = dict(class_thresholds or {})
        self.stabilizer_options = dict(
            detection_threshold=detection_threshold, retention_threshold=retention_threshold,
            confirmation_count=confirmation_count, detection_hold_ms=detection_hold_ms,
            confidence_ema_alpha=confidence_ema_alpha, class_thresholds=class_thresholds,
        )
        self._tracks: dict[int, _ObjectTrack] = {}
        self._next_id = 1
        self._session = uuid.uuid4().hex
        self._baseline_next_frame = False

    def reset(self) -> None:
        self._tracks.clear()
        # No reutilizar identificadores después de pagar o cancelar.
        self._session = uuid.uuid4().hex
        # Lo que ya está frente a la cámara al reiniciar la sesión no es entrada.
        self._baseline_next_frame = True

    @staticmethod
    def _center(box: tuple[float, float, float, float]) -> tuple[float, float]:
        return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)

    def _event(self, track: _ObjectTrack, action: RfidAction) -> VisualCrossing:
        return VisualCrossing(
            f"{self._session}:{track.track_id}:{action.value}", action,
            track.class_name, track.track_id, track.last_seen,
        )

    def update(
        self, detections: list[RawDetection], *, width: int, height: int, now: float,
    ) -> tuple[list[StableDetection], list[VisualCrossing], list]:
        if width <= 0 or height <= 0:
            raise ValueError("La imagen debe tener dimensiones positivas")
        stable: list[StableDetection] = []
        events: list[VisualCrossing] = []
        decisions = []
        # Expirar ANTES de asociar para no unir objetos separados por una oclusión larga.
        for identity, track in list(self._tracks.items()):
            if now - track.last_seen > self.hold_seconds:
                LOGGER.info(
                    "Trayectoria terminada: track=%s class=%s box=%s; sin baja (solo RFID)",
                    identity, track.class_name, track.box,
                )
                del self._tracks[identity]

        observations = []
        for raw in detections:
            x1, y1, x2, y2 = raw.bbox
            if x2 <= x1 or y2 <= y1:
                continue
            accept, retain = self.class_thresholds.get(raw.class_name, self.thresholds)
            if raw.confidence < retain:
                continue
            box = (x1 / width, y1 / height, x2 / width, y2 / height)
            observations.append((raw, box, accept))

        # Asociación mutuamente única. Si hay dos posibilidades, no adivinar IDs.
        candidates: dict[int, list[int]] = {}
        reverse: dict[int, list[int]] = {}
        for index, (raw, box, _) in enumerate(observations):
            for identity, track in self._tracks.items():
                if raw.class_name != track.class_name:
                    continue
                if math.dist(self._center(box), self._center(track.box)) <= self.match_distance:
                    candidates.setdefault(index, []).append(identity)
                    reverse.setdefault(identity, []).append(index)
        seen = set()
        for index, (raw, box, accept) in enumerate(observations):
            possible = candidates.get(index, [])
            if possible and (len(possible) != 1 or len(reverse[possible[0]]) != 1):
                LOGGER.info("Asociación visual ambigua: class=%s tracks=%s; sin entrada", raw.class_name, possible)
                for identity in possible:
                    track = self._tracks[identity]
                    track.entry_sent = True  # No fabricar una aparición tras perder identidad.
                continue
            if possible:
                track = self._tracks[possible[0]]
            else:
                if raw.confidence < accept:
                    continue
                identity = self._next_id
                self._next_id += 1
                track = _ObjectTrack(
                    identity, raw.class_name, box, now,
                    TemporalDetectionStabilizer(**self.stabilizer_options),
                    entry_sent=self._baseline_next_frame,
                )
                self._tracks[identity] = track
            seen.add(track.track_id)
            current, decision = track.stabilizer.update([raw], now=now)
            decisions.extend(decision)
            # Candidatos bajo aceptación no deben crear apariciones confirmadas.
            valid = bool(current) or any(d.decision == "candidate" for d in decision)
            if not valid:
                continue
            track.box, track.last_seen = box, now
            if current and not track.entry_sent:
                events.append(self._event(track, RfidAction.ENTRY))
                track.entry_sent = True
            stable.extend(current)

        for identity, track in self._tracks.items():
            if identity not in seen:
                current, decision = track.stabilizer.update([], now=now)
                decisions.extend(decision)
                stable.extend(current)
        self._baseline_next_frame = False
        # La cantidad pertenece a este frame de confirmación, no al refresco UI.
        # Las cajas retenidas no representan objetos actualmente visibles.
        counts: dict[str, int] = {}
        for item in stable:
            if not item.held:
                counts[item.class_name] = counts.get(item.class_name, 0) + 1
        events = [
            VisualCrossing(event.event_id, event.action, event.class_name,
                           event.track_id, event.observed_at,
                           counts.get(event.class_name, 0))
            for event in events
        ]
        return stable, events, decisions
