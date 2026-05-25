# ============================================================================
# ARCHIVO: models/user.py
# PROPÓSITO: Modelo de Usuario Unificado (Seguridad, Roles y Sede).
# ============================================================================

import re
from models.entidad_base import EntidadBase


class User(EntidadBase):
    """
    Modelo de Cuentas de Usuario Unificadas del SGCM.
    """

    TABLA = 'users'
    PK_COLUMNA = 'id_usuario'

    ROLES_VALIDOS = ['Admin', 'Recepcionista', 'Medico', 'Paciente']

    def __init__(self, id_usuario=None, username=None, password_hash=None, 
                 email=None, rol=None, id_sede=None, created_at=None, updated_at=None):
        super().__init__(id=id_usuario, created_at=created_at, updated_at=updated_at)
        self.username = username
        self.password_hash = password_hash
        self.email = email
        self.rol = rol
        self.id_sede = id_sede

    def validar(self):
        errores = []
        if not self.username or len(self.username.strip()) < 3:
            errores.append("El nombre de usuario debe tener al menos 3 caracteres.")
        if not self.password_hash:
            errores.append("La contraseña cifrada es obligatoria.")
        if not self.email or not re.match(r"[^@]+@[^@]+\.[^@]+", self.email):
            errores.append("Debe ingresar un correo electrónico con formato válido.")
        if self.rol not in self.ROLES_VALIDOS:
            errores.append(f"El rol '{self.rol}' no es válido para una cuenta del sistema.")
        return errores

    def _get_campos_valores(self):
        campos = ['username', 'password_hash', 'email', 'rol', 'id_sede']
        valores = [self.username, self.password_hash, self.email, self.rol, self.id_sede]
        return campos, valores
