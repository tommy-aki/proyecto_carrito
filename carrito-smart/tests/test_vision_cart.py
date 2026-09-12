from __future__ import annotations

from carrito_smart.cart import CartService
from carrito_smart.database import Database
from carrito_smart.config import AppConfig
from carrito_smart.detection_stabilizer import RawDetection, TemporalDetectionStabilizer
from carrito_smart.vision_cart import VisionCartIntegrator


BOTTLE = {
    "class_name": "bottle",
    "confidence": 0.82,
    "bbox": (10, 20, 100, 200),
    "held": False,
}

SODA_CAN = {
    "class_name": "aluminum soda can",
    "confidence": 0.79,
    "bbox": (120, 20, 220, 200),
    "held": False,
}


def test_bottle_adds_on_appearance_and_removes_on_disappearance(tmp_path):
    database = Database(tmp_path / "vision_cart.db")
    database.initialize()
    cart = CartService(database)
    integrator = VisionCartIntegrator(
        database,
        cart,
        {"bottle": "CS-001"},
    )

    first = integrator.update([BOTTLE])
    repeated = integrator.update([BOTTLE])
    held = integrator.update([{**BOTTLE, "held": True}])

    assert first[0].accepted
    assert repeated == []
    assert held == []
    assert cart.items[0].product.sku == "CS-001"
    assert cart.items[0].quantity == 1

    disappearance = integrator.update([])

    assert disappearance[0].accepted
    assert disappearance[0].action == "exit"
    assert cart.items == []

    second = integrator.update([BOTTLE])

    assert second[0].accepted
    assert second[0].action == "entry"
    assert cart.items[0].quantity == 1


def test_unmapped_class_does_not_modify_cart(tmp_path):
    database = Database(tmp_path / "vision_cart.db")
    database.initialize()
    cart = CartService(database)
    integrator = VisionCartIntegrator(database, cart, {"bottle": "CS-001"})

    assert integrator.update([{"class_name": "person"}]) == []
    assert cart.items == []


def test_yoloe_bottle_and_soda_can_map_to_separate_products(tmp_path):
    database = Database(tmp_path / "vision_cart.db")
    database.initialize()
    cart = CartService(database)
    integrator = VisionCartIntegrator(
        database,
        cart,
        {
            "plastic water bottle": "CS-001",
            "aluminum soda can": "CS-002",
        },
    )

    results = integrator.update(
        [{**BOTTLE, "class_name": "plastic water bottle"}, SODA_CAN]
    )

    assert len(results) == 2
    assert all(result.accepted for result in results)
    assert {item.product.sku for item in cart.items} == {"CS-001", "CS-002"}


def test_disabled_vision_cart_never_adds_products(tmp_path):
    database = Database(tmp_path / "vision_cart.db")
    database.initialize()
    cart = CartService(database)
    integrator = VisionCartIntegrator(
        database,
        cart,
        {"bottle": "CS-001"},
        enabled=False,
    )

    assert integrator.update([BOTTLE]) == []
    assert cart.items == []


def test_checkout_or_clear_can_release_visible_detection_claim(tmp_path):
    database = Database(tmp_path / "vision_cart.db")
    database.initialize()
    cart = CartService(database)
    integrator = VisionCartIntegrator(database, cart, {"bottle": "CS-001"})
    integrator.update([BOTTLE])

    cart.clear()
    integrator.release_cart_claims()

    assert integrator.update([]) == []
    assert cart.items == []


def test_weak_confirmed_chocolate_adds_once_and_expires_without_stock_change(tmp_path):
    config = AppConfig.from_env()
    database = Database(tmp_path / "chocolate.db")
    database.initialize()
    cart = CartService(database)
    prompt = config.yoloe_prompts[2]
    integrator = VisionCartIntegrator(database, cart, {prompt: "CS-006"})
    before_stock = database.get_product_by_sku("CS-006").stock
    stabilizer = TemporalDetectionStabilizer(
        detection_threshold=config.yoloe_detection_threshold,
        retention_threshold=config.yoloe_retention_threshold,
        confirmation_count=config.confirmation_count,
        detection_hold_ms=config.detection_hold_ms,
        confidence_ema_alpha=config.confidence_ema_alpha,
        class_thresholds={prompt: (
            config.yoloe_chocolate_detection_threshold,
            config.yoloe_chocolate_retention_threshold,
        )},
    )
    for index, confidence in enumerate([0.33, 0.304, 0.301, 0.308, 0.252]):
        stable, _ = stabilizer.update(
            [RawDetection(prompt, confidence, (10, 20, 100, 200))], now=index * 0.125
        )
        integrator.update([item.as_dict() for item in stable])
        if index < 2:
            assert cart.items == []
        else:
            assert len(cart.items) == 1
            assert cart.items[0].product.sku == "CS-006"
            assert cart.items[0].quantity == 1
    held, _ = stabilizer.update([], now=1.19)
    assert integrator.update([item.as_dict() for item in held]) == []
    assert cart.items[0].quantity == 1
    expired, _ = stabilizer.update([], now=1.21)
    exits = integrator.update([item.as_dict() for item in expired])
    assert len(exits) == 1 and exits[0].action == "exit"
    assert cart.items == []
    assert database.get_product_by_sku("CS-006").stock == before_stock
