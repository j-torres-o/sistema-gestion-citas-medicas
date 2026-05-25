# ============================================================================
# ARCHIVO: services/appointment_service.py
# PROPÓSITO: Servicio de Citas Médicas del SGCM.
#
# Administra la lógica de negocio para cancelaciones y reprogramaciones,
# garantizando reglas como la validación de 24 horas y disparadores LEA.
# ============================================================================

import json
from datetime import datetime, timezone, timedelta
from database import Database
from services.waiting_list_engine import WaitingListEngine


class AppointmentService:
    """
    Servicio centralizado que administra el ciclo de vida de las citas clínicas.
    """

    @staticmethod
    def cancel_appointment(id_cita, realizado_por, usuario_identificador):
        """
        Cancela una cita asignada. Si es realizada por el Paciente,
        se valida la regla estricta de las 24 horas de anticipación.
        Al liberar la cita, se limpia el paciente y se retorna al pool
        inicializando el motor LEA reactivamente.
        """
        conn = Database.get_connection()
        conn.autocommit = False  # Asegurar control de transacción manual
        from psycopg2.extras import RealDictCursor
        cursor = None
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Obtener y bloquear la cita para auditoría y validación
            cursor.execute(
                """
                SELECT id_cita, rango_cita, estado, id_paciente
                FROM appointments
                WHERE id_cita = %s
                FOR UPDATE;
                """,
                (id_cita,)
            )
            appointment = cursor.fetchone()
            if not appointment:
                raise ValueError(f"Cita con ID {id_cita} no encontrada.")

            rango_cita = appointment['rango_cita']
            estado_actual = appointment['estado']
            id_paciente = appointment['id_paciente']

            # Si ya está cancelada o no tiene paciente, simplemente retornamos éxito (idempotencia)
            if estado_actual == 'Cancelada' and id_paciente is None:
                conn.commit()
                print(f"[AppointmentService] Cita {id_cita} ya se encuentra liberada y cancelada.")
                return True

            # 2. Validar regla de las 24 Horas si es cancelada por el propio Paciente
            if realizado_por == 'Paciente':
                # Validar propiedad
                if not id_paciente or str(id_paciente) != str(usuario_identificador):
                    raise PermissionError("No está autorizado para cancelar una cita asignada a otro paciente.")

                # Comparar con zona horaria UTC
                cita_inicio = rango_cita.lower
                now_utc = datetime.now(timezone.utc)
                if cita_inicio - now_utc < timedelta(hours=24):
                    raise PermissionError(
                        "Las cancelaciones por parte del paciente deben realizarse con al menos 24 horas de anticipación."
                    )

            # 3. Liberar el slot de la cita: id_paciente = NULL, estado = 'Agendada'
            # De esta forma, el slot vuelve a estar disponible para que otro paciente lo tome (o LEA lo asigne).
            # Si el médico o recepcionista cancelan definitivamente la cita (sin que quede libre), el estado cambia a 'Cancelada'.
            # Pero para liberar el espacio para lista de espera, desvinculamos al paciente y devolvemos el estado a 'Agendada'.
            # Mantenemos 'Agendada' como el estado disponible sin paciente, que es el inicial de base de datos.
            nuevo_estado = 'Agendada'
            cursor.execute(
                """
                UPDATE appointments
                SET id_paciente = NULL, estado = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id_cita = %s;
                """,
                (nuevo_estado, id_cita)
            )

            # 4. Registrar en historial de auditoría
            cambios_dict = {
                "id_paciente": {"old": str(id_paciente) if id_paciente else None, "new": None},
                "estado": {"old": estado_actual, "new": nuevo_estado}
            }

            cursor.execute(
                """
                INSERT INTO appointments_history (
                    id_cita, estado_anterior, estado_nuevo, tipo_accion,
                    realizado_por, usuario_identificador, cambios
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb);
                """,
                (
                    id_cita,
                    estado_actual,
                    nuevo_estado,
                    'Cancelacion',
                    realizado_por,
                    str(usuario_identificador),
                    json.dumps(cambios_dict)
                )
            )

            # Confirmar cambios atómicamente en la base de datos
            conn.commit()
            print(f"[AppointmentService] Cita {id_cita} desvinculada y liberada con éxito por {realizado_por}.")

            # 5. Activar de manera reactiva e inmediata el motor LEA para asignar el slot libre
            WaitingListEngine.handle_liberated_slot(
                id_cita=id_cita,
                realizado_por='Sistema',
                usuario_identificador='system_engine@clinicasalud.com'
            )

            return True

        except Exception as e:
            if conn:
                conn.rollback()
            print(f"[AppointmentService] Error crítico al cancelar cita {id_cita}: {e}")
            raise e
        finally:
            if cursor:
                cursor.close()
            if conn:
                Database.release_connection(conn)
