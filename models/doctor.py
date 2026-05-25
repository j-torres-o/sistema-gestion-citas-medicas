# ============================================================================
# ARCHIVO: models/doctor.py
# PROPÓSITO: Modelo de Médico Especialista.
# ============================================================================

from models.entidad_base import EntidadBase


class Doctor(EntidadBase):
    """
    Modelo de Médicos de la clínica.
    """

    TABLA = 'doctors'
    PK_COLUMNA = 'id_medico'

    def __init__(self, id_medico=None, id_usuario=None, numero_licencia=None, nombre_completo=None, 
                 id_especialidad=None, duracion_defecto='30 minutes', created_at=None):
        super().__init__(id=id_medico, created_at=created_at)
        self.id_usuario = id_usuario
        self.numero_licencia = numero_licencia
        self.nombre_completo = nombre_completo
        self.id_especialidad = id_especialidad
        self.duracion_defecto = duracion_defecto

    def validar(self):
        errores = []
        if not self.numero_licencia or len(self.numero_licencia.strip()) < 3:
            errores.append("El número de licencia médica es obligatorio.")
        if not self.nombre_completo or len(self.nombre_completo.strip()) < 5:
            errores.append("El nombre completo del médico debe tener al menos 5 caracteres.")
        if not self.id_especialidad:
            errores.append("Debe asociar al médico a una especialidad válida.")
        return errores

    def _get_campos_valores(self):
        campos = ['id_usuario', 'numero_licencia', 'nombre_completo', 'id_especialidad', 'duracion_defecto']
        valores = [self.id_usuario, self.numero_licencia, self.nombre_completo, self.id_especialidad, self.duracion_defecto]
        return campos, valores
