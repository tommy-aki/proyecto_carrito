"""Servicio de carrito y simulación de eventos RFID."""

from __future__ import annotations

import logging

from carrito_smart.database import Database, InventoryError, SaleValidationError
from carrito_smart.models import CartItem, SaleReceipt


LOGGER = logging.getLogger(__name__)


class CartError(RuntimeError):
    pass


class CartService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._quantities: dict[int, int] = {}

    @property
    def items(self) -> list[CartItem]:
        result: list[CartItem] = []
        for product_id, quantity in self._quantities.items():
            product = self.database.get_product(product_id)
            if product is not None:
                result.append(CartItem(product=product, quantity=quantity))
        return sorted(result, key=lambda item: item.product.name)

    @property
    def total_cents(self) -> int:
        return sum(item.subtotal_cents for item in self.items)

    def add_product(self, product_id: int, *, source: str = "manual") -> None:
        product = self.database.get_product(product_id)
        if product is None or not product.active:
            raise CartError("Producto no disponible")
        new_quantity = self._quantities.get(product_id, 0) + 1
        if new_quantity > product.stock:
            raise CartError(f"No hay más unidades disponibles de {product.name}")
        self._quantities[product_id] = new_quantity
        LOGGER.info(
            "Entrada carrito: source=%s product_id=%s producto=%s cantidad=%s",
            source,
            product_id,
            product.name,
            new_quantity,
        )

    def remove_product(self, product_id: int, *, source: str = "manual") -> None:
        current = self._quantities.get(product_id, 0)
        if current <= 0:
            raise CartError("El producto no está en el carrito")
        if current == 1:
            del self._quantities[product_id]
        else:
            self._quantities[product_id] = current - 1
        LOGGER.info(
            "Salida carrito: source=%s product_id=%s cantidad=%s",
            source,
            product_id,
            max(0, current - 1),
        )

    def clear(self) -> None:
        self._quantities.clear()
        LOGGER.info("Carrito vaciado")

    def checkout(self) -> SaleReceipt:
        try:
            receipt = self.database.complete_sale(self.items)
        except (InventoryError, SaleValidationError):
            LOGGER.warning("Pago no completado")
            raise
        self.clear()
        return receipt
