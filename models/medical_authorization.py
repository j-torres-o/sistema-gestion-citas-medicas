# ============================================================================
# ARCHIVO: models/medical_authorization.py
# PROPÓSITO: Modelo de Autorización y Derivación Médica para Tratamientos Múltiples.
# ============================================================================

from models.entidad_base import EntidadBase


class MedicalAuthorization(EntidadBase):
    """
    Modelo de Derivaciones Clínicas y Control de Agendamiento Múltiple del SGCM.
    """

    TABLA = 'medical_authorizations'
    PK_COLUMNA = 'id_autorizacion'

    ESTADOS_VALIDOS = ['Activa', 'Consumida', 'Cancelada']

    def __init__(self, id_autorizacion=None, id_paciente=None, id_medico_emisor=None,
                 id_especialidad_dest=None, sesiones_totales=1, sesiones_consumidas=0,
                 frecuencia_dias=7, estado='Activa', created_at=None):
        super().__init__(id=id_autorizacion, created_at=created_at)
        self.id_paciente = id_paciente
        self.id_medico_emisor = id_medico_emisor
        self.id_especialidad_dest = id_especialidad_dest
        self.sesiones_totales = sesiones_totales
        self.sesiones_consumidas = sesiones_consumidas
        self.frecuencia_dias = frecuencia_dias
        self.estado = estado

    def validar(self):
        errores = []
        if not self.id_paciente:
            errores.append("Debe asociar la derivación a un paciente válido.")
        if not self.id_medico_emisor:
            errores.append("Debe registrar al médico emisor de la derivación.")
        if not self.id_especialidad_dest:
            errores.append("Debe registrar la especialidad clínica de destino.")
        if self.sesiones_totales <= 0:
            errores.append("El número total de sesiones autorizadas debe ser mayor a 0.")
        if self.sesiones_consumidas < 0 or self.sesiones_consumidas > self.sesiones_totales:
            errores.append("La cantidad de sesiones consumidas no es válida en relación al total.")
        if self.frecuencia_dias <= 0:
            errores.append("La frecuencia en días de las citas debe ser mayor a 0.")
        if self.estado not in self.ESTADOS_VALIDOS:
            errores.append(f"El estado '{self.estado}' no es válido para una derivación.")
        return errores

    def _get_campos_valores(self):
        campos = [
            'id_paciente', 'id_medico_emisor', 'id_especialidad_dest', 
            'sesiones_totales', 'sesiones_consumidas', 'frecuencia_dias', 'estado'
        ]
        valores = [
            self.id_paciente, self.id_medico_emisor, self.id_especialidad_dest,
            self.sesiones_totales, self.sesiones_consumidas, self.frecuencia_dias, self.estado
        ]
        return campos, valores
