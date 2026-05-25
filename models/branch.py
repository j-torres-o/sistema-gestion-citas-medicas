# ============================================================================
# ARCHIVO: models/branch.py
# PROPÓSITO: Modelo de Sede Clínica (Branch).
# ============================================================================

from models.entidad_base import EntidadBase


class Branch(EntidadBase):
    """
    Modelo de Sedes Clínicas del SGCM.
    """

    TABLA = 'branches'
    PK_COLUMNA = 'id_sede'

    def __init__(self, id_sede=None, nombre=None, ciudad=None, direccion=None, activa=True, created_at=None):
        super().__init__(id=id_sede, created_at=created_at)
        self.nombre = nombre
        self.ciudad = ciudad
        self.direccion = direccion
        self.activa = activa

    def validar(self):
        errores = []
        if not self.nombre or len(self.nombre.strip()) < 5:
            errores.append("El nombre de la sede debe tener al menos 5 caracteres y especificar ciudad y sector.")
        if not self.ciudad or len(self.ciudad.strip()) < 3:
            errores.append("La ciudad de la sede es obligatoria.")
        if not self.direccion or len(self.direccion.strip()) < 5:
            errores.append("La dirección de la sede debe ser detallada y descriptiva.")
        return errores

    def _get_campos_valores(self):
        campos = ['nombre', 'ciudad', 'direccion', 'activa']
        valores = [self.nombre, self.ciudad, self.direccion, self.activa]
        return campos, valores
