# Entrada RFID + webcam; salida exclusivamente RFID

Actualización del 2026-09-10: se conserva la entrada por aparición nueva + RFID
y se elimina el requisito de salida visual superior. La oclusión impide deducir
con fiabilidad si un objeto salió; el UID y la dirección confirmada por el Arduino
son ahora la única autoridad de salida. No se entrenó ni cambió YOLOE, Python,
PyTorch, CUDA, el entorno virtual o el firmware Arduino.

Ajuste de pago del mismo día: la cámara sin RFID genera avisos informativos,
no discrepancias bloqueantes. Se conserva la validación doble para agregar.

## Regla de compra

Una unidad se registra solo si un UID conocido emite ENTRADA y coincide con una
aparición visual nueva confirmada del mismo tipo de producto. Para retirarla basta
SALIDA de ese UID presente, sin espera ni confirmación de webcam. La etiqueta
identifica la unidad; la visión valida el tipo en la entrada, no la marca ni el UID.

| Señales | Resultado |
| --- | --- |
| ENTRADA RFID + entrada visual concordante | Agregar una unidad si hay stock |
| SALIDA RFID de UID presente | Retirar exactamente una unidad; no requiere webcam |
| SALIDA RFID repetida, desconocida o de UID no presente | No retirar nada ni descontar otra unidad |
| Solo entrada visual, sin RFID | Aviso no bloqueante; no agregar |
| ENTRADA RFID sin confirmación visual o con clase distinta | Pendiente RFID bloqueante; no agregar |
| Producto oculto o desaparición por cualquier borde sin SALIDA RFID | Conservar tabla aunque desaparezca la caja |
| Asociación ambigua entre varias unidades | No adivinar; repetir de una en una |
| Cámara desconectada o inferencia sin frames frescos | Pausar entradas/pago; permitir salidas con RFID disponible |
| RFID desconectado en modo real | Pausar entradas/salidas/pago; conservar tabla |

El plazo de concordancia de ENTRADA es 3000 ms, en ambos órdenes. Cada evento visual se consume una
sola vez y las lecturas RFID repetidas no aumentan cantidades ni extienden el
plazo. Un pendiente RFID vencido pasa a discrepancia y bloquea el pago; no se combina
con evidencia nueva. Un paso nuevo completo del mismo UID/producto/dirección
resuelve esa discrepancia. Con múltiples discrepancias hay que resolver cada
una; no basta con validar otro producto. Un UID desconocido debe registrarse y
volverse a pasar. Si se perdió el estado físico de la compra, cancelar la sesión
completa y vaciar físicamente el carrito es la recuperación explícita disponible.

La evidencia solo visual NO bloquea el pago, tampoco durante sus 3 segundos de
espera por RFID. Si vence, se elimina del emparejamiento y queda un aviso por SKU
que dice «no agregado, no bloquea el pago». Una lectura RFID posterior necesita
una aparición nueva; no puede reutilizar la vencida. Los avisos se limpian al
validar ese producto, salir por RFID o resetear/cambiar el modo; no se convierten
en errores al desconectar un sensor. Las fallas de sensores sí siguen bloqueando
el pago mientras estén presentes. Un carrito vacío tampoco se puede pagar.

Los avisos no ocultan ni resuelven pendientes RFID, UIDs desconocidos o errores
de stock. Esta decisión permite pagar unidades confirmadas aunque YOLO reporte
un objeto adicional por error; también significa que un objeto real sin etiqueta
solo generará un aviso y no impedirá el pago. No sustituye el control físico RFID.

Las salidas no esperan un evento visual ni vencen por falta de cámara. Se mantiene
la protección contra eventos seriales entregados con más de 3 s de antigüedad y
contra mensajes anteriores al cambio de sesión/modo o desconexión RFID; repetir
el paso si se descartan. Una falla de visión NO invalida una SALIDA ya recibida
que sigue fresca en la cola. Una salida válida tampoco queda bloqueada por
pendientes/discrepancias de otras entradas, ni los borra para habilitar el pago.

Si SALIDA llega cuando ENTRADA de ese UID sigue pendiente, se anula ese pendiente
sin quitar unidades y se conserva una discrepancia para revisión/reintento. Así,
una imagen retrasada no agrega después un producto que ya salió. Tras una salida,
se descarta la evidencia visual anterior de ese SKU; una reentrada requiere una
lectura RFID y aparición nuevas. Se usa el SKU guardado al admitir el UID, aunque
su asociación en el catálogo cambie durante la compra.

La oclusión puede durar indefinidamente sin borrar una unidad confirmada. Tras
700 ms sin ver el objeto se elimina su caja/track de visión, no su estado RFID.

Una aparición solo puede validar una entrada si en ese frame hay más unidades
confirmadas y NO retenidas de la clase que unidades de ese SKU ya registradas.
Ejemplo: si hay una botella en la tabla y reaparece una sola botella después de
taparla, no se genera un pendiente nuevo ni se valida otro UID. Para añadir una
segunda botella se deben ver ambas durante la nueva confirmación. La misma
condición se verifica otra vez al emparejar el RFID. Es una protección conservadora
por cantidad, no reidentificación visual infalible: si unidades anteriores están
ocultas, hay que destaparlas antes de presentar una adicional del mismo tipo.

Una detección continua no vuelve a emitir entradas ni renueva el plazo vencido.
Para reintentar una entrada sin validar: retirar el producto de la vista durante
más de 700 ms y volver a presentarlo junto con una lectura RFID nueva. Al resetear
trayectorias por cambio de modo/sesión, los objetos observados en el primer frame
se toman como referencia y no como apariciones nuevas; comenzar con vista vacía.

## Apariciones visuales y uso

Las coordenadas se normalizan por el tamaño REAL del frame, antes de escalarlo
en la ventana. Se quitaron las guías del 25%/35% y la evaluación de trayectorias
de salida. La cámara solo confirma apariciones nuevas y muestra cajas suavizadas.

- Entrada: nueva instancia confirmada con tres lecturas consecutivas en cualquier
  parte de la imagen. Se emite una sola vez por track, al confirmarse, sin exigir
  movimiento descendente ni pasar por las guías.
- Salida: solo el evento RFID. Ningún movimiento ni pérdida de detección emite
  una salida visual. Tampoco se crean pendientes de salida que bloqueen el pago.
- Desplazamiento máximo para asociar observaciones: 0.25 en coordenadas
  normalizadas (distancia euclídea entre centros). Si dos asociaciones son
  posibles, no se fabrica una nueva aparición de esas trayectorias.

Mantener los productos reconocibles durante la confirmación.
Con inferencia limitada a 8/s, un paso demasiado rápido puede no aportar tres
lecturas. Empezar sosteniéndolos aproximadamente un segundo delante de la cámara;
el plazo de 3 s se mide entre el evento RFID y la evidencia visual, no entre
la primera aparición del objeto y su desaparición completa.

Esta integración está **pendiente de prueba con el montaje físico**.
No se garantiza identidad visual después de oclusión ni robustez a objetos
idénticos cruzando juntos. Para la demo: un producto por paso y UID distinto por
unidad. Puede haber varias unidades del mismo SKU en la tabla, cada una con su
propia validación. La asociación conservadora prefiere dejar pendiente un paso
ambiguo antes que cargarlo erróneamente. Para las salidas, todos los productos
deben pasar por ambos lectores en dirección B→A; una SALIDA falsa del firmware
no será corroborada por la cámara. No es un sistema antirrobo infalible.

## Prueba con Arduino

1. Cerrar Carrito Smart, Monitor Serial y cualquier programa que ocupe webcam/COM.
2. Conectar Arduino y webcam; ejecutar `./run.ps1` desde la raíz del proyecto.
3. Dejar **Modo de prueba sin Arduino** desmarcado y esperar cámara y RFID listos.
4. Con el producto fuera de vista, registrar ENTRADA y mostrarlo en cualquier
   zona de la imagen hasta confirmar tres detecciones dentro de 3 segundos.
   También se acepta cámara primero y RFID después. Debe aparecer una sola fila.
5. Taparlo durante dos segundos sin pasar los lectores. La caja desaparecerá;
   la fila y el total deben conservarse.
6. Con el producto aún oculto, registrar SALIDA con los lectores (B→A). La fila
   debe retirarse de inmediato, sin destaparlo ni cruzar un borde de la imagen.
7. Para ENTRADA, probar solo RFID y solo aparición visual por separado: ninguno
   debe agregar. RFID sin cámara bloquea el pago; cámara sin RFID solo muestra aviso.
8. Probar SALIDA repetida y de UID no presente: no deben quitar otras unidades.
   Probar desaparición por arriba/lateral sin RFID: no debe retirar nada. Repetir
   con botella, lata y chocolate. Con una unidad ya admitida, desconectar la cámara:
   SALIDA RFID debe seguir retirándola; entradas/pago permanecen pausados.
9. Resolver pendientes RFID antes de pagar. Los avisos visuales no exigen repetir
   una entrada ni agregar un producto inexistente. El pago mantiene su transacción SQLite;
   el inventario no se descuenta al detectar ni al añadir al carrito.

También hay una ventana de prueba con una copia temporal de la base real:

```powershell
.\.venv\Scripts\python.exe scripts\check_fusion_hardware.py --seconds 45
```

Abre webcam y COM reales, pero cualquier cambio/pago afecta solo a la copia.
Empieza a contar cuando ambos sensores están listos; si no lo están en 30 s,
cierra la prueba. Los logs y el informe se guardan en `logs/fusion_hardware/`.
Este comando quedó preparado, pero **no se ejecutó con hardware en esta etapa**
porque el usuario prefirió hacer la prueba después.

## Sin Arduino

Activar **Modo de prueba sin Arduino**. Mostrar la aparición nueva y, dentro del
plazo, procesar la trama del UID registrado en **Probar trama sin Arduino**.
Los botones de producto solo inyectan RFID cuando existe exactamente una etiqueta
elegible; con varias etiquetas hay que escribir el UID concreto. No simulan
visión ni agregan directamente. Al cambiar de modo se invalidan pendientes y
trayectorias, no se vacía la compra.
Para retirar basta procesar `SALIDA:UID` de una unidad presente; en ese caso
la webcam puede estar apagada.

## Arquitectura y verificación

- `vision_crossing.py`: seguimiento local por instancia, apariciones nuevas con
  cantidad visible. Ya no emite eventos de salida ni evalúa bordes.
  Reutiliza el estabilizador/EMA por track, sin nuevas dependencias ni pesos.
- `sensor_fusion.py`: empareja entradas por SKU y tiempo; procesa SALIDA RFID
  directamente para un UID presente. Mantiene pendientes/discrepancias RFID y avisos
  visuales separados. `blocked` solo considera RFID pendiente, errores y salud de sensores.
  Usa barreras separadas para no bloquear salidas cuando falla la visión. Solo aquí
  se realizan altas/bajas automáticas de la ventana mediante `CartService`.
- `vision.py`: procesa frames distintos en el hilo de inferencia. Los eventos
  se emiten por lote a frecuencia de inferencia, independientemente del texto
  limitado a 4/s. Solo dibuja cajas/texto en copias, nunca sobre la entrada de YOLO.
- `rfid.py`: conserva protocolo y worker serial, añade hora de recepción y
  señales de disponibilidad. `RfidEventProcessor` y `vision_cart.py` son código
  legado para compatibilidad; la ventana ya no los importa ni los usa.
- `main_window.py`: reúne ambos sensores en su hilo, controla pendientes,
  simulador explícito y pago. Revalida la compra tras el diálogo modal usando
  `payment_revision`, separado del refresco UI: los avisos y mensajes ignorados
  no cancelan la confirmación. Cambios en UID presentes, pendientes RFID, errores,
  sensores o sesión sí la invalidan, incluso si después se recupera el estado.
  Además compara los productos/cantidades/precios antes de cobrar.

Pasaron 119 pruebas automatizadas tras el ajuste de avisos/pago, incluyendo entradas
en ambos órdenes, salidas duplicadas/desconocidas, dos unidades del mismo SKU,
salida sin cámara, eventos en cola, discrepancias, reentrada y cambios durante el
pago. Se ejecutó
`scripts/smoke_sensor_fusion.py` con capturas verificadas de la ventana en
`logs/fusion_smoke/20260910-181810/`: pendiente, entrada confirmada sin movimiento,
objeto oculto pero presente, avisos visuales vigentes/vencidos con pago habilitado,
falla de cámara y salida confirmada solo por RFID.
Se usó SQLite temporal y no se modificó el stock real. Son pruebas de lógica/interfaz,
no de YOLO ni Arduino físicos. Las pruebas reales previas de chocolate no validan
por sí solas este nuevo flujo.

### Regresión del chocolate extra y el pago

El log del 2026-09-10 registra los tres productos admitidos a las 18:10:10/29/36.
Después reporta dos chocolates visibles a las 18:10:39.445, 18:10:51.460 y
18:11:04.214; el anterior vencimiento visual dejaba el botón deshabilitado.
La reproducción automatizada de esos eventos ahora conserva tres unidades
confirmadas, muestra el aviso CS-006 y mantiene el pago disponible antes/después
de vencer el plazo. Las pruebas de interfaz confirman el pago con un aviso,
descuentan solo una unidad confirmada de chocolate en SQLite temporal y evitan
un segundo cobro. También cubren avisos durante el diálogo, RFID sin validar,
carrito vacío y una falla transitoria de sensor durante la confirmación.

### Regresión de la botella real

En los logs del 2026-09-09, `ENTRADA:13DF1E14` llegó a las 18:31:03.344. YOLO
confirmó la botella a las 18:31:05.129 (1.785 s después), pero la regla anterior
no generó entrada porque su primera caja ya tenía el centro al 52% de altura.
Se reprodujeron sus cajas/confianzas y la pérdida intermedia en un test aislado.
Con la nueva regla confirma una unidad de CS-001 dentro del plazo, sin modificar
stock. Esta reproducción usa datos del log, no una nueva prueba física.

Configuración adicional (variables con prefijo `CARRITO_SMART_`):

| Sufijo | Valor inicial |
| --- | ---: |
| `FUSION_WINDOW_MS` | 3000 |
| `CROSSING_MATCH_DISTANCE` | 0.25 |
| `VISION_STALE_MS` | 2500 |

Los argumentos/variables antiguos `CROSSING_TOP_RATIO`,
`CROSSING_HYSTERESIS_RATIO` y `CROSSING_EDGE_RATIO` se aceptan por compatibilidad,
pero ya no afectan la operación. Se conserva el nombre `TopCrossingTracker` para
no romper importaciones existentes; su función actual es confirmar apariciones.

Se conservan cámara a 30 FPS solicitados, YOLO máximo 8/s, texto máximo 4/s,
confirmación de 3 lecturas, 700 ms de tolerancia y EMA 0.30. Umbrales YOLOE:
botella/lata 0.45/0.25; chocolate 0.30/0.25. COCO fallback conserva 0.60/0.45 y
no podrá validar lata/chocolate, porque no tiene esas clases.
