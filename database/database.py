from pathlib import Path
import sqlite3

BASE_DIR = Path(__file__).resolve().parent.parent
RUTA_BASE_DATOS = BASE_DIR / "data" / "carrito.db"
RUTA_SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def obtener_conexion() -> sqlite3.Connection:
    RUTA_BASE_DATOS.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(RUTA_BASE_DATOS)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


def inicializar_base_datos() -> None:
    try:
        with obtener_conexion() as conexion:
            conexion.executescript(RUTA_SCHEMA.read_text(encoding="utf-8"))
    except sqlite3.Error:
        raise


def cerrar_conexion(conexion: sqlite3.Connection) -> None:
    if conexion is not None:
        conexion.close()