from datetime import datetime
from uuid import uuid4
import sqlite3


def obtener_o_crear_sesion(conexion):
    sesion = conexion.execute("SELECT id_sesion FROM sesiones_compra WHERE estado = 'ABIERTA' ORDER BY id_sesion LIMIT 1").fetchone()
    if sesion:
        return sesion[0]
    usuario = conexion.execute("SELECT id_usuario FROM usuarios WHERE activo = 1 ORDER BY rol = 'ADMINISTRADOR' DESC, id_usuario LIMIT 1").fetchone()
    if not usuario:
        raise sqlite3.IntegrityError("Se necesita ejecutar el seed para crear un usuario de prueba")
    codigo = f"DEMO-{datetime.now():%Y%m%d%H%M%S}-{uuid4().hex[:6].upper()}"
    return conexion.execute("INSERT INTO sesiones_compra (id_usuario, codigo_sesion) VALUES (?, ?)", (usuario[0], codigo)).lastrowid


def obtener_dispositivo(conexion, codigo):
    dispositivo = conexion.execute("SELECT id_dispositivo FROM dispositivos WHERE codigo_dispositivo = ?", (codigo,)).fetchone()
    if not dispositivo:
        raise sqlite3.IntegrityError(f"Dispositivo no configurado: {codigo}")
    return dispositivo[0]


def procesar_rfid(conexion, id_sesion, id_dispositivo, direccion, uid):
    sesion = conexion.execute("SELECT estado FROM sesiones_compra WHERE id_sesion = ?", (id_sesion,)).fetchone()
    if not sesion:
        raise sqlite3.IntegrityError("Sesion inexistente")
    if sesion[0] != "ABIERTA":
        conexion.execute("INSERT INTO eventos_deteccion (id_sesion, id_dispositivo, origen, direccion, valor_detectado, procesado, mensaje) VALUES (?, ?, 'RFID', 'IGNORADA', ?, 0, ?)", (id_sesion, id_dispositivo, uid, "Lectura ignorada: la sesión no está ABIERTA"))
        return "[RFID] Lectura ignorada: la sesión no está ABIERTA"
    etiqueta = conexion.execute("SELECT e.id_etiqueta, e.id_producto, e.estado, p.nombre, p.precio FROM etiquetas_rfid e JOIN productos p ON p.id_producto = e.id_producto WHERE e.uid = ?", (uid,)).fetchone()
    if not etiqueta or etiqueta[2] != "ACTIVA":
        conexion.execute("INSERT INTO eventos_deteccion (id_sesion, id_dispositivo, origen, direccion, valor_detectado, procesado, mensaje) VALUES (?, ?, 'RFID', ?, ?, 0, ?)", (id_sesion, id_dispositivo, direccion, uid, "UID RFID no registrado o etiqueta inactiva"))
        return f"[RFID] UID no registrado: {uid}"
    conexion.execute("INSERT INTO eventos_deteccion (id_sesion, id_dispositivo, id_producto, id_etiqueta, origen, direccion, valor_detectado, procesado) VALUES (?, ?, ?, ?, 'RFID', ?, ?, 1)", (id_sesion, id_dispositivo, etiqueta[1], etiqueta[0], direccion, uid))
    detalle = conexion.execute("SELECT cantidad FROM detalle_carrito WHERE id_sesion = ? AND id_producto = ?", (id_sesion, etiqueta[1])).fetchone()
    if direccion == "ENTRADA":
        if detalle:
            conexion.execute("UPDATE detalle_carrito SET cantidad = cantidad + 1, fecha_actualizacion = CURRENT_TIMESTAMP WHERE id_sesion = ? AND id_producto = ?", (id_sesion, etiqueta[1]))
        else:
            conexion.execute("INSERT INTO detalle_carrito (id_sesion, id_producto, precio_unitario) VALUES (?, ?, ?)", (id_sesion, etiqueta[1], etiqueta[4]))
        mensaje = f"Producto {uid} ingresado: {etiqueta[3]}"
    elif direccion == "SALIDA":
        if not detalle:
            mensaje = f"[RFID] Producto {uid} no está en el carrito"
        elif detalle[0] > 1:
            conexion.execute("UPDATE detalle_carrito SET cantidad = cantidad - 1, fecha_actualizacion = CURRENT_TIMESTAMP WHERE id_sesion = ? AND id_producto = ?", (id_sesion, etiqueta[1]))
            mensaje = f"Producto {uid} retirado del carrito"
        else:
            conexion.execute("DELETE FROM detalle_carrito WHERE id_sesion = ? AND id_producto = ?", (id_sesion, etiqueta[1]))
            mensaje = f"Producto {uid} eliminado del carrito"
    else:
        raise ValueError("Direccion RFID invalida")
    conexion.execute("UPDATE sesiones_compra SET total_calculado = COALESCE((SELECT SUM(cantidad * precio_unitario) FROM detalle_carrito WHERE id_sesion = ?), 0) WHERE id_sesion = ?", (id_sesion, id_sesion))
    return mensaje


def crear_venta_desde_sesion(conexion, id_sesion):
    sesion = conexion.execute("SELECT estado, total_calculado FROM sesiones_compra WHERE id_sesion = ?", (id_sesion,)).fetchone()
    if not sesion:
        raise sqlite3.IntegrityError("Sesion inexistente")
    if sesion[0] != "ABIERTA":
        raise sqlite3.IntegrityError("La sesion debe estar ABIERTA")
    if sesion[1] <= 0:
        raise sqlite3.IntegrityError("La sesion debe tener productos y un total mayor que cero")
    tiene_productos = conexion.execute("SELECT 1 FROM detalle_carrito WHERE id_sesion = ? LIMIT 1", (id_sesion,)).fetchone()
    if not tiene_productos:
        raise sqlite3.IntegrityError("La sesion debe tener productos")
    total = sesion[1]
    venta = conexion.execute("INSERT INTO ventas (id_sesion, numero_venta, subtotal, total) VALUES (?, ?, ?, ?)", (id_sesion, f"V-{uuid4().hex[:12].upper()}", total, total)).lastrowid
    conexion.execute("UPDATE sesiones_compra SET estado = 'PAGANDO' WHERE id_sesion = ?", (id_sesion,))
    return venta


def registrar_pago(conexion, id_venta, metodo, monto):
    venta = conexion.execute("SELECT id_sesion, total, estado FROM ventas WHERE id_venta = ?", (id_venta,)).fetchone()
    if not venta:
        raise sqlite3.IntegrityError("Venta inexistente")
    if venta[2] != "PENDIENTE":
        raise sqlite3.IntegrityError("La venta no está pendiente")
    sesion = conexion.execute("SELECT estado FROM sesiones_compra WHERE id_sesion = ?", (venta[0],)).fetchone()
    if not sesion or sesion[0] != "PAGANDO":
        raise sqlite3.IntegrityError("La sesión no está PAGANDO")
    if monto != venta[1]:
        raise sqlite3.IntegrityError("El monto del pago no coincide con el total de la venta")
    return conexion.execute("INSERT INTO pagos (id_venta, metodo, monto) VALUES (?, ?, ?)", (id_venta, metodo, monto)).lastrowid


def aprobar_pago(conexion, id_pago):
    pago = conexion.execute("SELECT id_venta, monto FROM pagos WHERE id_pago = ?", (id_pago,)).fetchone()
    if not pago:
        raise sqlite3.IntegrityError("Pago inexistente")
    venta = conexion.execute("SELECT id_sesion, total, estado FROM ventas WHERE id_venta = ?", (pago[0],)).fetchone()
    if not venta:
        raise sqlite3.IntegrityError("Venta inexistente")
    if venta[2] != "PENDIENTE":
        raise sqlite3.IntegrityError("La venta no está pendiente")
    sesion = conexion.execute("SELECT estado FROM sesiones_compra WHERE id_sesion = ?", (venta[0],)).fetchone()
    if not sesion or sesion[0] != "PAGANDO":
        raise sqlite3.IntegrityError("La sesión no está PAGANDO")
    if pago[1] != venta[1]:
        raise sqlite3.IntegrityError("El monto del pago no coincide con el total de la venta")
    detalles = conexion.execute("SELECT id_producto, cantidad, precio_unitario FROM detalle_carrito WHERE id_sesion = ?", (venta[0],)).fetchall()
    for id_producto, cantidad, _ in detalles:
        stock = conexion.execute("SELECT stock_actual FROM productos WHERE id_producto = ?", (id_producto,)).fetchone()[0]
        if stock < cantidad:
            raise sqlite3.IntegrityError(f"Stock insuficiente para producto {id_producto}")
    for id_producto, cantidad, precio in detalles:
        anterior = conexion.execute("SELECT stock_actual FROM productos WHERE id_producto = ?", (id_producto,)).fetchone()[0]
        conexion.execute("INSERT INTO detalle_venta (id_venta, id_producto, cantidad, precio_unitario, subtotal) VALUES (?, ?, ?, ?, ?)", (pago[0], id_producto, cantidad, precio, cantidad * precio))
        conexion.execute("UPDATE productos SET stock_actual = stock_actual - ? WHERE id_producto = ?", (cantidad, id_producto))
        conexion.execute("INSERT INTO movimientos_inventario (id_producto, id_venta, tipo, cantidad, stock_anterior, stock_nuevo, motivo) VALUES (?, ?, 'VENTA', ?, ?, ?, ?)", (id_producto, pago[0], cantidad, anterior, anterior - cantidad, "Pago aprobado"))
    conexion.execute("UPDATE pagos SET estado = 'APROBADO', fecha_respuesta = CURRENT_TIMESTAMP WHERE id_pago = ?", (id_pago,))
    conexion.execute("UPDATE ventas SET estado = 'PAGADA' WHERE id_venta = ?", (pago[0],))
    conexion.execute("UPDATE sesiones_compra SET estado = 'FINALIZADA', fecha_fin = CURRENT_TIMESTAMP WHERE id_sesion = ?", (venta[0],))


def cancelar_venta(conexion, id_venta):
    venta = conexion.execute("SELECT id_sesion FROM ventas WHERE id_venta = ? AND estado = 'PENDIENTE'", (id_venta,)).fetchone()
    if not venta:
        raise sqlite3.IntegrityError("La venta no existe o no está pendiente")
    conexion.execute("UPDATE ventas SET estado = 'CANCELADA' WHERE id_venta = ?", (id_venta,))
    conexion.execute("UPDATE sesiones_compra SET estado = 'CANCELADA', fecha_fin = CURRENT_TIMESTAMP WHERE id_sesion = ?", (venta[0],))