# ============================================================================
# ARCHIVO: services/waiting_list_engine.py
# PROPÓSITO: Motor de Lista de Espera Automática (LEA).
#
# Administra la cola FIFO de pacientes elegibles ante la liberación de slots.
# Implementa concurrencia pesimista FOR UPDATE SKIP LOCKED y reglas de negocio
# parametrizadas dinámicamente desde la base de datos (CTE y SQL en caliente).
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
        Aplica la Regla de Amortiguación Dinámica y Lookahead desde system_parameters.
        Incorporate prioritariamente coincidencia exacta de slots para cancelaciones masivas.
        """
        conn = Database.get_connection()
        conn.autocommit = False  # Asegurar control de transacción manual
        from psycopg2.extras import RealDictCursor
        cursor = None
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Obtener y bloquear la cita liberada para validar estado, id_sede e id_especialidad del médico
            cursor.execute(
                """
                SELECT a.id_cita, a.rango_cita, a.estado, a.id_paciente, a.id_sede, 
                       d.id_especialidad, d.nombre_completo as doctor_nombre
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

            # Desempaquetar los datos devueltos por el cursor
            id_cita = appointment['id_cita']
            rango_cita = appointment['rango_cita']  # psycopg2 DateTimeTZRange
            estado_actual = appointment['estado']
            id_paciente_actual = appointment['id_paciente']
            id_sede = appointment['id_sede']
            id_especialidad = appointment['id_especialidad']
            doctor_nombre = appointment['doctor_nombre']

            # Si el slot ya tiene un paciente asignado y no está en estado para reasignar (que es 'Agendada' con paciente = NULL)
            if id_paciente_actual is not None and estado_actual != 'Cancelada':
                print(f"[LEA ENGINE] Cita {id_cita} ya se encuentra ocupada por paciente {id_paciente_actual}.")
                conn.rollback()
                return None

            # 2. Aplicar la REGLA DE AMORTIGUACIÓN DINÁMICA (antigua Regla de las 2 Horas)
            # Consultar el parámetro 'buffer_horas' en caliente
            cursor.execute(
                "SELECT param_value::int as buffer_horas FROM system_parameters WHERE param_key = 'buffer_horas';"
            )
            row_param = cursor.fetchone()
            buffer_horas = row_param['buffer_horas'] if row_param else 2

            cita_inicio = rango_cita.lower
            now_utc = datetime.now(timezone.utc)

            if cita_inicio.date() == now_utc.date():
                time_diff = cita_inicio - now_utc
                if time_diff < timedelta(hours=buffer_horas):
                    print(
                        f"[LEA ENGINE] Cita {id_cita} no es elegible para asignación automática por Regla de "
                        f"Amortiguación Dinámica (Falta menos de {buffer_horas} horas)."
                    )
                    conn.rollback()
                    return None

            fecha_cita_date = cita_inicio.date()

            # 3. PRIORITY CHECK: Coincidencia Exacta de Slot para Pacientes Cancelados Masivamente
            # Si hay un paciente cuya cita fue cancelada exactamente en este mismo rango y sede, y sigue en lista de espera
            cursor.execute(
                """
                SELECT wl.id_espera, wl.id_paciente, p.telefono, p.nombre_completo as paciente_nombre
                FROM appointments a
                JOIN waiting_list wl ON a.id_paciente = wl.id_paciente
                JOIN patients p ON wl.id_paciente = p.id_paciente
                WHERE a.rango_cita = %s
                  AND a.id_sede = %s
                  AND a.estado = 'Cancelada'
                  AND wl.estado = 'Pendiente'
                  AND wl.id_especialidad = %s
                  AND wl.id_sede = %s
                LIMIT 1
                FOR UPDATE SKIP LOCKED;
                """,
                (rango_cita, id_sede, id_especialidad, id_sede)
            )
            priority_candidate = cursor.fetchone()

            if priority_candidate:
                id_espera = priority_candidate['id_espera']
                id_paciente_elegido = priority_candidate['id_paciente']
                paciente_nombre = priority_candidate['paciente_nombre']
                telefono_paciente = priority_candidate['telefono']
                print(f"[LEA ENGINE] Coincidencia exacta detectada para paciente cancelado {paciente_nombre} ({id_paciente_elegido}).")
            else:
                # 4. FIFO GENERAL CHECK con CTE parametrizado en caliente
                cursor.execute(
                    """
                    WITH params AS (
                        SELECT 
                            (SELECT param_value::int FROM system_parameters WHERE param_key = 'lookahead_dias') AS look_d
                    )
                    SELECT wl.id_espera, wl.id_paciente, wl.tipo_cola, wl.rango_deseado, p.telefono, p.nombre_completo as paciente_nombre
                    FROM waiting_list wl
                    JOIN patients p ON wl.id_paciente = p.id_paciente
                    CROSS JOIN params
                    WHERE wl.estado = 'Pendiente'
                      AND wl.id_especialidad = %s
                      AND wl.id_sede = %s
                      AND (
                          wl.tipo_cola = 'FechaCercana'
                          OR (
                              wl.tipo_cola = 'RangoEspecifico'
                              AND wl.rango_deseado @> %s::date
                          )
                          OR (
                              wl.tipo_cola = 'RangoEspecifico'
                              AND %s::date > upper(wl.rango_deseado)
                              AND %s::date <= upper(wl.rango_deseado) + params.look_d
                          )
                      )
                    ORDER BY wl.created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED;
                    """,
                    (id_especialidad, id_sede, fecha_cita_date, fecha_cita_date, fecha_cita_date)
                )
                candidate = cursor.fetchone()

                if not candidate:
                    print(f"[LEA ENGINE] No hay pacientes elegibles en la lista de espera para la cita {id_cita} en sede {id_sede}.")
                    conn.rollback()
                    return None

                id_espera = candidate['id_espera']
                id_paciente_elegido = candidate['id_paciente']
                paciente_nombre = candidate['paciente_nombre']
                telefono_paciente = candidate['telefono']

            # 5. Asignar el paciente a la cita
            cursor.execute(
                """
                UPDATE appointments
                SET id_paciente = %s, estado = 'Agendada', updated_at = CURRENT_TIMESTAMP
                WHERE id_cita = %s;
                """,
                (id_paciente_elegido, id_cita)
            )

            # 6. Cambiar el estado del paciente en la lista de espera
            cursor.execute(
                """
                UPDATE waiting_list
                SET estado = 'Asignada', updated_at = CURRENT_TIMESTAMP
                WHERE id_espera = %s;
                """,
                (id_espera,)
            )

            # 7. Registrar en el historial de citas (Appointments History)
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

            # 8. Disparar notificación SMS de forma simulada
            mensaje_sms = (
                f"Hola {paciente_nombre}, se te ha asignado una cita médica con el Dr(a). {doctor_nombre} "
                f"para el {cita_inicio.strftime('%d/%m/%Y a las %H:%M UTC')}."
            )
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
