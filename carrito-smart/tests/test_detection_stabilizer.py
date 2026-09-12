from __future__ import annotations

import pytest

from carrito_smart.detection_stabilizer import (
    RawDetection,
    TemporalDetectionStabilizer,
)


BOX = (10, 20, 110, 220)


def make_stabilizer() -> TemporalDetectionStabilizer:
    return TemporalDetectionStabilizer(
        detection_threshold=0.60,
        retention_threshold=0.45,
        confirmation_count=3,
        detection_hold_ms=700,
        confidence_ema_alpha=0.30,
    )


def raw(confidence: float, bbox=BOX) -> RawDetection:
    return RawDetection("person", confidence, bbox)


def test_requires_three_consecutive_detections_and_smooths_confidence():
    stabilizer = make_stabilizer()

    assert stabilizer.update([raw(0.65)], now=0.0)[0] == []
    assert stabilizer.update([raw(0.70)], now=0.1)[0] == []
    stable, decisions = stabilizer.update([raw(0.80)], now=0.2)

    assert len(stable) == 1
    assert stable[0].confidence == pytest.approx(0.7055)
    assert decisions[0].decision == "confirmed"


def test_hysteresis_maintains_active_detection_below_acceptance_threshold():
    stabilizer = make_stabilizer()
    for index in range(3):
        stabilizer.update([raw(0.70)], now=index * 0.1)

    stable, decisions = stabilizer.update([raw(0.50)], now=0.3)

    assert len(stable) == 1
    assert not stable[0].held
    assert decisions[0].decision == "maintained"


def test_new_detection_below_acceptance_threshold_is_discarded():
    stable, decisions = make_stabilizer().update([raw(0.55)], now=0.0)

    assert stable == []
    assert decisions[0].decision == "discarded"


def test_last_box_is_held_then_expires_after_tolerance():
    stabilizer = make_stabilizer()
    for index in range(3):
        stabilizer.update([raw(0.70)], now=index * 0.1)
    last_box = (30, 40, 130, 240)
    stabilizer.update([raw(0.50, last_box)], now=0.3)

    held, decisions = stabilizer.update([], now=0.99)
    expired, expiration_decisions = stabilizer.update([], now=1.01)

    assert held[0].bbox == last_box
    assert held[0].held
    assert decisions[0].decision == "held"
    assert expired == []
    assert expiration_decisions[0].decision == "expired"


def test_interrupted_candidate_must_restart_confirmation():
    stabilizer = make_stabilizer()
    stabilizer.update([raw(0.80)], now=0.0)

    stable, decisions = stabilizer.update([], now=0.1)

    assert stable == []
    assert decisions[0].decision == "discarded"


def make_chocolate_stabilizer() -> TemporalDetectionStabilizer:
    return TemporalDetectionStabilizer(
        detection_threshold=0.45, retention_threshold=0.25,
        confirmation_count=3, detection_hold_ms=700, confidence_ema_alpha=0.30,
        class_thresholds={"packet of chocolate": (0.30, 0.25)},
    )


def test_webcam_chocolate_sequence_confirms_without_lowering_other_thresholds():
    stabilizer = make_chocolate_stabilizer()
    # Lecturas del log real de webcam del 2026-09-09 a las 17:01:14–15.
    confidences = [0.299, 0.330, 0.304, 0.301, 0.308, 0.304, 0.252]
    for index, confidence in enumerate(confidences):
        stable, decisions = stabilizer.update([
            RawDetection("packet of chocolate", confidence, BOX),
            RawDetection("aluminum soda can", confidence, BOX),
            RawDetection("plastic water bottle", confidence, BOX),
        ], now=index * 0.125)
        assert [item.class_name for item in stable] == (
            ["packet of chocolate"] if index >= 3 else []
        )
    assert not stable[0].held
    assert decisions[0].decision == "maintained"
    assert "0.25" in decisions[0].reason
    assert "0.45" in decisions[1].reason


def test_weak_chocolate_spike_does_not_confirm_and_missing_candidate_restarts():
    stabilizer = make_chocolate_stabilizer()
    for index, confidence in enumerate([0.29, 0.59, 0.28, 0.32, 0.34]):
        assert stabilizer.update(
            [RawDetection("packet of chocolate", confidence, BOX)], now=index * 0.125
        )[0] == []
    assert stabilizer.update([], now=0.625)[0] == []
    assert stabilizer.update([RawDetection("packet of chocolate", 0.35, BOX)], now=0.75)[0] == []


def test_chocolate_keeps_ema_box_and_hold_without_accepting_low_confidence():
    stabilizer = make_chocolate_stabilizer()
    for index, confidence in enumerate([0.33, 0.34, 0.35]):
        stable, _ = stabilizer.update(
            [RawDetection("packet of chocolate", confidence, BOX)], now=index * 0.125
        )
    assert stable[0].confidence == pytest.approx(0.3381)
    held, _ = stabilizer.update(
        [RawDetection("packet of chocolate", 0.24, (1, 2, 3, 4))], now=0.4
    )
    assert held[0].held
    assert held[0].bbox == BOX
    assert held[0].confidence == stable[0].confidence
    assert stabilizer.update([], now=0.9)[0][0].held
    assert stabilizer.update([], now=0.951)[0] == []


def test_class_thresholds_reject_invalid_hysteresis():
    with pytest.raises(ValueError, match="Umbrales por clase"):
        TemporalDetectionStabilizer(
            detection_threshold=0.45, retention_threshold=0.25,
            confirmation_count=3, detection_hold_ms=700, confidence_ema_alpha=0.30,
            class_thresholds={"chocolate": (0.2, 0.3)},
        )
