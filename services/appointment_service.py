# ============================================================================
# ARCHIVO: services/appointment_service.py
# PROPÓSITO: Servicio centralizado de Citas Médicas del SGCM.
#
# Administra el ciclo de vida de las citas (cancelación, agendamiento, cambio de sede)
# e implementa la lógica de cancelaciones masivas con reportes en disco (blob local)
# y reglas clínicas complejas (amortiguación, inasistencia, doble reserva).
# ============================================================================

import os
import csv
import json
from datetime import datetime, timezone, timedelta
from database import Database
from services.waiting_list_engine import WaitingListEngine
from services.permission_service import PermissionService


class AppointmentService:
    """
    Servicio encargado de la lógica transaccional de citas clínicas,
    garantizando validaciones de geografía, tiempo, inasistencias y autorizaciones.
    """

    @staticmethod
    def cancel_appointment(id_cita, realizado_por, usuario_identificador):
        """
        Cancela una cita asignada. Si es realizada por el Paciente,
        se valida la regla de amortiguación horaria dinámica ('buffer_horas').
        """
        conn = Database.get_connection()
        conn.autocommit = False
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

            if estado_actual == 'Cancelada' and id_paciente is None:
                conn.commit()
                print(f"[AppointmentService] Cita {id_cita} ya se encuentra cancelada.")
                return True

            # 2. Validar regla de Amortiguación Dinámica si es cancelada por el propio Paciente
            if realizado_por == 'Paciente':
                # Validar propiedad
                if not id_paciente or str(id_paciente) != str(usuario_identificador):
                    raise PermissionError("No está autorizado para cancelar una cita asignada a otro paciente.")

                # Consultar buffer_horas
                cursor.execute(
                    "SELECT param_value::int as buffer_horas FROM system_parameters WHERE param_key = 'buffer_horas';"
                )
                row_param = cursor.fetchone()
                buffer_horas = row_param['buffer_horas'] if row_param else 2

                cita_inicio = rango_cita.lower
                now_utc = datetime.now(timezone.utc)
                if cita_inicio - now_utc < timedelta(hours=buffer_horas):
                    raise PermissionError(
                        f"Las cancelaciones por parte del paciente deben realizarse con al menos {buffer_horas} horas de anticipación."
                    )

            # 3. Liberar el slot de la cita: id_paciente = NULL, estado = 'Agendada'
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

            conn.commit()
            print(f"[AppointmentService] Cita {id_cita} desvinculada y liberada con éxito por {realizado_por}.")

            # 5. Activar el motor LEA reactivamente
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

    @staticmethod
    def change_appointment_branch(id_cita, id_sede_destino, realizado_por, usuario_identificador):
        """
        Cambia la sede física asignada a una cita.
        Aplica validación de geografía estricta: la sede de destino debe estar en la misma ciudad de origen del paciente.
        """
        conn = Database.get_connection()
        conn.autocommit = False
        from psycopg2.extras import RealDictCursor
        cursor = None
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Obtener y bloquear la cita
            cursor.execute(
                """
                SELECT a.id_cita, a.id_sede, a.id_paciente, a.estado, p.ciudad_origen
                FROM appointments a
                LEFT JOIN patients p ON a.id_paciente = p.id_paciente
                WHERE a.id_cita = %s
                FOR UPDATE OF a;
                """,
                (id_cita,)
            )
            appointment = cursor.fetchone()
            if not appointment:
                raise ValueError(f"Cita con ID {id_cita} no encontrada.")

            id_sede_anterior = appointment['id_sede']
            id_paciente = appointment['id_paciente']
            ciudad_paciente = appointment['ciudad_origen']
            estado_actual = appointment['estado']

            if not id_paciente:
                raise ValueError("No se puede cambiar de sede una cita que no tiene un paciente asignado.")

            # 2. Consultar ciudad de la sede de destino
            cursor.execute(
                "SELECT nombre, ciudad FROM branches WHERE id_sede = %s AND activa = TRUE;",
                (id_sede_destino,)
            )
            sede_destino = cursor.fetchone()
            if not sede_destino:
                raise ValueError(f"La sede de destino {id_sede_destino} no existe o no está activa.")

            ciudad_destino = sede_destino['ciudad']

            # 3. Validar geografía estricta
            if ciudad_paciente.strip().lower() != ciudad_destino.strip().lower():
                raise ValueError(
                    f"Restricción geográfica: El paciente reside en '{ciudad_paciente}' y la sede de destino se "
                    f"encuentra en la ciudad '{ciudad_destino}'."
                )

            # 4. Actualizar sede
            cursor.execute(
                """
                UPDATE appointments
                SET id_sede = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id_cita = %s;
                """,
                (id_sede_destino, id_cita)
            )

            # 5. Auditoría
            cambios_dict = {
                "id_sede": {"old": str(id_sede_anterior), "new": str(id_sede_destino)}
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
                    estado_actual,
                    'Modificacion',
                    realizado_por,
                    str(usuario_identificador),
                    json.dumps(cambios_dict)
                )
            )

            conn.commit()
            print(f"[AppointmentService] Cita {id_cita} trasladada a la sede {sede_destino['nombre']}.")
            return True

        except Exception as e:
            if conn:
                conn.rollback()
            print(f"[AppointmentService] Error crítico al cambiar de sede de la cita {id_cita}: {e}")
            raise e
        finally:
            if cursor:
                cursor.close()
            if conn:
                Database.release_connection(conn)

    @staticmethod
    def execute_massive_cancellation(id_sede, id_medico, realizado_por, id_usuario_ejecutor, auto_reschedule=True):
        """
        Cancela de forma masiva y atómica las futuras citas asignadas a una sede y/o médico.
        Genera y persiste localmente un reporte de evidencia CSV en 'storage/reports/'.
        Auto-reprograma a los pacientes afectados a la lista de espera con prioridad cronológica.
        """
        # Validar permisos delegados en tiempo real
        if not PermissionService.check_permission(id_usuario_ejecutor, 'can_execute_massive_cancellations'):
            raise PermissionError("No cuenta con permisos autorizados para ejecutar cancelaciones masivas.")

        if not id_sede and not id_medico:
            raise ValueError("Debe especificar al menos una sede o un médico para la cancelación masiva.")

        conn = Database.get_connection()
        conn.autocommit = False
        from psycopg2.extras import RealDictCursor
        cursor = None
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Buscar citas futuras afectadas (hora inicio > NOW())
            query_buscar = """
                SELECT a.id_cita, a.rango_cita, a.estado, a.id_paciente, a.id_sede, a.id_medico,
                       p.nombre_completo as paciente_nombre, p.dni as paciente_dni,
                       d.nombre_completo as doctor_nombre, d.id_especialidad,
                       s.nombre as sede_nombre
                FROM appointments a
                LEFT JOIN patients p ON a.id_paciente = p.id_paciente
                JOIN doctors d ON a.id_medico = d.id_medico
                JOIN branches s ON a.id_sede = s.id_sede
                WHERE lower(rango_cita) > CURRENT_TIMESTAMP
                  AND a.estado NOT IN ('Cancelada', 'Finalizada', 'NoAsistio')
            """
            params = []
            if id_sede:
                query_buscar += " AND a.id_sede = %s"
                params.append(id_sede)
            if id_medico:
                query_buscar += " AND a.id_medico = %s"
                params.append(id_medico)

            query_buscar += " FOR UPDATE OF a;"

            cursor.execute(query_buscar, tuple(params))
            citas_afectadas = cursor.fetchall()

            if not citas_afectadas:
                print("[Massive Cancellation] No se encontraron citas futuras activas que afecte esta contingencia.")
                conn.commit()
                return None, 0

            # 2. Generar Reporte CSV de Evidencia
            os.makedirs("storage/reports", exist_ok=True)
            report_filename = f"reporte_cancelacion_masiva_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{id_usuario_ejecutor}.csv"
            report_path = os.path.join("storage", "reports", report_filename)

            with open(report_path, mode="w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["ID Cita", "Paciente Nombre", "Paciente DNI", "Médico Nombre", "Fecha Hora Inicio", "Sede Nombre"])
                for cita in citas_afectadas:
                    cita_inicio = cita['rango_cita'].lower.strftime("%d/%m/%Y %H:%M %Z")
                    writer.writerow([
                        str(cita['id_cita']),
                        cita['paciente_nombre'] or "Sin asignar",
                        cita['paciente_dni'] or "N/A",
                        cita['doctor_nombre'],
                        cita_inicio,
                        cita['sede_nombre']
                    ])

            # 3. Cancelar las citas físicamente en la BD y re-programar en cola
            cantidad_canceladas = 0
            for cita in citas_afectadas:
                id_cita_c = cita['id_cita']
                estado_anterior = cita['estado']
                id_paciente_c = cita['id_paciente']

                # Actualizar estado a Cancelada (conservamos id_paciente para trazabilidad y prioridad en LEA)
                cursor.execute(
                    """
                    UPDATE appointments
                    SET estado = 'Cancelada', updated_at = CURRENT_TIMESTAMP
                    WHERE id_cita = %s;
                    """,
                    (id_cita_c,)
                )

                # Registrar auditoría de cancelación
                cambios_dict = {"estado": {"old": estado_anterior, "new": "Cancelada"}}
                cursor.execute(
                    """
                    INSERT INTO appointments_history (
                        id_cita, estado_anterior, estado_nuevo, tipo_accion,
                        realizado_por, usuario_identificador, cambios
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb);
                    """,
                    (
                        id_cita_c,
                        estado_anterior,
                        'Cancelada',
                        'Cancelacion',
                        realizado_por,
                        str(id_usuario_ejecutor),
                        json.dumps(cambios_dict)
                    )
                )

                cantidad_canceladas += 1

                # Re-programación automática en lista de espera
                if auto_reschedule and id_paciente_c:
                    # Se inyecta en la lista de espera con prioridad cronológica
                    # utilizando la hora de inicio de su cita cancelada como 'created_at'
                    cita_inicio_dt = cita['rango_cita'].lower
                    cursor.execute(
                        """
                        INSERT INTO waiting_list (
                            id_paciente, id_especialidad, id_sede, tipo_cola, estado, created_at
                        ) VALUES (%s, %s, %s, 'FechaCercana', 'Pendiente', %s);
                        """,
                        (id_paciente_c, cita['id_especialidad'], cita['id_sede'], cita_inicio_dt)
                    )

            # 4. Registrar la cancelación masiva en la tabla de auditoría
            cursor.execute(
                """
                INSERT INTO massive_cancellations (
                    id_sede, id_medico, cantidad_canceladas, auto_reschedule, reporte_path, ejecutado_por
                ) VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id_cancelacion;
                """,
                (id_sede, id_medico, cantidad_canceladas, auto_reschedule, report_path, id_usuario_ejecutor)
            )
            id_cancelacion = cursor.fetchone()['id_cancelacion']

            conn.commit()
            print(f"[Massive Cancellation] Cancelación masiva {id_cancelacion} completada con éxito. {cantidad_canceladas} citas afectadas.")
            return report_path, cantidad_canceladas

        except Exception as e:
            if conn:
                conn.rollback()
            print(f"[Massive Cancellation] Error crítico en cancelación masiva: {e}")
            raise e
        finally:
            if cursor:
                cursor.close()
            if conn:
                Database.release_connection(conn)

    @staticmethod
    def book_appointment(id_cita, id_paciente, realizado_por, usuario_identificador):
        """
        Reserva y asigna una cita a un paciente.
        Valida reglas de negocio: solapamiento del paciente, inasistencia reiterada,
        doble reserva por especialidad (con autorizaciones médicas) y tiempo de traslado inter-sede.
        """
        conn = Database.get_connection()
        conn.autocommit = False
        from psycopg2.extras import RealDictCursor
        cursor = None
        try:
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            # 1. Obtener y bloquear la cita para actualización
            cursor.execute(
                """
                SELECT a.id_cita, a.rango_cita, a.estado, a.id_sede, a.id_medico,
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
                raise ValueError(f"Cita con ID {id_cita} no encontrada.")

            rango_cita = appointment['rango_cita']
            estado_actual = appointment['estado']
            id_sede = appointment['id_sede']
            id_medico = appointment['id_medico']
            id_especialidad = appointment['id_especialidad']

            if appointment['estado'] != 'Agendada':
                raise ValueError("La cita seleccionada no está disponible para reserva.")

            # 2. Consultar parámetros del sistema en caliente
            cursor.execute(
                """
                SELECT param_key, param_value::int as val
                FROM system_parameters
                WHERE param_key IN (
                    'tolerancia_retraso_minutos', 'minutos_traslado_sedes',
                    'max_inasistencias_consecutivas', 'dias_bloqueo_inasistencia'
                );
                """
            )
            params = {r['param_key']: r['val'] for r in cursor.fetchall()}
            minutos_traslado_sedes = params.get('minutos_traslado_sedes', 60)
            max_inasistencias_consecutivas = params.get('max_inasistencias_consecutivas', 3)
            dias_bloqueo_inasistencia = params.get('dias_bloqueo_inasistencia', 15)

            # 3. Validar restricción de solapamiento temporal del paciente
            cursor.execute(
                """
                SELECT id_cita FROM appointments
                WHERE id_paciente = %s
                  AND rango_cita && %s::tstzrange
                  AND estado IN ('Agendada', 'Confirmada', 'EnCurso');
                """,
                (id_paciente, rango_cita)
            )
            overlapping = cursor.fetchone()
            if overlapping:
                raise ValueError("El paciente ya tiene una cita médica programada que se solapa temporalmente.")

            # 4. Validar inasistencia reiterada y suspensión temporal
            # Obtener las últimas 'max_inasistencias_consecutivas' citas ordenadas por rango_cita DESC
            cursor.execute(
                """
                SELECT estado, rango_cita
                FROM appointments
                WHERE id_paciente = %s
                  AND estado IN ('Confirmada', 'EnCurso', 'Finalizada', 'NoAsistio')
                ORDER BY rango_cita DESC
                LIMIT %s;
                """,
                (id_paciente, max_inasistencias_consecutivas)
            )
            recent_apts = cursor.fetchall()
            if len(recent_apts) == max_inasistencias_consecutivas and all(r['estado'] == 'NoAsistio' for r in recent_apts):
                # El paciente tiene inasistencias consecutivas
                # Verificar si el último 'NoAsistio' fue hace menos de 'dias_bloqueo_inasistencia'
                ultimo_no_asistio_fin = recent_apts[0]['rango_cita'].upper
                now_utc = datetime.now(timezone.utc)
                if now_utc - ultimo_no_asistio_fin < timedelta(days=dias_bloqueo_inasistencia):
                    # Solo bloqueamos el auto-agendamiento autónomo del Paciente
                    if realizado_por == 'Paciente':
                        raise PermissionError(
                            f"El paciente tiene suspendido el auto-agendamiento autónomo por acumular "
                            f"{max_inasistencias_consecutivas} inasistencias consecutivas. Debe agendar vía recepcionista."
                        )

            # 5. Validar regla de doble reserva activa y autorización médica
            cursor.execute(
                """
                SELECT COUNT(*) as active_count
                FROM appointments a
                JOIN doctors d ON a.id_medico = d.id_medico
                WHERE a.id_paciente = %s
                  AND d.id_especialidad = %s
                  AND a.estado IN ('Agendada', 'Confirmada', 'EnCurso');
                """,
                (id_paciente, id_especialidad)
            )
            active_count = cursor.fetchone()['active_count']
            if active_count > 0:
                # El paciente ya tiene una cita activa. Requiere autorización
                cursor.execute(
                    """
                    SELECT id_autorizacion, sesiones_totales, sesiones_consumidas
                    FROM medical_authorizations
                    WHERE id_paciente = %s
                      AND id_especialidad_dest = %s
                      AND estado = 'Activa'
                      AND sesiones_consumidas < sesiones_totales
                    FOR UPDATE;
                    """,
                    (id_paciente, id_especialidad)
                )
                auth = cursor.fetchone()
                if not auth:
                    raise ValueError(
                        "El paciente ya posee una cita programada activa para esta especialidad. "
                        "Requiere autorización médica firmada por derivación de múltiples sesiones."
                    )
                # Consumir una sesión de la autorización clínica
                id_auth = auth['id_autorizacion']
                nuevas_consumidas = auth['sesiones_consumidas'] + 1
                nuevo_estado_auth = 'Activa'
                if nuevas_consumidas >= auth['sesiones_totales']:
                    nuevo_estado_auth = 'Consumida'

                cursor.execute(
                    """
                    UPDATE medical_authorizations
                    SET sesiones_consumidas = %s, estado = %s
                    WHERE id_autorizacion = %s;
                    """,
                    (nuevas_consumidas, nuevo_estado_auth, id_auth)
                )

            # 6. Validar tiempo de traslado inter-sede el mismo día (si aplica)
            cita_inicio = rango_cita.lower
            cita_fin = rango_cita.upper

            cursor.execute(
                """
                SELECT id_cita, id_sede, rango_cita
                FROM appointments
                WHERE id_paciente = %s
                  AND id_sede != %s
                  AND estado IN ('Agendada', 'Confirmada', 'EnCurso')
                  AND rango_cita && tstzrange(%s::timestamptz - %s::interval, %s::timestamptz + %s::interval);
                """,
                (
                    id_paciente,
                    id_sede,
                    cita_inicio,
                    f"{minutos_traslado_sedes} minutes",
                    cita_fin,
                    f"{minutos_traslado_sedes} minutes"
                )
            )
            travel_clash = cursor.fetchone()
            if travel_clash:
                raise ValueError(
                    f"Tiempo de traslado inter-sede insuficiente. El paciente tiene otra cita activa programada "
                    f"en otra sede y se requiere un margen mínimo de {minutos_traslado_sedes} minutos para viajar."
                )

            # 7. Asignar el paciente a la cita
            cursor.execute(
                """
                UPDATE appointments
                SET id_paciente = %s, estado = 'Agendada', updated_at = CURRENT_TIMESTAMP
                WHERE id_cita = %s;
                """,
                (id_paciente, id_cita)
            )

            # 8. Registrar en el historial de citas
            cambios_dict = {
                "id_paciente": {"old": None, "new": str(id_paciente)}
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
                    str(usuario_identificador),
                    json.dumps(cambios_dict)
                )
            )

            conn.commit()
            print(f"[AppointmentService] Cita {id_cita} reservada con éxito para paciente {id_paciente}.")
            return True

        except Exception as e:
            if conn:
                conn.rollback()
            print(f"[AppointmentService] Error crítico al reservar cita {id_cita}: {e}")
            raise e
        finally:
            if cursor:
                cursor.close()
            if conn:
                Database.release_connection(conn)
