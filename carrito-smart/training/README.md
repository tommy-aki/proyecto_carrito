# Videos para entrenar los tres productos

La persona que graba solo debe colocar videos en estas carpetas. Los videos y frames
se ignoran en Git porque pueden ocupar mucho espacio.

Si las carpetas no aparecen después de clonar el repositorio, ejecute una vez el
comando de extracción indicado al final. El script creará toda la estructura y
avisará que aún no encontró videos.

```text
training/videos/
├── train/
│   ├── cocacola_lata/
│   ├── pepsi_lata/
│   ├── doritos_bolsa/
│   └── negativos/
├── val/
│   ├── cocacola_lata/
│   ├── pepsi_lata/
│   ├── doritos_bolsa/
│   └── negativos/
└── test/
    ├── cocacola_lata/
    ├── pepsi_lata/
    ├── doritos_bolsa/
    └── negativos/
```

## Grabación

- Use la misma webcam y ángulo que tendrá Carrito Smart.
- Grabe a 1280×720 y 30 FPS; MP4 es preferible.
- Cada video de producto debe contener solamente el producto indicado por la carpeta.
- Mueva y rote el producto lentamente; cambie distancia, inclinación y posición.
- Incluya momentos parcialmente tapados por la mano o por el borde del carrito.
- No use filtros, zoom digital ni fondos editados.
- `negativos` debe incluir el carrito vacío y latas/bolsas que NO sean las tres clases.

Grabe por cada producto:

- `train`: 2 videos de 60 segundos, en dos iluminaciones/fondos diferentes.
- `val`: 1 video de 45 segundos, en una sesión distinta.
- `test`: 1 video de 45 segundos, en otra sesión distinta.

Grabe además un video negativo de 45–60 segundos para cada split. No reutilice el
mismo video en splits diferentes: eso produciría métricas engañosamente altas.

## Extracción

Cuando estén todos los videos:

```powershell
.\.venv\Scripts\python.exe scripts\extract_training_frames.py
```

El extractor toma dos candidatos por segundo, descarta frames borrosos y evita
guardar imágenes casi idénticas. Es seguro ejecutarlo nuevamente: no sobrescribe
archivos de otra fuente.
