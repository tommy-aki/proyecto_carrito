import csv
from pathlib import Path

from .database import inicializar_base_datos, obtener_conexion


def migrar_csv(ruta_csv=None):
    """Importa UIDs como productos temporales de precio cero, sin inventar datos comerciales."""
    inicializar_base_datos()
    ruta = Path(ruta_csv) if ruta_csv else Path(__file__).resolve().parent.parent / "inventario.csv"
    if not ruta.exists():
        return 0
    importados = 0
    with ruta.open(newline="", encoding="utf-8-sig") as archivo, obtener_conexion() as conexion:
        for fila in csv.DictReader(archivo):
            uid = (fila.get("UID") or "").strip().upper()
            if not uid or conexion.execute("SELECT 1 FROM etiquetas_rfid WHERE uid = ?", (uid,)).fetchone():
                continue
            codigo = f"MIGRADO-{uid[:30]}"
            conexion.execute("INSERT OR IGNORE INTO productos (codigo_producto, nombre, precio, metodo_identificacion) VALUES (?, ?, 0, 'RFID')", (codigo, f"Producto migrado {uid}"))
            producto = conexion.execute("SELECT id_producto FROM productos WHERE codigo_producto = ?", (codigo,)).fetchone()
            conexion.execute("INSERT OR IGNORE INTO etiquetas_rfid (id_producto, uid, observaciones) VALUES (?, ?, ?)", (producto[0], uid, "Migrado desde inventario.csv; asociar datos comerciales"))
            importados += 1
    return importados


if __name__ == "__main__":
    print(f"UID migrados: {migrar_csv()}. inventario.csv se conserva.")