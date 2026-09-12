from __future__ import annotations

import sqlite3

import pytest

from carrito_smart.cart import CartService
from carrito_smart.database import Database, InventoryError
from carrito_smart.models import CartItem


def test_rfid_tag_can_be_reassigned_to_an_existing_product(tmp_path):
    database = Database(tmp_path / "rfid.db")
    database.initialize()
    product = database.list_products()[0]

    database.assign_rfid_tag("A1B2C3D4", product.id)

    resolved = database.get_product_by_rfid_uid("a1b2c3d4")
    assert resolved is not None
    assert resolved.id == product.id


@pytest.fixture()
def database(tmp_path):
    database = Database(tmp_path / "test.db")
    database.initialize()
    return database


def test_initial_products_are_seeded(database):
    products = database.list_products()
    assert len(products) == 6
    stock_by_sku = {product.sku: product.stock for product in products}
    assert stock_by_sku == {
        "CS-001": 100,
        "CS-002": 100,
        "CS-003": 100,
        "CS-004": 0,
        "CS-005": 100,
        "CS-006": 100,
    }


def test_inventory_is_only_discounted_after_checkout(database):
    product = database.list_products()[0]
    cart = CartService(database)
    cart.add_product(product.id)
    cart.add_product(product.id)

    assert database.get_product(product.id).stock == product.stock

    receipt = cart.checkout()

    assert receipt.total_cents == product.price_cents * 2
    assert database.get_product(product.id).stock == product.stock - 2
    assert cart.items == []


def test_failed_sale_rolls_back_every_change(database):
    first, second = database.list_products()[:2]
    impossible_items = [
        CartItem(first, 1),
        CartItem(second, second.stock + 1),
    ]

    with pytest.raises(InventoryError):
        database.complete_sale(impossible_items)

    assert database.get_product(first.id).stock == first.stock
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM sale_items").fetchone()[0] == 0


def test_cart_total_and_manual_exit(database):
    product = database.list_products()[0]
    cart = CartService(database)
    cart.add_product(product.id)
    cart.add_product(product.id)
    cart.remove_product(product.id)

    assert len(cart.items) == 1
    assert cart.items[0].quantity == 1
    assert cart.total_cents == product.price_cents
