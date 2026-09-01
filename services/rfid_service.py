try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None

from PySide6.QtCore import QThread, Signal


class RfidWorker(QThread):
    reading = Signal(str, str)
    connection = Signal(bool, str)

    def __init__(self, port, baud=9600):
        super().__init__()
        self.port = port
        self.baud = baud
        self.running = True

    def run(self):
        if serial is None:
            self.connection.emit(False, "pyserial no instalado")
            return
        try:
            device = serial.Serial(self.port, self.baud, timeout=1)
            self.connection.emit(True, self.port)
        except serial.SerialException as error:
            self.connection.emit(False, str(error))
            return
        try:
            while self.running:
                line = device.readline().decode("utf-8", errors="replace").strip()
                if ":" in line:
                    direction, uid = (part.strip().upper() for part in line.split(":", 1))
                    if direction in ("ENTRADA", "SALIDA") and uid:
                        self.reading.emit(direction, "".join(uid.split()))
        finally:
            device.close()

    def stop(self):
        self.running = False
        self.wait(1500)


def available_ports():
    return [port.device for port in list_ports.comports()] if list_ports else []
