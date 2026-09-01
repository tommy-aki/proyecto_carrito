from .database import inicializar_base_datos, obtener_conexion

HASH_DEMO = "DEMO_HASH_NO_USAR_EN_PRODUCCION"


def ejecutar_seed():
    inicializar_base_datos()
    with obtener_conexion() as conexion:
        conexion.execute("INSERT OR IGNORE INTO usuarios (nombre, correo, contrasena_hash, rol) VALUES (?, ?, ?, ?)", ("Administrador", "admin@carrito.local", HASH_DEMO, "ADMINISTRADOR"))
        dispositivos = [("ARDUINO-01", "Arduino Nano Principal", "ARDUINO"), ("RFID-A", "Lector RFID Entrada", "LECTOR_RFID"), ("RFID-B", "Lector RFID Salida", "LECTOR_RFID"), ("CAM-01", "Camara Principal", "CAMARA"), ("PC-01", "Computadora Principal", "COMPUTADORA")]
        conexion.executemany("INSERT OR IGNORE INTO dispositivos (codigo_dispositivo, nombre, tipo) VALUES (?, ?, ?)", dispositivos)
        productos = [("DEMO-001", "Producto demostracion 4A3B2C1D", 10.00, 20, "4A3B2C1D"), ("DEMO-002", "Producto demostracion 8F9E0D1C", 15.00, 20, "8F9E0D1C"), ("DEMO-003", "Producto demostracion 12345678", 7.50, 20, "12345678")]
        for codigo, nombre, precio, stock, uid in productos:
            conexion.execute("INSERT OR IGNORE INTO productos (codigo_producto, nombre, precio, stock_actual, metodo_identificacion) VALUES (?, ?, ?, ?, 'RFID')", (codigo, nombre, precio, stock))
            producto = conexion.execute("SELECT id_producto FROM productos WHERE codigo_producto = ?", (codigo,)).fetchone()
            conexion.execute("INSERT OR IGNORE INTO etiquetas_rfid (id_producto, uid) VALUES (?, ?)", (producto[0], uid))


if __name__ == "__main__":
    ejecutar_seed()
    print("Seed aplicado en data/carrito.db")