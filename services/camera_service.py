try:
    import cv2
except ImportError:
    cv2 = None


class CameraService:
    """Preview opcional de la única cámara física del prototipo."""

    def __init__(self):
        self.capture = None

    def start(self):
        if cv2 is None:
            return False
        self.capture = cv2.VideoCapture(0)
        return bool(self.capture.isOpened())

    def stop(self):
        if self.capture:
            self.capture.release()
            self.capture = None


class BuzzerService:
    def beep_producto(self):
        print("[BUZZER] Producto detectado")

    def beep_error(self):
        print("[BUZZER] Error")

    def beep_pago_aprobado(self):
        print("[BUZZER] Pago aprobado")
