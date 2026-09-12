"""Demostración reproducible sin hardware ni cambios a la base real.

Usa coordenadas sintéticas, el tracker y la ventana reales. NO valida YOLO,
el ángulo físico ni el Arduino. Guarda capturas de la interfaz en logs/.
"""

from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont, QFontDatabase

from carrito_smart.config import AppConfig
from carrito_smart.database import Database
from carrito_smart.detection_stabilizer import RawDetection
from carrito_smart.main_window import MainWindow
from carrito_smart.rfid import RfidAction
from carrito_smart.vision import draw_sensor_policy, draw_stable_detections, frame_to_qimage
from carrito_smart.vision_crossing import TopCrossingTracker, VisualCrossing


def main():
    application = QApplication.instance() or QApplication([])
    # El backend offscreen de Windows puede no descubrir fuentes del sistema.
    font = Path("C:/Windows/Fonts/segoeui.ttf")
    if font.exists():
        identity = QFontDatabase.addApplicationFont(str(font))
        families = QFontDatabase.applicationFontFamilies(identity)
        if families:
            application.setFont(QFont(families[0], 10))
    original = AppConfig.from_env()
    output = original.log_dir / "fusion_smoke" / datetime.now().strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="carrito-fusion-") as directory:
        db = Database(Path(directory) / "test.db")
        db.initialize()
        config = replace(original, data_dir=Path(directory), database_path=db.path, rfid_enabled=False)
        with patch.object(QTimer, "singleShot", lambda *args: None):
            window = MainWindow(db, config)
        window.resize(1280, 860)
        window.show()
        tracker = TopCrossingTracker(
            detection_threshold=.45, retention_threshold=.25, confirmation_count=3,
            detection_hold_ms=700, confidence_ema_alpha=.3,
        )

        def observe(y):
            now = time.monotonic()
            raw = [] if y is None else [RawDetection("bottle", .8, (520, y - 40, 640, y + 40))]
            stable, events, _ = tracker.update(raw, width=1280, height=720, now=now)
            window._vision_observation(now)
            window._handle_visual_crossings(events)
            window._show_detections([item.as_dict() for item in stable])
            canvas = draw_stable_detections(np.full((720, 1280, 3), 30, dtype=np.uint8), tuple(stable))
            draw_sensor_policy(canvas)
            window._show_frame(frame_to_qimage(canvas))
            application.processEvents()

        def snapshot(name):
            application.processEvents()
            window.grab().save(str(output / f"{name}.png"))

        try:
            time.sleep(.02)
            observe(None)
            window.serial_line_input.setText("ENTRADA:12345678")
            window._simulate_serial_line()
            assert window.cart.items == [] and window.fusion.pending
            snapshot("01-pendiente")
            for y in [350, 350, 350, 350]:
                observe(y)
                time.sleep(.125)
            assert window.cart.items[0].quantity == 1
            snapshot("02-confirmado")
            time.sleep(.8)
            observe(None)
            assert window.cart.items[0].quantity == 1
            snapshot("03-oculto-pero-presente")
            # Detección extra sin RFID: aviso visible, nunca una unidad cobrable.
            at = time.monotonic()
            window._handle_visual_crossings([
                VisualCrossing("smoke-extra", RfidAction.ENTRY, "bottle", 99, at, 2),
            ])
            assert window.pay_button.isEnabled() and window.cart.items[0].quantity == 1
            snapshot("04-aviso-visual-pago-habilitado")
            window.fusion.tick(now=at + 3.1)  # Vencimiento sintético, sin abrir hardware.
            window._refresh_fusion()
            assert window.pay_button.isEnabled() and not window.fusion.issues
            snapshot("05-aviso-vencido-pago-habilitado")
            # La baja ya no requiere trayectoria ni cámara funcionando.
            window._show_camera_error("Desconexión simulada para probar salida RFID")
            assert window.cart.items[0].quantity == 1
            snapshot("06-sin-camara")
            window.serial_line_input.setText("SALIDA:12345678")
            window._simulate_serial_line()
            assert window.cart.items == [] and not window.fusion.present_uids
            assert not window.fusion.pending and not window.fusion.issues
            snapshot("07-salida-rfid-sin-camara")
            window._simulate_serial_line()
            assert window.cart.items == []  # Repetición inocua.
            assert db.get_product_by_sku("CS-001").stock == 100
            (output / "results.json").write_text(json.dumps({
                "input": "synthetic coordinates, simulated RFID, isolated SQLite",
                "pending_then_entry": "passed", "occlusion_keeps_cart": "passed",
                "visual_notice_allows_payment": "passed",
                "expired_visual_notice_allows_payment": "passed",
                "rfid_only_exit_without_camera": "passed", "duplicate_exit": "passed",
                "inventory_unchanged": True,
                "hardware_test": False,
            }, indent=2), encoding="utf-8")
            print(output)
        finally:
            window.close()
            application.processEvents()


if __name__ == "__main__":
    main()
