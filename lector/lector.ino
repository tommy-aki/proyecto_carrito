#include <SPI.h>
#include <MFRC522.h>

#define SS_A_PIN 10
#define RST_A_PIN 9
#define SS_B_PIN 8
#define RST_B_PIN 7
#define BUZZER_PIN 5 

MFRC522 rfidA(SS_A_PIN, RST_A_PIN);
MFRC522 rfidB(SS_B_PIN, RST_B_PIN);

void setup() {
  Serial.begin(9600);
  SPI.begin();
  SPI.setClockDivider(SPI_CLOCK_DIV4); 
  
  // Pruebas de conexión
  rfidA.PCD_Init();
  rfidB.PCD_Init();

  delay(1000); //Tiempo de espera.

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

  // Inicializacióń del Buzzer
  pinMode(BUZZER_PIN, OUTPUT);
}

void loop() {
  // Simular que un producto entra cada 5 segundos para la demo
  delay(5000);
  
  String uids[] = {"4A3B2C1D", "8F9E0D1C", "12345678"};
  int index = random(0, 3);

  tone(BUZZER_PIN, 1000); // Emite un tono de 1000 Hz
  delay(200);            // Espera 1 segundo
  noTone(BUZZER_PIN);     // Apaga el sonido
  
  // Alternar entre ENTRADA y SALIDA de forma aleatoria
  if (random(0, 2) == 0) {
    Serial.println("ENTRADA:" + uids[index]);
  } else {
    Serial.println("SALIDA:" + uids[index]);
  }
}
