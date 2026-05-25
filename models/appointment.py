# ============================================================================
# ARCHIVO: models/appointment.py
# PROPÓSITO: Modelo de Cita Médica.
# ============================================================================

from models.entidad_base import EntidadBase


class Appointment(EntidadBase):
    """
    Modelo de Citas Médicas con soporte para rangos temporales de PostgreSQL y sede.
    """

    TABLA = 'appointments'
    PK_COLUMNA = 'id_cita'

    ESTADOS_VALIDOS = ['Agendada', 'Confirmada', 'EnCurso', 'Finalizada', 'Cancelada', 'NoAsistio']

    def __init__(self, id_cita=None, id_medico=None, id_paciente=None, id_sede=None,
                 rango_cita=None, estado='Agendada', created_at=None, updated_at=None):
        super().__init__(id=id_cita, created_at=created_at, updated_at=updated_at)
        self.id_medico = id_medico
        self.id_paciente = id_paciente
        self.id_sede = id_sede
        self.rango_cita = rango_cita  # Representado como string de rango o DateTimeTZRange
        self.estado = estado

    def validar(self):
        errores = []
        if not self.id_medico:
            errores.append("Debe asociar la cita a un médico especialista.")
        if not self.id_sede:
            errores.append("Debe asociar la cita a una sede física de atención.")
        if not self.rango_cita:
            errores.append("El rango de fecha y hora de la cita es obligatorio.")
        if self.estado not in self.ESTADOS_VALIDOS:
            errores.append(f"El estado '{self.estado}' no es válido para una cita médica.")
        return errores

    def _get_campos_valores(self):
        campos = ['id_medico', 'id_paciente', 'id_sede', 'rango_cita', 'estado']
        valores = [self.id_medico, self.id_paciente, self.id_sede, self.rango_cita, self.estado]
        return campos, valores
