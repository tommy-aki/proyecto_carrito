# Estabilización y comparación de visión

Fecha de evaluación: 5 de agosto de 2026.

## Diagnóstico inicial

La implementación anterior ejecutaba YOLO cada dos frames dentro del mismo bucle
que capturaba la webcam. Un frame de inferencia se mostraba anotado, pero el siguiente
frame de captura se enviaba crudo y eliminaba visualmente las cajas. Cada inferencia
también reemplazaba de inmediato la lista de clases/confianza. No había estado entre
inferencias, límites basados en tiempo, confirmación, suavizado ni histéresis.

## Diseño aplicado

- `CameraWorker` captura y publica video con un máximo de 30 FPS.
- `InferenceWorker` consume únicamente el frame más reciente con un máximo de 8 FPS.
- Ambos viven en `QThread` independientes; una inferencia lenta no detiene la captura.
- La lista de detecciones confirmadas se emite con un máximo de 4 actualizaciones/s.
- Una clase nueva necesita 3 detecciones consecutivas con confianza mínima de 0.60.
- Una clase confirmada puede mantenerse con confianza de 0.45.
- Una pérdida conserva caja y confianza suavizada durante 700 ms.
- La confianza visible usa EMA: `smooth = 0.30 * raw + 0.70 * previous`.
- El dibujo usa siempre el último estado estable, no `result.plot()` de un solo frame.
- Verde indica una detección observada; ámbar y “retenida” indican tolerancia temporal.
- El buffer de frames conserva un solo valor para evitar latencia acumulada.

Los logs incluyen cada detección cruda, confianza cruda, decisión del estabilizador,
confianza suavizada y motivo (`candidate`, `confirmed`, `maintained`, `held`,
`discarded` o `expired`).

## Entorno confirmado

| Componente | Versión |
| --- | --- |
| Python | 3.12.10 |
| Ultralytics | 8.4.115 |
| PyTorch | 2.13.0+cpu |
| OpenCV | 4.14.0 |
| PySide6 | 6.11.1 |
| Dispositivo PyTorch | CPU; CUDA no disponible |

No se reinstaló PyTorch, no se cambió CUDA y no se recreó el entorno virtual.
Ultralytics 8.4.115 cargó e infirió correctamente con `yolo26n.pt`.

## Comparación controlada

Condiciones idénticas para ambos modelos:

- Webcam índice 0.
- Resolución real y solicitada: 1280×720.
- 30 segundos por modelo, después de 3 inferencias de warm-up.
- Captura objetivo: 30 FPS.
- Inferencia objetivo: máximo 8 FPS.
- Actualización de texto objetivo: máximo 4 FPS.
- Entrada YOLO: 640 px.
- Aceptación: 0.60; retención: 0.45.
- Confirmación: 3; tolerancia: 700 ms; EMA alpha: 0.30.
- Dispositivo: CPU.

| Métrica | YOLO11n | YOLO26n |
| --- | ---: | ---: |
| FPS real de captura | 30.07 | 30.03 |
| FPS real de inferencia | 8.03 | 8.03 |
| Latencia promedio | 48.0 ms | 52.8 ms |
| Latencia P95 | 55.5 ms | 70.4 ms |
| Detecciones crudas | 25 | 201 |
| Actualizaciones UI con detección confirmada | 0 | 86 |
| Cambios de conjunto de clases UI | 0 | 10 |
| Estabilidad de clases UI | No comparable | 90.2% |
| Errores | Ninguno | Ninguno |

El 100% matemático que produciría YOLO11n al no cambiar nunca de firma no representa
calidad: no generó ninguna actualización confirmada en esa escena. YOLO26n fue 4.8 ms
más lento en promedio, pero sostuvo el máximo configurado de 8 inferencias/s, mantuvo
la captura fluida y produjo muchas más detecciones útiles sin errores.

## Decisión

`yolo26n.pt` queda como modelo predeterminado porque funcionó con el entorno actual,
cumplió la frecuencia objetivo y ofreció resultados de detección claramente mejores
en la prueba de la laptop. `yolo11n.pt` se conserva como fallback automático y puede
forzarse con `CARRITO_SMART_YOLO_MODEL`.

La comparación evalúa integración y comportamiento en una escena de webcam, no
precisión científica del modelo. Una evaluación de precisión requeriría un conjunto
etiquetado representativo del catálogo.
