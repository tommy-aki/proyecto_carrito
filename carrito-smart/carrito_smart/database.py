"""Acceso SQLite y operación transaccional de venta."""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from carrito_smart.models import CartItem, Product, SaleReceipt


LOGGER = logging.getLogger(__name__)


SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
    stock INTEGER NOT NULL CHECK (stock >= 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS rfid_tags (
    uid TEXT PRIMARY KEY COLLATE NOCASE,
    product_id INTEGER NOT NULL REFERENCES products(id),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_rfid_tags_product
ON rfid_tags(product_id);

CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    paid_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('APPROVED', 'CANCELLED')),
    total_cents INTEGER NOT NULL CHECK (total_cents >= 0)
);

CREATE TABLE IF NOT EXISTS sale_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id INTEGER NOT NULL REFERENCES sales(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_name TEXT NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price_cents INTEGER NOT NULL CHECK (unit_price_cents >= 0),
    subtotal_cents INTEGER NOT NULL CHECK (subtotal_cents >= 0)
);
"""


SEED_PRODUCTS = (
    ("CS-001", "Botella de agua", 1800, 100),
    ("CS-002", "Refresco en lata", 2500, 100),
    ("CS-003", "Bolsa de papas", 3200, 100),
    ("CS-004", "Caja de cereal", 8950, 0),
    ("CS-005", "Leche entera", 4200, 100),
    ("CS-006", "Chocolate", 2750, 100),
)

# UIDs usados por el firmware y simulador del repositorio Arduino del equipo.
SEED_RFID_TAGS = (
    ("4A3B2C1D", "CS-002"),
    ("8F9E0D1C", "CS-003"),
    ("12345678", "CS-001"),
)


class InventoryError(RuntimeError):
    """Se intenta vender una cantidad que no está disponible."""


class SaleValidationError(RuntimeError):
    """Los datos de la venta no coinciden con la base de datos."""


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.executemany(
                """
                INSERT OR IGNORE INTO products (sku, name, price_cents, stock)
                VALUES (?, ?, ?, ?)
                """,
                SEED_PRODUCTS,
            )
            for uid, sku in SEED_RFID_TAGS:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO rfid_tags (uid, product_id)
                    SELECT ?, id FROM products WHERE sku = ?
                    """,
                    (uid, sku),
                )
            connection.commit()
        LOGGER.info("Base de datos inicializada en %s", self.path)

    def list_products(self, *, active_only: bool = True) -> list[Product]:
        query = "SELECT id, sku, name, price_cents, stock, active FROM products"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY name"
        with self.connect() as connection:
            rows = connection.execute(query).fetchall()
        return [self._row_to_product(row) for row in rows]

    def get_product(self, product_id: int) -> Product | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, sku, name, price_cents, stock, active
                FROM products WHERE id = ?
                """,
                (product_id,),
            ).fetchone()
        return self._row_to_product(row) if row else None

    def get_product_by_sku(self, sku: str) -> Product | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id, sku, name, price_cents, stock, active
                FROM products WHERE sku = ? AND active = 1
                """,
                (sku.strip(),),
            ).fetchone()
        return self._row_to_product(row) if row else None

    def get_product_by_rfid_uid(self, uid: str) -> Product | None:
        normalized_uid = uid.strip().upper()
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT p.id, p.sku, p.name, p.price_cents, p.stock, p.active
                FROM rfid_tags AS tag
                JOIN products AS p ON p.id = tag.product_id
                WHERE tag.uid = ? AND tag.active = 1 AND p.active = 1
                """,
                (normalized_uid,),
            ).fetchone()
        return self._row_to_product(row) if row else None

    def assign_rfid_tag(self, uid: str, product_id: int) -> None:
        normalized_uid = uid.strip().upper()
        with self.connect() as connection:
            product = connection.execute(
                "SELECT id FROM products WHERE id = ? AND active = 1",
                (product_id,),
            ).fetchone()
            if product is None:
                raise ValueError(f"Producto no disponible: {product_id}")
            connection.execute(
                """
                INSERT INTO rfid_tags (uid, product_id, active)
                VALUES (?, ?, 1)
                ON CONFLICT(uid) DO UPDATE SET
                    product_id = excluded.product_id,
                    active = 1
                """,
                (normalized_uid, product_id),
            )
            connection.commit()
        LOGGER.info(
            "Etiqueta RFID asignada: uid=%s product_id=%s",
            normalized_uid,
            product_id,
        )

    def complete_sale(self, items: Iterable[CartItem]) -> SaleReceipt:
        sale_items = list(items)
        if not sale_items:
            raise SaleValidationError("No se puede pagar un carrito vacío")

        with self.connect() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                verified: list[tuple[Product, int]] = []
                total_cents = 0

                for item in sale_items:
                    if item.quantity <= 0:
                        raise SaleValidationError("La cantidad debe ser positiva")
                    row = connection.execute(
                        """
                        SELECT id, sku, name, price_cents, stock, active
                        FROM products WHERE id = ?
                        """,
                        (item.product.id,),
                    ).fetchone()
                    if row is None or not row["active"]:
                        raise SaleValidationError(
                            f"El producto {item.product.name} ya no está disponible"
                        )
                    product = self._row_to_product(row)
                    if product.price_cents != item.product.price_cents:
                        raise SaleValidationError(
                            f"El precio de {product.name} cambió; revise el carrito"
                        )
                    if product.stock < item.quantity:
                        raise InventoryError(
                            f"Stock insuficiente para {product.name}: "
                            f"disponibles {product.stock}, solicitados {item.quantity}"
                        )
                    verified.append((product, item.quantity))
                    total_cents += product.price_cents * item.quantity

                cursor = connection.execute(
                    """
                    INSERT INTO sales (paid_at, status, total_cents)
                    VALUES (CURRENT_TIMESTAMP, 'APPROVED', ?)
                    """,
                    (total_cents,),
                )
                sale_id = int(cursor.lastrowid)

                for product, quantity in verified:
                    subtotal = product.price_cents * quantity
                    connection.execute(
                        """
                        INSERT INTO sale_items (
                            sale_id, product_id, product_name, quantity,
                            unit_price_cents, subtotal_cents
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            sale_id,
                            product.id,
                            product.name,
                            quantity,
                            product.price_cents,
                            subtotal,
                        ),
                    )
                    updated = connection.execute(
                        """
                        UPDATE products SET stock = stock - ?
                        WHERE id = ? AND stock >= ?
                        """,
                        (quantity, product.id, quantity),
                    )
                    if updated.rowcount != 1:
                        raise InventoryError(
                            f"El inventario de {product.name} cambió durante el pago"
                        )

                connection.commit()
            except Exception:
                connection.rollback()
                LOGGER.exception("Venta rechazada y transacción revertida")
                raise

        LOGGER.info("Pago aprobado: venta=%s total_cents=%s", sale_id, total_cents)
        return SaleReceipt(sale_id=sale_id, total_cents=total_cents)

    @staticmethod
    def _row_to_product(row: sqlite3.Row) -> Product:
        return Product(
            id=int(row["id"]),
            sku=str(row["sku"]),
            name=str(row["name"]),
            price_cents=int(row["price_cents"]),
            stock=int(row["stock"]),
            active=bool(row["active"]),
        )
