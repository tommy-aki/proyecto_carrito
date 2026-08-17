#include <SPI.h>
#include <MFRC522.h>

// Pines lectores RFID
#define SS_A_PIN 10
#define RST_A_PIN 9
#define SS_B_PIN 8
#define RST_B_PIN 7

// Pin para Feedback Sonoro
#define BUZZER_PIN 5

void setup() {
  Serial.begin(9600);
}

void loop() {
  // Simular que un producto entra cada 5 segundos para la demo
  delay(5000);
  
  String uids[] = {"4A3B2C1D", "8F9E0D1C", "12345678"};
  int index = random(0, 3);
  
  // Alternar entre ENTRADA y SALIDA de forma aleatoria
  if (random(0, 2) == 0) {
    Serial.println("ENTRADA:" + uids[index]);
  } else {
    Serial.println("SALIDA:" + uids[index]);
  }
}
