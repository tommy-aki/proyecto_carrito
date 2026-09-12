from __future__ import annotations

from types import SimpleNamespace

import pytest

from carrito_smart.cart import CartService
from carrito_smart.database import Database
from carrito_smart.rfid import (
    RfidAction,
    RfidEventProcessor,
    RfidProtocolError,
    normalize_uid,
    parse_rfid_line,
    select_serial_port,
)


def test_parser_accepts_firmware_protocol_and_normalizes_uid():
    event = parse_rfid_line("  entrada:4a 3b 2c 1d  ")

    assert event is not None
    assert event.action is RfidAction.ENTRY
    assert event.uid == "4A3B2C1D"
    assert parse_rfid_line("Lector A: Conectado y respondiendo.") is None


def test_parser_rejects_invalid_event_uid():
    with pytest.raises(RfidProtocolError, match="UID"):
        parse_rfid_line("SALIDA:NO-ES-HEX")

    with pytest.raises(RfidProtocolError, match="UID"):
        normalize_uid("ABC")


def test_port_selection_prefers_arduino_and_respects_explicit_port():
    bluetooth = SimpleNamespace(
        device="COM2", description="Bluetooth", manufacturer="", hwid=""
    )
    arduino = SimpleNamespace(
        device="COM7", description="USB-SERIAL CH340", manufacturer="wch", hwid=""
    )

    assert select_serial_port("COM9", [bluetooth, arduino]) == "COM9"
    assert select_serial_port("AUTO", [bluetooth, arduino]) == "COM7"
    assert select_serial_port("AUTO", [bluetooth]) == "COM2"
    assert select_serial_port("AUTO", []) is None


def test_rfid_processor_adds_removes_and_deduplicates_physical_tag(tmp_path):
    database = Database(tmp_path / "rfid.db")
    database.initialize()
    cart = CartService(database)
    processor = RfidEventProcessor(database, cart)

    entry = parse_rfid_line("ENTRADA:4A3B2C1D")
    assert entry is not None
    accepted = processor.process(entry)
    duplicate = processor.process(entry)

    assert accepted.accepted
    assert not duplicate.accepted
    assert duplicate.reason == "duplicate_entry"
    assert len(cart.items) == 1
    assert cart.items[0].product.sku == "CS-002"
    assert cart.items[0].quantity == 1

    exit_event = parse_rfid_line("SALIDA:4A3B2C1D")
    assert exit_event is not None
    removed = processor.process(exit_event)
    repeated_exit = processor.process(exit_event)

    assert removed.accepted
    assert not repeated_exit.accepted
    assert repeated_exit.reason == "tag_not_present"
    assert cart.items == []


def test_rfid_processor_ignores_unknown_uid(tmp_path):
    database = Database(tmp_path / "rfid.db")
    database.initialize()
    processor = RfidEventProcessor(database, CartService(database))
    event = parse_rfid_line("ENTRADA:DEADBEEF")

    assert event is not None
    result = processor.process(event)
    assert not result.accepted
    assert result.reason == "unknown_uid"
