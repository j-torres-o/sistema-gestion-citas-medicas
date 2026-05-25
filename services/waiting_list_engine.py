# ============================================================================
# ARCHIVO: services/waiting_list_engine.py
# PROPÓSITO: Motor de Lista de Espera Automática (LEA).
#
# Administra la cola FIFO de pacientes elegibles ante la liberación de slots.
# Implementa concurrencia pesimista FOR UPDATE SKIP LOCKED y reglas de negocio.
# ============================================================================

import json
from datetime import datetime, timezone, timedelta
from database import Database
from services.notification_service import NotificationService


class WaitingListEngine:
    """
    Motor reactivo encargado de asignar de forma atómica y consistente
    los slots liberados a los pacientes en cola de espera.
    """

    @staticmethod
    def handle_liberated_slot(id_cita, realizado_por='Sistema', usuario_identificador='system_engine@clinicasalud.com'):
        """
        Evalúa un slot liberado y busca pacientes elegibles en la lista de espera (FIFO).
        Aplica la Regla de las 2 Horas y la Regla de los Días Siguientes (7 días de lookahead).
        """
        conn = Database.get_connection()
        conn.autocommit = False  # Asegurar control de transacción manual
        from psycopg2.extras import RealDictCursor
        cursor = None
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Obtener y bloquear la cita liberada para validar estado e id_especialidad del médico
            cursor.execute(
                """
                SELECT a.id_cita, a.rango_cita, a.estado, a.id_paciente, d.id_especialidad, d.nombre_completo as doctor_nombre
                FROM appointments a
                JOIN doctors d ON a.id_medico = d.id_medico
                WHERE a.id_cita = %s
                FOR UPDATE;
                """,
                (id_cita,)
            )
            appointment = cursor.fetchone()
            if not appointment:
                print(f"[LEA ENGINE] Cita {id_cita} no encontrada.")
                conn.rollback()
                return None

            # Desempaquetar los datos devueltos por el cursor (RealDictCursor)
            id_cita = appointment['id_cita']
            rango_cita = appointment['rango_cita']  # psycopg2 DateTimeTZRange
            estado_actual = appointment['estado']
            id_paciente_actual = appointment['id_paciente']
            id_especialidad = appointment['id_especialidad']
            doctor_nombre = appointment['doctor_nombre']

            # Si el slot ya tiene un paciente asignado y no está en estado para reasignar
            if id_paciente_actual is not None and estado_actual != 'Cancelada':
                print(f"[LEA ENGINE] Cita {id_cita} ya se encuentra ocupada por paciente {id_paciente_actual}.")
                conn.rollback()
                return None

            # 2. Aplicar la REGLA DE LAS 2 HORAS
            # Si el inicio de la cita es hoy, debe haber una diferencia de al menos 2 horas.
            # En psycopg2, rango_cita.lower es un objeto datetime con zona horaria UTC.
            cita_inicio = rango_cita.lower
            now_utc = datetime.now(timezone.utc)

            if cita_inicio.date() == now_utc.date():
                time_diff = cita_inicio - now_utc
                if time_diff < timedelta(hours=2):
                    print(f"[LEA ENGINE] Cita {id_cita} no es elegible para asignación automática por Regla de las 2 Horas (Falta menos de 2h).")
                    conn.rollback()
                    return None

            fecha_cita_date = cita_inicio.date()

            # 3. Buscar paciente elegible utilizando FOR UPDATE SKIP LOCKED
            # Orden estricto FIFO por created_at ASC
            cursor.execute(
                """
                SELECT wl.id_espera, wl.id_paciente, wl.tipo_cola, wl.rango_deseado, p.telefono, p.nombre_completo as paciente_nombre
                FROM waiting_list wl
                JOIN patients p ON wl.id_paciente = p.id_paciente
                WHERE wl.estado = 'Pendiente'
                  AND wl.id_especialidad = %s
                  AND (
                      wl.tipo_cola = 'FechaCercana'
                      OR (
                          wl.tipo_cola = 'RangoEspecifico'
                          AND wl.rango_deseado @> %s::date
                      )
                      OR (
                          wl.tipo_cola = 'RangoEspecifico'
                          AND %s::date > upper(wl.rango_deseado)
                          AND %s::date <= upper(wl.rango_deseado) + INTEGER '7'
                      )
                  )
                ORDER BY wl.created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED;
                """,
                (id_especialidad, fecha_cita_date, fecha_cita_date, fecha_cita_date)
            )
            candidate = cursor.fetchone()

            if not candidate:
                print(f"[LEA ENGINE] No hay pacientes elegibles en la lista de espera para la cita {id_cita}.")
                conn.rollback()
                return None

            id_espera = candidate['id_espera']
            id_paciente_elegido = candidate['id_paciente']
            paciente_nombre = candidate['paciente_nombre']
            telefono_paciente = candidate['telefono']

            # 4. Asignar el paciente a la cita
            cursor.execute(
                """
                UPDATE appointments
                SET id_paciente = %s, estado = 'Agendada', updated_at = CURRENT_TIMESTAMP
                WHERE id_cita = %s;
                """,
                (id_paciente_elegido, id_cita)
            )

            # 5. Cambiar el estado del paciente en la lista de espera
            cursor.execute(
                """
                UPDATE waiting_list
                SET estado = 'Asignada', updated_at = CURRENT_TIMESTAMP
                WHERE id_espera = %s;
                """,
                (id_espera,)
            )

            # 6. Registrar en el historial de citas (Appointments History)
            cambios_dict = {
                "id_paciente": {"old": None, "new": str(id_paciente_elegido)},
                "estado": {"old": estado_actual, "new": "Agendada"}
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
                    'Agendada',
                    'Asignacion',
                    realizado_por,
                    usuario_identificador,
                    json.dumps(cambios_dict)
                )
            )

            # Confirmar la transacción atómicamente
            conn.commit()
            print(f"[LEA ENGINE] Cita {id_cita} asignada de forma atómica al Paciente {paciente_nombre} ({id_paciente_elegido}).")

            # 7. Disparar notificación SMS de forma simulada
            mensaje_sms = f"Hola {paciente_nombre}, se te ha asignado una cita médica con el Dr(a). {doctor_nombre} para el {cita_inicio.strftime('%d/%m/%Y a las %H:%M UTC')}."
            NotificationService.send_sms_notification(id_paciente_elegido, telefono_paciente, mensaje_sms)

            return id_paciente_elegido

        except Exception as e:
            if conn:
                conn.rollback()
            print(f"[LEA ENGINE] Error crítico durante la asignación del slot: {e}")
            raise e
        finally:
            if cursor:
                cursor.close()
            if conn:
                Database.release_connection(conn)
