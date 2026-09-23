"""Demostración visual de PayPal.

No consume servicios de PayPal, no almacena credenciales y no modifica la BD.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from carrito_smart.models import format_money


class PayPalDemoDialog(QDialog):
    def __init__(self, total_cents: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.total_cents = total_cents
        self.setWindowTitle("PayPal · DEMO")
        self.setFixedSize(520, 610)
        self._build_ui()
        self.setStyleSheet(_STYLE)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 24)
        root.setSpacing(14)

        top = QHBoxLayout()
        brand = QLabel("PayPal")
        brand.setObjectName("brand")
        top.addWidget(brand)
        top.addStretch()
        demo = QLabel("DEMO")
        demo.setObjectName("demo")
        top.addWidget(demo)
        root.addLayout(top)

        notice = QLabel("Simulación visual para la presentación. No se conecta a PayPal ni realiza un cobro real.")
        notice.setObjectName("notice")
        notice.setWordWrap(True)
        root.addWidget(notice)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._checkout_page())
        self.stack.addWidget(self._processing_page())
        self.stack.addWidget(self._approved_page())
        root.addWidget(self.stack, 1)

    def _checkout_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(14)
        merchant = QLabel("SmartCart")
        merchant.setObjectName("merchant")
        merchant.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(merchant)
        total_caption = QLabel("TOTAL DE LA COMPRA")
        total_caption.setObjectName("caption")
        total_caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(total_caption)
        total = QLabel(format_money(self.total_cents))
        total.setObjectName("total")
        total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(total)
        layout.addSpacing(8)

        card = QFrame()
        card.setObjectName("loginCard")
        card_layout = QVBoxLayout(card)
        label = QLabel("Correo de PayPal")
        label.setObjectName("fieldLabel")
        card_layout.addWidget(label)
        self.email = QLineEdit("cliente.demo@paypal.local")
        self.email.setReadOnly(True)
        card_layout.addWidget(self.email)
        label2 = QLabel("Cuenta demostrativa")
        label2.setObjectName("fieldLabel")
        card_layout.addWidget(label2)
        account = QLineEdit("••••••••••")
        account.setReadOnly(True)
        card_layout.addWidget(account)
        layout.addWidget(card)
        layout.addStretch()

        approve = QPushButton("Simular aprobación con PayPal")
        approve.setObjectName("paypalButton")
        approve.clicked.connect(self._process)
        layout.addWidget(approve)
        cancel = QPushButton("Cerrar demostración")
        cancel.setObjectName("secondary")
        cancel.clicked.connect(self.reject)
        layout.addWidget(cancel)
        return page

    def _processing_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel("Procesando pago…")
        label.setObjectName("processing")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        amount = QLabel(format_money(self.total_cents))
        amount.setObjectName("processingTotal")
        amount.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(amount)
        text = QLabel("Modo demostración · no se está enviando ninguna transacción")
        text.setObjectName("muted")
        text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        text.setWordWrap(True)
        layout.addWidget(text)
        return page

    def _approved_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        check = QLabel("✓")
        check.setObjectName("check")
        check.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(check)
        title = QLabel("Pago PayPal aprobado")
        title.setObjectName("approved")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        amount = QLabel(format_money(self.total_cents))
        amount.setObjectName("approvedTotal")
        amount.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(amount)
        warning = QLabel("Demostración visual únicamente. El inventario y la venta real no fueron modificados.")
        warning.setObjectName("muted")
        warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        layout.addSpacing(18)
        close = QPushButton("Continuar")
        close.setObjectName("paypalButton")
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        return page

    def _process(self) -> None:
        self.stack.setCurrentIndex(1)
        QTimer.singleShot(1200, lambda: self.stack.setCurrentIndex(2))


_STYLE = """
QDialog, QWidget { background: #f6f8fb; color: #17233a; font-family: "Segoe UI"; font-size: 14px; }
QLabel#brand { color: #003087; font-size: 30px; font-weight: 800; font-style: italic; }
QLabel#demo { background: #e7edf8; color: #4c6285; border-radius: 8px; padding: 5px 9px; font-size: 11px; font-weight: 800; }
QLabel#notice { background: #fff8df; border: 1px solid #ead998; color: #6f5a18; border-radius: 8px; padding: 10px; }
QLabel#merchant { font-size: 21px; font-weight: 750; }
QLabel#caption { color: #68778d; font-size: 11px; font-weight: 750; }
QLabel#total { color: #10284d; font-size: 38px; font-weight: 850; }
QFrame#loginCard { background: white; border: 1px solid #dce4ef; border-radius: 10px; }
QLabel#fieldLabel { color: #5d6b80; font-size: 12px; font-weight: 650; }
QLineEdit { background: #f8fafc; border: 1px solid #d6dfeb; border-radius: 8px; padding: 11px; }
QPushButton#paypalButton { background: #0070ba; color: white; border: none; border-radius: 22px; padding: 13px 18px; font-size: 15px; font-weight: 750; }
QPushButton#paypalButton:hover { background: #005ea6; }
QPushButton#secondary { background: transparent; color: #4c5e78; border: none; padding: 10px; }
QLabel#processing { font-size: 25px; font-weight: 750; color: #173765; }
QLabel#processingTotal { font-size: 33px; font-weight: 850; color: #003087; }
QLabel#check { color: #1c9b67; font-size: 70px; font-weight: 900; }
QLabel#approved { font-size: 24px; font-weight: 800; }
QLabel#approvedTotal { font-size: 33px; font-weight: 850; color: #173765; }
QLabel#muted { color: #6b7a90; }
"""
