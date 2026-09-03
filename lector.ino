#include <SPI.h>
#include <MFRC522.h>

#define SS_A_PIN 10
#define RST_A_PIN 9
#define SS_B_PIN 8
#define RST_B_PIN 7
#define BUZZER_PIN 5

// --- Parámetros ajustables ---
// Tiempo máximo (ms) entre la lectura en un lector y la lectura en el otro
// para considerarlo un "cruce" válido (ENTRADA o SALIDA). Si se tarda más
// que esto, se descarta y se empieza una nueva secuencia.
const unsigned long VENTANA_LOCKOUT_MS = 1200;

// Tiempo mínimo (ms) entre lecturas consecutivas de UN MISMO lector.
// Evita que la misma tarjeta, si se queda quieta en el campo del lector,
// dispare varias lecturas "fantasma" seguidas.
const unsigned long COOLDOWN_LECTOR_MS = 300;

MFRC522 rfidA(SS_A_PIN, RST_A_PIN);
MFRC522 rfidB(SS_B_PIN, RST_B_PIN);

// Estado de la lectura "pendiente": la última tarjeta vista en algún lector,
// esperando a ver si cruza al otro lector dentro de la ventana de lockout.
String pendienteUID = "";
char pendienteLector = 0;       // 'A', 'B', o 0 (nada pendiente)
unsigned long pendienteTime = 0;

// Marca de tiempo de la última lectura aceptada por cada lector (para el cooldown).
unsigned long ultimaLecturaA = 0;
unsigned long ultimaLecturaB = 0;

void setup() {
  Serial.begin(9600);
  SPI.begin();
  SPI.setClockDivider(SPI_CLOCK_DIV4);

  rfidA.PCD_Init();
  rfidB.PCD_Init();

  delay(1000); // Tiempo de espera.

  Serial.println("--- TEST DE DIAGNÓSTICO RFID ---");

  // Prueba de comunicación con Lector A
  rfidA.PCD_DumpVersionToSerial();
  byte vA = rfidA.PCD_ReadRegister(rfidA.VersionReg);
  Serial.print("Lector A Versión de Firmware: 0x");
  Serial.println(vA, HEX);
  if (vA == 0xB2) {
    Serial.println("Lector A: Conectado y respondiendo.");
  } else {
    Serial.println("Lector A: Error de conexión o cableado.");
  }

  // Prueba de comunicación con Lector B
  byte vB = rfidB.PCD_ReadRegister(rfidB.VersionReg);
  Serial.print("Lector B Versión de Firmware: 0x");
  Serial.println(vB, HEX);
  if (vB == 0xB2) {
    Serial.println("Lector B: Conectado y respondiendo.");
  } else {
    Serial.println("Lector B: Error de conexión o cableado.");
  }

  pinMode(BUZZER_PIN, OUTPUT);
}

void loop() {
  chequearLector(rfidA, 'A');
  chequearLector(rfidB, 'B');
}

// Revisa si el lector indicado detectó una tarjeta nueva y, si es así,
// aplica el cooldown y pasa la lectura al procesador de cruces.
void chequearLector(MFRC522 &lector, char id) {
  if (!lector.PICC_IsNewCardPresent() || !lector.PICC_ReadCardSerial()) {
    return;
  }

  unsigned long ahora = millis();
  unsigned long &ultimaLectura = (id == 'A') ? ultimaLecturaA : ultimaLecturaB;

  if (ahora - ultimaLectura < COOLDOWN_LECTOR_MS) {
    // Misma tarjeta todavía en el campo del lector: se ignora.
    lector.PICC_HaltA();
    lector.PCD_StopCrypto1();
    return;
  }
  ultimaLectura = ahora;

  String uid = uidToString(lector.uid);
  procesarDeteccion(id, uid, ahora);

  lector.PICC_HaltA();
  lector.PCD_StopCrypto1();
}

// Lógica de cruce entre lectores:
// A -> B = ENTRADA (1 beep)
// B -> A = SALIDA  (2 beeps)
// Si no hay una lectura pendiente compatible dentro de la ventana de lockout,
// esta lectura simplemente se guarda como el nuevo punto de partida.
void procesarDeteccion(char lector, const String &uid, unsigned long ahora) {
  bool cruceValido = (pendienteLector != 0) &&
                      (pendienteLector != lector) &&
                      (pendienteUID == uid) &&
                      (ahora - pendienteTime <= VENTANA_LOCKOUT_MS);

  if (cruceValido) {
    if (pendienteLector == 'A' && lector == 'B') {
      Serial.println("ENTRADA:" + uid);
      beep(1);
    } else if (pendienteLector == 'B' && lector == 'A') {
      Serial.println("SALIDA:" + uid);
      beep(2);
    }
    // Se consume la secuencia: hay que volver a cruzar de cero para el
    // siguiente evento (evita disparos múltiples con la misma tarjeta).
    pendienteLector = 0;
    pendienteUID = "";
  } else {
    // Nueva lectura inicial (o la anterior expiró / era de otra tarjeta).
    pendienteLector = lector;
    pendienteUID = uid;
    pendienteTime = ahora;
  }
}

// Convierte el UID leído (bytes) al mismo formato de texto usado en el
// resto del proyecto: hexadecimal en mayúsculas, sin separadores.
String uidToString(MFRC522::Uid &uid) {
  String resultado = "";
  for (byte i = 0; i < uid.size; i++) {
    if (uid.uidByte[i] < 0x10) {
      resultado += "0";
    }
    resultado += String(uid.uidByte[i], HEX);
  }
  resultado.toUpperCase();
  return resultado;
}

// n = 1 -> beep simple (ENTRADA), n = 2 -> beep doble (SALIDA)
void beep(int n) {
  for (int i = 0; i < n; i++) {
    tone(BUZZER_PIN, 1000);
    delay(100);
    noTone(BUZZER_PIN);
    if (i < n - 1) {
      delay(100);
    }
  }
}
