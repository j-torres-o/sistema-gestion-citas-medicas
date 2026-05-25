# ============================================================================
# ARCHIVO: models/specialty.py
# PROPÓSITO: Modelo de Especialidad Médica.
# ============================================================================

from models.entidad_base import EntidadBase


class Specialty(EntidadBase):
    """
    Modelo de Especialidades Médicas.
    """

    TABLA = 'specialties'
    PK_COLUMNA = 'id_especialidad'

    def __init__(self, id_especialidad=None, nombre=None, descripcion=None, created_at=None):
        super().__init__(id=id_especialidad, created_at=created_at)
        self.nombre = nombre
        self.descripcion = descripcion

    def validar(self):
        errores = []
        if not self.nombre or len(self.nombre.strip()) < 3:
            errores.append("El nombre de la especialidad debe tener al menos 3 caracteres.")
        return errores

    def _get_campos_valores(self):
        campos = ['nombre', 'descripcion']
        valores = [self.nombre, self.descripcion]
        return campos, valores
