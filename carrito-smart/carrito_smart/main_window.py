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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from carrito_smart.cart import CartService
from carrito_smart.config import AppConfig
from carrito_smart.database import Database, InventoryError, SaleValidationError
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
from carrito_smart.manager_dashboard import ManagerDashboardWindow
from carrito_smart.paypal_demo import PayPalDemoDialog


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
        self._manager_window: ManagerDashboardWindow | None = None

        self.setWindowTitle("Carrito Smart · Prototipo")
        self.resize(1280, 760)
        self.setMinimumSize(1050, 650)
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
        root = QHBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(18)

        vision_panel = QVBoxLayout()
        title = QLabel("Visión del carrito")
        title.setObjectName("sectionTitle")
        vision_panel.addWidget(title)

        self.video_label = QLabel("Preparando cámara…")
        self.video_label.setObjectName("video")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumSize(620, 420)
        vision_panel.addWidget(self.video_label, 1)

        status_row = QHBoxLayout()
        self.vision_status = QLabel("Inicializando")
        self.vision_status.setObjectName("statusPill")
        self.detection_count = QLabel("0 detecciones")
        status_row.addWidget(self.vision_status)
        status_row.addStretch()
        status_row.addWidget(self.detection_count)
        vision_panel.addLayout(status_row)

        self.performance_label = QLabel(
            f"Captura ≤ {self.config.camera_fps:.0f} FPS · "
            f"YOLO ≤ {self.config.inference_fps:.0f} FPS · "
            f"Texto ≤ {self.config.ui_update_fps:.0f} FPS"
        )
        self.performance_label.setStyleSheet("color: #52667a; font-size: 12px;")
        vision_panel.addWidget(self.performance_label)

        detections_group = QGroupBox("Clases detectadas y confianza")
        detections_layout = QVBoxLayout(detections_group)
        self.detection_list = QListWidget()
        self.detection_list.setMaximumHeight(125)
        self.detection_list.addItem("Aún no hay detecciones")
        detections_layout.addWidget(self.detection_list)
        vision_panel.addWidget(detections_group)

        self.vision_cart_status = QLabel(
            "Entrada: aparición nueva + RFID · Salida: solo RFID"
        )
        self.vision_cart_status.setStyleSheet("color: #334155; font-size: 12px;")
        self.vision_cart_status.setWordWrap(True)
        vision_panel.addWidget(self.vision_cart_status)

        cart_panel = QVBoxLayout()
        cart_header = QHBoxLayout()
        cart_title = QLabel("Compra actual")
        cart_title.setObjectName("sectionTitle")
        cart_header.addWidget(cart_title)
        cart_header.addStretch()
        self.manager_button = QPushButton("Centro gerencial · DEMO")
        self.manager_button.setObjectName("managerButton")
        cart_header.addWidget(self.manager_button)
        cart_panel.addLayout(cart_header)

        simulator = QGroupBox("Entrada: RFID + cámara · Salida: solo RFID")
        simulator_layout = QGridLayout(simulator)
        self.product_combo = QComboBox()
        self.product_combo.setMinimumWidth(320)
        self.add_button = QPushButton("Simular RFID entrada")
        self.add_button.setObjectName("primaryButton")
        self.remove_button = QPushButton("Simular RFID salida")
        simulator_layout.addWidget(QLabel("Producto"), 0, 0, 1, 2)
        simulator_layout.addWidget(self.product_combo, 1, 0, 1, 2)
        simulator_layout.addWidget(self.add_button, 2, 0)
        simulator_layout.addWidget(self.remove_button, 2, 1)
        self.rfid_status = QLabel("Arduino: inicializando…")
        self.rfid_status.setStyleSheet("color: #52667a; font-size: 12px;")
        simulator_layout.addWidget(self.rfid_status, 3, 0, 1, 2)
        simulator_layout.addWidget(QLabel("Probar trama sin Arduino"), 4, 0, 1, 2)
        self.serial_line_input = QLineEdit("ENTRADA:4A3B2C1D")
        self.serial_line_input.setPlaceholderText("ENTRADA:UID o SALIDA:UID")
        self.serial_simulate_button = QPushButton("Procesar trama")
        simulator_layout.addWidget(self.serial_line_input, 5, 0)
        simulator_layout.addWidget(self.serial_simulate_button, 5, 1)
        self.rfid_last_event = QLabel("Sin eventos RFID")
        self.rfid_last_event.setWordWrap(True)
        self.rfid_last_event.setStyleSheet("color: #334155; font-size: 12px;")
        simulator_layout.addWidget(self.rfid_last_event, 6, 0, 1, 2)
        self.rfid_simulation = QCheckBox("Modo de prueba sin Arduino (webcam para entradas)")
        self.rfid_simulation.setChecked(not self.config.rfid_enabled)
        simulator_layout.addWidget(self.rfid_simulation, 7, 0, 1, 2)
        cart_panel.addWidget(simulator)

        self.cart_table = QTableWidget(0, 4)
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
        self.cart_table.verticalHeader().setVisible(False)
        header = self.cart_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        cart_panel.addWidget(self.cart_table, 1)

        total_frame = QFrame()
        total_frame.setObjectName("totalFrame")
        total_layout = QHBoxLayout(total_frame)
        total_layout.addWidget(QLabel("TOTAL"))
        total_layout.addStretch()
        self.total_label = QLabel(format_money(0))
        self.total_label.setObjectName("totalLabel")
        total_layout.addWidget(self.total_label)
        cart_panel.addWidget(total_frame)

        actions = QHBoxLayout()
        self.clear_button = QPushButton("Cancelar compra")
        self.paypal_button = QPushButton("PayPal · DEMO")
        self.paypal_button.setObjectName("paypalButton")
        self.pay_button = QPushButton("Simular pago aprobado")
        self.pay_button.setObjectName("payButton")
        actions.addWidget(self.clear_button)
        actions.addWidget(self.paypal_button)
        actions.addWidget(self.pay_button, 1)
        cart_panel.addLayout(actions)

        left_widget = QWidget()
        left_widget.setLayout(vision_panel)
        right_widget = QWidget()
        right_widget.setLayout(cart_panel)
        root.addWidget(left_widget, 3)
        root.addWidget(right_widget, 2)
        self.setCentralWidget(central)

        self.add_button.clicked.connect(self._simulate_entry)
        self.remove_button.clicked.connect(self._simulate_exit)
        self.serial_simulate_button.clicked.connect(self._simulate_serial_line)
        self.serial_line_input.returnPressed.connect(self._simulate_serial_line)
        self.clear_button.clicked.connect(self._clear_cart)
        self.paypal_button.clicked.connect(self._show_paypal_demo)
        self.manager_button.clicked.connect(self._show_manager_dashboard)
        self.pay_button.clicked.connect(self._pay)
        self.cart_table.itemSelectionChanged.connect(self._sync_combo_to_selection)
        self.rfid_simulation.toggled.connect(self._simulation_changed)
        self.statusBar().showMessage("Listo")

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #f3f5f7; color: #17212b; font-size: 14px; }
            QLabel#sectionTitle { font-size: 23px; font-weight: 700; color: #102a43; }
            QLabel#video { background: #0c1117; color: #91a3b5; border-radius: 10px; }
            QLabel#statusPill { background: #e0f2fe; color: #075985; padding: 6px 10px; border-radius: 8px; }
            QGroupBox { background: white; border: 1px solid #d9e2ec; border-radius: 8px; margin-top: 12px; padding-top: 12px; font-weight: 600; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
            QComboBox, QTableWidget, QListWidget { background: white; border: 1px solid #cbd5e1; border-radius: 6px; padding: 7px; }
            QPushButton { background: #e2e8f0; border: none; border-radius: 6px; padding: 10px 14px; font-weight: 600; }
            QPushButton:hover { background: #cbd5e1; }
            QPushButton#primaryButton { background: #2563eb; color: white; }
            QPushButton#primaryButton:hover { background: #1d4ed8; }
            QPushButton#payButton { background: #16a34a; color: white; font-size: 15px; }
            QPushButton#managerButton { background: #102a43; color: white; padding: 8px 12px; }
            QPushButton#managerButton:hover { background: #173f63; }
            QPushButton#paypalButton { background: #0070ba; color: white; padding: 10px 12px; }
            QPushButton#paypalButton:hover { background: #005ea6; }
            QPushButton#payButton:hover { background: #15803d; }
            QPushButton:disabled { background: #cbd5e1; color: #64748b; }
            QPushButton#payButton:disabled, QPushButton#primaryButton:disabled { background: #cbd5e1; color: #64748b; }
            QFrame#totalFrame { background: #102a43; border-radius: 8px; }
            QFrame#totalFrame QLabel { background: transparent; color: white; font-weight: 700; }
            QLabel#totalLabel { font-size: 25px; }
            QHeaderView::section { background: #e8edf2; border: none; padding: 8px; font-weight: 700; }
            """
        )

    def _load_products(self) -> None:
        selected_id = self.product_combo.currentData()
        self.product_combo.clear()
        products = self.database.list_products()
        for product in products:
            self.product_combo.addItem(
                f"{product.name} · {format_money(product.price_cents)} · stock {product.stock}",
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
        self.pay_button.setEnabled(bool(items) and not self.fusion.blocked and not self._payment_open)
        self.paypal_button.setEnabled(bool(items) and not self._payment_open)
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
            self.statusBar().showMessage("Indique el UID exacto en Probar trama; no se elige entre varias etiquetas", 6000)
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
            "Confirmar pago simulado",
            f"¿Aprobar el pago por {format_money(total)}?\n\n"
            "Al confirmar se registrará la venta y se descontará el inventario.",
        )
        self._payment_open = False
        self._poll_fusion()
        self._refresh_cart()
        if answer != QMessageBox.StandardButton.Yes:
            LOGGER.info("Pago simulado cancelado por el usuario")
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


    @Slot()
    def _show_paypal_demo(self) -> None:
        if not self.cart.items:
            self.statusBar().showMessage("Agregue productos antes de abrir PayPal DEMO", 4000)
            return
        PayPalDemoDialog(self.cart.total_cents, self).exec()

    @Slot()
    def _show_manager_dashboard(self) -> None:
        if self._manager_window is None:
            self._manager_window = ManagerDashboardWindow(
                self.cart,
                lambda: self._last_frame,
                self._manager_hardware_status,
                self,
            )
            self._manager_window.destroyed.connect(self._clear_manager_window)
        self._manager_window.show()
        self._manager_window.raise_()
        self._manager_window.activateWindow()

    @Slot()
    def _clear_manager_window(self) -> None:
        self._manager_window = None

    def _manager_hardware_status(self) -> dict[str, bool]:
        rfid_ok = bool(self.rfid_simulation.isChecked() or self._serial_available)
        camera_ok = bool(self.fusion.available.get("vision", False) and self._last_frame is not None)
        return {
            "camera": camera_ok,
            "rfid_a": rfid_ok,
            "rfid_b": rfid_ok,
        }

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
            self.rfid_status.setText("Arduino deshabilitado · use el modo de prueba para simular RFID")
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
        LOGGER.info("Trama RFID inyectada desde simulador: %s", event.raw_line)
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
        for widget in (self.add_button, self.remove_button, self.serial_line_input, self.serial_simulate_button):
            widget.setEnabled(simulated)
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
        self.rfid_status.setText(f"Arduino no disponible · {message}")

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
            f"Captura {capture_text} FPS · YOLO {inference_text} FPS / "
            f"{latency_text} · {device} · Texto ≤ {self.config.ui_update_fps:.0f} FPS"
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
