# ============================================================================
# ARCHIVO: models/system_parameter.py
# PROPÓSITO: Modelo de Parámetros Globales del Sistema.
# ============================================================================

from models.entidad_base import EntidadBase


class SystemParameter(EntidadBase):
    """
    Modelo de Parámetros de Configuración Dinámica del SGCM.
    """

    TABLA = 'system_parameters'
    PK_COLUMNA = 'param_key'

    def __init__(self, param_key=None, param_value=None, descripcion=None, updated_at=None):
        # Dado que param_key es una cadena, heredamos sin UUID autogenerado en entidad_base
        super().__init__(id=param_key, created_at=updated_at)
        self.param_key = param_key
        self.param_value = param_value
        self.descripcion = descripcion

    def validar(self):
        errores = []
        if not self.param_key or len(self.param_key.strip()) < 3:
            errores.append("La clave del parámetro es obligatoria y debe ser descriptiva.")
        if self.param_value is None or len(self.param_value.strip()) == 0:
            errores.append("El valor del parámetro es obligatorio.")
        return errores

    def _get_campos_valores(self):
        campos = ['param_key', 'param_value', 'descripcion']
        valores = [self.param_key, self.param_value, self.descripcion]
        return campos, valores
