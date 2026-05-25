# ============================================================================
# ARCHIVO: services/notification_service.py
# PROPÓSITO: Servicio simulado para envío de notificaciones asíncronas (SMS).
# ============================================================================

import time


class NotificationService:
    """
    Servicio encargado de notificar a los pacientes sobre las asignaciones de citas.
    Diseñado para simular un comportamiento asíncrono e ininterrumpido.
    """

    @staticmethod
    def send_sms_notification(id_paciente, telefono, mensaje):
        """
        Simula el envío de un SMS utilizando un retardo simulado mínimo
        para no bloquear el hilo de ejecución principal.
        """
        # En producción esto se conectaría con un proveedor como Twilio o AWS SNS
        print(f"[SMS NOTIFICACIÓN] Enviando a Paciente {id_paciente} al número {telefono}: {mensaje}")
        return True
