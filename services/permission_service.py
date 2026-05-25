# ============================================================================
# ARCHIVO: services/permission_service.py
# PROPÓSITO: Capa de autorización y validación de permisos en el SGCM.
#
# Administra la lógica de seguridad basada en roles (RBAC) y delegaciones
# dinámicas de permisos en tiempo real con expiración por base de datos.
# ============================================================================

from database import Database
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone


class PermissionService:
    """
    Servicio encargado de verificar permisos relacionales, roles de usuario,
    e historial de delegación de permisos temporales en caliente.
    """

    @staticmethod
    def check_permission(id_usuario, permiso_nombre):
        """
        Verifica si un usuario cuenta con un permiso específico, ya sea por
        su rol predeterminado o por una delegación activa.
        """
        conn = Database.get_connection()
        cursor = None
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Obtener el rol del usuario
            cursor.execute(
                "SELECT rol FROM users WHERE id_usuario = %s;",
                (id_usuario,)
            )
            user = cursor.fetchone()
            if not user:
                return False

            rol = user['rol']

            # 2. Verificar permisos por rol por defecto
            # El Administrador cuenta con todos los permisos operativos
            if rol == 'Admin':
                return True

            # Si es Recepcionista, verificar si tiene delegación activa
            if rol == 'Recepcionista':
                # Validar si existe una delegación activa en base de datos
                # donde la fecha de inicio ya pasó y la de expiración aún no llega (o es indefinida/null)
                now = datetime.now(timezone.utc)
                cursor.execute(
                    """
                    SELECT 1 FROM permissions_delegation
                    WHERE id_usuario_receptor = %s
                      AND permiso_nombre = %s
                      AND fecha_inicio <= %s
                      AND (fecha_expiracion IS NULL OR fecha_expiracion > %s);
                    """,
                    (id_usuario, permiso_nombre, now, now)
                )
                delegation = cursor.fetchone()
                if delegation:
                    return True

            return False

        except Exception as e:
            print(f"[PermissionService] Error al verificar permiso {permiso_nombre} para usuario {id_usuario}: {e}")
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                Database.release_connection(conn)

    @staticmethod
    def check_role(id_usuario, roles_permitidos):
        """
        Valida si el rol de un usuario se encuentra dentro de los roles permitidos.
        """
        conn = Database.get_connection()
        cursor = None
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute("SELECT rol FROM users WHERE id_usuario = %s;", (id_usuario,))
            user = cursor.fetchone()
            if not user:
                return False
            return user['rol'] in roles_permitidos
        except Exception as e:
            print(f"[PermissionService] Error al verificar rol de usuario {id_usuario}: {e}")
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                Database.release_connection(conn)

    @staticmethod
    def can_modify_profile(id_usuario_solicitante, id_usuario_destino):
        """
        Verifica si un usuario puede modificar un perfil de destino.
        Permite el acceso si es su propio perfil o si es Administrador.
        """
        if str(id_usuario_solicitante) == str(id_usuario_destino):
            return True

        # Verificar si es Administrador
        return PermissionService.check_role(id_usuario_solicitante, ['Admin'])

    @staticmethod
    def can_access_clinical_notes(id_usuario_solicitante, id_paciente):
        """
        Restringe la visualización de notas clínicas y expedientes.
        Solo permitido para Médicos o para el Paciente que es dueño del historial clínico.
        Las Recepcionistas tienen prohibido este acceso por políticas de privacidad clínica.
        """
        conn = Database.get_connection()
        cursor = None
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # Obtener datos del solicitante
            cursor.execute("SELECT rol FROM users WHERE id_usuario = %s;", (id_usuario_solicitante,))
            solicitante = cursor.fetchone()
            if not solicitante:
                return False

            rol = solicitante['rol']

            # Si es Médico, tiene autonomía y acceso a notas clínicas
            if rol == 'Medico':
                return True

            # Si es Paciente, verificar que sea el dueño del id_paciente
            if rol == 'Paciente':
                cursor.execute(
                    "SELECT 1 FROM patients WHERE id_paciente = %s AND id_usuario = %s;",
                    (id_paciente, id_usuario_solicitante)
                )
                is_owner = cursor.fetchone()
                return is_owner is not None

            return False
        except Exception as e:
            print(f"[PermissionService] Error en acceso a notas clínicas para {id_usuario_solicitante}: {e}")
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                Database.release_connection(conn)
