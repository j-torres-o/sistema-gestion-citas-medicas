# ============================================================================
# ARCHIVO: models/permission_delegation.py
# PROPÓSITO: Modelo de Delegación de Permisos Dinámicos y Temporales.
# ============================================================================

from models.entidad_base import EntidadBase


class PermissionDelegation(EntidadBase):
    """
    Modelo de Trazabilidad y Asignación de Permisos Delegados del SGCM.
    """

    TABLA = 'permissions_delegation'
    PK_COLUMNA = 'id_delegacion'

    PERMISOS_DELEGABLES = [
        'can_modify_appointment_duration',
        'can_execute_massive_cancellations',
        'can_configure_system_parameters'
    ]

    def __init__(self, id_delegacion=None, id_usuario_receptor=None, permiso_nombre=None,
                 fecha_inicio=None, fecha_expiracion=None, creado_por=None, created_at=None):
        super().__init__(id=id_delegacion, created_at=created_at)
        self.id_usuario_receptor = id_usuario_receptor
        self.permiso_nombre = permiso_nombre
        self.fecha_inicio = fecha_inicio
        self.fecha_expiracion = fecha_expiracion  # Puede ser None si es indefinido
        self.creado_por = creado_por

    def validar(self):
        errores = []
        if not self.id_usuario_receptor:
            errores.append("Debe seleccionar un usuario receptor válido.")
        if self.permiso_nombre not in self.PERMISOS_DELEGABLES:
            errores.append(f"El permiso '{self.permiso_nombre}' no es elegible para delegación.")
        if not self.fecha_inicio:
            errores.append("La fecha de inicio de la delegación es obligatoria.")
        return errores

    def _get_campos_valores(self):
        campos = ['id_usuario_receptor', 'permiso_nombre', 'fecha_inicio', 'fecha_expiracion', 'creado_por']
        valores = [self.id_usuario_receptor, self.permiso_nombre, self.fecha_inicio, self.fecha_expiracion, self.creado_por]
        return campos, valores
