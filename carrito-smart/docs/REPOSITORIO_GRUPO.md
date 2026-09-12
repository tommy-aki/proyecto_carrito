# Carrito Smart en el repositorio del equipo

Publicación: 2026-09-11. Código local copiado sin cambios funcionales a
`carrito-smart/`. Los archivos, firmware, historial y base de datos del proyecto
original de la raíz se mantienen intactos. No se fusionaron sus esquemas SQLite.

## Instalación en otra PC (PowerShell)

Requisitos: Windows, Python **3.12 de 64 bits**, Git e Internet para instalar las
dependencias y descargar los modelos al primer arranque. No se incluye un entorno
virtual ni una instalación de Python en el repositorio.

```powershell
git clone https://github.com/tommy-aki/proyecto_carrito.git
cd proyecto_carrito\carrito-smart
.\setup.ps1
.\run.ps1
```

Si PowerShell bloquea los scripts, habilitarlos solamente para esa terminal:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\setup.ps1
.\run.ps1
```

Si el repositorio ya está clonado y no tiene cambios locales, ejecutar `git pull`
en su raíz y entrar a `carrito-smart`. No hace falta volver a clonar.

## Webcam y Arduino

La cámara predeterminada es el índice `1`, elegido para la webcam externa del
montaje original. En una PC con una sola cámara puede ser necesario usar `0`:

```powershell
$env:CARRITO_SMART_CAMERA = "0"
.\run.ps1
```

Arduino se detecta automáticamente y usa 9600 baudios. Si hace falta seleccionar
el puerto, consultar el Administrador de dispositivos de Windows y configurarlo
antes de iniciar; `COM3` es solo un ejemplo:

```powershell
$env:CARRITO_SMART_RFID_PORT = "COM3"
.\run.ps1
```

**No ejecutar `logica_tabla.py` ni abrir el Monitor Serial al mismo tiempo que
Carrito Smart:** solo un programa debe abrir el puerto del Arduino. La aplicación
de escritorio recibe directamente `ENTRADA:UID` / `SALIDA:UID`. No necesita que el
programa de la raíz esté ejecutándose. El firmware existente no se cambió.

## Datos y etiquetas RFID

La base local, las ventas y el stock de la laptop no se publican. El primer
arranque crea `carrito-smart/data/carrito_smart.db` con los datos iniciales del
código; no utiliza ni modifica `data/carrito.db` del programa original.

Las asociaciones RFID guardadas únicamente en la base local deben registrarse
en la PC nueva. Con la app cerrada, estos comandos reproducen las asociaciones
verificadas en la laptop al publicar, sin importar sus ventas ni su inventario:

```powershell
.\.venv\Scripts\python.exe scripts\register_rfid_tag.py 03392214 CS-006
.\.venv\Scripts\python.exe scripts\register_rfid_tag.py 08001789 CS-006
.\.venv\Scripts\python.exe scripts\register_rfid_tag.py 080C0328 CS-001
.\.venv\Scripts\python.exe scripts\register_rfid_tag.py 12345678 CS-001
.\.venv\Scripts\python.exe scripts\register_rfid_tag.py 13DF1E14 CS-001
.\.venv\Scripts\python.exe scripts\register_rfid_tag.py 4A3B2C1D CS-002
.\.venv\Scripts\python.exe scripts\register_rfid_tag.py 73EA8A2E CS-006
.\.venv\Scripts\python.exe scripts\register_rfid_tag.py 7744C964 CS-006
.\.venv\Scripts\python.exe scripts\register_rfid_tag.py 8F9E0D1C CS-003
.\.venv\Scripts\python.exe scripts\register_rfid_tag.py B38A092F CS-002
```

`CS-001` = agua; `CS-002` = lata; `CS-006` = chocolate; `CS-003` = papas.
Cada UID representa una unidad física. Registrar una etiqueta no añade una unidad
al carrito: las entradas siguen requiriendo concordancia entre RFID y cámara.

## Verificación y limitación conocida de esta publicación

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Resultado antes de publicar: **115 aprobadas, 4 fallidas, 119 en total**. No se
modificaron las pruebas ni el código para disimular esos fallos.

El estado local incluye `ballpoint pen` antes de `packet of chocolate` en
`AppConfig.yoloe_prompts`. Esto añade una cuarta clase y desplaza el chocolate de
la posición 2 a la 3. `InferenceWorker._class_thresholds_for_model` todavía usa
`yoloe_prompts[2]`, por lo que el umbral específico del chocolate se aplica al
bolígrafo. Es un problema pendiente real: el chocolate queda con el umbral general
y puede ser más difícil confirmarlo. El bolígrafo no tiene un producto asociado
en el carrito. Las referencias a tres textos en el README describen la integración
anterior; no reflejan esa cuarta clase añadida en el estado local publicado.

Fallos observados:

- `tests/test_config.py::test_vision_defaults_are_centralized`
- `tests/test_vision.py::test_loader_configures_yoloe_with_three_product_prompts`
- `tests/test_vision.py::test_yoloe_and_coco_models_use_separate_thresholds`
- `tests/test_vision.py::test_worker_applies_chocolate_override_and_lowest_prediction_floor`

Esta publicación conserva el avance solicitado; no es una certificación de
funcionamiento completo ni una corrección de visión. No se hizo una nueva prueba
física con webcam/Arduino durante la subida.

## Qué queda fuera de Git

- `.venv/`, Python local, herramientas temporales y cachés.
- Bases de datos locales, ventas, logs y capturas de webcam.
- Pesos `.pt` y `mobileclip2_b.ts`, que se descargan al primer uso.
- Fotos originales, videos y datasets locales; sí se incluyen sus scripts y guías.
- Variables `.env` y credenciales.

La impresión térmica PT-210 quedó pausada y revertida por solicitud del equipo:
esta versión solo contiene el ticket digital existente, no impresión física.
