# ============================================================================
# ARCHIVO: models/patient.py
# PROPÓSITO: Modelo de Paciente.
# ============================================================================

import re
from models.entidad_base import EntidadBase


class Patient(EntidadBase):
    """
    Modelo de Pacientes del sistema SGCM.
    """

    TABLA = 'patients'
    PK_COLUMNA = 'id_paciente'

    def __init__(self, id_paciente=None, dni=None, nombre_completo=None, 
                 telefono=None, email=None, created_at=None):
        super().__init__(id=id_paciente, created_at=created_at)
        self.dni = dni
        self.nombre_completo = nombre_completo
        self.telefono = telefono
        self.email = email

    def validar(self):
        errores = []
        
        # Validar DNI (Control de Calidad)
        if not self.dni or not self.dni.strip().isdigit() or len(self.dni.strip()) < 6:
            errores.append("El DNI debe ser numérico y tener al menos 6 dígitos.")
            
        if not self.nombre_completo or len(self.nombre_completo.strip()) < 5:
            errores.append("El nombre completo es obligatorio (mínimo 5 caracteres).")
            
        # Validar Teléfono
        if not self.telefono or len(self.telefono.strip()) < 7:
            errores.append("El número telefónico debe tener al menos 7 dígitos.")
            
        # Validar Formato de Correo Electrónico (Control de Calidad)
        email_regex = r'^[\w\.-]+@[\w\.-]+\.\w+$'
        if not self.email or not re.match(email_regex, self.email):
            errores.append("El formato del correo electrónico ingresado no es válido.")
            
        return errores

    def _get_campos_valores(self):
        campos = ['dni', 'nombre_completo', 'telefono', 'email']
        valores = [self.dni, self.nombre_completo, self.telefono, self.email]
        return campos, valores
