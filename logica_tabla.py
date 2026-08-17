import serial
import pandas as pd
import os

PUERTO = '/dev/ttyUSB0'  # En Windows, usar COM3
BAUDIOS = 9600
ARCHIVO_TABLA = 'inventario.csv' # Pruebas con csv antes de crear la base de datos

# Cargar o crear tabla inicial
if os.path.exists(ARCHIVO_TABLA):
    tabla = pd.read_csv(ARCHIVO_TABLA)
else:
    tabla = pd.DataFrame(columns=['UID', 'Estado', 'Ultima_Actualizacion'])

def guardar_tabla():
    tabla.to_csv(ARCHIVO_TABLA, index=False)
    print("\n--- TABLA ACTUALIZADA ---")
    print(tabla)
    print("-------------------------\n")

try:
    arduino = serial.Serial(PUERTO, BAUDIOS, timeout=1)
    print("Escuchando Arduino...")

    while True:
        if arduino.in_waiting > 0:
            linea = arduino.readline().decode('utf-8').strip()

            if ":" in linea:
                accion, uid = linea.split(":")

                if accion == "ENTRADA":
                    if uid not in tabla['UID'].values:
                        nueva_fila = {'UID': uid, 'Estado': 'Dentro', 'Ultima_Actualizacion': pd.Timestamp.now()}
                        tabla = pd.concat([tabla, pd.DataFrame([nueva_fila])], ignore_index=False)
                        print(f"Producto {uid} INGRESADO a la tabla.")
                    else:
                        print(f"El producto {uid} ya figura en la tabla.")

                elif accion == "SALIDA":
                    if uid in tabla['UID'].values:
                        tabla = tabla[tabla['UID'] != uid]  # Elimina el registro
                        print(f"❌ Producto {uid} ELIMINADO de la tabla.")
                    else:
                        print(f"⚠️ El producto {uid} no está en la tabla para eliminar.")

                guardar_tabla()

except KeyboardInterrupt:
    print("\nPrograma finalizado.")
