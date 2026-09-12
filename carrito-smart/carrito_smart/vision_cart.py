"""Integrador legado de visión sola; la ventana usa ahora sensor_fusion.

Se conserva para compatibilidad con pruebas anteriores, no se activa en la app.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Mapping

from carrito_smart.cart import CartError, CartService
from carrito_smart.database import Database


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VisionCartResult:
    accepted: bool
    action: str
    class_name: str
    sku: str
    message: str


class VisionCartIntegrator:
    """Agrega una unidad solamente al comenzar una aparición confirmada."""

    def __init__(
        self,
        database: Database,
        cart: CartService,
        class_to_sku: Mapping[str, str],
        *,
        enabled: bool = True,
    ) -> None:
        self.database = database
        self.cart = cart
        self.enabled = enabled
        self.class_to_sku = {
            class_name.strip().casefold(): sku.strip()
            for class_name, sku in class_to_sku.items()
        }
        self._active_classes: set[str] = set()
        self._classes_added_to_cart: set[str] = set()

    def release_cart_claims(self) -> None:
        """Olvida aportes ya consumidos sin rearmar objetos aún visibles."""
        self._classes_added_to_cart.clear()

    def update(self, detections: list[dict]) -> list[VisionCartResult]:
        visible_classes = {
            str(detection.get("class_name", "")).strip().casefold()
            for detection in detections
            if detection.get("class_name")
        }
        new_classes = visible_classes - self._active_classes
        disappeared_classes = self._active_classes - visible_classes
        self._active_classes = visible_classes
        if not self.enabled:
            return []

        results: list[VisionCartResult] = []
        for class_name in sorted(new_classes):
            sku = self.class_to_sku.get(class_name)
            if sku is None:
                continue
            product = self.database.get_product_by_sku(sku)
            if product is None:
                message = f"SKU configurado no disponible: {sku}"
                LOGGER.warning(
                    "Visión no agregó producto: class=%s sku=%s reason=unknown_sku",
                    class_name,
                    sku,
                )
                results.append(
                    VisionCartResult(False, "entry", class_name, sku, message)
                )
                continue
            try:
                self.cart.add_product(product.id, source="vision")
            except CartError as error:
                LOGGER.warning(
                    "Visión no agregó producto: class=%s sku=%s reason=cart_error error=%s",
                    class_name,
                    sku,
                    error,
                )
                results.append(
                    VisionCartResult(False, "entry", class_name, sku, str(error))
                )
                continue
            self._classes_added_to_cart.add(class_name)
            message = f"Visión agregó {product.name}"
            LOGGER.info(
                "Producto agregado por visión: class=%s sku=%s product_id=%s producto=%s",
                class_name,
                sku,
                product.id,
                product.name,
            )
            results.append(
                VisionCartResult(True, "entry", class_name, sku, message)
            )

        for class_name in sorted(disappeared_classes):
            if class_name not in self._classes_added_to_cart:
                continue
            self._classes_added_to_cart.discard(class_name)
            sku = self.class_to_sku.get(class_name)
            if sku is None:
                continue
            product = self.database.get_product_by_sku(sku)
            if product is None:
                message = f"SKU configurado no disponible: {sku}"
                LOGGER.warning(
                    "Visión no retiró producto: class=%s sku=%s reason=unknown_sku",
                    class_name,
                    sku,
                )
                results.append(
                    VisionCartResult(False, "exit", class_name, sku, message)
                )
                continue
            try:
                self.cart.remove_product(product.id, source="vision")
            except CartError as error:
                LOGGER.warning(
                    "Visión no retiró producto: class=%s sku=%s reason=cart_error error=%s",
                    class_name,
                    sku,
                    error,
                )
                results.append(
                    VisionCartResult(False, "exit", class_name, sku, str(error))
                )
                continue
            message = f"Visión retiró {product.name}"
            LOGGER.info(
                "Producto retirado por visión: class=%s sku=%s product_id=%s producto=%s",
                class_name,
                sku,
                product.id,
                product.name,
            )
            results.append(
                VisionCartResult(True, "exit", class_name, sku, message)
            )
        return results
