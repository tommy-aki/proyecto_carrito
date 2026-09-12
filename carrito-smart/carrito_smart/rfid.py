"""Protocolo y recepción serial para eventos RFID del Arduino Nano."""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from carrito_smart.cart import CartError, CartService
from carrito_smart.database import Database


LOGGER = logging.getLogger(__name__)
UID_PATTERN = re.compile(r"^[0-9A-F]{4,32}$")
PREFERRED_PORT_MARKERS = (
    "arduino",
    "ch340",
    "ch341",
    "usb serial",
    "usb-serial",
    "wch",
    "cp210",
)


class RfidProtocolError(ValueError):
    """Una línea RFID reconocible tiene contenido inválido."""


class RfidAction(str, Enum):
    ENTRY = "ENTRADA"
    EXIT = "SALIDA"


@dataclass(frozen=True, slots=True)
class RfidEvent:
    action: RfidAction
    uid: str
    raw_line: str
    received_at: float = field(default_factory=time.monotonic)


@dataclass(frozen=True, slots=True)
class RfidProcessResult:
    accepted: bool
    reason: str
    message: str
    product_id: int | None = None


def normalize_uid(value: str) -> str:
    """Normaliza UID hexadecimal permitiendo espacios y separadores comunes."""
    uid = re.sub(r"[\s:\-]", "", value).upper()
    if len(uid) % 2 != 0 or not UID_PATTERN.fullmatch(uid):
        raise RfidProtocolError(f"UID RFID inválido: {value!r}")
    return uid


def parse_rfid_line(line: str) -> RfidEvent | None:
    """Interpreta ``ENTRADA:<UID>`` / ``SALIDA:<UID>`` e ignora diagnóstico."""
    raw_line = line.strip()
    if not raw_line or ":" not in raw_line:
        return None
    action_text, uid_text = (part.strip() for part in raw_line.split(":", 1))
    action_text = action_text.upper()
    if action_text not in {action.value for action in RfidAction}:
        return None
    uid = normalize_uid(uid_text)
    return RfidEvent(RfidAction(action_text), uid, raw_line)


def select_serial_port(configured_port: str, ports: list[Any]) -> str | None:
    """Elige un puerto explícito o un candidato USB/Arduino detectable."""
    configured = configured_port.strip()
    if configured and configured.upper() != "AUTO":
        return configured
    available = list(ports)
    if not available:
        return None
    preferred = [
        port
        for port in available
        if any(
            marker
            in (
                f"{getattr(port, 'description', '')} "
                f"{getattr(port, 'manufacturer', '')} "
                f"{getattr(port, 'hwid', '')}"
            ).lower()
            for marker in PREFERRED_PORT_MARKERS
        )
    ]
    if preferred:
        return str(preferred[0].device)
    if len(available) == 1:
        return str(available[0].device)
    return None


class RfidEventProcessor:
    """Procesador legado aislado; la ventana usa SensorFusionCoordinator."""

    def __init__(self, database: Database, cart: CartService) -> None:
        self.database = database
        self.cart = cart
        self._present_uids: set[str] = set()

    def reset(self) -> None:
        self._present_uids.clear()

    def process(self, event: RfidEvent) -> RfidProcessResult:
        product = self.database.get_product_by_rfid_uid(event.uid)
        if product is None:
            message = f"UID no registrado: {event.uid}"
            LOGGER.warning(
                "RFID descartado: action=%s uid=%s reason=unknown_uid",
                event.action.value,
                event.uid,
            )
            return RfidProcessResult(False, "unknown_uid", message)

        if event.action is RfidAction.ENTRY and event.uid in self._present_uids:
            message = f"Lectura repetida ignorada: {product.name} ya está dentro"
            LOGGER.info(
                "RFID descartado: action=ENTRADA uid=%s product_id=%s reason=duplicate",
                event.uid,
                product.id,
            )
            return RfidProcessResult(False, "duplicate_entry", message, product.id)

        if event.action is RfidAction.EXIT and event.uid not in self._present_uids:
            message = f"Salida ignorada: {product.name} no registró entrada"
            LOGGER.info(
                "RFID descartado: action=SALIDA uid=%s product_id=%s reason=not_present",
                event.uid,
                product.id,
            )
            return RfidProcessResult(False, "tag_not_present", message, product.id)

        try:
            if event.action is RfidAction.ENTRY:
                self.cart.add_product(product.id, source="rfid")
                self._present_uids.add(event.uid)
                message = f"Entrada RFID: {product.name}"
            else:
                self.cart.remove_product(product.id, source="rfid")
                self._present_uids.remove(event.uid)
                message = f"Salida RFID: {product.name}"
        except CartError as error:
            LOGGER.warning(
                "RFID rechazado: action=%s uid=%s product_id=%s reason=cart_error error=%s",
                event.action.value,
                event.uid,
                product.id,
                error,
            )
            return RfidProcessResult(False, "cart_error", str(error), product.id)

        LOGGER.info(
            "RFID aceptado: action=%s uid=%s product_id=%s producto=%s",
            event.action.value,
            event.uid,
            product.id,
            product.name,
        )
        return RfidProcessResult(True, "accepted", message, product.id)


class RfidSerialWorker(QObject):
    """Lee el Arduino con reconexión; debe ejecutarse dentro de un QThread."""

    event_received = Signal(object)
    availability_changed = Signal(bool)
    status_changed = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        port: str,
        baud_rate: int,
        reconnect_ms: int,
    ) -> None:
        super().__init__()
        self.port = port
        self.baud_rate = baud_rate
        self.reconnect_seconds = reconnect_ms / 1000
        self._stop_event = threading.Event()
        self._connection: Any | None = None
        self._last_status = ""

    def _set_status(self, message: str) -> None:
        if message != self._last_status:
            self._last_status = message
            self.status_changed.emit(message)
            LOGGER.info("Estado RFID: %s", message)

    @Slot()
    def run(self) -> None:
        try:
            try:
                import serial
                from serial.tools import list_ports
            except ImportError:
                self.failed.emit(
                    "Falta pyserial; ejecute setup.ps1 para habilitar el Arduino"
                )
                return

            while not self._stop_event.is_set():
                available_ports = list(list_ports.comports())
                selected_port = select_serial_port(self.port, available_ports)
                if selected_port is None:
                    self._set_status("Arduino desconectado · active el modo de prueba si desea simular RFID")
                    self._stop_event.wait(self.reconnect_seconds)
                    continue
                try:
                    self._connection = serial.Serial(
                        selected_port,
                        self.baud_rate,
                        timeout=0.25,
                    )
                    self._set_status(
                        f"Arduino conectado · {selected_port} · {self.baud_rate} baudios"
                    )
                    self.availability_changed.emit(True)
                    self._read_connection(serial)
                except (serial.SerialException, OSError) as error:
                    LOGGER.warning(
                        "Conexión RFID perdida: port=%s error=%s",
                        selected_port,
                        error,
                    )
                    self._set_status("Arduino desconectado · reintentando")
                finally:
                    self.availability_changed.emit(False)
                    connection, self._connection = self._connection, None
                    if connection is not None:
                        try:
                            connection.close()
                        except (serial.SerialException, OSError):
                            pass
                self._stop_event.wait(self.reconnect_seconds)
        finally:
            self.availability_changed.emit(False)
            self.finished.emit()

    def _read_connection(self, serial_module: Any) -> None:
        while not self._stop_event.is_set() and self._connection is not None:
            try:
                payload = self._connection.readline()
            except (serial_module.SerialException, OSError):
                raise
            if not payload:
                continue
            line = payload.decode("utf-8", errors="replace").strip()
            LOGGER.debug("Serial Arduino recibido: %s", line)
            try:
                event = parse_rfid_line(line)
            except RfidProtocolError as error:
                LOGGER.warning("Trama RFID inválida: raw=%r error=%s", line, error)
                continue
            if event is not None:
                LOGGER.info(
                    "Trama RFID válida: action=%s uid=%s",
                    event.action.value,
                    event.uid,
                )
                self.event_received.emit(event)

    def request_stop(self) -> None:
        self._stop_event.set()
        connection = self._connection
        if connection is not None:
            try:
                connection.close()
            except Exception:  # El puerto puede cerrarse simultáneamente al desconectarse.
                pass
