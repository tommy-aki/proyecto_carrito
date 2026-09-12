# Integración RFID con Arduino Nano

## Contrato observado

El firmware del repositorio del equipo trabaja a `9600` baudios y emite una
trama de texto terminada en salto de línea solamente cuando confirma un cruce:

```text
ENTRADA:4A3B2C1D
SALIDA:4A3B2C1D
```

El UID es hexadecimal en mayúsculas y sin separadores. Carrito Smart también
acepta minúsculas, espacios, `:` o `-` dentro del UID y lo normaliza antes de
consultarlo.

El archivo `lector.ino` de la raíz del repositorio Arduino contiene la lógica
real de dos lectores: A→B produce `ENTRADA` y B→A produce `SALIDA`. El archivo
`lector/lector.ino` genera entradas/salidas aleatorias cada cinco segundos y es
solo una demostración; no debe cargarse para la prueba física final.

## Comportamiento de Carrito Smart

Desde el ajuste del 2026-09-10, **entrada = RFID + cámara; salida = solo RFID**.
Una entrada requiere una aparición nueva confirmada en cualquier zona; ambas
señales deben coincidir por producto dentro de 3 segundos, en cualquier orden.
`SALIDA:UID` retira inmediatamente una unidad si ese UID está presente, sin
necesitar trayectoria, desaparición visual ni cámara disponible. Solo el lector
RFID debe estar conectado (o estar activo el modo explícito de simulación).
Véase [SENSOR_FUSION.md](SENSOR_FUSION.md).

- Busca automáticamente puertos descritos como Arduino, CH340/CH341, WCH,
  CP210 o USB Serial.
- Si hay un único puerto serial, lo utiliza aunque la descripción sea genérica.
- Lee en un `QThread`, por lo que la webcam y la interfaz no se bloquean.
- Reintenta la conexión cada dos segundos después de una desconexión.
- Ignora el texto diagnóstico que imprime el MFRC522 al arrancar.
- Una entrada con UID desconocido deja una discrepancia; no agrega productos.
- Ignora entradas duplicadas y salidas de UID desconocido/no presente; repetir
  SALIDA no puede quitar otra unidad del mismo producto.
- Los botones y el campo de simulación solo inyectan RFID; requieren webcam
  para agregar, no para retirar.
  Hay que activar explícitamente **Modo de prueba sin Arduino** para usarlos;
  el modo real no cambia automáticamente a simulación al perder la conexión.

Una detección visual sin RFID se guarda hasta 3 segundos para permitir cámara
primero y RFID después. Por sí sola solo muestra un aviso y no bloquea el pago,
ni siquiera al vencer; tampoco agrega productos. Una ENTRADA RFID pendiente o
vencida sin confirmación visual sí bloquea el pago hasta resolverla.

Si hay varios puertos y no se identifica el Arduino, fuerce el correcto antes de
iniciar la aplicación:

```powershell
$env:CARRITO_SMART_RFID_PORT = "COM4"
.\run.ps1
```

Puede deshabilitar temporalmente la búsqueda serial con:

```powershell
$env:CARRITO_SMART_RFID_ENABLED = "0"
.\run.ps1
```

## UIDs de demostración

| Trama | Producto de Carrito Smart |
| --- | --- |
| `4A3B2C1D` | Refresco en lata (`CS-002`) |
| `8F9E0D1C` | Bolsa de papas (`CS-003`) |
| `12345678` | Botella de agua (`CS-001`) |

Desde la interfaz se puede pegar una trama completa en **Probar trama sin
Arduino**. Una entrada repetida de la misma etiqueta no incrementa dos veces la
cantidad, porque cada UID representa una unidad física. La primera entrada
tampoco incrementa nada hasta coincidir con su aparición visual nueva.
Cada salida debe atravesar ambos lectores en dirección B→A. La cámara ya no
verifica ese sentido: si el firmware emite una SALIDA incorrecta de un UID
presente, el software lo retirará. Se debe probar la dirección y evitar que un
producto pueda salir físicamente sin pasar por los lectores.

## Registrar las etiquetas físicas

Después de leer el UID real en el monitor serial, asócielo al SKU del producto:

```powershell
.\.venv\Scripts\python.exe scripts\register_rfid_tag.py 04A1B2C3 CS-002
```

La asociación queda guardada en `data/carrito_smart.db`. Repetir el comando con
el mismo UID actualiza su producto de forma segura.

## Verificación física pendiente

La integración de software puede probarse completamente con tramas simuladas.
Con el hardware reunido todavía se debe confirmar:

1. El nombre del puerto COM detectado por Windows.
2. Que el firmware cargado sea el `lector.ino` de la raíz.
3. Que A→B y B→A correspondan a la orientación física del carrito.
4. Que la ventana de cruce de 1200 ms sea suficiente a velocidad normal.
5. Que cada producto tenga un UID distinto y registrado.
