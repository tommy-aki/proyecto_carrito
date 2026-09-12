from __future__ import annotations

from dataclasses import replace
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from carrito_smart.config import AppConfig
from carrito_smart.database import Database
from carrito_smart.main_window import MainWindow
from carrito_smart.rfid import RfidAction
from carrito_smart.vision_crossing import VisualCrossing


@pytest.fixture
def window(tmp_path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "ui.db")
    database.initialize()
    chocolate = database.get_product_by_sku("CS-006")
    database.assign_rfid_tag("13DF1E14", chocolate.id)
    config = replace(
        AppConfig.from_env(), data_dir=tmp_path, log_dir=tmp_path,
        database_path=database.path, yoloe_chocolate_bar_prompt="wrapped chocolate bar",
    )
    monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
    instance = MainWindow(database, config)
    instance.rfid_simulation.setChecked(True)
    instance._vision_observation(time.monotonic())
    # En Windows el reloj puede repetir el mismo milisegundo del cambio de modo.
    instance.fusion.barrier -= .001
    instance.fusion.rfid_exit_barrier -= .001
    yield instance
    instance.close()
    application.processEvents()


def crossing(window, action="ENTRADA", name="aluminum soda can", identity="one", visible_count=1):
    window._handle_visual_crossings([VisualCrossing(
        identity, RfidAction(action), name, 1, time.monotonic(), visible_count,
    )])


def rfid(window, line="ENTRADA:4A3B2C1D"):
    window.serial_line_input.setText(line)
    window._simulate_serial_line()


def test_main_window_requires_both_sensors_and_occlusion_never_removes(window):
    assert window.product_combo.count() == 6
    assert window.cart_table.rowCount() == 0
    assert not window.pay_button.isEnabled()
    rfid(window)
    assert window.cart_table.rowCount() == 0
    crossing(window)
    assert window.cart_table.rowCount() == 1
    assert window.pay_button.isEnabled()
    assert window.cart_table.item(0, 0).text() == "Refresco en lata"
    window._show_detections([])
    assert window.cart_table.rowCount() == 1
    rfid(window, "SALIDA:4A3B2C1D")
    assert window.cart_table.rowCount() == 0
    assert not window.pay_button.isEnabled()
    crossing(window, "SALIDA", identity="exit")
    assert window.cart_table.rowCount() == 0
    assert not window.fusion.pending and not window.fusion.issues


def test_vision_display_and_buttons_cannot_bypass_fusion(window):
    window._show_detections([{
        "class_name": "bottle", "confidence": .9,
        "bbox": (10, 20, 100, 200), "held": False,
    }])
    assert window.cart.items == []
    product = window.database.get_product_by_sku("CS-001")
    window.product_combo.setCurrentIndex(window.product_combo.findData(product.id))
    window._simulate_entry()
    assert window.cart.items == [] and window.fusion.pending
    crossing(window, name="bottle")
    assert window.cart.items[0].product.sku == "CS-001"
    assert window.cart.items[0].quantity == 1


def test_custom_chocolate_prompt_maps_to_cs006_with_joint_validation(window):
    rfid(window, "ENTRADA:13DF1E14")
    crossing(window, name=window.config.yoloe_chocolate_bar_prompt)
    assert window.cart.items[0].product.sku == "CS-006"
    assert window.database.get_product_by_sku("CS-006").stock == 100
    window._show_detections([])
    assert window.cart.items[0].quantity == 1


def test_disconnect_blocks_checkout_and_preserves_cart(window, monkeypatch):
    rfid(window)
    crossing(window)
    window._show_inference_error("test")
    assert window.cart_table.rowCount() == 1
    assert not window.pay_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: pytest.fail("Debe bloquear antes del diálogo"))
    window._pay()
    assert window.database.get_product_by_sku("CS-002").stock == 100


@pytest.mark.parametrize("failure", ["camera", "inference", "stale_frames"])
def test_rfid_exit_updates_ui_without_vision(window, failure):
    rfid(window)
    crossing(window)
    if failure == "camera":
        window._show_camera_error("test")
    elif failure == "inference":
        window._show_inference_error("test")
    else:
        window._last_observation_at = time.monotonic() - 10
        window._poll_fusion()
    assert window.cart_table.rowCount() == 1
    assert not window.fusion.available["vision"]
    rfid(window, "SALIDA:4A3B2C1D")
    assert window.cart_table.rowCount() == 0 and window.cart.total_cents == 0
    assert not window.fusion.present_uids and not window.fusion.pending
    rfid(window, "SALIDA:4A3B2C1D")
    assert window.cart_table.rowCount() == 0
    rfid(window)  # No debe permitir entradas sin webcam.
    assert window.cart_table.rowCount() == 0 and not window.fusion.pending
    assert window.database.get_product_by_sku("CS-002").stock == 100


def test_real_serial_handler_exits_without_camera(window):
    from carrito_smart.rfid import parse_rfid_line
    window.rfid_simulation.setChecked(False)
    window._rfid_availability(True)
    window.fusion.barrier -= .001
    window.fusion.rfid_exit_barrier -= .001
    window._handle_rfid_event(parse_rfid_line("ENTRADA:4A3B2C1D"))
    crossing(window)
    assert window.cart_table.rowCount() == 1
    # Encola antes de fallar la cámara, se entrega después: sigue siendo válido.
    event = parse_rfid_line("SALIDA:4A3B2C1D")
    window._show_camera_error("test")
    window._handle_rfid_event(event)
    assert window.cart_table.rowCount() == 0 and not window.fusion.present_uids


def test_product_exit_button_only_needs_rfid(window):
    rfid(window)
    crossing(window)
    window.cart_table.selectRow(0)
    window._show_camera_error("test")
    window._simulate_exit()
    assert window.cart_table.rowCount() == 0
    assert not window.fusion.pending


def test_rfid_exit_during_payment_confirmation_prevents_charge(window, monkeypatch):
    rfid(window)
    crossing(window)
    def question(*args):
        rfid(window, "SALIDA:4A3B2C1D")
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", question)
    window._pay()
    assert not window.cart.items and not window.fusion.present_uids
    assert window.database.get_product_by_sku("CS-002").stock == 100


def test_payment_cannot_confirm_a_cart_changed_during_dialog(window, monkeypatch):
    rfid(window)
    crossing(window)
    def question(*args):
        rfid(window, "ENTRADA:12345678")
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", question)
    window._pay()
    assert window.database.get_product_by_sku("CS-002").stock == 100
    assert window.cart.items and window.fusion.blocked


def test_cancel_requires_confirmation_and_discards_queued_evidence(window, monkeypatch):
    rfid(window)
    old = VisualCrossing("old", RfidAction.ENTRY, "aluminum soda can", 1, time.monotonic())
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window._clear_cart()
    assert window.fusion.pending
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window._clear_cart()
    window._handle_visual_crossings([old])
    assert not window.fusion.pending and not window.fusion.present_uids


def test_approved_payment_discounts_inventory_only_once(window, monkeypatch):
    from carrito_smart.receipt_dialog import ReceiptDialog
    rfid(window)
    crossing(window)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(ReceiptDialog, "exec", lambda *args: None)
    window._pay()
    assert window.database.get_product_by_sku("CS-002").stock == 99
    assert not window.cart.items and not window.fusion.present_uids
    window._pay()
    assert window.database.get_product_by_sku("CS-002").stock == 99


def test_camera_only_notice_cannot_enable_payment_for_empty_cart(window):
    crossing(window)
    assert not window.fusion.blocked
    assert not window.pay_button.isEnabled() and not window.cart.items
    window.fusion.tick(now=time.monotonic() + 3.1)
    window._refresh_fusion()
    assert window.fusion.visual_notices and not window.fusion.issues
    assert not window.pay_button.isEnabled()


@pytest.mark.parametrize("expired", [False, True])
def test_extra_chocolate_notice_allows_paying_only_confirmed_units(window, monkeypatch, expired):
    from carrito_smart.receipt_dialog import ReceiptDialog
    rfid(window, "ENTRADA:13DF1E14")
    crossing(window, name=window.config.yoloe_chocolate_bar_prompt)
    total = window.cart.total_cents
    crossing(window, name=window.config.yoloe_chocolate_bar_prompt, identity="extra", visible_count=2)
    if expired:
        window.fusion.tick(now=time.monotonic() + 3.1)
        window._refresh_fusion()
    assert window.pay_button.isEnabled() and window.cart.total_cents == total
    assert "Aviso CS-006" in window.vision_cart_status.text()
    receipts = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(ReceiptDialog, "exec", lambda self: receipts.append(True))
    window._pay()
    assert receipts == [True]
    assert window.database.get_product_by_sku("CS-006").stock == 99
    assert not window.cart.items and not window.fusion.visual_notices
    window._pay()
    assert window.database.get_product_by_sku("CS-006").stock == 99


def test_visual_events_during_confirmation_do_not_cancel_payment(window, monkeypatch):
    from carrito_smart.receipt_dialog import ReceiptDialog
    rfid(window)
    crossing(window)
    def question(*args):
        crossing(window, identity="extra", visible_count=2)
        window.fusion.tick(now=time.monotonic() + 3.1)
        crossing(window, identity="another-extra", visible_count=2)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", question)
    monkeypatch.setattr(ReceiptDialog, "exec", lambda *args: None)
    window._pay()
    assert window.database.get_product_by_sku("CS-002").stock == 99
    assert not window.cart.items


def test_rfid_without_camera_confirmation_still_disables_payment_after_timeout(window):
    rfid(window)
    crossing(window)
    rfid(window, "ENTRADA:12345678")
    assert not window.pay_button.isEnabled()
    window.fusion.tick(now=time.monotonic() + 3.1)
    window._refresh_fusion()
    assert window.fusion.issues and not window.pay_button.isEnabled()
    crossing(window, identity="extra", visible_count=2)
    assert not window.pay_button.isEnabled()
    assert window.database.get_product_by_sku("CS-002").stock == 100


def test_transient_sensor_failure_during_dialog_still_prevents_charge(window, monkeypatch):
    rfid(window)
    crossing(window)
    def question(*args):
        window._show_inference_error("test")
        window._vision_observation(time.monotonic())
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", question)
    window._pay()
    assert not window.fusion.blocked  # Volvió el sensor, pero la validación cambió.
    assert window.cart.items
    assert window.database.get_product_by_sku("CS-002").stock == 100
