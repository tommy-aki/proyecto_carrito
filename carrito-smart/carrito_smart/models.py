"""Modelos de dominio sin dependencias de la interfaz."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Product:
    id: int
    sku: str
    name: str
    price_cents: int
    stock: int
    active: bool = True


@dataclass(frozen=True, slots=True)
class CartItem:
    product: Product
    quantity: int

    @property
    def subtotal_cents(self) -> int:
        return self.product.price_cents * self.quantity


@dataclass(frozen=True, slots=True)
class SaleReceipt:
    sale_id: int
    total_cents: int


def format_money(cents: int) -> str:
    return f"L {cents / 100:,.2f}"

