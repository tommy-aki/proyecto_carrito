#include <SPI.h>
#include <MFRC522.h>

#define SS_A_PIN 10
#define RST_A_PIN 9
#define BUZZER_PIN 5

// --- Parámetros ajustables ---
// Tiempo mínimo (ms) entre lecturas consecutivas para evitar lecturas "fantasma"
// si la tarjeta se queda posada sobre el lector.
const unsigned long COOLDOWN_LECTOR_MS = 1000; 

MFRC522 rfidA(SS_A_PIN, RST_A_PIN);

// Marca de tiempo de la última lectura aceptada
unsigned long ultimaLecturaA = 0;

void setup() {
  Serial.begin(9600);
  SPI.begin();
  SPI.setClockDivider(SPI_CLOCK_DIV4);

  rfidA.PCD_Init();

  delay(1000); // Tiempo de espera inicial

  Serial.println("--- MODO DEMO: SOLO LECTOR A (ENTRADAS DIRECTAS) ---");

  // Prueba de comunicación con Lector A
  rfidA.PCD_DumpVersionToSerial();
  byte vA = rfidA.PCD_ReadRegister(rfidA.VersionReg);
  Serial.print("Lector A Versión de Firmware: 0x");
  Serial.println(vA, HEX);
  
  if (vA == 0xB2 || vA == 0x92 || vA == 0x91) { 
    // Nota: 0x92 o 0x91 también son versiones válidas comunes en clones RC522
    Serial.println("Lector A: Conectado y respondiendo.");
  } else {
    Serial.println("Lector A: Error de conexión o cableado.");
  }

  pinMode(BUZZER_PIN, OUTPUT);
}

void loop() {
  chequearLectorA();
}

// Revisa si el Lector A detectó una tarjeta y genera automáticamente el evento ENTRADA
void chequearLectorA() {
  if (!rfidA.PICC_IsNewCardPresent() || !rfidA.PICC_ReadCardSerial()) {
    return;
  }

  unsigned long ahora = millis();

  // Cooldown para evitar disparos múltiples seguidos de la misma tarjeta
  if (ahora - ultimaLecturaA < COOLDOWN_LECTOR_MS) {
    rfidA.PICC_HaltA();
    rfidA.PCD_StopCrypto1();
    return;
  }
  ultimaLecturaA = ahora;

  // Obtener UID y emitir entrada
  String uid = uidToString(rfidA.uid);
  
  Serial.println("ENTRADA:" + uid);
  beep(1); // 1 beep para confirmación de Entrada

  rfidA.PICC_HaltA();
  rfidA.PCD_StopCrypto1();
}

// Convierte el UID leído a texto en hexadecimal mayúsculas
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

// n = 1 -> beep simple (ENTRADA)
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