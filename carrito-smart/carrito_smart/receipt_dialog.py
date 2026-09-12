"""Comprobante de compra mostrado en la pantalla del carrito."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from carrito_smart.models import CartItem, SaleReceipt, format_money


class ReceiptDialog(QDialog):
    """Confirma el pago y presenta un ticket digital orientado al cliente."""

    def __init__(
        self,
        receipt: SaleReceipt,
        purchased_items: list[CartItem],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.receipt = receipt
        self.purchased_items = purchased_items
        self.setWindowTitle("Pago aprobado · Carrito Smart")
        self.setModal(True)
        self.resize(620, 520)
        self.setMinimumSize(540, 440)
        self._build_ui()
        self._apply_styles()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        check = QLabel("✓")
        check.setObjectName("successIcon")
        check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(check, alignment=Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("¡Pago aprobado!")
        title.setObjectName("receiptTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        subtitle = QLabel(
            f"Compra #{self.receipt.sale_id} registrada correctamente"
        )
        subtitle.setObjectName("receiptSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(subtitle)

        self.items_table = QTableWidget(len(self.purchased_items), 4)
        self.items_table.setHorizontalHeaderLabels(
            ["Producto", "Cant.", "Precio", "Subtotal"]
        )
        self.items_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.items_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, 4):
            self.items_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        for row, item in enumerate(self.purchased_items):
            values = (
                item.product.name,
                str(item.quantity),
                format_money(item.product.price_cents),
                format_money(item.subtotal_cents),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column > 0:
                    cell.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.items_table.setItem(row, column, cell)
        root.addWidget(self.items_table, 1)

        total_card = QWidget()
        total_card.setObjectName("receiptTotalCard")
        total_layout = QHBoxLayout(total_card)
        total_caption = QLabel("TOTAL PAGADO")
        total_caption.setObjectName("totalCaption")
        total_value = QLabel(format_money(self.receipt.total_cents))
        total_value.setObjectName("receiptTotal")
        total_layout.addWidget(total_caption)
        total_layout.addStretch()
        total_layout.addWidget(total_value)
        root.addWidget(total_card)

        message = QLabel(
            "Gracias por su compra. Puede retirar sus productos del carrito."
        )
        message.setObjectName("thanksMessage")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setWordWrap(True)
        root.addWidget(message)

        self.new_purchase_button = QPushButton("Iniciar nueva compra")
        self.new_purchase_button.setObjectName("newPurchaseButton")
        self.new_purchase_button.clicked.connect(self.accept)
        root.addWidget(self.new_purchase_button)

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QDialog { background: #f8fafc; color: #17212b; }
            QLabel#successIcon {
                background: #16a34a; color: white; border-radius: 30px;
                min-width: 60px; max-width: 60px; min-height: 60px;
                max-height: 60px; font-size: 38px; font-weight: 700;
            }
            QLabel#receiptTitle { color: #166534; font-size: 28px; font-weight: 800; }
            QLabel#receiptSubtitle { color: #52667a; font-size: 15px; }
            QTableWidget { background: white; border: 1px solid #cbd5e1; border-radius: 7px; }
            QHeaderView::section { background: #e8edf2; border: none; padding: 8px; font-weight: 700; }
            QWidget#receiptTotalCard { background: #102a43; border-radius: 8px; }
            QLabel#totalCaption { background: transparent; color: #cbd5e1; font-weight: 700; }
            QLabel#receiptTotal { background: transparent; color: white; font-size: 25px; font-weight: 800; }
            QLabel#thanksMessage { color: #475569; }
            QPushButton#newPurchaseButton {
                background: #2563eb; color: white; border: none;
                border-radius: 7px; padding: 12px; font-size: 16px; font-weight: 700;
            }
            QPushButton#newPurchaseButton:hover { background: #1d4ed8; }
            """
        )
