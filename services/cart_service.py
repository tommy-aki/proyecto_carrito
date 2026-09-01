import sqlite3

from database.database import inicializar_base_datos, obtener_conexion
from database.operations import (
    aprobar_pago,
    asociar_etiqueta,
    cancelar_venta,
    crear_venta_desde_sesion,
    obtener_carrito,
    obtener_eventos,
    obtener_o_crear_sesion,
    obtener_productos,
    obtener_sesion,
    procesar_rfid,
    rechazar_pago,
    registrar_pago,
    resumen_admin,
    actualizar_producto, ajustar_inventario, cambiar_estado_etiqueta, crear_producto,
    desactivar_producto, obtener_detalle_venta, obtener_dispositivos, obtener_etiquetas,
    obtener_eventos_admin, obtener_ventas,
)
from database.seed import ejecutar_seed


class CartService:
    """Fachada transaccional: la interfaz nunca ejecuta SQL directamente."""

    def __init__(self):
        inicializar_base_datos()
        ejecutar_seed()
        self.session_id = None

    def start_session(self):
        with obtener_conexion() as connection:
            self.session_id = obtener_o_crear_sesion(connection)
            connection.commit()
        return self.session_id

    def new_session(self):
        self.session_id = None
        return self.start_session()

    def snapshot(self):
        if not self.session_id:
            self.start_session()
        with obtener_conexion() as connection:
            session = obtener_sesion(connection, self.session_id)
            return session, obtener_carrito(connection, self.session_id), obtener_eventos(connection, self.session_id)

    def rfid(self, direction, uid):
        if not self.session_id:
            self.start_session()
        with obtener_conexion() as connection:
            device = "RFID-A" if direction == "ENTRADA" else "RFID-B"
            message = procesar_rfid(connection, self.session_id, _device(connection, device), direction, uid)
            connection.commit()
            return message

    def begin_checkout(self):
        with obtener_conexion() as connection:
            sale_id = crear_venta_desde_sesion(connection, self.session_id)
            connection.commit()
            return sale_id

    def pay(self, sale_id, method, approved=True):
        with obtener_conexion() as connection:
            sale = connection.execute("SELECT total FROM ventas WHERE id_venta = ?", (sale_id,)).fetchone()
            payment_id = registrar_pago(connection, sale_id, method, sale[0])
            if approved:
                aprobar_pago(connection, payment_id)
            else:
                rechazar_pago(connection, payment_id)
            connection.commit()
            return payment_id

    def cancel(self, sale_id):
        with obtener_conexion() as connection:
            cancelar_venta(connection, sale_id)
            connection.commit()

    def admin_summary(self):
        with obtener_conexion() as connection:
            return resumen_admin(connection)

    def products(self):
        with obtener_conexion() as connection:
            return obtener_productos(connection)

    def associate(self, uid, product_id):
        with obtener_conexion() as connection:
            result = asociar_etiqueta(connection, uid, product_id)
            connection.commit()
            return result

    def admin_data(self, kind, value=None):
        with obtener_conexion() as connection:
            if kind == "ventas": return obtener_ventas(connection)
            if kind == "detalle_venta": return obtener_detalle_venta(connection, value)
            if kind == "eventos": return obtener_eventos_admin(connection, value)
            if kind == "dispositivos": return obtener_dispositivos(connection)
            if kind == "etiquetas": return obtener_etiquetas(connection)
            raise ValueError(f"Vista administrativa desconocida: {kind}")

    def set_tag_state(self, tag_id, state):
        with obtener_conexion() as connection:
            cambiar_estado_etiqueta(connection, tag_id, state)
            connection.commit()

    def adjust_stock(self, product_id, quantity, adjustment):
        with obtener_conexion() as connection:
            result = ajustar_inventario(connection, product_id, quantity, adjustment)
            connection.commit()
            return result

    def create_product(self, code, name, price, stock, minimum):
        with obtener_conexion() as connection:
            result = crear_producto(connection, code, name, price, stock, minimum)
            connection.commit()
            return result

    def update_product(self, product_id, name, price, minimum):
        with obtener_conexion() as connection:
            actualizar_producto(connection, product_id, name, price, minimum)
            connection.commit()

    def deactivate_product(self, product_id):
        with obtener_conexion() as connection:
            desactivar_producto(connection, product_id)
            connection.commit()


def _device(connection, code):
    row = connection.execute("SELECT id_dispositivo FROM dispositivos WHERE codigo_dispositivo = ?", (code,)).fetchone()
    if not row:
        raise sqlite3.IntegrityError(f"Dispositivo no configurado: {code}")
    return row[0]
