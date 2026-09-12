# Carrito Smart

> Aplicación de escritorio del equipo, independiente del programa de la raíz.
> Para instalar desde este repositorio y revisar las limitaciones conocidas de
> esta publicación, consulte [la guía del equipo](docs/REPOSITORIO_GRUPO.md).
> Verificación del 2026-09-11: **121 pruebas aprobadas, ninguna fallida**.
> Se retiró la pluma y se corrigió la asignación del umbral del chocolate.

Primer avance funcional de un carrito de compras inteligente. El prototipo combina
una interfaz de escritorio, inventario y ventas en SQLite, eventos RFID desde
Arduino por USB y detección en vivo con un modelo YOLO nano preentrenado.

## Funcionalidad incluida

- Webcam en vivo con cajas de detección YOLOE.
- Inferencia en un hilo de trabajo separado para no bloquear la interfaz.
- Lista de clases detectadas y porcentajes de confianza.
- YOLOE busca `plastic water bottle`, `aluminum soda can` y `packet of chocolate`
  sin entrenamiento personalizado.
- Validación conjunta: una aparición nueva confirmada, en cualquier zona de la
  imagen, debe coincidir con RFID de entrada del mismo producto dentro de 3 segundos.
- Botella corresponde a `CS-001`, lata a `CS-002` y chocolate a `CS-006`.
  Cada unidad requiere su propio UID y evidencia visual nueva no utilizada.
  Para añadir otra unidad del mismo tipo deben verse más unidades confirmadas
  que las ya registradas; una caja retenida no cuenta como visible.
- Para retirar basta `SALIDA:UID` de una unidad registrada: salida exclusivamente
  RFID, sin trayectoria visual ni espera de 700 ms, incluso si falla la cámara.
  Desaparecer de la imagen por cualquier borde o taparse no retira nada por sí solo.
- Carrito con producto, cantidad, precio, subtotal y total.
- Entrada y salida RFID por Arduino Serial, con reconexión y simulador integrado.
- Asociación persistente de cada UID RFID con un producto de SQLite.
- Protección contra entradas duplicadas y salidas sin entrada previa.
- Modo explícito de RFID simulado; requiere webcam para entradas, no para salidas.
- Pendientes RFID/discrepancias visibles; pago bloqueado hasta resolverlos.
- Detecciones solo de cámara: avisos informativos, sin agregar ni bloquear el pago;
  la evidencia caduca a los 3 segundos si no llega el RFID correspondiente.
- Catálogo e inventario persistentes en SQLite.
- Pago aprobado simulado con confirmación del usuario.
- Ticket digital en pantalla con productos, cantidades, subtotales y total pagado.
- Registro de venta y descuento de inventario en una sola transacción SQLite.
- Reversión completa si algún producto ya no tiene stock suficiente.
- Logs rotativos de detecciones, carrito, errores y pagos.
- Seis productos iniciales para la demostración.
  Chocolate comienza con 100 unidades y el cereal es el único producto sin stock.
  Los datos iniciales se insertan solamente si faltan; reiniciar no repone inventario.

## Requisitos

- Windows 10/11
- Python 3.12 o 3.13 de 64 bits
- Webcam
- Arduino Nano con lectores MFRC522 (opcional para usar el simulador)
- Conexión a Internet la primera vez que se descarguen YOLOE y su codificador de
  texto. Las ejecuciones posteriores reutilizan los archivos locales.

No se utiliza ni se entrena un modelo personalizado. `yoloe-26n-seg.pt` es el
modelo predeterminado y recibe tres textos de búsqueda para botella de agua, lata
de refresco y barra de chocolate. Si YOLOE o su descarga fallan, la aplicación vuelve automáticamente
a `yolo26n.pt` y después a `yolo11n.pt`. Los fallbacks reconocen la botella general,
pero no incluyen clases para latas ni barras de chocolate. La precisión de cada
producto y envoltura debe validarse con la webcam; configurar un texto no equivale
a entrenar con los productos físicos.

El texto del chocolate se eligió comparando el frente y reverso de la envoltura
Tutto proporcionada por el equipo. La comparación reproducible y sus limitaciones
están en [docs/CHOCOLATE_VISION.md](docs/CHOCOLATE_VISION.md).
La prueba posterior de webcam mostró lecturas de chocolate inferiores al umbral
general. Solo para chocolate se usa aceptación de 0.30 y retención de 0.25;
botella y lata conservan 0.45/0.25. Todas requieren tres lecturas consecutivas.
Es un ajuste de sensibilidad para la demo, no una garantía de precisión con
cualquier envoltura, iluminación u orientación.

## Instalación

Desde PowerShell, en la raíz del proyecto:

```powershell
.\setup.ps1
```

El script busca Python 3.12, crea `.venv` e instala el proyecto con sus dependencias.
También instala el codificador de texto oficial usado por YOLOE. Los pesos de
YOLOE y del codificador se descargan automáticamente al iniciar por primera vez.
La alternativa manual es:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Ejecución

```powershell
.\run.ps1
```

También puede iniciarse directamente:

```powershell
.\.venv\Scripts\python.exe -m carrito_smart
```

La primera ejecución crea automáticamente:

- `data/carrito_smart.db`: catálogo, inventario y ventas.
- `data/Ultralytics/`: configuración local de Ultralytics.
- `logs/carrito_smart.log`: registro rotativo de actividad.

## Guion de demostración

1. Abra la aplicación y espere el estado **Webcam y YOLO activos**.
2. Con Arduino, deje desmarcado **Modo de prueba sin Arduino** y espere conexión.
   Para simularlo, marque esa casilla; no se activa sola por una desconexión.
3. Con el producto inicialmente fuera de vista, registre RFID de entrada y
   muéstrelo a la cámara hasta confirmar tres lecturas dentro de los 3 segundos.
   También puede aparecer primero y leerse después. No necesita cruzar líneas.
4. Sin Arduino puede procesar `ENTRADA:4A3B2C1D` para una lata, pero debe hacer
   también una aparición nueva confirmada dentro de 3 segundos. Solo RFID no agrega.
5. Tape el producto: el rectángulo desaparece, pero la fila sigue en la tabla.
6. Para retirarlo, páselo por los lectores en dirección de salida (B→A)
   o simule `SALIDA:4A3B2C1D`. Se retira una unidad inmediatamente, aunque la
   cámara no lo vea. Repetir SALIDA del mismo UID no retira otra unidad.
7. Repita con otros productos, uno por uno. Pendientes RFID vencidos requieren
   repetir el paso completo. Una detección visual extra sin RFID solo deja un aviso:
   no agrega unidades ni bloquea el pago, incluso cuando vence su plazo.
8. Con productos confirmados y sin discrepancias, simule y confirme el pago.
   Solo entonces se registra la venta y se descuenta el inventario.
9. **Cancelar compra** descarta toda la sesión con confirmación; hay que vaciar
   físicamente el carrito antes de comenzar otra. No es una salida automática.


Si falla un sensor, se conservan los productos y se pausan entradas/pago.
Si solo falla la cámara, las salidas RFID siguen disponibles mientras el lector
esté conectado. Cierre otras aplicaciones que ocupen webcam o puerto serial.
Las reglas y casos de prueba están en [docs/SENSOR_FUSION.md](docs/SENSOR_FUSION.md).

## Pruebas

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Las pruebas cubren datos iniciales, cálculo del carrito, salida manual, descuento
posterior al pago, rollback de una venta inválida, extracción de detecciones,
protocolo/deduplicación RFID y construcción de la ventana en modo sin pantalla.
También cubren apariciones, oclusiones, múltiples instancias, concordancia temporal
de entrada, salidas solo RFID sin cámara, duplicados, desconexiones y cambios
durante el diálogo de pago.
Los avisos visuales tampoco cancelan un pago mientras está abierto su diálogo;
las lecturas RFID pendientes, cambios de productos y fallas de sensores sí lo hacen.

La configuración, protocolo y prueba física pendiente del Arduino están en
[`docs/RFID_INTEGRATION.md`](docs/RFID_INTEGRATION.md).

## Preparar el modelo de tres productos

La captura de datos para `cocacola_lata`, `pepsi_lata` y `doritos_bolsa` se
describe paso a paso en [training/README.md](training/README.md). El proyecto
incluye un extractor que convierte los videos en frames nítidos y elimina tomas
casi repetidas. El etiquetado, la revisión y el entrenamiento se realizan después
de recopilar los videos; el modelo actual no se reemplaza hasta validar el nuevo
`best.pt`.

## Configuración opcional

La aplicación acepta estas variables de entorno:

| Variable | Predeterminado | Uso |
| --- | --- | --- |
| `CARRITO_SMART_CAMERA` | `1` | Webcam externa del montaje actual; sobrescribible según el índice de OpenCV en cada PC |
| `CARRITO_SMART_CAMERA_WIDTH` | `1280` | Ancho solicitado a la webcam |
| `CARRITO_SMART_CAMERA_HEIGHT` | `720` | Alto solicitado a la webcam |
| `CARRITO_SMART_YOLO_MODEL` | `yoloe-26n-seg.pt` | Modelo principal o ruta a pesos |
| `CARRITO_SMART_FALLBACK_MODEL` | `yolo26n.pt` | Primer fallback si falla YOLOE |
| `CARRITO_SMART_SECONDARY_FALLBACK_MODEL` | `yolo11n.pt` | Último fallback configurable |
| `CARRITO_SMART_CAMERA_FPS` | `30` | Máximo de capturas/video por segundo |
| `CARRITO_SMART_INFERENCE_FPS` | `8` | Máximo de inferencias YOLO por segundo |
| `CARRITO_SMART_UI_UPDATE_FPS` | `4` | Máximo de actualizaciones del texto por segundo |
| `CARRITO_SMART_DETECTION_THRESHOLD` | `0.60` | Umbral para aceptar una clase nueva |
| `CARRITO_SMART_RETENTION_THRESHOLD` | `0.45` | Umbral para mantener una clase confirmada |
| `CARRITO_SMART_CONFIRMATION_COUNT` | `3` | Detecciones consecutivas antes de confirmar |
| `CARRITO_SMART_DETECTION_HOLD_MS` | `700` | Retención tras una pérdida temporal |
| `CARRITO_SMART_CONFIDENCE_EMA_ALPHA` | `0.30` | Alpha de la media móvil de confianza |
| `CARRITO_SMART_INFERENCE_IMAGE_SIZE` | `640` | Tamaño de entrada de YOLO |
| `CARRITO_SMART_VISION_AUTO_CART` | `1` | Habilita validación visual de entradas; en 0 bloquea entradas/pago, no salidas RFID |
| `CARRITO_SMART_VISION_BOTTLE_SKU` | `CS-001` | Producto asociado a la clase `bottle` |
| `CARRITO_SMART_VISION_SODA_CAN_SKU` | `CS-002` | Producto asociado a la lata de refresco |
| `CARRITO_SMART_VISION_CHOCOLATE_BAR_SKU` | `CS-006` | Producto asociado a la barra de chocolate |
| `CARRITO_SMART_YOLOE_WATER_BOTTLE_PROMPT` | `plastic water bottle` | Texto que YOLOE usa para buscar botellas |
| `CARRITO_SMART_YOLOE_SODA_CAN_PROMPT` | `aluminum soda can` | Texto que YOLOE usa para buscar latas |
| `CARRITO_SMART_YOLOE_CHOCOLATE_BAR_PROMPT` | `packet of chocolate` | Texto que YOLOE usa para buscar chocolate empacado |
| `CARRITO_SMART_YOLOE_DETECTION_THRESHOLD` | `0.45` | Umbral general YOLOE (botella/lata; chocolate tiene ajuste propio) |
| `CARRITO_SMART_YOLOE_RETENTION_THRESHOLD` | `0.25` | Retención general YOLOE (botella/lata) |
| `CARRITO_SMART_YOLOE_CHOCOLATE_DETECTION_THRESHOLD` | `0.30` | Umbral específico para confirmar chocolate |
| `CARRITO_SMART_YOLOE_CHOCOLATE_RETENTION_THRESHOLD` | `0.25` | Umbral específico para mantener chocolate |
| `CARRITO_SMART_FUSION_WINDOW_MS` | `3000` | Concordancia de entrada y límite de antigüedad de eventos en cola; no espera visual para salir |
| `CARRITO_SMART_CROSSING_TOP_RATIO` | `0.25` | Legado: aceptado por compatibilidad, sin efecto en las salidas |
| `CARRITO_SMART_CROSSING_HYSTERESIS_RATIO` | `0.10` | Legado: aceptado por compatibilidad, sin efecto en las salidas |
| `CARRITO_SMART_CROSSING_EDGE_RATIO` | `0.06` | Legado: aceptado por compatibilidad, sin efecto en las salidas |
| `CARRITO_SMART_CROSSING_MATCH_DISTANCE` | `0.25` | Distancia máxima entre centros normalizados para asociar un track |
| `CARRITO_SMART_VISION_STALE_MS` | `2500` | Pausa entradas/pago sin inferencias frescas; no pausa salidas RFID |
| `CARRITO_SMART_RFID_ENABLED` | `1` | Activa el lector Serial del Arduino |
| `CARRITO_SMART_RFID_PORT` | `AUTO` | Puerto COM explícito o autodetección |
| `CARRITO_SMART_RFID_BAUD_RATE` | `9600` | Velocidad usada por el firmware actual |
| `CARRITO_SMART_RFID_RECONNECT_MS` | `2000` | Espera antes de reconectar |
| `CARRITO_SMART_DATA_DIR` | `data` | Directorio de SQLite/configuración |
| `CARRITO_SMART_LOG_DIR` | `logs` | Directorio de logs |

Ejemplo para una segunda webcam:

```powershell
$env:CARRITO_SMART_CAMERA = "1"
.\run.ps1
```

## Arquitectura

```text
carrito_smart/
├── app.py             # arranque y composición
├── main_window.py     # interfaz PySide6
├── vision.py          # workers separados de webcam e inferencia
├── detection_stabilizer.py # confirmación, EMA, histéresis y retención
├── rfid.py            # protocolo, procesamiento y worker Serial
├── cart.py            # reglas del carrito
├── database.py        # esquema, consultas y transacción de venta
├── models.py          # modelos de dominio
├── config.py          # configuración por entorno
└── logging_config.py  # logs de consola y archivo
```

La UI no actualiza inventario directamente. El pago llama a `complete_sale`, que
abre `BEGIN IMMEDIATE`, vuelve a validar precio/stock, registra encabezado y detalle,
descuenta cada existencia y finalmente hace `COMMIT`. Cualquier error ejecuta
`ROLLBACK`.

## Estabilidad de visión y benchmark

La captura y la inferencia se ejecutan en dos `QThread` independientes y comparten
solamente el frame más reciente, sin una cola que acumule retraso. El video puede
mantener 30 FPS aunque YOLO opere a 8 FPS. Las cajas se dibujan en cada frame desde
el último estado confirmado, mientras que la lista de texto se limita a 4 FPS.

Para repetir la comparación con la misma cámara y configuración:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_vision.py `
  --duration 30 --models yolo11n.pt yolo26n.pt
```

El resultado se guarda en `logs/benchmarks/`. Las condiciones, métricas obtenidas y
la decisión de modelo están documentadas en
[`docs/VISION_STABILITY.md`](docs/VISION_STABILITY.md).
