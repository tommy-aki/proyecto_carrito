"""Ventana principal de Carrito Smart."""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import Qt, QThread, QTimer, Slot
from PySide6.QtGui import QCloseEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from carrito_smart.cart import CartService
from carrito_smart.config import AppConfig
from carrito_smart.database import Database, InventoryError, SaleValidationError
from carrito_smart.manager_dashboard import ManagerDashboardWindow
from carrito_smart.models import format_money
from carrito_smart.receipt_dialog import ReceiptDialog
from carrito_smart.rfid import (
    RfidEvent,
    RfidProtocolError,
    RfidSerialWorker,
    parse_rfid_line,
)
from carrito_smart.vision import (
    CameraWorker,
    InferenceWorker,
    LatestFrameBuffer,
    StableDetectionBuffer,
)
from carrito_smart.sensor_fusion import SensorFusionCoordinator


LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, database: Database, config: AppConfig) -> None:
        super().__init__()
        self.database = database
        self.config = config
        self.cart = CartService(database)
        self.fusion = SensorFusionCoordinator(
            database,
            self.cart,
            {
                "bottle": config.vision_bottle_sku,
                config.yoloe_water_bottle_prompt: config.vision_bottle_sku,
                config.yoloe_soda_can_prompt: config.vision_soda_can_sku,
                config.yoloe_chocolate_bar_prompt: config.vision_chocolate_bar_sku,
            },
            window_ms=config.fusion_window_ms,
        )
        self._last_observation_at: float | None = None
        self._serial_available = False
        self._fusion_revision = -1
        self._payment_open = False
        self._last_frame: QImage | None = None
        self._camera_thread: QThread | None = None
        self._camera_worker: CameraWorker | None = None
        self._inference_thread: QThread | None = None
        self._inference_worker: InferenceWorker | None = None
        self._rfid_thread: QThread | None = None
        self._rfid_worker: RfidSerialWorker | None = None
        self._vision_metrics: dict[str, object] = {}

        self.setWindowTitle("Carrito Smart")
        self.resize(1360, 820)
        self.setMinimumSize(1180, 760)
        self._build_ui()
        self._apply_styles()
        self._load_products()
        self._refresh_cart()
        self._fusion_timer = QTimer(self)
        self._fusion_timer.setInterval(100)
        self._fusion_timer.timeout.connect(self._poll_fusion)
        self._fusion_timer.start()
        self._simulation_changed()
        QTimer.singleShot(150, self._start_vision)
        QTimer.singleShot(250, self._start_rfid)

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("appBackground")
        page = QVBoxLayout(central)
        page.setContentsMargins(22, 20, 22, 20)
        page.setSpacing(18)

        header = QFrame()
        header.setObjectName("appHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 14, 18, 14)
        header_layout.setSpacing(14)

        brand = QLabel("CS")
        brand.setObjectName("brandMark")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(brand)

        heading = QVBoxLayout()
        heading.setSpacing(2)
        app_title = QLabel("Carrito Smart")
        app_title.setObjectName("appTitle")
        app_subtitle = QLabel("Compra asistida por RFID y visión")
        app_subtitle.setObjectName("appSubtitle")
        heading.addWidget(app_title)
        heading.addWidget(app_subtitle)
        header_layout.addLayout(heading)
        header_layout.addStretch()

        self.manager_button = QPushButton("Centro gerencial")
        self.manager_button.setObjectName("managerButton")
        self.manager_button.setMinimumHeight(36)
        header_layout.addWidget(self.manager_button)

        workflow_chip = QLabel("RFID + CÁMARA")
        workflow_chip.setObjectName("workflowChip")
        header_layout.addWidget(workflow_chip)
        page.addWidget(header)

        content = QHBoxLayout()
        content.setSpacing(18)

        vision_card = QFrame()
        vision_card.setObjectName("panelCard")
        vision_panel = QVBoxLayout(vision_card)
        vision_panel.setContentsMargins(18, 18, 18, 18)
        vision_panel.setSpacing(12)

        vision_heading = QHBoxLayout()
        vision_titles = QVBoxLayout()
        vision_titles.setSpacing(2)
        title = QLabel("Cámara y validación")
        title.setObjectName("sectionTitle")
        title_help = QLabel("Seguimiento visual de los productos dentro del carrito")
        title_help.setObjectName("sectionSubtitle")
        vision_titles.addWidget(title)
        vision_titles.addWidget(title_help)
        vision_heading.addLayout(vision_titles)
        vision_heading.addStretch()
        self.vision_status = QLabel("Inicializando")
        self.vision_status.setObjectName("statusPill")
        vision_heading.addWidget(self.vision_status, alignment=Qt.AlignmentFlag.AlignTop)
        vision_panel.addLayout(vision_heading)

        self.video_label = QLabel("Preparando cámara…")
        self.video_label.setObjectName("video")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumSize(560, 350)
        self.video_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        vision_panel.addWidget(self.video_label, 1)

        camera_meta = QHBoxLayout()
        self.detection_count = QLabel("0 detecciones")
        self.detection_count.setObjectName("metricBadge")
        camera_meta.addWidget(self.detection_count)
        camera_meta.addStretch()
        self.performance_label = QLabel(
            f"Cámara ≤ {self.config.camera_fps:.0f} FPS · "
            f"Detección ≤ {self.config.inference_fps:.0f} FPS"
        )
        self.performance_label.setObjectName("metaText")
        camera_meta.addWidget(self.performance_label)
        vision_panel.addLayout(camera_meta)

        self.detection_list = QListWidget()
        self.detection_list.setVisible(False)
        self.detection_list.setMaximumHeight(0)
        self.detection_list.addItem("Aún no hay detecciones")

        cart_card = QFrame()
        cart_card.setObjectName("panelCard")
        cart_panel = QVBoxLayout(cart_card)
        cart_panel.setContentsMargins(18, 18, 18, 18)
        cart_panel.setSpacing(12)

        cart_heading = QHBoxLayout()
        cart_titles = QVBoxLayout()
        cart_titles.setSpacing(2)
        cart_title = QLabel("Tu compra")
        cart_title.setObjectName("sectionTitle")
        self.cart_summary_label = QLabel("0 productos")
        self.cart_summary_label.setObjectName("sectionSubtitle")
        cart_titles.addWidget(cart_title)
        cart_titles.addWidget(self.cart_summary_label)
        cart_heading.addLayout(cart_titles)
        cart_heading.addStretch()
        cart_panel.addLayout(cart_heading)

        simulator = QGroupBox("Control RFID")
        simulator.setObjectName("rfidGroup")
        simulator_layout = QGridLayout(simulator)
        simulator_layout.setContentsMargins(14, 16, 14, 12)
        simulator_layout.setHorizontalSpacing(10)
        simulator_layout.setVerticalSpacing(12)

        self.product_combo = QComboBox(simulator)
        self.product_combo.setMinimumWidth(300)
        self.product_combo.setMinimumHeight(34)
        self.product_combo.setVisible(False)
        self.add_button = QPushButton("Registrar entrada", simulator)
        self.add_button.setObjectName("primaryButton")
        self.add_button.setMinimumHeight(38)
        self.add_button.setVisible(False)
        self.remove_button = QPushButton("Registrar salida", simulator)
        self.remove_button.setObjectName("secondaryButton")
        self.remove_button.setMinimumHeight(38)
        self.remove_button.setVisible(False)

        divider = QFrame()
        divider.setObjectName("sectionDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        simulator_layout.addWidget(divider, 0, 0, 1, 2)

        self.rfid_status = QLabel("Lector RFID: inicializando…")
        self.rfid_status.setObjectName("deviceStatus")
        self.rfid_status.setWordWrap(True)
        self.rfid_status.setMinimumHeight(28)
        simulator_layout.addWidget(self.rfid_status, 1, 0, 1, 2)

        self.serial_line_input = QLineEdit()
        self.serial_line_input.setPlaceholderText("ENTRADA:UID o SALIDA:UID")
        self.serial_line_input.setMinimumHeight(34)
        self.serial_line_input.setVisible(False)
        self.serial_simulate_button = QPushButton("Procesar lectura")
        self.serial_simulate_button.setMinimumHeight(34)
        self.serial_simulate_button.setVisible(False)

        self.rfid_last_event = QLabel("Sin lecturas RFID")
        self.rfid_last_event.setObjectName("lastEvent")
        self.rfid_last_event.setWordWrap(True)
        self.rfid_last_event.setVisible(False)

        self.rfid_simulation = QCheckBox("Modo manual sin lector")
        self.rfid_simulation.setChecked(not self.config.rfid_enabled)
        self.rfid_simulation.setVisible(False)
        simulator_layout.addWidget(self.rfid_simulation, 2, 0, 1, 2)

        validation_card = QFrame()
        validation_card.setObjectName("validationCard")
        validation_layout = QVBoxLayout(validation_card)
        validation_layout.setContentsMargins(14, 12, 14, 12)
        validation_layout.setSpacing(8)
        validation_caption = QLabel("Estado de validación")
        validation_caption.setObjectName("eyebrow")
        validation_badge = QLabel("RFID + visión")
        validation_badge.setObjectName("validationBadge")
        title_row = QHBoxLayout()
        title_row.addWidget(validation_caption)
        title_row.addStretch()
        title_row.addWidget(validation_badge)
        self.vision_cart_status = QLabel(
            "Entrada: aparición nueva + RFID · Salida: solo RFID"
        )
        self.vision_cart_status.setObjectName("validationText")
        self.vision_cart_status.setWordWrap(True)
        validation_layout.addLayout(title_row)
        validation_layout.addWidget(self.vision_cart_status)
        cart_panel.addWidget(validation_card)

        cart_panel.addWidget(simulator)

        self.cart_table = QTableWidget(0, 4)
        self.cart_table.setObjectName("cartTable")
        self.cart_table.setHorizontalHeaderLabels(
            ["Producto", "Cant.", "Precio", "Subtotal"]
        )
        self.cart_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.cart_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.cart_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.cart_table.setAlternatingRowColors(True)
        self.cart_table.verticalHeader().setVisible(False)
        self.cart_table.setMinimumHeight(140)
        header_view = self.cart_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            header_view.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        cart_panel.addWidget(self.cart_table, 1)

        total_frame = QFrame()
        total_frame.setObjectName("totalFrame")
        total_layout = QHBoxLayout(total_frame)
        total_layout.setContentsMargins(16, 12, 16, 12)
        total_caption = QLabel("Total")
        total_caption.setObjectName("totalCaption")
        total_layout.addWidget(total_caption)
        total_layout.addStretch()
        self.total_label = QLabel(format_money(0))
        self.total_label.setObjectName("totalLabel")
        total_layout.addWidget(self.total_label)
        cart_panel.addWidget(total_frame)

        actions = QHBoxLayout()
        actions.setSpacing(9)
        self.clear_button = QPushButton("Cancelar compra")
        self.clear_button.setObjectName("dangerButton")
        self.clear_button.setMinimumHeight(40)
        self.pay_button = QPushButton("Confirmar pago")
        self.pay_button.setObjectName("payButton")
        self.pay_button.setMinimumHeight(40)
        actions.addWidget(self.clear_button)
        actions.addWidget(self.pay_button, 1)
        cart_panel.addLayout(actions)

        content.addWidget(vision_card, 3)
        content.addWidget(cart_card, 2)
        page.addLayout(content, 1)
        self.setCentralWidget(central)

        self.add_button.clicked.connect(self._simulate_entry)
        self.remove_button.clicked.connect(self._simulate_exit)
        self.serial_simulate_button.clicked.connect(self._simulate_serial_line)
        self.serial_line_input.returnPressed.connect(self._simulate_serial_line)
        self.clear_button.clicked.connect(self._clear_cart)
        self.pay_button.clicked.connect(self._pay)
        self.manager_button.clicked.connect(self._open_manager_dashboard)
        self.cart_table.itemSelectionChanged.connect(self._sync_combo_to_selection)
        self.rfid_simulation.toggled.connect(self._simulation_changed)
        self.statusBar().showMessage("Listo")

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #eef3f8;
            }
            QWidget#appBackground {
                background: #eef3f8;
                color: #162235;
                font-size: 14px;
            }
            QFrame#appHeader {
                background: #ffffff;
                border: 1px solid #dbe5ef;
                border-radius: 14px;
            }
            QLabel#brandMark {
                background: #0f67d8;
                color: #ffffff;
                border-radius: 20px;
                min-width: 40px;
                max-width: 40px;
                min-height: 40px;
                max-height: 40px;
                font-size: 16px;
                font-weight: 800;
            }
            QLabel#appTitle {
                color: #102a43;
                font-size: 21px;
                font-weight: 800;
            }
            QLabel#appSubtitle, QLabel#sectionSubtitle {
                color: #6b7c93;
                font-size: 12px;
            }
            QLabel#workflowChip {
                background: #eef6ff;
                color: #0f67d8;
                border: 1px solid #cfe4ff;
                border-radius: 9px;
                padding: 7px 10px;
                font-size: 11px;
                font-weight: 800;
            }
            QPushButton#managerButton {
                background: #edf8f2;
                color: #166a43;
                border: 1px solid #bfe4ca;
                border-radius: 9px;
                padding: 8px 14px;
                min-height: 30px;
                font-weight: 800;
            }
            QPushButton#managerButton:hover {
                background: #e2f3ea;
            }
            QFrame#panelCard {
                background: #ffffff;
                border: 1px solid #dbe5ef;
                border-radius: 16px;
            }
            QLabel#sectionTitle {
                color: #102a43;
                font-size: 22px;
                font-weight: 800;
            }
            QLabel#video {
                background: #0d1724;
                color: #8ea2b8;
                border: 1px solid #1f3044;
                border-radius: 12px;
                padding: 4px;
            }
            QLabel#statusPill {
                background: #e9f7ef;
                color: #177245;
                border: 1px solid #ccebd9;
                border-radius: 10px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#metricBadge {
                background: #f3f6fa;
                color: #42566c;
                border: 1px solid #dbe5ef;
                border-radius: 9px;
                padding: 5px 9px;
                font-size: 12px;
                font-weight: 700;
            }
            QLabel#metaText, QLabel#deviceStatus, QLabel#lastEvent {
                color: #60758a;
                font-size: 11px;
            }
            QGroupBox#compactGroup, QGroupBox#rfidGroup {
                background: #fbfcfe;
                border: 1px solid #dbe5ef;
                border-radius: 11px;
                margin-top: 11px;
                padding-top: 8px;
                color: #2b4057;
                font-weight: 800;
            }
            QGroupBox#compactGroup::title, QGroupBox#rfidGroup::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 5px;
                color: #2b4057;
            }
            QFrame#sectionDivider {
                background: #dbe5ef;
                max-height: 1px;
                border: none;
            }
            QListWidget, QTableWidget {
                background: #ffffff;
                color: #1f2f42;
                border: 1px solid #dbe5ef;
                border-radius: 9px;
                gridline-color: #edf1f5;
                selection-background-color: #e7f1ff;
                selection-color: #102a43;
                outline: none;
            }
            QListWidget {
                padding: 5px;
            }
            QTableWidget#cartTable {
                alternate-background-color: #f8fafc;
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
            QFrame#validationCard {
                background: #f5f9ff;
                border: 1px solid #d9e9ff;
                border-radius: 10px;
            }
            QLabel#eyebrow {
                color: #0f67d8;
                font-size: 10px;
                font-weight: 800;
            }
            QLabel#validationBadge {
                background: #eaf4ff;
                color: #0f67d8;
                border: 1px solid #cfe4ff;
                border-radius: 999px;
                padding: 4px 9px;
                font-size: 10px;
                font-weight: 800;
            }
            QLabel#validationText {
                color: #2c435b;
                font-size: 12px;
                line-height: 1.3;
            }
            QLabel#fieldLabel {
                color: #4a5f75;
                font-size: 11px;
                font-weight: 800;
            }
            QComboBox, QLineEdit {
                background: #ffffff;
                color: #17283b;
                border: 1px solid #cfdbe7;
                border-radius: 8px;
                padding: 9px 10px;
                min-height: 18px;
            }
            QComboBox:focus, QLineEdit:focus {
                border: 1px solid #0f67d8;
            }
            QCheckBox {
                color: #52677d;
                font-size: 11px;
                spacing: 7px;
            }
            QPushButton {
                background: #edf2f7;
                color: #263b52;
                border: 1px solid #d6e0ea;
                border-radius: 8px;
                padding: 9px 12px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #e3eaf1;
            }
            QPushButton#primaryButton {
                background: #0f67d8;
                color: #ffffff;
                border: 1px solid #0f67d8;
            }
            QPushButton#primaryButton:hover {
                background: #0c59bc;
            }
            QPushButton#secondaryButton {
                background: #ffffff;
                color: #0f67d8;
                border: 1px solid #a9cdf7;
            }
            QPushButton#secondaryButton:hover {
                background: #f1f7ff;
            }
            QPushButton#payButton {
                background: #14945f;
                color: #ffffff;
                border: 1px solid #14945f;
                font-size: 14px;
                padding: 11px 14px;
            }
            QPushButton#payButton:hover {
                background: #117c50;
            }
            QPushButton#dangerButton {
                background: #fff7f7;
                color: #a13d3d;
                border: 1px solid #efcdcd;
            }
            QPushButton#dangerButton:hover {
                background: #ffeded;
            }
            QPushButton:disabled {
                background: #e7edf3;
                color: #9aaaba;
                border-color: #dde5ed;
            }
            QFrame#totalFrame {
                background: #102a43;
                border-radius: 11px;
            }
            QLabel#totalCaption {
                background: transparent;
                color: #c6d5e5;
                font-size: 12px;
                font-weight: 800;
            }
            QLabel#totalLabel {
                background: transparent;
                color: #ffffff;
                font-size: 25px;
                font-weight: 900;
            }
            QStatusBar {
                background: #ffffff;
                color: #5f7287;
                border-top: 1px solid #dbe5ef;
                font-size: 11px;
            }
            """
        )

    def _manager_hardware_status(self) -> dict[str, bool]:
        return {
            "camera": bool(self._camera_worker is not None and self._camera_thread is not None and self._camera_thread.isRunning()),
            "rfid_a": self.rfid_simulation.isChecked() or self._serial_available,
            "rfid_b": self.rfid_simulation.isChecked() or self._serial_available,
        }

    def _open_manager_dashboard(self) -> None:
        dashboard = ManagerDashboardWindow(
            self.cart,
            lambda: self._last_frame,
            self._manager_hardware_status,
            self,
        )
        dashboard.show()
        dashboard.raise_()
        dashboard.activateWindow()

    def _load_products(self) -> None:
        selected_id = self.product_combo.currentData()
        self.product_combo.clear()
        products = self.database.list_products()
        for product in products:
            self.product_combo.addItem(
                f"{product.name} · {format_money(product.price_cents)} · disponible {product.stock}",
                product.id,
            )
        if selected_id is not None:
            index = self.product_combo.findData(selected_id)
            if index >= 0:
                self.product_combo.setCurrentIndex(index)

    def _refresh_cart(self) -> None:
        items = self.cart.items
        self.cart_table.setRowCount(len(items))
        for row, item in enumerate(items):
            values = (
                item.product.name,
                str(item.quantity),
                format_money(item.product.price_cents),
                format_money(item.subtotal_cents),
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if column == 0:
                    cell.setData(Qt.ItemDataRole.UserRole, item.product.id)
                if column > 0:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.cart_table.setItem(row, column, cell)
        total = self.cart.total_cents
        self.total_label.setText(format_money(total))
        units = sum(item.quantity for item in items)
        noun = "producto" if units == 1 else "productos"
        self.cart_summary_label.setText(f"{units} {noun}")
        self.pay_button.setEnabled(bool(items) and not self.fusion.blocked and not self._payment_open)
        self.clear_button.setEnabled(bool(items or self.fusion.pending or self.fusion.issues or self.fusion.visual_notices) and not self._payment_open)

    @Slot()
    def _simulate_entry(self) -> None:
        self._simulate_product_rfid("ENTRADA")

    @Slot()
    def _simulate_exit(self) -> None:
        self._simulate_product_rfid("SALIDA")

    def _simulate_product_rfid(self, action: str) -> None:
        if not self.rfid_simulation.isChecked():
            return
        product_id = self._selected_cart_product_id()
        if product_id is None or action == "ENTRADA":
            product_id = self.product_combo.currentData()
        if product_id is None:
            return
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT uid FROM rfid_tags WHERE product_id=? AND active=1 ORDER BY uid",
                (int(product_id),),
            ).fetchall()
        candidates = [row["uid"] for row in rows if
                      (row["uid"] in self.fusion.present_uids) == (action == "SALIDA")]
        if len(candidates) != 1:
            self.statusBar().showMessage("Indique el UID exacto en Lectura manual; no se elige entre varias etiquetas", 6000)
            return
        self.serial_line_input.setText(f"{action}:{candidates[0]}")
        self._simulate_serial_line()

    @Slot()
    def _clear_cart(self) -> None:
        if self._payment_open:
            return
        answer = QMessageBox.question(
            self, "Cancelar compra", "¿Cancelar toda la compra y sus pendientes? "
            "Vacíe físicamente el carrito antes de iniciar otra compra.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.cart.clear()
        self._reset_purchase()

    def _reset_purchase(self) -> None:
        self.fusion.reset()
        if self._inference_worker is not None:
            self._inference_worker.reset_crossings()
        self._refresh_fusion()

    @Slot()
    def _pay(self) -> None:
        if self._payment_open:
            return
        self._poll_fusion()
        if self.fusion.blocked or not self.cart.items:
            self.statusBar().showMessage("Pago bloqueado: resuelva la validación RFID + webcam", 5000)
            return
        total = self.cart.total_cents
        purchased_items = self.cart.items
        revision = self.fusion.payment_revision
        self._payment_open = True
        self._refresh_cart()
        answer = QMessageBox.question(
            self,
            "Confirmar pago",
            f"¿Aprobar el pago por {format_money(total)}?\n\n"
            "Al confirmar se registrará la venta y se descontará el inventario.",
        )
        self._payment_open = False
        self._poll_fusion()
        self._refresh_cart()
        if answer != QMessageBox.StandardButton.Yes:
            LOGGER.info("Pago cancelado por el usuario")
            return
        if self.fusion.blocked or self.fusion.payment_revision != revision or self.cart.items != purchased_items:
            self.statusBar().showMessage("La compra cambió durante la confirmación; revise y confirme de nuevo", 6000)
            return
        try:
            receipt = self.cart.checkout()
        except (InventoryError, SaleValidationError) as error:
            QMessageBox.critical(self, "Pago rechazado", str(error))
            return
        self._reset_purchase()
        self._load_products()
        self.statusBar().showMessage(f"Venta #{receipt.sale_id} aprobada", 5000)
        ReceiptDialog(receipt, purchased_items, self).exec()

    def _selected_cart_product_id(self) -> int | None:
        row = self.cart_table.currentRow()
        if row < 0:
            return None
        item = self.cart_table.item(row, 0)
        return int(item.data(Qt.ItemDataRole.UserRole)) if item else None

    @Slot()
    def _sync_combo_to_selection(self) -> None:
        product_id = self._selected_cart_product_id()
        if product_id is None:
            return
        index = self.product_combo.findData(product_id)
        if index >= 0:
            self.product_combo.setCurrentIndex(index)

    def _start_vision(self) -> None:
        frames = LatestFrameBuffer()
        stable_detections = StableDetectionBuffer()

        self._camera_thread = QThread(self)
        self._camera_worker = CameraWorker(
            self.config, frames, stable_detections
        )
        self._camera_worker.moveToThread(self._camera_thread)
        self._camera_thread.started.connect(self._camera_worker.run)
        self._camera_worker.frame_ready.connect(self._show_frame)
        self._camera_worker.status_changed.connect(self._show_vision_status)
        self._camera_worker.metrics_ready.connect(self._show_vision_metrics)
        self._camera_worker.failed.connect(self._show_camera_error)
        self._camera_worker.finished.connect(
            self._camera_thread.quit, Qt.ConnectionType.DirectConnection
        )

        self._inference_thread = QThread(self)
        self._inference_worker = InferenceWorker(
            self.config, frames, stable_detections
        )
        self._inference_worker.moveToThread(self._inference_thread)
        self._inference_thread.started.connect(self._inference_worker.run)
        self._inference_worker.detections_ready.connect(self._show_detections)
        self._inference_worker.crossings_ready.connect(self._handle_visual_crossings)
        self._inference_worker.observation_ready.connect(self._vision_observation)
        self._inference_worker.status_changed.connect(self._show_vision_status)
        self._inference_worker.metrics_ready.connect(self._show_vision_metrics)
        self._inference_worker.failed.connect(self._show_inference_error)
        self._inference_worker.finished.connect(
            self._inference_thread.quit, Qt.ConnectionType.DirectConnection
        )

        self._inference_thread.start()
        self._camera_thread.start()

    def _start_rfid(self) -> None:
        if not self.config.rfid_enabled:
            self.rfid_status.setText("Arduino desconectado")
            return
        self._rfid_thread = QThread(self)
        self._rfid_worker = RfidSerialWorker(
            self.config.rfid_port,
            self.config.rfid_baud_rate,
            self.config.rfid_reconnect_ms,
        )
        self._rfid_worker.moveToThread(self._rfid_thread)
        self._rfid_thread.started.connect(self._rfid_worker.run)
        self._rfid_worker.event_received.connect(self._handle_rfid_event)
        self._rfid_worker.availability_changed.connect(self._rfid_availability)
        self._rfid_worker.status_changed.connect(self._show_rfid_status)
        self._rfid_worker.failed.connect(self._show_rfid_error)
        self._rfid_worker.finished.connect(
            self._rfid_thread.quit, Qt.ConnectionType.DirectConnection
        )
        self._rfid_thread.start()

    @Slot()
    def _simulate_serial_line(self) -> None:
        if not self.rfid_simulation.isChecked():
            return
        self._poll_fusion()
        line = self.serial_line_input.text()
        try:
            event = parse_rfid_line(line)
        except RfidProtocolError as error:
            QMessageBox.warning(self, "Trama RFID inválida", str(error))
            return
        if event is None:
            QMessageBox.warning(
                self,
                "Trama RFID inválida",
                "Use el formato ENTRADA:UID o SALIDA:UID",
            )
            return
        LOGGER.info("Trama RFID procesada desde el modo manual: %s", event.raw_line)
        self.fusion.on_rfid(event)
        self.rfid_last_event.setText(self.fusion.message)
        self._refresh_fusion()

    @Slot(object)
    def _handle_rfid_event(self, event: RfidEvent) -> None:
        if self.rfid_simulation.isChecked():
            return
        self._poll_fusion()
        self.fusion.on_rfid(event)
        self.rfid_last_event.setText(f"{event.uid} · {self.fusion.message}")
        self._refresh_fusion()

    @Slot()
    def _simulation_changed(self) -> None:
        simulated = self.rfid_simulation.isChecked()
        self.fusion.invalidate("Cambio de modo RFID; repetir pendientes")
        self.fusion.set_available("rfid", simulated or self._serial_available)
        if self._inference_worker is not None:
            self._inference_worker.reset_crossings()
        self._refresh_fusion()

    @Slot(bool)
    def _rfid_availability(self, available: bool) -> None:
        self._serial_available = available
        self.fusion.set_available("rfid", self.rfid_simulation.isChecked() or available)
        if not available and not self.rfid_simulation.isChecked() and self._inference_worker is not None:
            self._inference_worker.reset_crossings()
        self._refresh_fusion()

    @Slot(float)
    def _vision_observation(self, captured_at: float) -> None:
        self._last_observation_at = captured_at
        fresh = time.monotonic() - captured_at <= self.config.vision_stale_ms / 1000
        self.fusion.set_available("vision", fresh and self.config.vision_auto_cart_enabled)
        self._refresh_fusion()

    @Slot(list)
    def _handle_visual_crossings(self, events: list) -> None:
        self.fusion.on_visual_batch(events)
        self._refresh_fusion()

    @Slot()
    def _poll_fusion(self) -> None:
        if self._last_observation_at is not None and time.monotonic() - self._last_observation_at > self.config.vision_stale_ms / 1000:
            if self.fusion.available["vision"] and self._inference_worker is not None:
                self._inference_worker.reset_crossings()
            self.fusion.set_available("vision", False)
        self.fusion.tick()
        self._refresh_fusion()

    def _refresh_fusion(self) -> None:
        if self._fusion_revision == self.fusion.revision:
            return
        self._fusion_revision = self.fusion.revision
        self.vision_cart_status.setText(self.fusion.status)
        self._refresh_cart()

    @Slot(str)
    def _show_rfid_status(self, message: str) -> None:
        self.rfid_status.setText(message)

    @Slot(str)
    def _show_rfid_error(self, message: str) -> None:
        self._rfid_availability(False)
        LOGGER.error("RFID no disponible: %s", message)
        self.rfid_status.setText("Arduino desconectado")

    @Slot(QImage)
    def _show_frame(self, image: QImage) -> None:
        self._last_frame = image
        self._render_last_frame()

    def _render_last_frame(self) -> None:
        if self._last_frame is None:
            return
        pixmap = QPixmap.fromImage(self._last_frame)
        self.video_label.setPixmap(
            pixmap.scaled(
                self.video_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._render_last_frame()

    @Slot(list)
    def _show_detections(self, detections: list[dict]) -> None:
        self.detection_list.clear()
        if not detections:
            self.detection_list.addItem("Sin objetos sobre el umbral configurado")
        else:
            for detection in detections:
                confidence = float(detection["confidence"]) * 100
                state = " · retenida" if detection.get("held") else ""
                self.detection_list.addItem(
                    f"{detection['class_name']}  ·  {confidence:.1f}%{state}"
                )
        count = len(detections)
        noun = "detección" if count == 1 else "detecciones"
        self.detection_count.setText(f"{count} {noun}")

    @Slot(str)
    def _show_vision_status(self, message: str) -> None:
        self.vision_status.setText(message)

    @Slot(str)
    def _show_camera_error(self, message: str) -> None:
        self.fusion.set_available("vision", False)
        self._refresh_fusion()
        self.vision_status.setText("Visión no disponible")
        self.video_label.setText(f"No se pudo iniciar la visión\n\n{message}")
        self.statusBar().showMessage("Sin cámara: entradas y pago pausados; salidas por RFID disponibles si el lector está conectado")
        if self._inference_worker is not None:
            self._inference_worker.request_stop()

    @Slot(str)
    def _show_inference_error(self, message: str) -> None:
        self.fusion.set_available("vision", False)
        self._refresh_fusion()
        self.vision_status.setText("YOLO no disponible; webcam activa")
        self.statusBar().showMessage(f"Error de inferencia: {message} · Entradas y pago pausados; salidas solo RFID")

    @Slot(dict)
    def _show_vision_metrics(self, metrics: dict[str, object]) -> None:
        self._vision_metrics.update(metrics)
        capture = self._vision_metrics.get("capture_fps")
        inference = self._vision_metrics.get("inference_fps")
        latency = self._vision_metrics.get("latency_ms")
        device = self._vision_metrics.get("device", "—")
        capture_text = f"{float(capture):.1f}" if capture is not None else "—"
        inference_text = f"{float(inference):.1f}" if inference is not None else "—"
        latency_text = f"{float(latency):.0f} ms" if latency is not None else "—"
        self.performance_label.setText(
            f"Cámara {capture_text} FPS · Detección {inference_text} FPS · "
            f"Latencia {latency_text} · {device}"
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        self._fusion_timer.stop()
        for worker in (
            self._camera_worker,
            self._inference_worker,
            self._rfid_worker,
        ):
            if worker is not None:
                worker.request_stop()
        for name, thread in (
            ("captura", self._camera_thread),
            ("inferencia", self._inference_thread),
            ("RFID", self._rfid_thread),
        ):
            if thread is not None and thread.isRunning() and not thread.wait(7000):
                LOGGER.warning("El hilo de %s no respondió a tiempo al cierre", name)
                event.ignore()
                self.statusBar().showMessage("Esperando a que termine la inferencia…")
                QTimer.singleShot(1000, self.close)
                return
        event.accept()
