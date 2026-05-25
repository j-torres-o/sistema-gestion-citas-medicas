# ============================================================================
# ARCHIVO: models/waiting_list.py
# PROPÓSITO: Modelo de Solicitud en Lista de Espera (LEA).
# ============================================================================

from models.entidad_base import EntidadBase


class WaitingList(EntidadBase):
    """
    Modelo de Lista de Espera del SGCM.
    """

    TABLA = 'waiting_list'
    PK_COLUMNA = 'id_espera'

    TIPOS_COLA_VALIDOS = ['FechaCercana', 'RangoEspecifico']
    ESTADOS_VALIDOS = ['Pendiente', 'Asignada', 'Cancelada', 'Expirada']

    def __init__(self, id_espera=None, id_paciente=None, id_especialidad=None, 
                 tipo_cola='FechaCercana', rango_deseado=None, estado='Pendiente', 
                 created_at=None, updated_at=None):
        super().__init__(id=id_espera, created_at=created_at, updated_at=updated_at)
        self.id_paciente = id_paciente
        self.id_especialidad = id_especialidad
        self.tipo_cola = tipo_cola
        self.rango_deseado = rango_deseado  # Mapeado a daterange, ej. '[2026-06-01, 2026-06-07]'
        self.estado = estado

    def validar(self):
        errores = []
        if not self.id_paciente:
            errores.append("Debe asociar la solicitud a un paciente válido.")
        if not self.id_especialidad:
            errores.append("Debe seleccionar la especialidad médica requerida.")
        if self.tipo_cola not in self.TIPOS_COLA_VALIDOS:
            errores.append(f"El tipo de cola '{self.tipo_cola}' no es válido.")
        if self.estado not in self.ESTADOS_VALIDOS:
            errores.append(f"El estado '{self.estado}' no es válido para lista de espera.")
        if self.tipo_cola == 'RangoEspecifico' and not self.rango_deseado:
            errores.append("Debe especificar el rango de fechas estimado para este tipo de cola.")
        return errores

    def _get_campos_valores(self):
        campos = ['id_paciente', 'id_especialidad', 'tipo_cola', 'rango_deseado', 'estado']
        valores = [self.id_paciente, self.id_especialidad, self.tipo_cola, self.rango_deseado, self.estado]
        return campos, valores
