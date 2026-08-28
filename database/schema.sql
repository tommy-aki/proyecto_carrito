PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario INTEGER PRIMARY KEY AUTOINCREMENT, nombre VARCHAR(120) NOT NULL,
    correo VARCHAR(150) NOT NULL UNIQUE, contrasena_hash VARCHAR(255) NOT NULL,
    rol TEXT NOT NULL DEFAULT 'OPERADOR' CHECK (rol IN ('ADMINISTRADOR','OPERADOR')),
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1)), fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, ultimo_acceso DATETIME
);
CREATE TABLE IF NOT EXISTS productos (
    id_producto INTEGER PRIMARY KEY AUTOINCREMENT, codigo_producto VARCHAR(40) NOT NULL UNIQUE,
    nombre VARCHAR(150) NOT NULL, descripcion TEXT, precio NUMERIC NOT NULL CHECK (precio >= 0),
    stock_actual INTEGER NOT NULL DEFAULT 0 CHECK (stock_actual >= 0), stock_minimo INTEGER NOT NULL DEFAULT 0 CHECK (stock_minimo >= 0),
    unidad_medida VARCHAR(30) NOT NULL DEFAULT 'unidad', metodo_identificacion TEXT NOT NULL CHECK (metodo_identificacion IN ('RFID','VISION','AMBOS')),
    activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1)), fecha_creacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, fecha_actualizacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_productos_nombre ON productos(nombre);
CREATE INDEX IF NOT EXISTS idx_productos_stock ON productos(stock_actual);
CREATE TABLE IF NOT EXISTS etiquetas_rfid (
    id_etiqueta INTEGER PRIMARY KEY AUTOINCREMENT, id_producto INTEGER NOT NULL, uid VARCHAR(50) NOT NULL UNIQUE,
    tipo_tag VARCHAR(60) NOT NULL DEFAULT 'MIFARE 13.56 MHz', estado TEXT NOT NULL DEFAULT 'ACTIVA' CHECK (estado IN ('ACTIVA','INACTIVA','EXTRAVIADA')),
    fecha_registro DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, observaciones TEXT, FOREIGN KEY (id_producto) REFERENCES productos(id_producto)
);
CREATE INDEX IF NOT EXISTS idx_etiquetas_producto ON etiquetas_rfid(id_producto);
CREATE TABLE IF NOT EXISTS modelos_vision (
    id_modelo INTEGER PRIMARY KEY AUTOINCREMENT, nombre VARCHAR(120) NOT NULL, version VARCHAR(30) NOT NULL, ruta_archivo VARCHAR(255) NOT NULL,
    fecha_entrenamiento DATETIME, precision_validacion NUMERIC, activo INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0,1)), observaciones TEXT,
    CONSTRAINT uq_modelo_version UNIQUE(nombre, version)
);
CREATE TABLE IF NOT EXISTS clases_vision (
    id_clase_vision INTEGER PRIMARY KEY AUTOINCREMENT, id_modelo INTEGER NOT NULL, id_producto INTEGER NOT NULL, nombre_clase VARCHAR(100) NOT NULL,
    umbral_confianza NUMERIC NOT NULL DEFAULT 70.00 CHECK (umbral_confianza BETWEEN 0 AND 100), activa INTEGER NOT NULL DEFAULT 1 CHECK (activa IN (0,1)),
    FOREIGN KEY (id_modelo) REFERENCES modelos_vision(id_modelo), FOREIGN KEY (id_producto) REFERENCES productos(id_producto),
    CONSTRAINT uq_modelo_clase UNIQUE(id_modelo, nombre_clase), CONSTRAINT uq_modelo_producto UNIQUE(id_modelo, id_producto)
);
CREATE TABLE IF NOT EXISTS dispositivos (
    id_dispositivo INTEGER PRIMARY KEY AUTOINCREMENT, codigo_dispositivo VARCHAR(40) NOT NULL UNIQUE, nombre VARCHAR(100) NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('ARDUINO','LECTOR_RFID','CAMARA','COMPUTADORA')), identificador_tecnico VARCHAR(100), ubicacion VARCHAR(150),
    estado TEXT NOT NULL DEFAULT 'ACTIVO' CHECK (estado IN ('ACTIVO','INACTIVO','ERROR')), fecha_registro DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, ultima_comunicacion DATETIME, observaciones TEXT
);
CREATE TABLE IF NOT EXISTS sesiones_compra (
    id_sesion INTEGER PRIMARY KEY AUTOINCREMENT, id_usuario INTEGER NOT NULL, codigo_sesion VARCHAR(50) NOT NULL UNIQUE,
    estado TEXT NOT NULL DEFAULT 'ABIERTA' CHECK (estado IN ('ABIERTA','PAGANDO','FINALIZADA','CANCELADA')), fecha_inicio DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_fin DATETIME, total_calculado NUMERIC NOT NULL DEFAULT 0.00, observaciones TEXT, FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario)
);
CREATE INDEX IF NOT EXISTS idx_sesiones_estado ON sesiones_compra(estado);
CREATE INDEX IF NOT EXISTS idx_sesiones_fecha ON sesiones_compra(fecha_inicio);
CREATE TABLE IF NOT EXISTS detalle_carrito (
    id_detalle_carrito INTEGER PRIMARY KEY AUTOINCREMENT, id_sesion INTEGER NOT NULL, id_producto INTEGER NOT NULL, cantidad INTEGER NOT NULL DEFAULT 1 CHECK (cantidad > 0),
    precio_unitario NUMERIC NOT NULL CHECK (precio_unitario >= 0), fecha_agregado DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, fecha_actualizacion DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (id_sesion) REFERENCES sesiones_compra(id_sesion), FOREIGN KEY (id_producto) REFERENCES productos(id_producto), CONSTRAINT uq_sesion_producto UNIQUE(id_sesion, id_producto)
);
CREATE TABLE IF NOT EXISTS eventos_deteccion (
    id_evento INTEGER PRIMARY KEY AUTOINCREMENT, id_sesion INTEGER NOT NULL, id_dispositivo INTEGER NOT NULL, id_producto INTEGER, id_etiqueta INTEGER, id_clase_vision INTEGER,
    origen TEXT NOT NULL CHECK (origen IN ('RFID','VISION','MANUAL')), direccion TEXT NOT NULL DEFAULT 'PENDIENTE' CHECK (direccion IN ('ENTRADA','SALIDA','PENDIENTE','IGNORADA')),
    valor_detectado VARCHAR(150), confianza NUMERIC, procesado INTEGER NOT NULL DEFAULT 0 CHECK (procesado IN (0,1)), fecha_evento DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, mensaje TEXT,
    FOREIGN KEY (id_sesion) REFERENCES sesiones_compra(id_sesion), FOREIGN KEY (id_dispositivo) REFERENCES dispositivos(id_dispositivo), FOREIGN KEY (id_producto) REFERENCES productos(id_producto),
    FOREIGN KEY (id_etiqueta) REFERENCES etiquetas_rfid(id_etiqueta), FOREIGN KEY (id_clase_vision) REFERENCES clases_vision(id_clase_vision)
);
CREATE INDEX IF NOT EXISTS idx_eventos_sesion ON eventos_deteccion(id_sesion);
CREATE INDEX IF NOT EXISTS idx_eventos_producto ON eventos_deteccion(id_producto);
CREATE INDEX IF NOT EXISTS idx_eventos_fecha ON eventos_deteccion(fecha_evento);
CREATE INDEX IF NOT EXISTS idx_eventos_procesados ON eventos_deteccion(id_sesion, procesado);
CREATE TABLE IF NOT EXISTS ventas (
    id_venta INTEGER PRIMARY KEY AUTOINCREMENT, id_sesion INTEGER NOT NULL UNIQUE, numero_venta VARCHAR(50) NOT NULL UNIQUE, subtotal NUMERIC NOT NULL,
    descuento NUMERIC NOT NULL DEFAULT 0.00, impuesto NUMERIC NOT NULL DEFAULT 0.00, total NUMERIC NOT NULL, estado TEXT NOT NULL DEFAULT 'PENDIENTE' CHECK (estado IN ('PENDIENTE','PAGADA','CANCELADA')),
    fecha_venta DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, observaciones TEXT, FOREIGN KEY (id_sesion) REFERENCES sesiones_compra(id_sesion)
);
CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha_venta);
CREATE INDEX IF NOT EXISTS idx_ventas_estado ON ventas(estado);
CREATE TABLE IF NOT EXISTS detalle_venta (
    id_detalle_venta INTEGER PRIMARY KEY AUTOINCREMENT, id_venta INTEGER NOT NULL, id_producto INTEGER NOT NULL, cantidad INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario NUMERIC NOT NULL CHECK (precio_unitario >= 0), subtotal NUMERIC NOT NULL CHECK (subtotal >= 0), FOREIGN KEY (id_venta) REFERENCES ventas(id_venta),
    FOREIGN KEY (id_producto) REFERENCES productos(id_producto), CONSTRAINT uq_venta_producto UNIQUE(id_venta, id_producto)
);
CREATE TABLE IF NOT EXISTS pagos (
    id_pago INTEGER PRIMARY KEY AUTOINCREMENT, id_venta INTEGER NOT NULL, metodo TEXT NOT NULL CHECK (metodo IN ('TARJETA_SIMULADA','QR_SIMULADO','EFECTIVO_SIMULADO')),
    monto NUMERIC NOT NULL CHECK (monto >= 0), estado TEXT NOT NULL DEFAULT 'PENDIENTE' CHECK (estado IN ('PENDIENTE','APROBADO','RECHAZADO','ANULADO')),
    referencia VARCHAR(100), codigo_autorizacion VARCHAR(100), fecha_solicitud DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, fecha_respuesta DATETIME, mensaje_respuesta TEXT,
    FOREIGN KEY (id_venta) REFERENCES ventas(id_venta)
);
CREATE INDEX IF NOT EXISTS idx_pagos_venta ON pagos(id_venta);
CREATE INDEX IF NOT EXISTS idx_pagos_estado ON pagos(estado);
CREATE TABLE IF NOT EXISTS movimientos_inventario (
    id_movimiento INTEGER PRIMARY KEY AUTOINCREMENT, id_producto INTEGER NOT NULL, id_venta INTEGER, id_usuario INTEGER, tipo TEXT NOT NULL CHECK (tipo IN ('VENTA','DEVOLUCION','AJUSTE_ENTRADA','AJUSTE_SALIDA')),
    cantidad INTEGER NOT NULL CHECK (cantidad > 0), stock_anterior INTEGER NOT NULL, stock_nuevo INTEGER NOT NULL, motivo VARCHAR(255), fecha_movimiento DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (id_producto) REFERENCES productos(id_producto), FOREIGN KEY (id_venta) REFERENCES ventas(id_venta), FOREIGN KEY (id_usuario) REFERENCES usuarios(id_usuario)
);
CREATE INDEX IF NOT EXISTS idx_movimientos_producto ON movimientos_inventario(id_producto);
CREATE INDEX IF NOT EXISTS idx_movimientos_fecha ON movimientos_inventario(fecha_movimiento);