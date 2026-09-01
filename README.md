# Carrito de Compras Autonomo

Prototipo que recibe lecturas RFID desde Arduino por Serial y mantiene el carrito en SQLite. El CSV original se conserva como respaldo y ya no es la fuente principal.

## Estructura

- `database/schema.sql`: las 13 tablas, restricciones, claves foraneas e indices.
- `database/database.py`: rutas independientes del directorio actual, conexiones y `foreign_keys`.
- `database/operations.py`: carrito, sesiones, ventas y pagos transaccionales.
- `database/seed.py`: usuario, dispositivos y productos RFID de demostracion.
- `database/migrate.py`: migracion segura de UIDs del CSV a productos temporales de precio cero.
- `data/carrito.db`: base creada automaticamente.
- `logica_tabla.py`: lector Serial y simulacion local.
- `lector/lector.ino`: firmware Arduino existente, sin cambios.

## Instalacion y ejecucion

Se requiere Python 3.10 o superior. Las dependencias son `pyserial` y `PySide6` (OpenCV es opcional y no es necesaria para abrir la aplicación):

```text
pip install -r requirements.txt
py -m database.seed
py -m database.migrate
py logica_tabla.py --simular
py -m frontend.main --demo
py -m frontend.main
```

`carrito.db` se genera en `data/`, sin depender del directorio desde el que se ejecute Python. La inicializacion es idempotente. El seed usa `DEMO_HASH_NO_USAR_EN_PRODUCCION`: no es una contrasena real y debe sustituirse por autenticacion real.

El frontend detecta los puertos COM disponibles mediante `serial.tools.list_ports`. En modo normal intenta conectar el primero disponible y, si no encuentra Arduino, permanece abierto en estado desconectado. La clase `RfidWorker` lee Serial en un `QThread`, nunca en el hilo de la interfaz.

Desde el panel de control se puede volver al modo cliente. El panel distingue `C-01 FÍSICO`, que es la única sesión consultada en SQLite, de `C-02`, `C-03` y `C-04 DEMO`, que son representaciones en memoria y no crean sesiones falsas.

La migracion elige la alternativa A: cada UID no conocido se asocia a `MIGRADO-<UID>`, con nombre identificable y precio `0`. No inventa precio, stock ni codigo comercial; esos datos deben completarse posteriormente. `inventario.csv` no se borra.

## Inspeccion SQLite

Con el ejecutable `sqlite3`:

```sql
SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name;
PRAGMA foreign_keys;
SELECT * FROM eventos_deteccion ORDER BY id_evento;
SELECT * FROM detalle_carrito;
SELECT id_sesion, total_calculado FROM sesiones_compra;
```

Flujo actual:

```text
Arduino -> Serial -> Python -> SQLite
```

Flujo de la aplicación:

```text
Arduino/RFID -> RfidWorker -> CartService -> operations.py -> SQLite -> PySide6
```

El modo `--demo` no requiere Arduino ni cámara: los botones de demostración disparan el mismo procesamiento RFID contra la sesión real de C-01. El pago es simulado, pero recorre `registrar_pago`, `aprobar_pago` y `cancelar_venta`; solo un pago aprobado descuenta inventario. La pantalla de salida es una autorización de software, porque no existe una puerta física.

El prototipo tiene una única computadora y una única cámara asociada a C-01. `CameraService` deja preparada la detección y el preview opcional, pero todavía no hay modelo de visión artificial: los eventos de visión son demostraciones visuales y no se guardan como detecciones reales.

Flujo previsto:

```text
RFID --+                         +--> Carrito
       +--> Python -> SQLite ---+
Camara+                          +--> Venta/Pago
```

Las lecturas validas agregan o retiran unidades y recalculan el total. Las desconocidas se registran como eventos no procesados sin cerrar el programa. El inventario solo se descuenta dentro de `aprobar_pago`, junto con detalle de venta y movimiento de inventario, en una unica transaccion.

## Tablas

`usuarios`, `productos`, `etiquetas_rfid`, `modelos_vision`, `clases_vision`, `dispositivos`, `sesiones_compra`, `detalle_carrito`, `eventos_deteccion`, `ventas`, `detalle_venta`, `pagos` y `movimientos_inventario`.