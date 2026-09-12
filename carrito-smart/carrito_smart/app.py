"""Punto de entrada de la aplicación."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from carrito_smart.config import AppConfig
from carrito_smart.database import Database
from carrito_smart.logging_config import setup_logging
from carrito_smart.main_window import MainWindow


def main() -> int:
    config = AppConfig.from_env()
    config.ensure_directories()
    log_path = setup_logging(config.log_dir)
    logger = logging.getLogger(__name__)
    logger.info("Iniciando Carrito Smart; log=%s", log_path)

    database = Database(config.database_path)
    database.initialize()

    application = QApplication(sys.argv)
    application.setApplicationName("Carrito Smart")
    application.setOrganizationName("Prototipo académico")
    window = MainWindow(database, config)
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())

