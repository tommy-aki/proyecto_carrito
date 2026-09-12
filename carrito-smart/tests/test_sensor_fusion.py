import pytest

from carrito_smart.cart import CartService
from carrito_smart.database import Database
from carrito_smart.rfid import RfidAction, RfidEvent
from carrito_smart.sensor_fusion import SensorFusionCoordinator
from carrito_smart.vision_crossing import VisualCrossing


@pytest.fixture
def fusion(tmp_path):
    db = Database(tmp_path / "fusion.db")
    db.initialize()
    subject = SensorFusionCoordinator(db, CartService(db), {"bottle": "CS-001", "can": "CS-002"})
    subject.set_available("rfid", True, now=0)
    subject.set_available("vision", True, now=0)
    return subject


def tag(action=RfidAction.ENTRY, uid="12345678"):
    return RfidEvent(action, uid, f"{action.value}:{uid}")


def visual(at=1, action=RfidAction.ENTRY, name="bottle", identity="one", visible_count=1):
    return VisualCrossing(identity, action, name, 1, at, visible_count)


@pytest.mark.parametrize("rfid_first", [True, False])
def test_both_orders_add_once_and_do_not_change_inventory(fusion, rfid_first):
    stock = fusion.database.get_product_by_sku("CS-001").stock
    if rfid_first:
        fusion.on_rfid(tag(), now=1)
        assert fusion.cart.items == [] and fusion.blocked
        fusion.on_visual(visual(1.5), now=1.5)
    else:
        fusion.on_visual(visual(1), now=1)
        assert fusion.cart.items == [] and not fusion.blocked
        fusion.on_rfid(tag(), now=1.5)
    assert fusion.cart.items[0].quantity == 1
    assert not fusion.blocked
    fusion.on_rfid(tag(), now=2)
    fusion.on_visual(visual(), now=2)
    assert fusion.cart.items[0].quantity == 1
    assert fusion.database.get_product_by_sku("CS-001").stock == stock


def test_wrong_product_and_expired_evidence_never_match(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(name="can"), now=1)
    assert fusion.cart.items == []
    fusion.tick(now=4.1)
    assert fusion.issues and not fusion.pending and fusion.blocked
    fusion.on_visual(visual(5, identity="new"), now=5)
    assert fusion.cart.items == []


def test_exit_requires_only_rfid_even_after_long_occlusion(fusion):
    fusion.on_visual(visual(), now=1)
    fusion.on_rfid(tag(), now=1)
    fusion.tick(now=100)
    assert fusion.cart.items[0].quantity == 1
    fusion.on_rfid(tag(RfidAction.EXIT), now=101)
    assert fusion.cart.items == [] and not fusion.present_uids
    fusion.on_visual(visual(102, RfidAction.EXIT, identity="exit"), now=102)
    assert fusion.cart.items == [] and not fusion.present_uids
    assert not fusion.pending and not fusion.issues and not fusion.blocked


def test_two_tags_cannot_reuse_one_visual_and_ambiguous_pair_is_not_applied(fusion):
    with fusion.database.connect() as connection:
        product = fusion.database.get_product_by_sku("CS-001")
        connection.execute("INSERT INTO rfid_tags(uid,product_id) VALUES(?,?)", ("AAAAAAAA", product.id))
        connection.commit()
    fusion.on_rfid(tag(), now=1)
    fusion.on_rfid(tag(uid="AAAAAAAA"), now=1.1)
    fusion.on_visual(visual(1.2), now=1.2)
    assert fusion.cart.items == [] and fusion.blocked


def test_retry_after_timeout_requires_new_visual_event(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_rfid(tag(), now=3)  # No prolonga el plazo.
    fusion.tick(now=4.1)
    assert fusion.issues
    fusion.on_rfid(tag(), now=5)
    fusion.on_visual(visual(5.1), now=5.1)
    assert fusion.cart.items[0].quantity == 1 and not fusion.blocked


def test_disconnect_freezes_cart_invalidates_pending_and_rejects_queued_events(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.set_available("vision", False, now=2)
    fusion.on_visual(visual(1.5), now=2.1)
    fusion.set_available("vision", True, now=3)
    fusion.on_visual(visual(1.5, identity="queued"), now=3)
    assert fusion.cart.items == [] and fusion.blocked


def test_out_of_stock_blocks_payment_and_reset_rejects_old_crossing(fusion):
    with fusion.database.connect() as connection:
        connection.execute("UPDATE products SET stock=0 WHERE sku='CS-001'")
        connection.commit()
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(), now=1)
    assert fusion.cart.items == [] and fusion.issues
    fusion.reset(now=2)
    fusion.on_visual(visual(1, identity="queued"), now=2)
    assert not fusion.pending and not fusion.issues


def test_two_sequential_units_of_same_product_need_distinct_tags_and_crossings(fusion):
    product = fusion.database.get_product_by_sku("CS-001")
    fusion.database.assign_rfid_tag("AAAAAAAA", product.id)
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    fusion.on_rfid(tag(uid="AAAAAAAA"), now=2)
    fusion.on_visual(visual(1), now=2)  # Reutilizar evidencia no suma otra botella.
    assert fusion.cart.items[0].quantity == 1
    fusion.on_visual(visual(2.1, identity="second", visible_count=2), now=2.1)
    assert fusion.cart.items[0].quantity == 2
    fusion.on_visual(visual(3, RfidAction.EXIT, identity="exit"), now=3)
    assert fusion.cart.items[0].quantity == 2
    fusion.on_rfid(tag(RfidAction.EXIT, "AAAAAAAA"), now=3.1)
    assert fusion.cart.items[0].quantity == 1
    assert fusion.present_uids == {"12345678": "CS-001"}


def test_batch_of_two_visual_entries_is_ambiguous_with_one_tag(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual_batch([visual(1.1), visual(1.1, identity="second")], now=1.1)
    assert fusion.cart.items == [] and fusion.blocked


def test_disconnect_does_not_remove_already_accepted_units(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    fusion.set_available("rfid", False, now=2)
    fusion.on_visual(visual(3, RfidAction.EXIT, identity="exit"), now=3)
    assert fusion.cart.items[0].quantity == 1 and fusion.blocked


def test_stationary_occluded_and_rfid_exit_end_to_end(fusion):
    from carrito_smart.vision_crossing import TopCrossingTracker
    from carrito_smart.detection_stabilizer import RawDetection
    tracker = TopCrossingTracker(
        detection_threshold=.45, retention_threshold=.25, confirmation_count=3,
        detection_hold_ms=700, confidence_ema_alpha=.3,
    )
    def observe(y, at):
        raw = [] if y is None else [RawDetection("bottle", .8, (400, y - 50, 500, y + 50))]
        _, events, _ = tracker.update(raw, width=1000, height=1000, now=at)
        fusion.on_visual_batch(events, now=at)
    fusion.on_rfid(tag(), now=1)
    for at, y in [(1, 100), (1.125, 200), (1.25, 380), (1.375, 500)]:
        observe(y, at)
    assert fusion.cart.items[0].quantity == 1
    observe(None, 2.1)
    assert fusion.cart.items[0].quantity == 1
    for at, y in [(3, 500), (3.125, 500), (3.25, 500), (3.375, 300), (3.5, 100)]:
        observe(y, at)
    fusion.on_rfid(tag(RfidAction.EXIT), now=3.6)
    assert fusion.cart.items == []
    observe(None, 4.21)
    assert fusion.cart.items == [] and not fusion.blocked


@pytest.mark.parametrize("name,sku,uid", [
    ("bottle", "CS-001", "13DF1E14"),
    ("can", "CS-002", "B38A092F"),
    ("chocolate", "CS-006", "7744C964"),
])
def test_rfid_only_exit_for_each_product_without_camera_or_stock_change(fusion, name, sku, uid):
    product = fusion.database.get_product_by_sku(sku)
    fusion.database.assign_rfid_tag(uid, product.id)
    fusion.class_to_sku[name] = sku
    fusion.on_rfid(tag(uid=uid), now=1)
    fusion.on_visual(visual(1.2, name=name), now=1.2)
    fusion.set_available("vision", False, now=2)
    assert fusion.cart.items[0].quantity == 1
    assert "salidas RFID habilitadas" in fusion.status
    fusion.on_rfid(tag(RfidAction.EXIT, uid), now=100)
    assert not fusion.cart.items and not fusion.present_uids and not fusion.pending
    assert fusion.blocked  # El pago sigue exigiendo sensores sanos.
    assert fusion.database.get_product_by_sku(sku).stock == product.stock
    fusion.on_rfid(tag(uid=uid), now=101)
    assert not fusion.cart.items and not fusion.pending  # No habilitar entradas solo RFID.


def test_repeated_and_unknown_exits_cannot_remove_another_unit(fusion):
    fusion.database.assign_rfid_tag("AAAAAAAA", fusion.database.get_product_by_sku("CS-001").id)
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    fusion.on_rfid(tag(uid="AAAAAAAA"), now=2)
    fusion.on_visual(visual(2, identity="two", visible_count=2), now=2)
    fusion.on_rfid(tag(RfidAction.EXIT, "AAAAAAAA"), now=3)
    for uid in ("AAAAAAAA", "DEADBEEF", "4A3B2C1D"):
        fusion.on_rfid(tag(RfidAction.EXIT, uid), now=3.1)
    assert fusion.cart.items[0].quantity == 1
    assert fusion.present_uids == {"12345678": "CS-001"}
    assert not fusion.blocked


def test_visual_exit_never_removes_or_blocks_checkout(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    fusion.on_visual(visual(2, RfidAction.EXIT, identity="exit"), now=2)
    fusion.tick(now=10)
    assert fusion.cart.items[0].quantity == 1
    assert not fusion.pending and not fusion.issues and not fusion.blocked


def test_rfid_disconnect_still_prevents_removal(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    fusion.set_available("rfid", False, now=2)
    fusion.on_rfid(tag(RfidAction.EXIT), now=3)
    assert fusion.cart.items[0].quantity == 1
    fusion.set_available("rfid", True, now=4)
    fusion.on_rfid(tag(RfidAction.EXIT), now=4.1)
    assert not fusion.cart.items


def test_camera_failure_does_not_discard_already_received_rfid_exit(fusion, monkeypatch):
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    event = RfidEvent(RfidAction.EXIT, "12345678", "SALIDA:12345678", received_at=2)
    fusion.set_available("vision", False, now=2.1)
    monkeypatch.setattr("carrito_smart.sensor_fusion.time.monotonic", lambda: 2.2)
    fusion.on_rfid(event)
    assert not fusion.cart.items


@pytest.mark.parametrize("reason", ["reset", "rfid_disconnect", "mode_change", "too_old"])
def test_stale_rfid_exit_cannot_remove_current_purchase(fusion, monkeypatch, reason):
    event = RfidEvent(RfidAction.EXIT, "12345678", "SALIDA:12345678", received_at=1)
    if reason == "reset":
        fusion.reset(now=2)
    elif reason == "rfid_disconnect":
        fusion.set_available("rfid", False, now=2)
        fusion.set_available("rfid", True, now=2.1)
    elif reason == "mode_change":
        fusion.invalidate("Cambio de modo", now=2)
    fusion.on_rfid(tag(), now=3)
    fusion.on_visual(visual(3), now=3)
    monkeypatch.setattr("carrito_smart.sensor_fusion.time.monotonic", lambda: 4.1 if reason == "too_old" else 3.1)
    fusion.on_rfid(event)
    assert fusion.cart.items[0].quantity == 1


def test_pending_other_entry_does_not_block_rfid_exit_or_get_cleared(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    fusion.on_rfid(tag(uid="4A3B2C1D"), now=2)
    fusion.tick(now=6)
    issues = dict(fusion.issues)
    fusion.on_rfid(tag(RfidAction.EXIT), now=7)
    assert not fusion.cart.items and fusion.issues == issues and fusion.blocked


def test_exit_before_pending_entry_confirmation_cannot_add_late(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_rfid(tag(RfidAction.EXIT), now=1.2)
    fusion.on_visual(visual(1.1), now=1.3)
    fusion.on_visual(visual(1.4, identity="later"), now=1.4)
    assert not fusion.cart.items and not fusion.present_uids
    assert not any(item.uid for item in fusion.pending.values())
    assert fusion.issues  # No resolver silenciosamente una entrada incompleta.


def test_reentry_requires_fresh_rfid_and_visual_after_exit(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    fusion.on_visual(visual(1.1, identity="unused", visible_count=2), now=1.1)
    fusion.on_rfid(tag(RfidAction.EXIT), now=1.2)
    assert not fusion.pending
    fusion.on_rfid(tag(), now=1.3)
    fusion.on_visual(visual(1.1, identity="queued", visible_count=2), now=1.4)
    assert not fusion.cart.items
    fusion.on_visual(visual(1.5, identity="fresh"), now=1.5)
    assert fusion.cart.items[0].quantity == 1 and not fusion.blocked


def test_exit_uses_admitted_sku_even_if_tag_mapping_changes(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    fusion.database.assign_rfid_tag("12345678", fusion.database.get_product_by_sku("CS-002").id)
    fusion.on_rfid(tag(RfidAction.EXIT), now=2)
    assert not fusion.cart.items and not fusion.present_uids


def test_failed_cart_removal_preserves_uid_for_retry(fusion, monkeypatch):
    from carrito_smart.cart import CartError
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    original = fusion.cart.remove_product
    def fail(*args, **kwargs):
        raise CartError("No se pudo retirar")
    monkeypatch.setattr(fusion.cart, "remove_product", fail)
    fusion.on_rfid(tag(RfidAction.EXIT), now=2)
    assert fusion.present_uids == {"12345678": "CS-001"}
    assert fusion.cart.items[0].quantity == 1 and fusion.issues
    monkeypatch.setattr(fusion.cart, "remove_product", original)
    fusion.on_rfid(tag(RfidAction.EXIT), now=3)
    assert not fusion.cart.items and not fusion.present_uids and not fusion.blocked


def test_registered_bottle_reappearing_cannot_validate_another_uid(fusion):
    from carrito_smart.detection_stabilizer import RawDetection
    from carrito_smart.vision_crossing import TopCrossingTracker
    tracker = TopCrossingTracker(
        detection_threshold=.45, retention_threshold=.25, confirmation_count=3,
        detection_hold_ms=700, confidence_ema_alpha=.3,
    )
    product = fusion.database.get_product_by_sku("CS-001")
    fusion.database.assign_rfid_tag("AAAAAAAA", product.id)
    def observe(at, visible=True):
        raw = [RawDetection("bottle", .8, (400, 400, 500, 600))] if visible else []
        _, events, _ = tracker.update(raw, width=1000, height=1000, now=at)
        fusion.on_visual_batch(events, now=at)
    fusion.on_rfid(tag(), now=1)
    for at in (1.1, 1.2, 1.3):
        observe(at)
    assert fusion.cart.items[0].quantity == 1
    observe(2.1, False)
    for at in (3.1, 3.2, 3.3):
        observe(at)
    assert not fusion.blocked  # La reaparición no crea un falso pendiente.
    fusion.on_rfid(tag(uid="AAAAAAAA"), now=3.4)
    observe(3.5)
    assert fusion.cart.items[0].quantity == 1
    assert fusion.present_uids == {"12345678": "CS-001"}
    assert fusion.blocked  # Falta una unidad visual realmente adicional.


def test_expired_appearance_is_not_refreshed_by_stationary_detection(fusion):
    from carrito_smart.detection_stabilizer import RawDetection
    from carrito_smart.vision_crossing import TopCrossingTracker
    tracker = TopCrossingTracker(
        detection_threshold=.45, retention_threshold=.25, confirmation_count=3,
        detection_hold_ms=700, confidence_ema_alpha=.3,
    )
    for i in range(40):
        at = 1 + i * .125
        _, events, _ = tracker.update([RawDetection("bottle", .8, (400, 400, 500, 600))],
                                     width=1000, height=1000, now=at)
        fusion.on_visual_batch(events, now=at)
    fusion.on_rfid(tag(), now=6)
    assert fusion.cart.items == [] and fusion.blocked


def test_real_bottle_log_confirms_entry_inside_three_seconds(fusion):
    from carrito_smart.detection_stabilizer import RawDetection
    from carrito_smart.vision_crossing import TopCrossingTracker
    fusion.class_to_sku["plastic water bottle"] = "CS-001"
    fusion.database.assign_rfid_tag("13DF1E14", fusion.database.get_product_by_sku("CS-001").id)
    tracker = TopCrossingTracker(
        detection_threshold=.45, retention_threshold=.25, confirmation_count=3,
        detection_hold_ms=700, confidence_ema_alpha=.3,
    )
    fusion.on_rfid(tag(uid="13DF1E14"), now=0)
    # Log 2026-09-09: RFID 18:31:03.344; primera botella 04.417;
    # confirmación 05.129. El centro ya estaba al 52% del alto, no arriba.
    sequence = [
        (1.073, .785, (509, 114, 706, 636)),
        (1.222, .704, (504, 113, 703, 636)),
        (1.377, None, None),
        (1.514, .749, (506, 115, 703, 636)),
        (1.646, .773, (508, 112, 705, 637)),
        (1.785, .803, (507, 115, 703, 637)),
    ]
    emitted = []
    for at, confidence, box in sequence:
        raw = [] if confidence is None else [RawDetection("plastic water bottle", confidence, box)]
        _, events, _ = tracker.update(raw, width=1280, height=720, now=at)
        emitted += events
        fusion.on_visual_batch(events, now=at)
    assert len(emitted) == 1 and emitted[0].observed_at == 1.785
    assert fusion.cart.items[0].quantity == 1
    assert fusion.present_uids == {"13DF1E14": "CS-001"}
    assert not fusion.blocked
    assert fusion.database.get_product_by_sku("CS-001").stock == 100


def test_camera_only_evidence_is_advisory_before_and_after_timeout(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    payment_revision = fusion.payment_revision
    for index, at in enumerate((2, 6, 10)):
        fusion.on_visual(visual(at, identity=f"extra-{index}", visible_count=2), now=at)
        assert fusion.pending and not fusion.blocked
        assert "Aviso CS-001" in fusion.status and "no bloquea el pago" in fusion.status
        fusion.tick(now=at + 3.1)
        assert not fusion.pending and not fusion.issues and not fusion.blocked
        assert len(fusion.visual_notices) == 1
        assert fusion.payment_revision == payment_revision
        assert fusion.cart.items[0].quantity == 1
    assert fusion.database.get_product_by_sku("CS-001").stock == 100


def test_expired_visual_notice_cannot_validate_late_rfid(fusion):
    fusion.on_visual(visual(1), now=1)
    fusion.tick(now=4.1)
    assert fusion.visual_notices and not fusion.issues and not fusion.blocked
    fusion.on_rfid(tag(), now=4.2)
    fusion.on_visual(visual(1), now=4.2)  # No reutilizar evidencia vencida.
    assert not fusion.cart.items and fusion.blocked
    fusion.on_visual(visual(4.3, identity="fresh"), now=4.3)
    assert fusion.cart.items[0].quantity == 1
    assert not fusion.visual_notices and not fusion.blocked


def test_visual_notice_never_clears_unconfirmed_rfid_or_unknown_uid(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_rfid(tag(uid="DEADBEEF"), now=1.1)
    fusion.on_visual(visual(1.2, name="can"), now=1.2)
    fusion.tick(now=5)
    assert len(fusion.issues) == 2 and fusion.blocked
    assert fusion.visual_notices and not fusion.cart.items
    fusion.on_rfid(tag(uid="4A3B2C1D"), now=6)
    fusion.on_visual(visual(6.1, name="can", identity="fresh"), now=6.1)
    assert fusion.cart.items[0].product.sku == "CS-002"
    assert len(fusion.issues) == 2 and fusion.blocked


@pytest.mark.parametrize("sensor", ["vision", "rfid"])
def test_disconnect_does_not_promote_visual_warning_to_blocking_issue(fusion, sensor):
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    fusion.on_visual(visual(2, name="can", identity="extra"), now=2)
    fusion.set_available(sensor, False, now=2.1)
    assert not fusion.pending and not fusion.issues and fusion.blocked
    fusion.set_available(sensor, True, now=3)
    assert not fusion.blocked and fusion.cart.items[0].quantity == 1


def test_reset_and_mode_change_clear_visual_notices_without_waiving_rfid(fusion):
    fusion.on_visual(visual(1), now=1)
    fusion.tick(now=5)
    assert fusion.visual_notices
    fusion.on_rfid(tag(uid="4A3B2C1D"), now=5)
    fusion.invalidate("Cambio de modo", now=5.1)
    assert not fusion.visual_notices and fusion.issues and fusion.blocked
    fusion.reset(now=6)
    assert not fusion.visual_notices and not fusion.issues and not fusion.blocked


def test_payment_revision_ignores_notices_but_tracks_real_changes(fusion):
    fusion.on_rfid(tag(), now=1)
    fusion.on_visual(visual(1), now=1)
    before = fusion.payment_revision
    fusion.on_visual(visual(2, identity="extra", visible_count=2), now=2)
    fusion.on_rfid(tag(), now=2.1)  # Lectura repetida de la unidad ya admitida.
    fusion.tick(now=6)
    assert fusion.payment_revision == before
    fusion.on_rfid(tag(uid="4A3B2C1D"), now=7)
    assert fusion.payment_revision > before and fusion.blocked


def test_real_three_product_log_extra_chocolate_does_not_block_payment(fusion):
    # Reproduce ENTRADAS confirmadas a las 18:10:10/29/36 y el falso extra a :39.
    fusion.class_to_sku["chocolate"] = "CS-006"
    for uid, sku, name, at in [
        ("03392214", "CS-006", "chocolate", 10.572),
        ("13DF1E14", "CS-001", "bottle", 29.198),
        ("B38A092F", "CS-002", "can", 36.070),
    ]:
        product = fusion.database.get_product_by_sku(sku)
        fusion.database.assign_rfid_tag(uid, product.id)
        fusion.on_rfid(tag(uid=uid), now=at - .2)
        fusion.on_visual(visual(at, name=name, identity=uid), now=at)
    purchased_items = fusion.cart.items
    revision = fusion.payment_revision
    for index, at in enumerate((39.445, 51.460, 64.214)):
        fusion.on_visual(visual(at, name="chocolate", identity=f"duplicate-{index}", visible_count=2), now=at)
        assert not fusion.blocked
        fusion.tick(now=at + 3.1)
        assert not fusion.blocked and not fusion.issues
    assert fusion.cart.items == purchased_items and len(purchased_items) == 3
    assert fusion.payment_revision == revision
    assert "CS-006" in fusion.visual_notices
    assert all(item.quantity == 1 and item.product.stock == 100 for item in purchased_items)
