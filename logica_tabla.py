import argparse
import sqlite3

try:
    import serial
except ImportError:
    serial = None

from database.database import inicializar_base_datos, obtener_conexion
from database.operations import obtener_dispositivo, obtener_o_crear_sesion, procesar_rfid
from database.seed import ejecutar_seed

PUERTO = "/dev/ttyUSB0"  # En Windows, usar COM3 o COM4.
BAUDIOS = 9600


def procesar_linea(conexion, id_sesion, linea):
    if ":" not in linea:
        return None
    accion, uid = (parte.strip() for parte in linea.split(":", 1))
    accion = accion.upper()
    uid = "".join(uid.split()).upper()
    if accion not in ("ENTRADA", "SALIDA") or not uid:
        return None
    codigo = "RFID-A" if accion == "ENTRADA" else "RFID-B"
    return procesar_rfid(conexion, id_sesion, obtener_dispositivo(conexion, codigo), accion, uid)


def ejecutar_simulacion():
    inicializar_base_datos()
    ejecutar_seed()
    with obtener_conexion() as conexion:
        id_sesion = obtener_o_crear_sesion(conexion)
        for linea in ("ENTRADA:4A3B2C1D", "ENTRADA:8F9E0D1C", "SALIDA:4A3B2C1D"):
            try:
                print(procesar_linea(conexion, id_sesion, linea))
                conexion.commit()
            except (sqlite3.Error, ValueError) as error:
                conexion.rollback()
                print(f"[SQLite] Lectura ignorada por error: {error}")
        total = conexion.execute("SELECT total_calculado FROM sesiones_compra WHERE id_sesion = ?", (id_sesion,)).fetchone()[0]
        print(f"Sesion {id_sesion}; total_calculado={total}")


def escuchar_serial():
    if serial is None:
        raise RuntimeError("Falta pyserial. Instala dependencias con: pip install -r requirements.txt")
    inicializar_base_datos()
    ejecutar_seed()
    with obtener_conexion() as conexion:
        id_sesion = obtener_o_crear_sesion(conexion)
        try:
            arduino = serial.Serial(PUERTO, BAUDIOS, timeout=1)
        except serial.SerialException as error:
            raise RuntimeError(f"No se pudo abrir {PUERTO}: {error}") from error
        print(f"Escuchando Arduino en {PUERTO} a {BAUDIOS} baudios...")
        try:
            while True:
                if arduino.in_waiting:
                    linea = arduino.readline().decode("utf-8", errors="replace").strip()
                    try:
                        mensaje = procesar_linea(conexion, id_sesion, linea)
                        conexion.commit()
                        if mensaje:
                            print(mensaje)
                    except (sqlite3.Error, ValueError) as error:
                        conexion.rollback()
                        print(f"[SQLite] Lectura ignorada por error: {error}")
        except KeyboardInterrupt:
            print("\nPrograma finalizado.")
        finally:
            arduino.close()


def main():
    parser = argparse.ArgumentParser(description="Procesador RFID del carrito")
    parser.add_argument("--simular", action="store_true", help="Procesa tres lecturas sin Arduino")
    if parser.parse_args().simular:
        ejecutar_simulacion()
    else:
        escuchar_serial()


if __name__ == "__main__":
    main()
