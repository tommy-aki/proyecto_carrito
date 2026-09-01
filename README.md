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

Se requiere Python 3.10 o superior y pyserial:

```text
pip install -r requirements.txt
python -m database.seed
python -m database.migrate
python logica_tabla.py --simular
python logica_tabla.py
```

`carrito.db` se genera en `data/`, sin depender del directorio desde el que se ejecute Python. La inicializacion es idempotente. El seed usa `DEMO_HASH_NO_USAR_EN_PRODUCCION`: no es una contrasena real y debe sustituirse por autenticacion real.

En Windows cambia `PUERTO` en `logica_tabla.py` a `COM3` o `COM4`. En Linux puede mantenerse `/dev/ttyUSB0`.

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

Flujo previsto:

```text
RFID --+                         +--> Carrito
       +--> Python -> SQLite ---+
Camara+                          +--> Venta/Pago
```

Las lecturas validas agregan o retiran unidades y recalculan el total. Las desconocidas se registran como eventos no procesados sin cerrar el programa. El inventario solo se descuenta dentro de `aprobar_pago`, junto con detalle de venta y movimiento de inventario, en una unica transaccion.

## Tablas

`usuarios`, `productos`, `etiquetas_rfid`, `modelos_vision`, `clases_vision`, `dispositivos`, `sesiones_compra`, `detalle_carrito`, `eventos_deteccion`, `ventas`, `detalle_venta`, `pagos` y `movimientos_inventario`.