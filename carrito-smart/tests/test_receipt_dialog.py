from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog

from carrito_smart.models import CartItem, Product, SaleReceipt
from carrito_smart.receipt_dialog import ReceiptDialog


def test_receipt_dialog_shows_paid_items_and_total():
    application = QApplication.instance() or QApplication([])
    product = Product(1, "CS-001", "Botella de agua", 1800, 20)
    receipt = SaleReceipt(sale_id=42, total_cents=3600)

    dialog = ReceiptDialog(receipt, [CartItem(product, 2)])
    application.processEvents()

    assert dialog.items_table.rowCount() == 1
    assert dialog.items_table.item(0, 0).text() == "Botella de agua"
    assert dialog.items_table.item(0, 1).text() == "2"
    assert dialog.windowTitle() == "Pago aprobado · Carrito Smart"
    dialog.new_purchase_button.click()
    assert dialog.result() == QDialog.DialogCode.Accepted
