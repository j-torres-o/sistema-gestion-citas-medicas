# ============================================================================
# ARCHIVO: models/audit.py
# PROPÓSITO: Modelo de Historial y Auditoría Transaccional de Citas.
# ============================================================================

import json
from models.entidad_base import EntidadBase


class AppointmentHistory(EntidadBase):
    """
    Modelo de Auditoría de cambios en las citas clínicas.
    Mapea a la tabla appointments_history en PostgreSQL.
    """

    TABLA = 'appointments_history'
    PK_COLUMNA = 'id_historial'

    ACCIONES_VALIDAS = ['Creacion', 'Asignacion', 'Modificacion', 'Cancelacion']
    ACTORES_VALIDOS = ['Paciente', 'Recepcionista', 'Medico', 'Sistema']

    def __init__(self, id_historial=None, id_cita=None, estado_anterior=None, 
                 estado_nuevo=None, tipo_accion=None, realizado_por=None, 
                 usuario_identificador=None, cambios='{}', created_at=None):
        super().__init__(id=id_historial, created_at=created_at)
        self.id_cita = id_cita
        self.estado_anterior = estado_anterior
        self.estado_nuevo = estado_nuevo
        self.tipo_accion = tipo_accion
        self.realizado_por = realizado_por
        self.usuario_identificador = usuario_identificador
        self.cambios = cambios  # String JSON o dict para mapear a JSONB en Postgres

    def validar(self):
        errores = []
        if not self.id_cita:
            errores.append("Debe asociar el historial a una cita válida.")
        if not self.estado_nuevo:
            errores.append("El estado nuevo es obligatorio.")
        if self.tipo_accion not in self.ACCIONES_VALIDAS:
            errores.append(f"El tipo de acción '{self.tipo_accion}' no es válido.")
        if self.realizado_por not in self.ACTORES_VALIDOS:
            errores.append(f"El actor '{self.realizado_por}' no es válido.")
        if not self.usuario_identificador:
            errores.append("El identificador del usuario que ejecutó el cambio es obligatorio.")
        return errores

    def _get_campos_valores(self):
        # Convertir a JSON string si es un diccionario de Python
        cambios_json = self.cambios
        if isinstance(cambios_json, dict):
            cambios_json = json.dumps(cambios_json)

        campos = [
            'id_cita', 'estado_anterior', 'estado_nuevo', 
            'tipo_accion', 'realizado_por', 'usuario_identificador', 'cambios'
        ]
        valores = [
            self.id_cita, self.estado_anterior, self.estado_nuevo, 
            self.tipo_accion, self.realizado_por, self.usuario_identificador, cambios_json
        ]
        return campos, valores
