"""Prueba guiada real de RFID + webcam en una copia TEMPORAL de SQLite."""

import argparse
from contextlib import closing
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from carrito_smart.config import AppConfig
from carrito_smart.database import Database
from carrito_smart.logging_config import setup_logging
from carrito_smart.main_window import MainWindow


def copy_database(source_path: Path, target_path: Path) -> None:
    with closing(sqlite3.connect(source_path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(target_path)) as target:
            source.backup(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=45)
    args = parser.parse_args()
    if not 5 <= args.seconds <= 120:
        parser.error("Use entre 5 y 120 segundos")
    original = AppConfig.from_env()
    output = original.log_dir / "fusion_hardware" / datetime.now().strftime("%Y%m%d-%H%M%S")
    setup_logging(output)
    with tempfile.TemporaryDirectory(prefix="carrito-hardware-") as directory:
        database_path = Path(directory) / "snapshot.db"
        # La fuente es estrictamente de solo lectura; incluso un pago de prueba
        # en esta ventana solo puede modificar la copia temporal.
        copy_database(original.database_path, database_path)
        config = replace(original, database_path=database_path, log_dir=output, rfid_enabled=True)
        application = QApplication.instance() or QApplication([])
        window = MainWindow(Database(database_path), config)
        window.setWindowTitle("Carrito Smart · PRUEBA AISLADA · inventario real protegido")
        window.resize(1280, 860)
        window.show()
        started = time.monotonic()
        ready_at = None
        previous_revision = -1
        entered = False
        removed = False
        messages = []
        closing = False

        def inspect():
            nonlocal ready_at, previous_revision, entered, removed, closing
            if closing:
                return
            now = time.monotonic()
            if window.fusion.ready and ready_at is None:
                ready_at = now
                print("LISTO: aparicion nueva + RFID, tapar, salida solo RFID (sin cruce visual).", flush=True)
            if window.fusion.revision != previous_revision:
                previous_revision = window.fusion.revision
                row = {
                    "seconds": round(now - started, 3), "status": window.fusion.status,
                    "uids": dict(window.fusion.present_uids),
                    "cart": {item.product.sku: item.quantity for item in window.cart.items},
                }
                messages.append(row)
                print(json.dumps(row, ensure_ascii=True), flush=True)
                if window.fusion.present_uids and not entered:
                    entered = True
                    if window._last_frame is not None:
                        window._last_frame.save(str(output / "entrada-confirmada.png"))
                if entered and not window.fusion.present_uids and not window.cart.items:
                    removed = True
            expired = now - ready_at >= args.seconds if ready_at is not None else now - started >= 30
            if expired:
                closing = True
                timer.stop()
                window.close()

        timer = QTimer(window)
        timer.setInterval(100)
        timer.timeout.connect(inspect)
        timer.start()
        print(f"Preparando hardware; resultados en {output}", flush=True)
        application.exec()
        report = {
            "real_database_modified": False, "both_sensors_ready": ready_at is not None,
            "entry_observed": entered, "removal_observed": removed,
            "metrics": window._vision_metrics, "events": messages,
        }
        (output / "results.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "events"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
