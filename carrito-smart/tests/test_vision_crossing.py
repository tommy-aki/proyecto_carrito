from carrito_smart.detection_stabilizer import RawDetection
from carrito_smart.rfid import RfidAction
from carrito_smart.vision_crossing import TopCrossingTracker


def tracker():
    return TopCrossingTracker(
        detection_threshold=.45, retention_threshold=.25, confirmation_count=3,
        detection_hold_ms=700, confidence_ema_alpha=.3,
    )


def raw(y, x=500, name="bottle", confidence=.8):
    return RawDetection(name, confidence, (x - 50, y - 50, x + 50, y + 50))


def update(subject, values, now):
    return subject.update(values, width=1000, height=1000, now=now)


def test_new_stationary_appearance_confirms_once_without_crossing_lines():
    subject = tracker()
    events = []
    for i in range(5):
        batch = update(subject, [raw(600)], i * .125)[1]
        if i < 2:
            assert batch == []
        events += batch
    assert len(events) == 1
    assert events[0].action is RfidAction.ENTRY
    assert events[0].observed_at == .25 and events[0].visible_count == 1
    subject = tracker()
    events = []
    for i, y in enumerate([100, 200, 380, 500, 550]):
        events += update(subject, [raw(y)], i * .125)[1]
    assert [e.action for e in events] == [RfidAction.ENTRY]


def test_covered_or_sideways_object_never_generates_exit():
    for x in (500, 50):
        subject = tracker()
        for i in range(3):
            update(subject, [raw(600, x=x)], i * .125)
        assert update(subject, [], .5)[0][0].held
        stable, events, _ = update(subject, [], 1.0)
        assert stable == [] and events == []


def test_upward_edge_trajectory_then_loss_never_emits_exit():
    subject = tracker()
    for i, y in enumerate([550, 550, 500, 300, 100]):
        assert all(e.action is not RfidAction.EXIT for e in update(subject, [raw(y)], i * .125)[1])
    assert update(subject, [], 1.19)[1] == []
    stable, events, _ = update(subject, [], 1.21)
    assert not stable and not events
    assert update(subject, [], 2)[1] == []


def test_return_from_top_cancels_exit_and_held_boxes_do_not_move():
    subject = tracker()
    for i, y in enumerate([500, 500, 500, 300, 100, 300, 500]):
        update(subject, [raw(y)], i * .125)
    assert update(subject, [], 2)[1] == []


def test_two_same_class_objects_have_separate_tracks_and_ambiguity_is_rejected():
    subject = tracker()
    for i in range(3):
        stable, _, _ = update(subject, [raw(500, x=200), raw(500, x=800)], i * .125)
    assert len(stable) == 2
    subject = tracker()
    for i in range(3):
        update(subject, [raw(180, x=450), raw(180, x=550)], i * .125)
    assert update(subject, [raw(380, x=500)], .4)[1] == []
    assert update(subject, [], 2)[1] == []


def test_reset_drops_old_exit_and_does_not_add_visible_product():
    subject = tracker()
    for i, y in enumerate([500, 500, 500, 300, 100]):
        update(subject, [raw(y)], i * .125)
    subject.reset()
    for i in range(3):
        assert update(subject, [raw(500)], 3 + i * .125)[1] == []
    assert update(subject, [], 4)[1] == []
    events = []
    for i in range(3):
        events += update(subject, [raw(500)], 5 + i * .125)[1]
    assert len(events) == 1 and events[0].action is RfidAction.ENTRY


def test_delayed_frame_with_object_still_visible_is_not_an_exit():
    subject = tracker()
    for i, y in enumerate([500, 500, 500, 300, 100]):
        update(subject, [raw(y)], i * .125)
    assert update(subject, [raw(100)], 1.3)[1] == []


def test_held_box_does_not_inflate_count_for_new_appearance():
    subject = tracker()
    for i in range(3):
        update(subject, [raw(500, x=200)], i * .125)
    events = []
    for i in range(3):
        stable, batch, _ = update(subject, [raw(500, x=800)], .4 + i * .125)
        events += batch
    assert len(stable) == 2  # Una real y una retenida.
    assert len(events) == 1 and events[0].visible_count == 1


def test_second_visible_object_reports_two_instances():
    subject = tracker()
    for i in range(3):
        update(subject, [raw(500, x=200)], i * .125)
    events = []
    for i in range(3):
        events += update(subject, [raw(500, x=200), raw(500, x=800)], .4 + i * .125)[1]
    assert len(events) == 1 and events[0].visible_count == 2
