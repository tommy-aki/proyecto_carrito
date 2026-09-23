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
        root.setSpacing(14)

        header = QWidget()
        header.setObjectName("receiptHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 18, 20, 18)
        header_layout.setSpacing(6)

        check = QLabel("✓")
        check.setObjectName("successIcon")
        check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(check, alignment=Qt.AlignmentFlag.AlignHCenter)

        title = QLabel("¡Pago aprobado!")
        title.setObjectName("receiptTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(title)

        subtitle = QLabel(
            f"Compra #{self.receipt.sale_id} registrada correctamente"
        )
        subtitle.setObjectName("receiptSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(subtitle)
        root.addWidget(header)

        detail_title = QLabel("Resumen de compra")
        detail_title.setObjectName("detailTitle")
        root.addWidget(detail_title)

        self.items_table = QTableWidget(len(self.purchased_items), 4)
        self.items_table.setObjectName("receiptTable")
        self.items_table.setHorizontalHeaderLabels(
            ["Producto", "Cant.", "Precio", "Subtotal"]
        )
        self.items_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.items_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.items_table.setAlternatingRowColors(True)
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
        total_layout.setContentsMargins(18, 13, 18, 13)
        total_caption = QLabel("TOTAL PAGADO")
        total_caption.setObjectName("totalCaption")
        total_value = QLabel(format_money(self.receipt.total_cents))
        total_value.setObjectName("receiptTotal")
        total_layout.addWidget(total_caption)
        total_layout.addStretch()
        total_layout.addWidget(total_value)
        root.addWidget(total_card)

        message = QLabel(
            "Compra finalizada. Retire sus productos y cierre el carrito al terminar."
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
            QDialog {
                background: #eef3f8;
                color: #17283b;
            }
            QWidget#receiptHeader {
                background: #ffffff;
                border: 1px solid #dbe5ef;
                border-radius: 14px;
            }
            QLabel#successIcon {
                background: #14945f;
                color: #ffffff;
                border-radius: 27px;
                min-width: 54px;
                max-width: 54px;
                min-height: 54px;
                max-height: 54px;
                font-size: 32px;
                font-weight: 800;
            }
            QLabel#receiptTitle {
                color: #116a47;
                font-size: 26px;
                font-weight: 900;
            }
            QLabel#receiptSubtitle {
                color: #667b90;
                font-size: 13px;
            }
            QLabel#detailTitle {
                color: #102a43;
                font-size: 15px;
                font-weight: 800;
            }
            QTableWidget#receiptTable {
                background: #ffffff;
                alternate-background-color: #f8fafc;
                color: #1f2f42;
                border: 1px solid #dbe5ef;
                border-radius: 10px;
                gridline-color: #edf1f5;
                outline: none;
            }
            QHeaderView::section {
                background: #f3f6fa;
                color: #4b6076;
                border: none;
                border-bottom: 1px solid #dbe5ef;
                padding: 9px 8px;
                font-size: 11px;
                font-weight: 800;
            }
            QWidget#receiptTotalCard {
                background: #102a43;
                border-radius: 11px;
            }
            QLabel#totalCaption {
                background: transparent;
                color: #c6d5e5;
                font-size: 12px;
                font-weight: 800;
            }
            QLabel#receiptTotal {
                background: transparent;
                color: #ffffff;
                font-size: 25px;
                font-weight: 900;
            }
            QLabel#thanksMessage {
                color: #52677d;
                font-size: 12px;
                padding: 2px 8px;
            }
            QPushButton#newPurchaseButton {
                background: #0f67d8;
                color: #ffffff;
                border: 1px solid #0f67d8;
                border-radius: 9px;
                padding: 12px;
                font-size: 15px;
                font-weight: 800;
            }
            QPushButton#newPurchaseButton:hover {
                background: #0c59bc;
            }
            """
        )
