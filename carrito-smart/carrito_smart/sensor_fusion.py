"""Altas con aparición nueva + RFID; bajas exclusivamente por UID RFID.

Se ejecuta en el hilo de la interfaz. No escribe inventario; CartService conserva
la transacción de venta existente. Solo los pendientes RFID bloquean el pago;
la evidencia visual sin RFID es temporal y sus avisos son informativos.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import time

from carrito_smart.cart import CartError, CartService
from carrito_smart.database import Database
from carrito_smart.rfid import RfidAction, RfidEvent
from carrito_smart.vision_crossing import VisualCrossing

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _Evidence:
    key: str
    action: RfidAction
    sku: str
    at: float
    uid: str | None = None
    visible_count: int = 0


class SensorFusionCoordinator:
    def __init__(self, database: Database, cart: CartService,
                 class_to_sku: dict[str, str], *, window_ms: int = 3000) -> None:
        self.database, self.cart = database, cart
        self.class_to_sku = {name.strip().casefold(): sku for name, sku in class_to_sku.items()}
        self.window = window_ms / 1000
        self.present_uids: dict[str, str] = {}
        self.pending: dict[str, _Evidence] = {}
        self.issues: dict[str, str] = {}
        self.visual_notices: dict[str, str] = {}
        self.available = {"vision": False, "rfid": False}
        self.seen_visual: set[str] = set()
        self.barrier = float("-inf")
        # La pérdida de visión invalida entradas, pero no salidas RFID en cola.
        self.rfid_exit_barrier = float("-inf")
        self._visual_entry_after: dict[str, float] = {}
        self.revision = 0
        self.payment_revision = 0
        self._last_payment_state = self._payment_state()
        self.message = "Esperando cámara y RFID"

    @property
    def ready(self) -> bool:
        return all(self.available.values())

    @property
    def blocked(self) -> bool:
        return not self.ready or bool(self.issues) or any(
            item.uid is not None for item in self.pending.values()
        )

    def _payment_state(self) -> tuple:
        """Solo cambios de compra/validación, no mensajes ni avisos visuales."""
        return (
            tuple(sorted(self.available.items())),
            tuple(sorted(self.present_uids.items())),
            tuple(sorted((item.key, item.sku, item.at) for item in self.pending.values()
                         if item.uid is not None)),
            tuple(sorted(self.issues.items())),
            self.barrier, self.rfid_exit_barrier,
        )

    @property
    def status(self) -> str:
        details = list(self.issues.values())
        details += [
            f"{item.sku} {item.action.value}: esperando aparición nueva en webcam; pago bloqueado"
            for item in self.pending.values() if item.uid is not None
        ]
        # Agrupar por SKU evita llenar la interfaz de avisos por una caja duplicada.
        notices = dict(self.visual_notices)
        for item in self.pending.values():
            if item.uid is None:
                notices[item.sku] = (
                    f"Aviso {item.sku}: cámara sin RFID; no agregado, no bloquea el pago"
                )
        details += notices.values()
        if not self.ready:
            details.insert(0, "Sin " + ", ".join(k for k, v in self.available.items() if not v))
            if self.available["rfid"]:
                details.insert(1, "Entradas y pago pausados; salidas RFID habilitadas")
        return " · ".join(details) if details else self.message

    def _say(self, message: str) -> None:
        self.message = message
        self.revision += 1
        state = self._payment_state()
        if state != self._last_payment_state:
            self.payment_revision += 1
            self._last_payment_state = state
        LOGGER.info("Fusión: %s", message)

    def set_available(self, sensor: str, available: bool, *, now: float | None = None) -> None:
        if self.available[sensor] == available:
            return
        self.available[sensor] = available
        if not available:
            self.invalidate(f"Se perdió {sensor}; repetir entrada pendiente", now=now,
                            invalidate_rfid=sensor == "rfid")
        self._say(f"{sensor}: {'disponible' if available else 'no disponible'}")

    def invalidate(self, reason: str, *, now: float | None = None,
                   invalidate_rfid: bool = True) -> None:
        self.barrier = time.monotonic() if now is None else now
        if invalidate_rfid:
            self.rfid_exit_barrier = self.barrier
        for evidence in self.pending.values():
            if evidence.uid is not None:
                self.issues[self._issue_key(evidence)] = f"{evidence.sku}: {reason}"
        self.pending.clear()
        self.visual_notices.clear()
        self._say(reason)

    def reset(self, *, now: float | None = None) -> None:
        """Solo después de pagar o cancelar explícitamente la compra completa."""
        self.present_uids.clear()
        self.pending.clear()
        self.issues.clear()
        self.visual_notices.clear()
        self.seen_visual.clear()
        self._visual_entry_after.clear()
        self.barrier = time.monotonic() if now is None else now
        self.rfid_exit_barrier = self.barrier
        self._say("Nueva compra: entrada RFID + aparición nueva; salida solo RFID")

    @staticmethod
    def _issue_key(evidence: _Evidence) -> str:
        return f"{evidence.uid or 'visual:' + evidence.sku}:{evidence.action.value}"

    def tick(self, *, now: float | None = None) -> None:
        timestamp = time.monotonic() if now is None else now
        for key, evidence in list(self.pending.items()):
            if timestamp - evidence.at > self.window:
                del self.pending[key]
                if evidence.uid is not None:
                    message = f"{evidence.sku} {evidence.action.value}: falta coincidencia; repetir paso"
                    self.issues[self._issue_key(evidence)] = message
                else:
                    message = f"Aviso {evidence.sku}: evidencia visual vencida sin RFID; no agregado, no bloquea el pago"
                    self.visual_notices[evidence.sku] = message
                self._say(message)

    def on_rfid(self, event: RfidEvent, *, now: float | None = None) -> None:
        timestamp = time.monotonic() if now is None else now
        self.tick(now=timestamp)
        if not self.available["rfid"]:
            self._say("RFID sin validar: lector no disponible")
            return
        if event.action is RfidAction.ENTRY and not self.ready:
            self._say("Entrada sin validar: ambos sensores deben estar disponibles")
            return
        at = event.received_at if now is None else now
        barrier = self.rfid_exit_barrier if event.action is RfidAction.EXIT else self.barrier
        if at <= barrier or timestamp - at > self.window:
            self._say("RFID antiguo ignorado; repetir paso")
            return
        if event.action is RfidAction.EXIT:
            self._exit_by_rfid(event.uid, at)
            return
        product = self.database.get_product_by_rfid_uid(event.uid)
        if product is None:
            self.issues[f"unknown:{event.uid}"] = f"UID desconocido {event.uid}; registrar y repetir"
            self._say(self.issues[f"unknown:{event.uid}"])
            return
        self.issues.pop(f"unknown:{event.uid}", None)
        if event.uid in self.present_uids:
            self._say(f"Entrada repetida ignorada: {event.uid}")
            return
        key = f"rfid:{event.action.value}:{event.uid}"
        if key in self.pending:
            self._say(f"RFID repetido pendiente: {event.uid}; no se prolonga el plazo")
            return
        self.pending[key] = _Evidence(key, event.action, product.sku, at, event.uid)
        self._say(f"RFID {event.action.value} uid={event.uid} sku={product.sku}; pendiente de webcam")
        self._match()

    def _exit_by_rfid(self, uid: str, at: float) -> None:
        """Retira exactamente la unidad registrada, sin depender de la webcam."""
        sku = self.present_uids.get(uid)
        if sku is None:
            # Una entrada aún pendiente no puede confirmarse después de salir.
            cancelled = self.pending.pop(f"rfid:{RfidAction.ENTRY.value}:{uid}", None)
            if cancelled is not None:
                self.issues[self._issue_key(cancelled)] = (
                    f"{cancelled.sku}: entrada anulada por SALIDA antes de confirmar; repetir paso"
                )
                self._discard_visual_before_exit(cancelled.sku, at)
            self._say(f"Salida sin entrada confirmada: {uid}; no se retira nada")
            return
        # Usar el SKU admitido, no una asociación de catálogo cambiada a mitad de compra.
        product = self.database.get_product_by_sku(sku)
        issue_key = f"{uid}:{RfidAction.EXIT.value}"
        try:
            if product is None:
                raise CartError(f"SKU no disponible: {sku}")
            self.cart.remove_product(product.id, source="rfid")
        except CartError as error:
            self.issues[issue_key] = str(error)
            self._say(f"Salida RFID rechazada: {error}; UID {uid}")
            return
        del self.present_uids[uid]
        self.issues.pop(issue_key, None)
        self._discard_visual_before_exit(sku, at)
        self._say(f"Confirmado SALIDA: {product.name} · UID {uid} · solo RFID")

    def _discard_visual_before_exit(self, sku: str, at: float) -> None:
        # Una imagen anterior a la salida no puede validar una futura reentrada.
        self._visual_entry_after[sku] = max(at, self._visual_entry_after.get(sku, float("-inf")))
        self.visual_notices.pop(sku, None)
        for key, evidence in list(self.pending.items()):
            if not evidence.uid and evidence.sku == sku and evidence.at <= at:
                del self.pending[key]
                LOGGER.info("Evidencia visual anterior a salida descartada: sku=%s event=%s", sku, key)

    def on_visual(self, event: VisualCrossing, *, now: float | None = None) -> None:
        self.on_visual_batch([event], now=now)

    def on_visual_batch(self, events: list[VisualCrossing], *, now: float | None = None) -> None:
        for event in events:
            self._queue_visual(event, now=now)
        self._match()

    def _queue_visual(self, event: VisualCrossing, *, now: float | None = None) -> None:
        if event.action is not RfidAction.ENTRY:
            LOGGER.debug("Salida visual ignorada: event=%s; las bajas son solo RFID", event.event_id)
            return
        timestamp = time.monotonic() if now is None else now
        self.tick(now=timestamp)
        if event.event_id in self.seen_visual:
            return
        self.seen_visual.add(event.event_id)
        if not self.ready or event.observed_at <= self.barrier or timestamp - event.observed_at > self.window:
            self._say("Evidencia visual sin validar: sensores no disponibles o evidencia antigua")
            return
        sku = self.class_to_sku.get(event.class_name.strip().casefold())
        if sku is None:
            return
        if event.observed_at <= self._visual_entry_after.get(sku, float("-inf")):
            self._say(f"Aparición anterior a salida RFID ignorada: {sku}; presentar de nuevo")
            return
        if not self._has_new_unit(sku, event.visible_count):
            self._say(
                f"Aparición ignorada {sku}: visibles={event.visible_count}, "
                f"registradas={self._registered_count(sku)}; "
                "no hay evidencia de una unidad adicional"
            )
            return
        key = f"visual:{event.event_id}"
        self.pending[key] = _Evidence(
            key, event.action, sku, event.observed_at, visible_count=event.visible_count,
        )
        self.visual_notices.pop(sku, None)
        self._say(f"Webcam {event.action.value} sku={sku} track={event.track_id} visibles={event.visible_count}; evidencia temporal, por sí sola no bloquea el pago")

    def _registered_count(self, sku: str) -> int:
        return sum(registered == sku for registered in self.present_uids.values())

    def _has_new_unit(self, sku: str, visible_count: int) -> bool:
        return visible_count > self._registered_count(sku)

    def _match(self) -> None:
        groups = {(item.sku, item.action) for item in self.pending.values()}
        for sku, action in groups:
            group = [item for item in self.pending.values() if (item.sku, item.action) == (sku, action)]
            tags = [item for item in group if item.uid]
            visuals = [item for item in group if not item.uid]
            if not tags or not visuals:
                continue
            if len(tags) != 1 or len(visuals) != 1:
                self._say(f"Asociación ambigua {sku}: pasar una unidad a la vez; no se modifica el carrito")
                continue
            tag, visual = tags[0], visuals[0]
            if abs(tag.at - visual.at) > self.window:
                continue
            if not self._has_new_unit(sku, visual.visible_count):
                # Otra coincidencia pudo consumir la capacidad después de encolar.
                del self.pending[visual.key]
                self._say(f"Evidencia visual ya cubierta por unidades registradas: {sku}; esperando aparición nueva")
                continue
            # Consumir ambas pruebas incluso si el inventario rechaza la operación.
            del self.pending[tag.key]
            del self.pending[visual.key]
            product = self.database.get_product_by_sku(sku)
            try:
                if product is None:
                    raise CartError(f"SKU no disponible: {sku}")
                self.cart.add_product(product.id, source="rfid+vision")
                self.present_uids[tag.uid] = sku
            except CartError as error:
                self.issues[self._issue_key(tag)] = str(error)
                self._say(f"Coincidencia rechazada: {error}; repetir paso")
                continue
            self.issues.pop(self._issue_key(tag), None)
            self.visual_notices.pop(sku, None)
            self._say(f"Confirmado {action.value}: {product.name} · UID {tag.uid} · RFID + webcam")
