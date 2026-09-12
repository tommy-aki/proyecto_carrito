# Chocolate con envoltura: ajuste del texto YOLOE

Fecha: 2026-09-09.

Nota de integración posterior: se conservan el modelo, el texto y los umbrales
del chocolate documentados aquí, pero **detectar presencia ya no agrega ni
retira productos por sí solo**. La ventana usa ahora RFID + cruces visuales;
ver [SENSOR_FUSION.md](SENSOR_FUSION.md). Las pruebas históricas de este documento
validaban detección, no la nueva concordancia con RFID.

Se analizaron localmente las fotografías IMG_9236.jpeg (frente) e IMG_9237.jpeg
(reverso) de una barra Tutto ChocoLovers Mix Nueces Crocantes de 175 g. Ambas fotos
tienen 2268 × 4032 píxeles. Los originales no se modificaron ni se subieron a ningún
servicio. No se entrenó un modelo.

## Comparación

Se probaron 17 descripciones distintas, conservando `plastic water bottle` y
`aluminum soda can` como las otras dos clases. Todas las pruebas usaron
`yoloe-26n-seg.pt`, CPU, entrada de inferencia de 640 y `agnostic_nms=True`.
Se recargó el checkpoint para cada descripción para evitar reutilizar un
clasificador ya fusionado con otro texto. Los embeddings se calcularon en lote.

Confianza de la mejor caja que cubre el paquete completo:

| Texto | Frente | Reverso |
| --- | ---: | ---: |
| `chocolate bar` | 22.0% | Sin detección ≥5% |
| `wrapped chocolate bar` | 28.2% | 10.4% |
| `packaged chocolate bar` | 64.7% | 41.4% |
| `chocolate packaging` | 70.7% | 47.2% |
| `chocolate package` | 73.4% | 50.5% |
| `packet of chocolate` | 88.9% | 55.5% |

Se seleccionó `packet of chocolate` por obtener la mayor confianza mínima entre
las dos vistas. La clase continúa asociada a `CS-006 · Chocolate` mediante la
configuración de la ventana. En esta primera prueba los umbrales eran 0.45 para confirmar
y 0.25 para mantener, con tres detecciones consecutivas, retención de 700 ms y
EMA de 0.30. El estabilizador conserva la mejor caja por clase: las cajas
secundarias del mismo paquete no agregan más unidades al carrito.

El piso de 0.05 se utilizó solo en el diagnóstico para observar lecturas débiles;
no es el umbral del carrito. Los porcentajes son puntuaciones del modelo en estas
fotos, no medidas de precisión, probabilidades calibradas ni resultados en vivo.
El reverso tiene menos margen sobre el umbral. Se eligió el texto con estas mismas
dos fotos; aún falta validarlo con video nuevo de la webcam, cambios de luz,
distancia, rotación y objetos que no sean chocolate. Tampoco identifica la marca
ni puede verificar si una envoltura está vacía.

La verificación final usó el cargador real de la aplicación y `set_classes` con
las tres clases definitivas, obteniendo 88.9% y 55.5% de nuevo. Al repetir cada
foto tres veces, el estabilizador confirmó una sola clase y el carrito de prueba
agregó una unidad de CS-006; la retuvo ante una pérdida breve y la retiró después
de la tolerancia, sin cambiar inventario. Es una prueba de integración con fotos
estáticas, no una medición de estabilidad de la webcam. Tres recortes sin el
producto (pantalla/teclado, mesa y zona inferior) no produjeron detecciones desde
0.25. Pasaron las 33 pruebas existentes. La evidencia final está en
`20260909-165532/verification.json` y las imágenes `IMG_9236-verified.jpg` e
`IMG_9237-verified.jpg` de la carpeta de comparaciones.

## Repetir

Desde la raíz del proyecto, con rutas a las fotos originales:

```powershell
.\.venv\Scripts\python.exe scripts\compare_yoloe_prompts.py `
  C:\Users\excal\Downloads\IMG_9236.jpeg `
  C:\Users\excal\Downloads\IMG_9237.jpeg `
  --prompts "wrapped chocolate bar" "packet of chocolate"
```

El script guarda resultados JSON y visualizaciones de diagnóstico en
`logs/prompt_comparisons/<fecha-hora>/`. Estas salidas están ignoradas por Git.
Los informes de esta comparación son `20260909-165452/results.json` y
`20260909-165532/results.json`, dentro de esa carpeta.

La descripción se puede cambiar con
`CARRITO_SMART_YOLOE_CHOCOLATE_BAR_PROMPT`. Si esa variable ya está definida en la
terminal, tiene prioridad sobre el valor del código. Reiniciar la app carga la
descripción nueva.

## Ajuste posterior con webcam real

Al reiniciar con el texto nuevo, el usuario seguía sin ver el chocolate. El log
del 2026-09-09, alrededor de las 17:01, confirmó que se había cargado
`packet of chocolate` y la inferencia seguía activa. Las lecturas del objeto
solían estar en 0.25–0.40. Un pico de 0.587 fue seguido por 0.368, por lo que
se reiniciaba la confirmación que exigía tres lecturas consecutivas ≥0.45.
El log no permite atribuir la diferencia de confianza a una causa visual exacta:
las fotos de teléfono y la webcam son entradas diferentes.

Se añadió histéresis configurable por clase en `detection_stabilizer.py` y el
worker de `vision.py` aplica el ajuste solamente al texto configurado de chocolate:

| Clase/modelo | Aceptar | Mantener |
| --- | ---: | ---: |
| Chocolate en YOLOE | 0.30 | 0.25 |
| Botella/lata en YOLOE | 0.45 | 0.25 |
| Fallbacks COCO | 0.60 | 0.45 |

Se conservan confirmación de 3 lecturas, tolerancia de 700 ms, EMA 0.30,
captura solicitada a 30 FPS, inferencia limitada a 8/s y lista de detecciones
a 4 actualizaciones/s. El filtro previo de YOLO usa el menor umbral de retención
configurado para no eliminar una clase antes de estabilizarla. Los logs incluyen
los valores efectivos al iniciar y el umbral usado en cada decisión.

Con el usuario sosteniendo la misma barra frente a su webcam se ejecutó una
prueba de 12 segundos, seguida de otra de 12 segundos sin el producto. Ambas
usaron cámara 0 a 1280×720, `yoloe-26n-seg.pt`, CPU e `imgsz=640`:

| Prueba | Inferencias | FPS medido | Latencia media | Inferencias con chocolate confirmado |
| --- | ---: | ---: | ---: | ---: |
| Con barra | 95 | 7.90 | 85.5 ms | 93 (las dos primeras aún eran candidatas) |
| Sin barra | 94 | 7.81 | 104.4 ms | 0 |

La confianza cruda máxima con la barra fue 0.755. Se inspeccionó la captura de
confirmación: el rectángulo rodeaba el paquete completo, sostenido al revés.
En la prueba sin producto no hubo ni siquiera lecturas crudas de chocolate
por encima del filtro 0.25. Se usaron el capturador y cargador del proyecto,
con el mismo estabilizador y configuración; no se abrió la ventana del carrito
ni SQLite durante estas pruebas de hardware. El primer intento desde el entorno
aislado no pudo abrir la webcam; al ejecutarlo con acceso al dispositivo funcionó.

Evidencia local, ignorada por Git:

- `logs/chocolate_webcam/20260909-171035-810838/results.json` y `confirmed.jpg`.
- `logs/chocolate_webcam/20260909-171320-917718/results.json` y `first.jpg`.

No se entrenó ni cambió el modelo, Python, PyTorch, CUDA o el entorno virtual.
La prueba automatizada de integración verifica que lecturas 0.33/0.304/0.301
agregan solo una unidad de CS-006, la mantienen y luego la retiran sin descontar
stock. Hay pruebas para umbrales por clase, falsas candidatas aisladas,
retención/EMA, configuración y el filtro previo del worker.

Estas pruebas cortas no miden precisión general ni garantizan ausencia de falsos
positivos con otros objetos. Bajar el umbral aumenta la sensibilidad y también
ese riesgo; todavía deben validarse distancia, reverso, reflejos y oclusiones.
El texto y los umbrales son parámetros de integración, no entrenamiento.

Para repetir con la app cerrada y el producto colocado (o retirado):

```powershell
.\.venv\Scripts\python.exe scripts\check_chocolate_webcam.py --seconds 12 --label con-barra
.\.venv\Scripts\python.exe scripts\check_chocolate_webcam.py --seconds 12 --label sin-producto
```

Cada comando hace una prueba independiente: hay que cambiar la escena entre
ambos. Guarda capturas y resultados solo en `logs/chocolate_webcam/`; no toca
el carrito, RFID, inventario ni los archivos de pesos.
