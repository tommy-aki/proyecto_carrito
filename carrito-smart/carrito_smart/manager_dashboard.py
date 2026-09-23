"""Centro gerencial demostrativo para monitoreo multi-sucursal.

Todos los carritos y sucursales, salvo C-01, viven únicamente en memoria.
No crea tablas, no modifica SQLite y no representa hardware adicional real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from carrito_smart.cart import CartService
from carrito_smart.models import format_money


@dataclass(slots=True)
class DemoItem:
    name: str
    quantity: int
    unit_price_cents: int

    @property
    def subtotal_cents(self) -> int:
        return self.quantity * self.unit_price_cents


@dataclass(slots=True)
class DemoCart:
    code: str
    branch: str
    status: str
    camera_ok: bool = True
    rfid_a_ok: bool = True
    rfid_b_ok: bool = True
    physical: bool = False
    items: list[DemoItem] = field(default_factory=list)
    last_seen: str = "Ahora"

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def total_cents(self) -> int:
        return sum(item.subtotal_cents for item in self.items)

    @property
    def has_alert(self) -> bool:
        return not (self.camera_ok and self.rfid_a_ok and self.rfid_b_ok)

    @property
    def sensor_summary(self) -> str:
        failures: list[str] = []
        if not self.camera_ok:
            failures.append("Cámara")
        if not self.rfid_a_ok:
            failures.append("RFID A")
        if not self.rfid_b_ok:
            failures.append("RFID B")
        return ", ".join(failures) if failures else "Sensores operativos"


@dataclass(slots=True)
class DemoBranch:
    name: str
    manager: str
    location: str
    carts: list[DemoCart]


class CartDetailDialog(QDialog):
    """Detalle gerencial de un carrito real o simulado."""

    def __init__(
        self,
        cart: DemoCart,
        manager_name: str,
        physical_cart: CartService,
        frame_provider: Callable[[], QImage | None],
        hardware_status_provider: Callable[[], dict[str, bool]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.cart_demo = cart
        self.manager_name = manager_name
        self.physical_cart = physical_cart
        self.frame_provider = frame_provider
        self.hardware_status_provider = hardware_status_provider
        self.setWindowTitle(f"{cart.code} · Detalle del carrito")
        self.resize(980, 650)
        self.setMinimumSize(860, 580)
        self._build_ui()
        self._refresh()
        self._timer = QTimer(self)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        self.title = QLabel(f"Carrito {self.cart_demo.code}")
        self.title.setObjectName("dialogTitle")
        self.subtitle = QLabel(f"{self.cart_demo.branch} · Encargado: {self.manager_name}")
        self.subtitle.setObjectName("muted")
        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)
        header.addLayout(title_box)
        header.addStretch()
        self.status_badge = QLabel()
        self.status_badge.setObjectName("statusBadge")
        header.addWidget(self.status_badge)
        root.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "General")
        self.tabs.addTab(self._purchase_tab(), "Compra actual")
        self.tabs.addTab(self._camera_tab(), "Cámara")
        self.tabs.addTab(self._sensors_tab(), "Sensores")
        root.addWidget(self.tabs, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        close_button = QPushButton("Cerrar")
        close_button.setObjectName("secondaryButton")
        close_button.clicked.connect(self.accept)
        footer.addWidget(close_button)
        root.addLayout(footer)

        self.setStyleSheet(_DIALOG_STYLE)

    def _general_tab(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(10, 18, 10, 10)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(14)
        self.general_labels: dict[str, QLabel] = {}
        labels = [
            ("Sucursal", "branch"),
            ("Encargado", "manager"),
            ("Tipo", "type"),
            ("Estado", "status"),
            ("Artículos", "items"),
            ("Total actual", "total"),
            ("Última comunicación", "seen"),
            ("Estado técnico", "technical"),
        ]
        for index, (caption, key) in enumerate(labels):
            card = QFrame()
            card.setObjectName("infoCard")
            card_layout = QVBoxLayout(card)
            cap = QLabel(caption.upper())
            cap.setObjectName("smallLabel")
            value = QLabel("—")
            value.setObjectName("infoValue")
            value.setWordWrap(True)
            card_layout.addWidget(cap)
            card_layout.addWidget(value)
            self.general_labels[key] = value
            layout.addWidget(card, index // 2, index % 2)
        return page

    def _purchase_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 18, 10, 10)
        self.purchase_hint = QLabel()
        self.purchase_hint.setObjectName("muted")
        layout.addWidget(self.purchase_hint)
        self.items_table = QTableWidget(0, 4)
        self.items_table.setHorizontalHeaderLabels(["Producto", "Cant.", "Precio", "Subtotal"])
        self.items_table.verticalHeader().setVisible(False)
        self.items_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.items_table.horizontalHeader().setStretchLastSection(False)
        self.items_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            self.items_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.items_table, 1)
        self.purchase_total = QLabel()
        self.purchase_total.setObjectName("purchaseTotal")
        self.purchase_total.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self.purchase_total)
        return page

    def _camera_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 18, 10, 10)
        camera_header = QHBoxLayout()
        label = QLabel("Vista del carrito")
        label.setObjectName("tabHeading")
        camera_header.addWidget(label)
        camera_header.addStretch()
        self.camera_status = QLabel()
        self.camera_status.setObjectName("cameraStatus")
        camera_header.addWidget(self.camera_status)
        layout.addLayout(camera_header)
        self.camera_view = QLabel()
        self.camera_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.camera_view.setMinimumHeight(380)
        self.camera_view.setObjectName("cameraView")
        layout.addWidget(self.camera_view, 1)
        self.camera_note = QLabel()
        self.camera_note.setObjectName("muted")
        self.camera_note.setWordWrap(True)
        layout.addWidget(self.camera_note)
        return page

    def _sensors_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 18, 10, 10)
        heading = QLabel("Estado de sensores")
        heading.setObjectName("tabHeading")
        layout.addWidget(heading)
        grid = QGridLayout()
        grid.setSpacing(14)
        self.sensor_labels: dict[str, QLabel] = {}
        for column, (key, title) in enumerate((
            ("rfid_a", "RFID A · Entrada"),
            ("rfid_b", "RFID B · Salida"),
            ("camera", "Cámara"),
        )):
            card = QFrame()
            card.setObjectName("sensorCard")
            card_layout = QVBoxLayout(card)
            name = QLabel(title)
            name.setObjectName("sensorName")
            state = QLabel()
            state.setObjectName("sensorState")
            detail = QLabel("Monitoreo centralizado")
            detail.setObjectName("muted")
            card_layout.addWidget(name)
            card_layout.addWidget(state)
            card_layout.addWidget(detail)
            grid.addWidget(card, 0, column)
            self.sensor_labels[key] = state
        layout.addLayout(grid)
        layout.addStretch()
        disclaimer = QLabel(
            "Los carritos marcados DEMO son representaciones visuales para la presentación; "
            "no corresponden a hardware adicional conectado."
        )
        disclaimer.setObjectName("demoNotice")
        disclaimer.setWordWrap(True)
        layout.addWidget(disclaimer)
        return page

    def _current_items(self) -> list[DemoItem]:
        if self.cart_demo.physical:
            return [
                DemoItem(item.product.name, item.quantity, item.product.price_cents)
                for item in self.physical_cart.items
            ]
        return list(self.cart_demo.items)

    def _current_sensor_status(self) -> tuple[bool, bool, bool]:
        if not self.cart_demo.physical:
            return self.cart_demo.camera_ok, self.cart_demo.rfid_a_ok, self.cart_demo.rfid_b_ok
        runtime = self.hardware_status_provider()
        return (
            bool(runtime.get("camera", False)),
            bool(runtime.get("rfid_a", False)),
            bool(runtime.get("rfid_b", False)),
        )

    def _refresh(self) -> None:
        items = self._current_items()
        camera_ok, rfid_a_ok, rfid_b_ok = self._current_sensor_status()
        total = sum(item.subtotal_cents for item in items)
        count = sum(item.quantity for item in items)
        healthy = camera_ok and rfid_a_ok and rfid_b_ok

        self.status_badge.setText("● OPERATIVO" if healthy else "● REQUIERE ATENCIÓN")
        self.status_badge.setProperty("alert", not healthy)
        self.status_badge.style().unpolish(self.status_badge)
        self.status_badge.style().polish(self.status_badge)

        values = {
            "branch": self.cart_demo.branch,
            "manager": self.manager_name,
            "type": "FÍSICO" if self.cart_demo.physical else "DEMO",
            "status": self.cart_demo.status,
            "items": str(count),
            "total": format_money(total),
            "seen": datetime.now().strftime("%H:%M:%S") if self.cart_demo.physical else self.cart_demo.last_seen,
            "technical": "Sensores operativos" if healthy else self._technical_text(camera_ok, rfid_a_ok, rfid_b_ok),
        }
        for key, value in values.items():
            self.general_labels[key].setText(value)

        self.purchase_hint.setText(
            "Datos reales del carrito físico C-01." if self.cart_demo.physical
            else "Datos de demostración; no se guardan en la base de datos."
        )
        self.items_table.setRowCount(len(items))
        for row, item in enumerate(items):
            values_row = (item.name, str(item.quantity), format_money(item.unit_price_cents), format_money(item.subtotal_cents))
            for column, text in enumerate(values_row):
                cell = QTableWidgetItem(text)
                if column > 0:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.items_table.setItem(row, column, cell)
        self.purchase_total.setText(f"TOTAL · {format_money(total)}")

        self._set_sensor(self.sensor_labels["camera"], camera_ok)
        self._set_sensor(self.sensor_labels["rfid_a"], rfid_a_ok)
        self._set_sensor(self.sensor_labels["rfid_b"], rfid_b_ok)
        self._refresh_camera(camera_ok)

    @staticmethod
    def _technical_text(camera_ok: bool, rfid_a_ok: bool, rfid_b_ok: bool) -> str:
        failed: list[str] = []
        if not camera_ok:
            failed.append("Cámara sin señal")
        if not rfid_a_ok:
            failed.append("RFID A no detectado")
        if not rfid_b_ok:
            failed.append("RFID B no detectado")
        return " · ".join(failed)

    @staticmethod
    def _set_sensor(label: QLabel, ok: bool) -> None:
        label.setText("✓ OPERATIVO" if ok else "✕ NO DETECTADO")
        label.setProperty("alert", not ok)
        label.style().unpolish(label)
        label.style().polish(label)

    def _refresh_camera(self, camera_ok: bool) -> None:
        if not camera_ok:
            self.camera_status.setText("● SIN SEÑAL")
            self.camera_status.setProperty("alert", True)
            self.camera_view.setPixmap(QPixmap())
            self.camera_view.setText("CÁMARA SIN SEÑAL\n\nRevise conexión o alimentación")
            self.camera_note.setText("El centro gerencial marcó este carrito en rojo porque la cámara no responde.")
        elif self.cart_demo.physical:
            self.camera_status.setText("● EN VIVO")
            self.camera_status.setProperty("alert", False)
            frame = self.frame_provider()
            if frame is None:
                self.camera_view.setPixmap(QPixmap())
                self.camera_view.setText("Esperando imagen de la cámara física C-01…")
            else:
                pixmap = QPixmap.fromImage(frame)
                self.camera_view.setPixmap(pixmap.scaled(
                    self.camera_view.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
            self.camera_note.setText("C-01 utiliza la cámara real del prototipo cuando está disponible.")
        else:
            self.camera_status.setText("● DEMO · OPERATIVA")
            self.camera_status.setProperty("alert", False)
            self.camera_view.setPixmap(QPixmap())
            self.camera_view.setText(
                f"VISTA DE CÁMARA SIMULADA\n\n{self.cart_demo.code} · {self.cart_demo.branch}\n\n"
                "Demostración visual — no existe una cámara física adicional"
            )
            self.camera_note.setText("Vista simulada para demostrar monitoreo remoto de múltiples carritos.")
        self.camera_status.style().unpolish(self.camera_status)
        self.camera_status.style().polish(self.camera_status)


class ManagerDashboardWindow(QMainWindow):
    """Interfaz gerencial 100 % demostrativa, salvo C-01."""

    def __init__(
        self,
        physical_cart: CartService,
        frame_provider: Callable[[], QImage | None],
        hardware_status_provider: Callable[[], dict[str, bool]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.physical_cart = physical_cart
        self.frame_provider = frame_provider
        self.hardware_status_provider = hardware_status_provider
        self.branches = self._build_demo_branches()
        self.setWindowTitle("SmartCart · Centro Gerencial (DEMO)")
        self.resize(1440, 860)
        self.setMinimumSize(1120, 700)
        self._build_ui()
        self._apply_styles()
        self._refresh()
        self._timer = QTimer(self)
        self._timer.setInterval(1200)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    def _build_demo_branches(self) -> list[DemoBranch]:
        return [
            DemoBranch(
                "Sucursal Centro",
                "Ana López",
                "Zona Centro",
                [
                    DemoCart("C-01", "Sucursal Centro", "COMPRANDO", physical=True),
                    DemoCart("C-02", "Sucursal Centro", "COMPRANDO", camera_ok=False,
                             items=[DemoItem("Leche entera", 1, 4200), DemoItem("Chocolate", 2, 2750)], last_seen="Hace 12 s"),
                    DemoCart("C-03", "Sucursal Centro", "DISPONIBLE", items=[], last_seen="Hace 5 s"),
                    DemoCart("C-04", "Sucursal Centro", "PAGANDO", rfid_b_ok=False,
                             items=[DemoItem("Botella de agua", 2, 1800), DemoItem("Refresco en lata", 1, 2500)], last_seen="Hace 18 s"),
                ],
            ),
            DemoBranch(
                "Sucursal Mall",
                "Carlos Rivera",
                "Centro Comercial",
                [
                    DemoCart("M-01", "Sucursal Mall", "COMPRANDO",
                             items=[DemoItem("Caja de cereal", 1, 8950), DemoItem("Leche entera", 1, 4200)], last_seen="Ahora"),
                    DemoCart("M-02", "Sucursal Mall", "DISPONIBLE", last_seen="Hace 4 s"),
                    DemoCart("M-03", "Sucursal Mall", "COMPRANDO", rfid_a_ok=False,
                             items=[DemoItem("Chocolate", 3, 2750)], last_seen="Hace 24 s"),
                    DemoCart("M-04", "Sucursal Mall", "DISPONIBLE", last_seen="Ahora"),
                ],
            ),
            DemoBranch(
                "Sucursal Norte",
                "Sofía Martínez",
                "Zona Norte",
                [
                    DemoCart("N-01", "Sucursal Norte", "COMPRANDO",
                             items=[DemoItem("Botella de agua", 1, 1800), DemoItem("Bolsa de papas", 1, 3200)], last_seen="Hace 3 s"),
                    DemoCart("N-02", "Sucursal Norte", "COMPRANDO", camera_ok=False, rfid_a_ok=False,
                             items=[DemoItem("Refresco en lata", 2, 2500)], last_seen="Hace 31 s"),
                    DemoCart("N-03", "Sucursal Norte", "PAGANDO",
                             items=[DemoItem("Chocolate", 1, 2750), DemoItem("Leche entera", 1, 4200)], last_seen="Ahora"),
                    DemoCart("N-04", "Sucursal Norte", "DISPONIBLE", last_seen="Hace 8 s"),
                ],
            ),
        ]

    def _build_ui(self) -> None:
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(270)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(22, 26, 22, 22)
        side.setSpacing(12)
        brand = QLabel("SMARTCART")
        brand.setObjectName("brand")
        side.addWidget(brand)
        subtitle = QLabel("CENTRO GERENCIAL · DEMO")
        subtitle.setObjectName("brandSub")
        side.addWidget(subtitle)
        side.addSpacing(16)
        branch_label = QLabel("SUCURSALES")
        branch_label.setObjectName("sideLabel")
        side.addWidget(branch_label)
        self.branch_list = QListWidget()
        self.branch_list.setObjectName("branchList")
        self.branch_list.addItem("Todas las sucursales")
        for branch in self.branches:
            item = QListWidgetItem(f"{branch.name}\n{branch.manager}")
            item.setData(Qt.ItemDataRole.UserRole, branch.name)
            self.branch_list.addItem(item)
        self.branch_list.setCurrentRow(0)
        self.branch_list.currentRowChanged.connect(self._refresh)
        side.addWidget(self.branch_list)
        side.addStretch()
        demo_notice = QLabel("Los carritos adicionales y sucursales son simulados para la demostración del evento.")
        demo_notice.setObjectName("demoSide")
        demo_notice.setWordWrap(True)
        side.addWidget(demo_notice)
        back = QPushButton("Volver al carrito")
        back.setObjectName("backButton")
        back.clicked.connect(self.close)
        side.addWidget(back)
        root.addWidget(sidebar)

        content = QWidget()
        main = QVBoxLayout(content)
        main.setContentsMargins(28, 24, 28, 24)
        main.setSpacing(18)

        top = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Operación de tienda")
        title.setObjectName("pageTitle")
        title_box.addWidget(title)
        self.branch_info = QLabel()
        self.branch_info.setObjectName("pageSubtitle")
        title_box.addWidget(self.branch_info)
        top.addLayout(title_box)
        top.addStretch()
        self.updated_label = QLabel()
        self.updated_label.setObjectName("updated")
        top.addWidget(self.updated_label)
        main.addLayout(top)

        self.kpi_layout = QHBoxLayout()
        self.kpi_layout.setSpacing(12)
        self.kpi_values: dict[str, QLabel] = {}
        for key, caption in (
            ("branches", "Sucursales"),
            ("carts", "Carritos"),
            ("active", "En uso"),
            ("alerts", "Alertas técnicas"),
        ):
            card = QFrame()
            card.setObjectName("kpi")
            box = QVBoxLayout(card)
            value = QLabel("0")
            value.setObjectName("kpiValue")
            name = QLabel(caption)
            name.setObjectName("kpiCaption")
            box.addWidget(value)
            box.addWidget(name)
            self.kpi_values[key] = value
            self.kpi_layout.addWidget(card, 1)
        main.addLayout(self.kpi_layout)

        body = QHBoxLayout()
        body.setSpacing(16)

        cart_area = QFrame()
        cart_area.setObjectName("section")
        carts_layout = QVBoxLayout(cart_area)
        carts_header = QHBoxLayout()
        carts_title = QLabel("Carritos")
        carts_title.setObjectName("sectionTitle")
        carts_header.addWidget(carts_title)
        carts_header.addStretch()
        filter_label = QLabel("Mostrar")
        filter_label.setObjectName("muted")
        carts_header.addWidget(filter_label)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["Todos", "Con alertas", "Comprando", "Pagando", "Disponibles"])
        self.status_filter.currentIndexChanged.connect(self._refresh)
        carts_header.addWidget(self.status_filter)
        carts_layout.addLayout(carts_header)
        self.cart_scroll = QScrollArea()
        self.cart_scroll.setWidgetResizable(True)
        self.cart_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.cart_host = QWidget()
        self.cart_grid = QGridLayout(self.cart_host)
        self.cart_grid.setSpacing(12)
        self.cart_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.cart_scroll.setWidget(self.cart_host)
        carts_layout.addWidget(self.cart_scroll, 1)
        body.addWidget(cart_area, 3)

        alerts = QFrame()
        alerts.setObjectName("section")
        alerts.setMinimumWidth(310)
        alerts.setMaximumWidth(380)
        alerts_layout = QVBoxLayout(alerts)
        alert_header = QHBoxLayout()
        alert_title = QLabel("Alertas")
        alert_title.setObjectName("sectionTitle")
        alert_header.addWidget(alert_title)
        alert_header.addStretch()
        self.alert_count = QLabel("0")
        self.alert_count.setObjectName("alertCount")
        alert_header.addWidget(self.alert_count)
        alerts_layout.addLayout(alert_header)
        self.alert_list = QListWidget()
        self.alert_list.setObjectName("alertList")
        self.alert_list.itemDoubleClicked.connect(self._open_alert_cart)
        alerts_layout.addWidget(self.alert_list, 1)
        hint = QLabel("Seleccione un carrito en rojo para revisar cámara, RFIDs y compra actual.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        alerts_layout.addWidget(hint)
        body.addWidget(alerts, 1)

        main.addLayout(body, 1)
        root.addWidget(content, 1)
        self.setCentralWidget(central)

    def _selected_branch(self) -> str | None:
        item = self.branch_list.currentItem()
        if item is None or self.branch_list.currentRow() == 0:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _all_carts(self) -> list[DemoCart]:
        carts: list[DemoCart] = []
        for branch in self.branches:
            carts.extend(branch.carts)
        self._sync_physical_cart(carts)
        return carts

    def _sync_physical_cart(self, carts: list[DemoCart]) -> None:
        physical = next((cart for cart in carts if cart.physical), None)
        if physical is None:
            return
        runtime = self.hardware_status_provider()
        physical.camera_ok = bool(runtime.get("camera", False))
        physical.rfid_a_ok = bool(runtime.get("rfid_a", False))
        physical.rfid_b_ok = bool(runtime.get("rfid_b", False))
        physical.status = "COMPRANDO" if self.physical_cart.items else "DISPONIBLE"
        physical.items = [
            DemoItem(item.product.name, item.quantity, item.product.price_cents)
            for item in self.physical_cart.items
        ]
        physical.last_seen = "Ahora"

    def _filtered_carts(self) -> list[DemoCart]:
        carts = self._all_carts()
        selected_branch = self._selected_branch()
        if selected_branch:
            carts = [cart for cart in carts if cart.branch == selected_branch]
        mode = self.status_filter.currentText()
        if mode == "Con alertas":
            carts = [cart for cart in carts if cart.has_alert]
        elif mode == "Comprando":
            carts = [cart for cart in carts if cart.status == "COMPRANDO"]
        elif mode == "Pagando":
            carts = [cart for cart in carts if cart.status == "PAGANDO"]
        elif mode == "Disponibles":
            carts = [cart for cart in carts if cart.status == "DISPONIBLE"]
        return carts

    def _refresh(self, *_args) -> None:
        all_carts = self._all_carts()
        selected_branch = self._selected_branch()
        branches = self.branches if selected_branch is None else [branch for branch in self.branches if branch.name == selected_branch]
        visible_carts = self._filtered_carts()

        for index in reversed(range(self.cart_grid.count())):
            item = self.cart_grid.takeAt(index)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        columns = 3 if self.width() >= 1320 else 2
        for index, cart in enumerate(visible_carts):
            self.cart_grid.addWidget(self._cart_card(cart), index // columns, index % columns)

        branch_count = len(branches)
        cart_scope = [cart for cart in all_carts if selected_branch is None or cart.branch == selected_branch]
        active = sum(cart.status in {"COMPRANDO", "PAGANDO"} for cart in cart_scope)
        alerts = [cart for cart in cart_scope if cart.has_alert]
        self.kpi_values["branches"].setText(str(branch_count))
        self.kpi_values["carts"].setText(str(len(cart_scope)))
        self.kpi_values["active"].setText(str(active))
        self.kpi_values["alerts"].setText(str(len(alerts)))
        self.kpi_values["alerts"].setProperty("alert", bool(alerts))
        self.kpi_values["alerts"].style().unpolish(self.kpi_values["alerts"])
        self.kpi_values["alerts"].style().polish(self.kpi_values["alerts"])
        self.alert_count.setText(str(len(alerts)))

        self.alert_list.clear()
        if not alerts:
            self.alert_list.addItem("✓ Sin alertas técnicas en este alcance")
        else:
            for cart in alerts:
                item = QListWidgetItem(f"{cart.cart_alert_icon if hasattr(cart, 'cart_alert_icon') else '●'} {cart.code} · {cart.branch}\n{cart.sensor_summary}")
                item.setData(Qt.ItemDataRole.UserRole, cart.code)
                self.alert_list.addItem(item)

        if selected_branch is None:
            self.branch_info.setText("Todas las sucursales · monitoreo centralizado de operación y sensores")
        else:
            branch = next(branch for branch in self.branches if branch.name == selected_branch)
            self.branch_info.setText(f"{branch.name} · Encargado: {branch.manager} · {branch.location}")
        self.updated_label.setText(f"Actualizado {datetime.now().strftime('%H:%M:%S')} · DEMO")

    def _cart_card(self, cart: DemoCart) -> QFrame:
        card = QFrame()
        card.setObjectName("cartCard")
        card.setProperty("alert", cart.has_alert)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        code = QLabel(cart.code)
        code.setObjectName("cartCode")
        top.addWidget(code)
        top.addStretch()
        type_badge = QLabel("FÍSICO" if cart.physical else "DEMO")
        type_badge.setObjectName("typeBadge")
        type_badge.setProperty("physical", cart.physical)
        top.addWidget(type_badge)
        layout.addLayout(top)

        status = QLabel(f"● {cart.status}")
        status.setObjectName("cartStatus")
        status.setProperty("alert", cart.has_alert)
        layout.addWidget(status)

        metrics = QHBoxLayout()
        items = QLabel(f"{cart.item_count} artículos")
        items.setObjectName("muted")
        total = QLabel(format_money(cart.total_cents))
        total.setObjectName("cartTotal")
        metrics.addWidget(items)
        metrics.addStretch()
        metrics.addWidget(total)
        layout.addLayout(metrics)

        sensors = QLabel(
            f"Cámara {'✓' if cart.camera_ok else '✕'}   "
            f"RFID A {'✓' if cart.rfid_a_ok else '✕'}   "
            f"RFID B {'✓' if cart.rfid_b_ok else '✕'}"
        )
        sensors.setObjectName("sensorLine")
        sensors.setProperty("alert", cart.has_alert)
        layout.addWidget(sensors)

        if cart.has_alert:
            alert = QLabel(cart.sensor_summary)
            alert.setObjectName("inlineAlert")
            alert.setWordWrap(True)
            layout.addWidget(alert)

        button = QPushButton("Ver carrito")
        button.setObjectName("viewButton")
        button.clicked.connect(lambda _checked=False, selected=cart: self._open_cart(selected))
        layout.addWidget(button)
        return card

    def _manager_for(self, branch_name: str) -> str:
        branch = next(branch for branch in self.branches if branch.name == branch_name)
        return branch.manager

    def _open_cart(self, cart: DemoCart) -> None:
        dialog = CartDetailDialog(
            cart,
            self._manager_for(cart.branch),
            self.physical_cart,
            self.frame_provider,
            self.hardware_status_provider,
            self,
        )
        dialog.exec()

    def _open_alert_cart(self, item: QListWidgetItem) -> None:
        code = item.data(Qt.ItemDataRole.UserRole)
        cart = next((cart for cart in self._all_carts() if cart.code == code), None)
        if cart is not None:
            self._open_cart(cart)

    def _apply_styles(self) -> None:
        self.setStyleSheet(_MANAGER_STYLE)


_MANAGER_STYLE = """
QMainWindow, QWidget { background: #f4f7fb; color: #132238; font-family: "Segoe UI"; font-size: 14px; }
QLabel { background: transparent; }
QFrame#sidebar { background: #101b2d; }
QLabel#brand { color: white; font-size: 24px; font-weight: 800; letter-spacing: 1px; }
QLabel#brandSub { color: #7f93b2; font-size: 11px; font-weight: 700; }
QLabel#sideLabel { color: #7f93b2; font-size: 11px; font-weight: 700; }
QListWidget#branchList { background: transparent; border: none; color: #dce6f4; outline: none; }
QListWidget#branchList::item { border-radius: 8px; padding: 10px 9px; margin: 2px 0; }
QListWidget#branchList::item:selected { background: #1c2d47; color: white; }
QListWidget#branchList::item:hover { background: #17263d; }
QLabel#demoSide { color: #91a2bd; font-size: 12px; line-height: 1.35; }
QPushButton#backButton { background: transparent; color: #e5edf8; border: 1px solid #53657f; border-radius: 9px; padding: 11px; font-weight: 650; }
QPushButton#backButton:hover { background: #1a2a42; }
QLabel#pageTitle { font-size: 29px; font-weight: 800; color: #111c2e; }
QLabel#pageSubtitle, QLabel#updated, QLabel#muted { color: #66758b; }
QFrame#kpi, QFrame#section { background: white; border: 1px solid #e0e7f0; border-radius: 12px; }
QLabel#kpiValue { font-size: 29px; font-weight: 800; color: #10233e; }
QLabel#kpiValue[alert="true"] { color: #c0392b; }
QLabel#kpiCaption { color: #697a90; font-size: 12px; font-weight: 650; }
QLabel#sectionTitle { font-size: 18px; font-weight: 750; color: #14233a; }
QComboBox { background: #f8fafc; border: 1px solid #dbe3ed; border-radius: 8px; padding: 7px 10px; min-width: 125px; }
QScrollArea { background: transparent; }
QFrame#cartCard { background: #fbfdff; border: 1px solid #dce5ef; border-radius: 10px; }
QFrame#cartCard[alert="true"] { background: #fff8f7; border: 2px solid #e45c4f; }
QLabel#cartCode { font-size: 19px; font-weight: 800; color: #12243d; }
QLabel#typeBadge { background: #edf1f7; color: #5d6c82; border-radius: 7px; padding: 4px 8px; font-size: 10px; font-weight: 750; }
QLabel#typeBadge[physical="true"] { background: #dff6ea; color: #16784c; }
QLabel#cartStatus { color: #23825a; font-weight: 700; }
QLabel#cartStatus[alert="true"] { color: #c84235; }
QLabel#cartTotal { font-size: 17px; font-weight: 800; color: #17273f; }
QLabel#sensorLine { color: #627187; font-size: 12px; }
QLabel#sensorLine[alert="true"] { color: #bd4338; font-weight: 650; }
QLabel#inlineAlert { background: #feeceb; color: #a73830; border-radius: 6px; padding: 6px 8px; font-size: 11px; font-weight: 650; }
QPushButton#viewButton { background: #153d68; color: white; border: none; border-radius: 8px; padding: 9px 12px; font-weight: 700; }
QPushButton#viewButton:hover { background: #102f50; }
QListWidget#alertList { background: #fff; border: none; outline: none; }
QListWidget#alertList::item { background: #fff7f6; border: 1px solid #f1d1ce; border-radius: 8px; margin: 4px 0; padding: 10px; color: #a83d34; }
QLabel#alertCount { background: #ffe5e2; color: #b73d33; border-radius: 10px; padding: 4px 8px; font-weight: 800; }
"""

_DIALOG_STYLE = """
QDialog, QWidget { background: #f5f8fc; color: #14233a; font-family: "Segoe UI"; font-size: 14px; }
QLabel { background: transparent; }
QLabel#dialogTitle { font-size: 25px; font-weight: 800; }
QLabel#muted { color: #6a788c; }
QLabel#statusBadge { background: #e2f6eb; color: #18774f; border-radius: 9px; padding: 7px 10px; font-weight: 750; }
QLabel#statusBadge[alert="true"] { background: #fde8e6; color: #b33d34; }
QTabWidget::pane { border: 1px solid #dce4ee; border-radius: 10px; background: white; }
QTabBar::tab { background: #e9eef5; padding: 9px 15px; margin-right: 3px; border-top-left-radius: 7px; border-top-right-radius: 7px; }
QTabBar::tab:selected { background: #173d66; color: white; }
QFrame#infoCard, QFrame#sensorCard { background: white; border: 1px solid #dfe6ef; border-radius: 9px; }
QLabel#smallLabel { color: #718096; font-size: 10px; font-weight: 750; }
QLabel#infoValue { font-size: 17px; font-weight: 700; color: #18304e; }
QLabel#tabHeading { font-size: 18px; font-weight: 750; }
QLabel#sensorName { font-weight: 700; }
QLabel#sensorState { color: #1e8057; font-size: 17px; font-weight: 800; }
QLabel#sensorState[alert="true"] { color: #c23e34; }
QLabel#cameraStatus { color: #207f58; font-weight: 750; }
QLabel#cameraStatus[alert="true"] { color: #c13e35; }
QLabel#cameraView { background: #111b2a; color: #ced8e6; border-radius: 10px; font-size: 16px; font-weight: 600; }
QLabel#demoNotice { background: #fff7df; color: #775d17; border: 1px solid #f0df9b; border-radius: 8px; padding: 10px; }
QLabel#purchaseTotal { font-size: 22px; font-weight: 800; color: #112b49; padding: 8px; }
QTableWidget { background: white; border: 1px solid #dfe6ef; border-radius: 8px; gridline-color: #edf1f5; }
QHeaderView::section { background: #edf2f7; border: none; padding: 8px; font-weight: 750; }
QPushButton#secondaryButton { background: white; border: 1px solid #cbd5e1; border-radius: 8px; padding: 9px 18px; font-weight: 650; }
"""
