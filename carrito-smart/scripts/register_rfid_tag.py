"""Asocia un UID RFID físico con un producto existente de Carrito Smart."""

from __future__ import annotations

import argparse

from carrito_smart.config import AppConfig
from carrito_smart.database import Database
from carrito_smart.rfid import RfidProtocolError, normalize_uid


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Asocia una etiqueta RFID a un SKU del catálogo"
    )
    parser.add_argument("uid", help="UID hexadecimal leído por el Arduino")
    parser.add_argument("sku", help="SKU de Carrito Smart, por ejemplo CS-002")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        uid = normalize_uid(args.uid)
    except RfidProtocolError as error:
        raise SystemExit(str(error)) from error

    config = AppConfig.from_env()
    config.ensure_directories()
    database = Database(config.database_path)
    database.initialize()
    product = next(
        (item for item in database.list_products() if item.sku == args.sku.strip()),
        None,
    )
    if product is None:
        available = ", ".join(item.sku for item in database.list_products())
        raise SystemExit(f"SKU inexistente. Disponibles: {available}")
    database.assign_rfid_tag(uid, product.id)
    print(f"Etiqueta {uid} asociada a {product.sku} · {product.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
