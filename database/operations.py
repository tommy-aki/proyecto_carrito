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


def obtener_sesion(conexion, id_sesion):
    return conexion.execute("SELECT id_sesion, codigo_sesion, estado, fecha_inicio, total_calculado FROM sesiones_compra WHERE id_sesion = ?", (id_sesion,)).fetchone()


def obtener_carrito(conexion, id_sesion):
    return conexion.execute("SELECT p.id_producto, p.nombre, dc.cantidad, dc.precio_unitario, dc.cantidad * dc.precio_unitario AS subtotal FROM detalle_carrito dc JOIN productos p ON p.id_producto = dc.id_producto WHERE dc.id_sesion = ? ORDER BY p.nombre", (id_sesion,)).fetchall()


def obtener_eventos(conexion, id_sesion, limite=12):
    return conexion.execute("SELECT strftime('%H:%M:%S', fecha_evento) AS hora, origen, direccion, valor_detectado, mensaje FROM eventos_deteccion WHERE id_sesion = ? ORDER BY id_evento DESC LIMIT ?", (id_sesion, limite)).fetchall()


def obtener_productos(conexion, activos_solo=False):
    filtro = " WHERE activo = 1" if activos_solo else ""
    return conexion.execute("SELECT id_producto, codigo_producto, nombre, precio, stock_actual, stock_minimo, metodo_identificacion, activo FROM productos" + filtro + " ORDER BY nombre").fetchall()


def asociar_etiqueta(conexion, uid, id_producto):
    uid = "".join((uid or "").split()).upper()
    if not uid:
        raise sqlite3.IntegrityError("El UID no puede estar vacío")
    if not conexion.execute("SELECT 1 FROM productos WHERE id_producto = ? AND activo = 1", (id_producto,)).fetchone():
        raise sqlite3.IntegrityError("El producto no existe o está inactivo")
    if conexion.execute("SELECT 1 FROM etiquetas_rfid WHERE uid = ?", (uid,)).fetchone():
        raise sqlite3.IntegrityError("El UID ya está registrado")
    return conexion.execute("INSERT INTO etiquetas_rfid (id_producto, uid) VALUES (?, ?)", (id_producto, uid)).lastrowid


def rechazar_pago(conexion, id_pago, mensaje="Pago rechazado en modo demostración"):
    pago = conexion.execute("SELECT id_venta FROM pagos WHERE id_pago = ? AND estado = 'PENDIENTE'", (id_pago,)).fetchone()
    if not pago:
        raise sqlite3.IntegrityError("El pago no existe o ya fue procesado")
    conexion.execute("UPDATE pagos SET estado = 'RECHAZADO', fecha_respuesta = CURRENT_TIMESTAMP, mensaje_respuesta = ? WHERE id_pago = ?", (mensaje, id_pago))


def resumen_admin(conexion):
    return {
        "productos": conexion.execute("SELECT COUNT(*) FROM productos WHERE activo = 1").fetchone()[0],
        "stock_bajo": conexion.execute("SELECT COUNT(*) FROM productos WHERE activo = 1 AND stock_actual <= stock_minimo").fetchone()[0],
        "ventas_hoy": conexion.execute("SELECT COUNT(*) FROM ventas WHERE date(fecha_venta) = date('now') AND estado = 'PAGADA'").fetchone()[0],
        "sesiones_activas": conexion.execute("SELECT COUNT(*) FROM sesiones_compra WHERE estado IN ('ABIERTA', 'PAGANDO')").fetchone()[0],
        "ventas": conexion.execute("SELECT numero_venta, total, estado, strftime('%d/%m %H:%M', fecha_venta) AS fecha FROM ventas ORDER BY id_venta DESC LIMIT 8").fetchall(),
    }


def obtener_ventas(conexion):
    return conexion.execute("SELECT v.id_venta, v.numero_venta, v.fecha_venta, v.total, v.estado, COALESCE((SELECT GROUP_CONCAT(metodo, ', ') FROM pagos WHERE id_venta = v.id_venta), 'SIN PAGO') FROM ventas v ORDER BY v.id_venta DESC").fetchall()


def obtener_detalle_venta(conexion, id_venta):
    return conexion.execute("SELECT p.nombre, dv.cantidad, dv.precio_unitario, dv.subtotal FROM detalle_venta dv JOIN productos p ON p.id_producto = dv.id_producto WHERE dv.id_venta = ?", (id_venta,)).fetchall()


def obtener_eventos_admin(conexion, origen=None):
    query = "SELECT strftime('%H:%M:%S', e.fecha_evento), e.origen, e.direccion, COALESCE(p.nombre, '-'), COALESCE(e.valor_detectado, '-'), CASE WHEN e.procesado = 1 THEN 'PROCESADO' ELSE 'PENDIENTE' END FROM eventos_deteccion e LEFT JOIN productos p ON p.id_producto = e.id_producto"
    params = ()
    if origen:
        query += " WHERE e.origen = ?"
        params = (origen,)
    return conexion.execute(query + " ORDER BY e.id_evento DESC LIMIT 100", params).fetchall()


def obtener_dispositivos(conexion):
    return conexion.execute("SELECT codigo_dispositivo, nombre, tipo, estado, identificador_tecnico, ultima_comunicacion FROM dispositivos ORDER BY id_dispositivo").fetchall()


def obtener_etiquetas(conexion):
    return conexion.execute("SELECT e.uid, p.nombre, e.estado, e.fecha_registro, e.id_etiqueta FROM etiquetas_rfid e JOIN productos p ON p.id_producto = e.id_producto ORDER BY e.id_etiqueta DESC").fetchall()


def cambiar_estado_etiqueta(conexion, id_etiqueta, estado):
    if estado not in ("ACTIVA", "INACTIVA", "EXTRAVIADA"):
        raise sqlite3.IntegrityError("Estado RFID inválido")
    conexion.execute("UPDATE etiquetas_rfid SET estado = ? WHERE id_etiqueta = ?", (estado, id_etiqueta))


def ajustar_inventario(conexion, id_producto, cantidad, tipo, id_usuario=None):
    if tipo not in ("AJUSTE_ENTRADA", "AJUSTE_SALIDA") or cantidad <= 0:
        raise sqlite3.IntegrityError("Ajuste de inventario inválido")
    producto = conexion.execute("SELECT stock_actual FROM productos WHERE id_producto = ?", (id_producto,)).fetchone()
    if not producto:
        raise sqlite3.IntegrityError("Producto inexistente")
    anterior = producto[0]
    nuevo = anterior + cantidad if tipo == "AJUSTE_ENTRADA" else anterior - cantidad
    if nuevo < 0:
        raise sqlite3.IntegrityError("El stock no puede ser negativo")
    conexion.execute("UPDATE productos SET stock_actual = ? WHERE id_producto = ?", (nuevo, id_producto))
    return conexion.execute("INSERT INTO movimientos_inventario (id_producto, id_usuario, tipo, cantidad, stock_anterior, stock_nuevo, motivo) VALUES (?, ?, ?, ?, ?, ?, ?)", (id_producto, id_usuario, tipo, cantidad, anterior, nuevo, "Ajuste administrativo")).lastrowid


def crear_producto(conexion, codigo, nombre, precio, stock, minimo, metodo="RFID"):
    if not codigo.strip() or not nombre.strip() or precio < 0 or stock < 0 or minimo < 0:
        raise sqlite3.IntegrityError("Datos de producto inválidos")
    return conexion.execute("INSERT INTO productos (codigo_producto, nombre, precio, stock_actual, stock_minimo, metodo_identificacion) VALUES (?, ?, ?, ?, ?, ?)", (codigo.strip(), nombre.strip(), precio, stock, minimo, metodo)).lastrowid


def actualizar_producto(conexion, id_producto, nombre, precio, minimo):
    if not nombre.strip() or precio < 0 or minimo < 0:
        raise sqlite3.IntegrityError("Datos de producto inválidos")
    conexion.execute("UPDATE productos SET nombre = ?, precio = ?, stock_minimo = ?, fecha_actualizacion = CURRENT_TIMESTAMP WHERE id_producto = ?", (nombre.strip(), precio, minimo, id_producto))


def desactivar_producto(conexion, id_producto):
    conexion.execute("UPDATE productos SET activo = 0, fecha_actualizacion = CURRENT_TIMESTAMP WHERE id_producto = ?", (id_producto,))