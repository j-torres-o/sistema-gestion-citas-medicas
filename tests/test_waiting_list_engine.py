# ============================================================================
# ARCHIVO: tests/test_waiting_list_engine.py
# PROPÓSITO: Pruebas unitarias e integrales para el motor LEA y AppointmentService.
# ============================================================================

import os
import csv
import json
from datetime import datetime, timezone, timedelta
import pytest
from psycopg2.extras import RealDictCursor
from database import Database
from services.waiting_list_engine import WaitingListEngine
from services.appointment_service import AppointmentService
from services.permission_service import PermissionService


def clean_tables():
    """
    Limpia los registros de las tablas para garantizar pruebas aisladas y deterministas.
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("DELETE FROM appointments_history;")
            cursor.execute("DELETE FROM appointments;")
            cursor.execute("DELETE FROM waiting_list;")
            cursor.execute("DELETE FROM medical_authorizations;")
            cursor.execute("DELETE FROM massive_cancellations;")
            cursor.execute("DELETE FROM permissions_delegation;")
            cursor.execute("DELETE FROM patients;")
            cursor.execute("DELETE FROM doctors;")
            cursor.execute("DELETE FROM specialties;")
            cursor.execute("DELETE FROM users;")
            cursor.execute("DELETE FROM branches;")
            cursor.execute("DELETE FROM system_parameters;")
        conn.commit()
    finally:
        Database.release_connection(conn)


@pytest.fixture(autouse=True)
def setup_clean_db():
    clean_tables()
    # Inyectar parámetros base por defecto para que las pruebas pasen sin fallas
    conn = Database.get_connection()
    try:
        with conn.cursor() as cursor:
            parameters = [
                ("buffer_horas", "2", "Límite de amortiguación horaria"),
                ("lookahead_dias", "7", "Días máximos de lookahead"),
                ("tolerancia_retraso_minutos", "15", "Tolerancia de retraso"),
                ("minutos_traslado_sedes", "60", "Intervalo mínimo de traslado"),
                ("max_inasistencias_consecutivas", "3", "Inasistencias consecutivas antes de bloqueo"),
                ("dias_bloqueo_inasistencia", "15", "Días de suspensión temporal")
            ]
            for key, val, desc in parameters:
                cursor.execute(
                    "INSERT INTO system_parameters (param_key, param_value, descripcion) VALUES (%s, %s, %s);",
                    (key, val, desc)
                )
        conn.commit()
    finally:
        Database.release_connection(conn)
    yield
    clean_tables()


def test_lea_engine_fifo_assignment_success():
    """
    Valida que el motor LEA asigne un slot libre al primer paciente en cola de espera (FIFO).
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Crear Sede
            cursor.execute(
                "INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede Poblado', 'Medellin', 'Calle 10') RETURNING id_sede;"
            )
            id_sede = cursor.fetchone()['id_sede']

            # 2. Crear Especialidad
            cursor.execute(
                "INSERT INTO specialties (nombre, descripcion) VALUES ('Oftalmologia', 'Cuidado de ojos') RETURNING id_especialidad;"
            )
            id_especialidad = cursor.fetchone()['id_especialidad']

            # 3. Crear Médico
            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad) VALUES ('Dr. Oftalmo', 'LIC-1002', %s) RETURNING id_medico;",
                (id_especialidad,)
            )
            id_medico = cursor.fetchone()['id_medico']

            # 4. Crear Pacientes
            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) VALUES ('7010', 'Paciente Uno', '555-1111', 'uno@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_paciente_1 = cursor.fetchone()['id_paciente']

            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) VALUES ('7020', 'Paciente Dos', '555-2222', 'dos@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_paciente_2 = cursor.fetchone()['id_paciente']

            # 5. Registrar en lista de espera (Paciente 1 se registra antes que Paciente 2 - FIFO)
            cursor.execute(
                "INSERT INTO waiting_list (id_paciente, id_especialidad, id_sede, tipo_cola, estado, created_at) VALUES (%s, %s, %s, 'FechaCercana', 'Pendiente', NOW() - INTERVAL '10 minutes') RETURNING id_espera;",
                (id_paciente_1, id_especialidad, id_sede)
            )
            id_espera_1 = cursor.fetchone()['id_espera']

            cursor.execute(
                "INSERT INTO waiting_list (id_paciente, id_especialidad, id_sede, tipo_cola, estado, created_at) VALUES (%s, %s, %s, 'FechaCercana', 'Pendiente', NOW()) RETURNING id_espera;",
                (id_paciente_2, id_especialidad, id_sede)
            )
            id_espera_2 = cursor.fetchone()['id_espera']

            # 6. Crear slot disponible (Cita para mañana - pasa regla de las 2 horas)
            tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
            tomorrow_start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
            tomorrow_end = tomorrow_start + timedelta(minutes=30)
            rango_cita_str = f"[{tomorrow_start.isoformat()}, {tomorrow_end.isoformat()}]"

            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, NULL, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, id_sede, rango_cita_str)
            )
            id_cita = cursor.fetchone()['id_cita']

        conn.commit()

        # 7. Disparar el motor LEA
        assigned_patient = WaitingListEngine.handle_liberated_slot(id_cita)

        # 8. Validar asignación FIFO al Paciente 1 (el más antiguo)
        assert assigned_patient == id_paciente_1

        # Validar base de datos
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT id_paciente, estado FROM appointments WHERE id_cita = %s;", (id_cita,))
            apt = cursor.fetchone()
            assert apt['id_paciente'] == id_paciente_1
            assert apt['estado'] == 'Agendada'

    finally:
        Database.release_connection(conn)


def test_lea_engine_two_hour_rule_prevents_assignment():
    """
    Valida que la regla de las 2 horas (amortiguación) prevenga la auto-asignación si el slot inicia hoy en < 2h.
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede Poblado', 'Medellin', 'Calle 10') RETURNING id_sede;"
            )
            id_sede = cursor.fetchone()['id_sede']

            cursor.execute(
                "INSERT INTO specialties (nombre, descripcion) VALUES ('Neurologia', 'Cuidado del cerebro') RETURNING id_especialidad;"
            )
            id_especialidad = cursor.fetchone()['id_especialidad']

            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad) VALUES ('Dr. Neuro', 'LIC-1003', %s) RETURNING id_medico;",
                (id_especialidad,)
            )
            id_medico = cursor.fetchone()['id_medico']

            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) VALUES ('7030', 'Paciente Tres', '555-3333', 'tres@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_paciente = cursor.fetchone()['id_paciente']

            cursor.execute(
                "INSERT INTO waiting_list (id_paciente, id_especialidad, id_sede, tipo_cola, estado) VALUES (%s, %s, %s, 'FechaCercana', 'Pendiente');",
                (id_paciente, id_especialidad, id_sede)
            )

            # Slot que empieza hoy en 30 minutos (invalida asignación automática de las 2 horas)
            in_30_min = datetime.now(timezone.utc) + timedelta(minutes=30)
            in_60_min = in_30_min + timedelta(minutes=30)
            rango_cita_str = f"[{in_30_min.isoformat()}, {in_60_min.isoformat()}]"

            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, NULL, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, id_sede, rango_cita_str)
            )
            id_cita = cursor.fetchone()['id_cita']

        conn.commit()

        # Disparar motor LEA
        res = WaitingListEngine.handle_liberated_slot(id_cita)

        # No debe haber asignado a nadie
        assert res is None

    finally:
        Database.release_connection(conn)


def test_appointment_cancellation_buffer_rule():
    """
    Valida la regla de amortiguación horaria dinámica para cancelaciones realizadas por el propio paciente.
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede Poblado', 'Medellin', 'Calle 10') RETURNING id_sede;"
            )
            id_sede = cursor.fetchone()['id_sede']

            cursor.execute(
                "INSERT INTO specialties (nombre, descripcion) VALUES ('Cardiologia', 'Cardio') RETURNING id_especialidad;"
            )
            id_especialidad = cursor.fetchone()['id_especialidad']

            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad) VALUES ('Dr. Cardio', 'LIC-1004', %s) RETURNING id_medico;",
                (id_especialidad,)
            )
            id_medico = cursor.fetchone()['id_medico']

            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) VALUES ('7040', 'Paciente Cuatro', '555-4444', 'cuatro@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_paciente = cursor.fetchone()['id_paciente']

            # Caso A: Cita en 1 hora (Debe fallar al cancelar como Paciente si buffer es 2)
            in_1_hour = datetime.now(timezone.utc) + timedelta(hours=1)
            rango_cita_1h = f"[{in_1_hour.isoformat()}, {(in_1_hour + timedelta(minutes=30)).isoformat()}]"
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, %s, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, id_paciente, id_sede, rango_cita_1h)
            )
            id_cita_corta = cursor.fetchone()['id_cita']

            # Caso B: Cita en 10 horas (Debe pasar exitosamente)
            in_10_hours = datetime.now(timezone.utc) + timedelta(hours=10)
            rango_cita_10h = f"[{in_10_hours.isoformat()}, {(in_10_hours + timedelta(minutes=30)).isoformat()}]"
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, %s, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, id_paciente, id_sede, rango_cita_10h)
            )
            id_cita_larga = cursor.fetchone()['id_cita']

        conn.commit()

        # Intentar cancelar Caso A como Paciente (Debe fallar con PermissionError)
        with pytest.raises(PermissionError) as exc_info:
            AppointmentService.cancel_appointment(
                id_cita=id_cita_corta,
                realizado_por='Paciente',
                usuario_identificador=id_paciente
            )
        assert "horas de anticipación" in str(exc_info.value)

        # Cancelar Caso A como Recepcionista (Pasa sin problemas)
        res_recep = AppointmentService.cancel_appointment(
            id_cita=id_cita_corta,
            realizado_por='Recepcionista',
            usuario_identificador='admin@clinica.com'
        )
        assert res_recep is True

        # Cancelar Caso B como Paciente (Pasa exitosamente)
        res_paciente = AppointmentService.cancel_appointment(
            id_cita=id_cita_larga,
            realizado_por='Paciente',
            usuario_identificador=id_paciente
        )
        assert res_paciente is True

    finally:
        Database.release_connection(conn)


def test_appointment_branch_change_geography():
    """
    Valida la restricción geográfica estricta al cambiar la sede de una cita.
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Crear sedes
            cursor.execute("INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede Pob El Poblado', 'Medellin', 'Calle 10') RETURNING id_sede;")
            id_sede_med = cursor.fetchone()['id_sede']

            cursor.execute("INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede Chap Chapinero', 'Bogota', 'Calle 60') RETURNING id_sede;")
            id_sede_bog = cursor.fetchone()['id_sede']

            cursor.execute("INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede Laureles', 'Medellin', 'Av Nutibara') RETURNING id_sede;")
            id_sede_med_2 = cursor.fetchone()['id_sede']

            # Paciente en Medellin
            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) VALUES ('7050', 'Carmen Medellin', '555-5555', 'carmen.med@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_paciente = cursor.fetchone()['id_paciente']

            cursor.execute(
                "INSERT INTO specialties (nombre, descripcion) VALUES ('Dermatologia', 'Piel') RETURNING id_especialidad;"
            )
            id_especialidad = cursor.fetchone()['id_especialidad']

            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad) VALUES ('Dr. Piel', 'LIC-1005', %s) RETURNING id_medico;",
                (id_especialidad,)
            )
            id_medico = cursor.fetchone()['id_medico']

            tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
            t_start = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
            t_end = t_start + timedelta(minutes=30)
            rango_cita = f"[{t_start.isoformat()}, {t_end.isoformat()}]"

            # Crear cita
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, %s, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, id_paciente, id_sede_med, rango_cita)
            )
            id_cita = cursor.fetchone()['id_cita']

        conn.commit()

        # Intentar cambiar sede a Bogotá (Debe fallar con ValueError por restricción de geografía)
        with pytest.raises(ValueError) as exc_info:
            AppointmentService.change_appointment_branch(
                id_cita=id_cita,
                id_sede_destino=id_sede_bog,
                realizado_por='Recepcionista',
                usuario_identificador='recep1@email.com'
            )
        assert "Restricción geográfica" in str(exc_info.value)

        # Cambiar sede a Laureles (Misma ciudad: Medellin, debe tener éxito)
        res = AppointmentService.change_appointment_branch(
            id_cita=id_cita,
            id_sede_destino=id_sede_med_2,
            realizado_por='Recepcionista',
            usuario_identificador='recep1@email.com'
        )
        assert res is True

    finally:
        Database.release_connection(conn)


def test_execute_massive_cancellation_and_chronological_priority():
    """
    Valida la ejecución de una cancelación masiva con exportación de reporte CSV y auto-reprogramación en orden cronológico.
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Crear administrador y delegación
            cursor.execute(
                "INSERT INTO users (username, password_hash, email, rol) VALUES ('superadmin', 'hash', 'admin@clinica.com', 'Admin') RETURNING id_usuario;"
            )
            id_admin = cursor.fetchone()['id_usuario']

            cursor.execute("INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede Central', 'Medellin', 'Centro') RETURNING id_sede;")
            id_sede = cursor.fetchone()['id_sede']

            cursor.execute("INSERT INTO specialties (nombre, descripcion) VALUES ('General', 'Atención Gral') RETURNING id_especialidad;")
            id_especialidad = cursor.fetchone()['id_especialidad']

            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad) VALUES ('Dr. General', 'LIC-3000', %s) RETURNING id_medico;",
                (id_especialidad,)
            )
            id_medico = cursor.fetchone()['id_medico']

            # Pacientes
            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) VALUES ('9001', 'Pac A', '555-9001', 'a@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_pac_a = cursor.fetchone()['id_paciente']

            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) VALUES ('9002', 'Pac B', '555-9002', 'b@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_pac_b = cursor.fetchone()['id_paciente']

            # Citas futuras programadas
            tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
            
            # Paciente A: Cita a las 8:00 AM
            start_a = tomorrow.replace(hour=8, minute=0, second=0, microsecond=0)
            rango_a = f"[{start_a.isoformat()}, {(start_a + timedelta(minutes=30)).isoformat()}]"
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, %s, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, id_pac_a, id_sede, rango_a)
            )

            # Paciente B: Cita a las 9:00 AM (Posterior en tiempo)
            start_b = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
            rango_b = f"[{start_b.isoformat()}, {(start_b + timedelta(minutes=30)).isoformat()}]"
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, %s, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, id_pac_b, id_sede, rango_b)
            )

        conn.commit()

        # Ejecutar cancelación masiva por el Administrador
        report_path, cantidad = AppointmentService.execute_massive_cancellation(
            id_sede=id_sede,
            id_medico=id_medico,
            realizado_por='Sistema',
            id_usuario_ejecutor=id_admin,
            auto_reschedule=True
        )

        assert cantidad == 2
        assert report_path is not None
        assert os.path.exists(report_path)

        # Validar reprogramación cronológica en la lista de espera
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT id_paciente, created_at FROM waiting_list ORDER BY created_at ASC;")
            wl_rows = cursor.fetchall()
            assert len(wl_rows) == 2
            
            # Paciente A (cita a las 8:00) debe estar primero en prioridad temporal que Paciente B (cita a las 9:00)
            assert wl_rows[0]['id_paciente'] == id_pac_a
            assert wl_rows[1]['id_paciente'] == id_pac_b

    finally:
        Database.release_connection(conn)


def test_coincidencia_exacta_priority():
    """
    Valida que un paciente cuya cita fue cancelada masivamente reciba prioridad de coincidencia exacta si se crea un slot idéntico.
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "INSERT INTO users (username, password_hash, email, rol) VALUES ('superadmin2', 'hash', 'admin2@clinica.com', 'Admin') RETURNING id_usuario;"
            )
            id_admin = cursor.fetchone()['id_usuario']

            cursor.execute("INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede Norte', 'Medellin', 'Norte') RETURNING id_sede;")
            id_sede = cursor.fetchone()['id_sede']

            cursor.execute("INSERT INTO specialties (nombre, descripcion) VALUES ('Urologia', 'Uro') RETURNING id_especialidad;")
            id_especialidad = cursor.fetchone()['id_especialidad']

            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad) VALUES ('Dr. Uro A', 'LIC-4001', %s) RETURNING id_medico;",
                (id_especialidad,)
            )
            id_medico_a = cursor.fetchone()['id_medico']

            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad) VALUES ('Dr. Uro B', 'LIC-4002', %s) RETURNING id_medico;",
                (id_especialidad,)
            )
            id_medico_b = cursor.fetchone()['id_medico']

            # Paciente A (Afectado por cancelación)
            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) VALUES ('9101', 'Pac Cancelado', '555-9101', 'canc@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_pac_cancelado = cursor.fetchone()['id_paciente']

            # Paciente B (FIFO general más antiguo en la cola)
            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) VALUES ('9102', 'Pac Normal FIFO', '555-9102', 'normal@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_pac_fifo = cursor.fetchone()['id_paciente']

            # Citas
            tomorrow = datetime.now(timezone.utc) + timedelta(days=2)
            start_time = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
            end_time = start_time + timedelta(minutes=30)
            rango_cita_str = f"[{start_time.isoformat()}, {end_time.isoformat()}]"

            # Cita original con Medico A
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, %s, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico_a, id_pac_cancelado, id_sede, rango_cita_str)
            )

            # Lista de espera: Paciente B (Normal FIFO) tiene una solicitud más antigua
            cursor.execute(
                "INSERT INTO waiting_list (id_paciente, id_especialidad, id_sede, tipo_cola, estado, created_at) VALUES (%s, %s, %s, 'FechaCercana', 'Pendiente', NOW() - INTERVAL '1 hour') RETURNING id_espera;",
                (id_pac_fifo, id_especialidad, id_sede)
            )

        conn.commit()

        # 1. Cancelar masivamente para mover a Paciente A a la lista de espera
        AppointmentService.execute_massive_cancellation(
            id_sede=id_sede,
            id_medico=id_medico_a,
            realizado_por='Sistema',
            id_usuario_ejecutor=id_admin,
            auto_reschedule=True
        )

        # 2. Ahora creamos un nuevo slot con el Medico B en el mismo rango de hora y sede
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, NULL, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico_b, id_sede, rango_cita_str)
            )
            id_cita_nueva = cursor.fetchone()['id_cita']
        conn.commit()

        # 3. Disparar el motor LEA
        assigned_patient = WaitingListEngine.handle_liberated_slot(id_cita_nueva)

        # Debe priorizar por coincidencia exacta de slot a Paciente A, a pesar de que Paciente B es el FIFO más antiguo de la cola!
        assert assigned_patient == id_pac_cancelado

    finally:
        Database.release_connection(conn)


def test_double_booking_and_medical_authorization():
    """
    Valida la regla de doble reserva activa y cómo se exceptúa mediante autorizaciones médicas de sesiones múltiples.
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede Sur', 'Medellin', 'Sur') RETURNING id_sede;")
            id_sede = cursor.fetchone()['id_sede']

            cursor.execute("INSERT INTO specialties (nombre, descripcion) VALUES ('Fisioterapia', 'Terapia') RETURNING id_especialidad;")
            id_especialidad = cursor.fetchone()['id_especialidad']

            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad) VALUES ('Dr. Fisio', 'LIC-5001', %s) RETURNING id_medico;",
                (id_especialidad,)
            )
            id_medico = cursor.fetchone()['id_medico']

            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) VALUES ('9201', 'Pac Terapias', '555-9201', 'fis@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_paciente = cursor.fetchone()['id_paciente']

            # Crear slots
            t1 = datetime.now(timezone.utc) + timedelta(days=3)
            r1 = f"[{t1.replace(hour=8, minute=0).isoformat()}, {t1.replace(hour=8, minute=30).isoformat()}]"
            r2 = f"[{t1.replace(hour=9, minute=0).isoformat()}, {t1.replace(hour=9, minute=30).isoformat()}]"

            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, NULL, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, id_sede, r1)
            )
            c1 = cursor.fetchone()['id_cita']

            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, NULL, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, id_sede, r2)
            )
            c2 = cursor.fetchone()['id_cita']

        conn.commit()

        # Reservar primera cita (Debe pasar con éxito)
        res1 = AppointmentService.book_appointment(c1, id_paciente, 'Paciente', id_paciente)
        assert res1 is True

        with pytest.raises(ValueError) as exc_info:
            AppointmentService.book_appointment(c2, id_paciente, 'Paciente', id_paciente)
        assert "cita programada activa" in str(exc_info.value)

        # Insertar una autorización médica para múltiples terapias
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO medical_authorizations (id_paciente, id_medico_emisor, id_especialidad_dest, sesiones_totales, sesiones_consumidas, frecuencia_dias, estado)
                VALUES (%s, %s, %s, 10, 0, 7, 'Activa');
                """,
                (id_paciente, id_medico, id_especialidad)
            )
        conn.commit()

        # Ahora intentar reservar la segunda cita (Debe pasar exitosamente y consumir una sesión)
        res2 = AppointmentService.book_appointment(c2, id_paciente, 'Paciente', id_paciente)
        assert res2 is True

        # Validar en base de datos que se consumió 1 sesión
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT sesiones_consumidas FROM medical_authorizations WHERE id_paciente = %s;", (id_paciente,))
            auth_row = cursor.fetchone()
            assert auth_row['sesiones_consumidas'] == 1

    finally:
        Database.release_connection(conn)


def test_consecutive_no_show_suspension():
    """
    Valida el bloqueo de auto-agendamiento autónomo al acumular inasistencias consecutivas.
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede Oeste', 'Medellin', 'Oeste') RETURNING id_sede;")
            id_sede = cursor.fetchone()['id_sede']

            cursor.execute("INSERT INTO specialties (nombre, descripcion) VALUES ('Pediatria', 'Pediatra') RETURNING id_especialidad;")
            id_especialidad = cursor.fetchone()['id_especialidad']

            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad) VALUES ('Dra. Pedi', 'LIC-6001', %s) RETURNING id_medico;",
                (id_especialidad,)
            )
            id_medico = cursor.fetchone()['id_medico']

            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) VALUES ('9301', 'Pac Falton', '555-9301', 'falt@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_paciente = cursor.fetchone()['id_paciente']

            # Crear 3 citas previas del paciente marcadas como 'NoAsistio'
            base_time = datetime.now(timezone.utc) - timedelta(days=5)
            for i in range(3):
                t_start = base_time + timedelta(hours=i)
                t_end = t_start + timedelta(minutes=30)
                r_str = f"[{t_start.isoformat()}, {t_end.isoformat()}]"
                cursor.execute(
                    "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, %s, %s, %s::tstzrange, 'NoAsistio');",
                    (id_medico, id_paciente, id_sede, r_str)
                )

            # Slot nuevo a agendar
            tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
            slot_rango = f"[{tomorrow.replace(hour=11, minute=0).isoformat()}, {tomorrow.replace(hour=11, minute=30).isoformat()}]"
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, NULL, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, id_sede, slot_rango)
            )
            id_cita_nueva = cursor.fetchone()['id_cita']

        conn.commit()

        # Intentar reservar autónomamente como Paciente (Debe fallar con PermissionError)
        with pytest.raises(PermissionError) as exc_info:
            AppointmentService.book_appointment(id_cita_nueva, id_paciente, 'Paciente', id_paciente)
        assert "suspendido el auto-agendamiento autónomo" in str(exc_info.value)

        # Pero si lo hace la Recepcionista (Pasa exitosamente)
        res = AppointmentService.book_appointment(id_cita_nueva, id_paciente, 'Recepcionista', 'recep@clinica.com')
        assert res is True

    finally:
        Database.release_connection(conn)


def test_travel_time_inter_branch():
    """
    Valida el requerimiento de al menos 1 hora de margen de traslado si hay citas el mismo día en sedes físicas distintas.
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Dos sedes distintas en la misma ciudad
            cursor.execute("INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede A', 'Medellin', 'Direccion A') RETURNING id_sede;")
            id_sede_a = cursor.fetchone()['id_sede']

            cursor.execute("INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede B', 'Medellin', 'Direccion B') RETURNING id_sede;")
            id_sede_b = cursor.fetchone()['id_sede']

            cursor.execute("INSERT INTO specialties (nombre, descripcion) VALUES ('Oftalmologia', 'Ojo') RETURNING id_especialidad;")
            id_spec_1 = cursor.fetchone()['id_especialidad']

            cursor.execute("INSERT INTO specialties (nombre, descripcion) VALUES ('Cardiologia', 'Corazon') RETURNING id_especialidad;")
            id_spec_2 = cursor.fetchone()['id_especialidad']

            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad) VALUES ('Dr. Ojo', 'LIC-7001', %s) RETURNING id_medico;",
                (id_spec_1,)
            )
            id_medico_ojo = cursor.fetchone()['id_medico']

            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad) VALUES ('Dr. Cardio', 'LIC-7002', %s) RETURNING id_medico;",
                (id_spec_2,)
            )
            id_medico_cardio = cursor.fetchone()['id_medico']

            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) VALUES ('9401', 'Pac Viajero', '555-9401', 'viaj@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_paciente = cursor.fetchone()['id_paciente']

            # Crear citas
            tomorrow = datetime.now(timezone.utc) + timedelta(days=2)
            
            # Cita 1: Mañana a las 10:00 - 10:30 en Sede A
            start_1 = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
            end_1 = start_1 + timedelta(minutes=30)
            r1 = f"[{start_1.isoformat()}, {end_1.isoformat()}]"
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, NULL, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico_ojo, id_sede_a, r1)
            )
            c1 = cursor.fetchone()['id_cita']

            # Cita 2: Mañana a las 11:00 - 11:30 en Sede B (Solo 30 minutos de traslado, debe fallar ya que se requiere 1 hora)
            start_2 = tomorrow.replace(hour=11, minute=0, second=0, microsecond=0)
            end_2 = start_2 + timedelta(minutes=30)
            r2 = f"[{start_2.isoformat()}, {end_2.isoformat()}]"
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, NULL, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico_cardio, id_sede_b, r2)
            )
            c2 = cursor.fetchone()['id_cita']

            # Cita 3: Mañana a las 12:00 - 12:30 en Sede B (1 hora y 30 minutos después de Cita 1, debe pasar)
            start_3 = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)
            end_3 = start_3 + timedelta(minutes=30)
            r3 = f"[{start_3.isoformat()}, {end_3.isoformat()}]"
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, id_sede, rango_cita, estado) VALUES (%s, NULL, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico_cardio, id_sede_b, r3)
            )
            c3 = cursor.fetchone()['id_cita']

        conn.commit()

        # Agendar primera cita en Sede A (Éxito)
        AppointmentService.book_appointment(c1, id_paciente, 'Paciente', id_paciente)

        # Intentar agendar segunda cita en Sede B con solo 30 min de diferencia (Falla)
        with pytest.raises(ValueError) as exc_info:
            AppointmentService.book_appointment(c2, id_paciente, 'Paciente', id_paciente)
        assert "Tiempo de traslado" in str(exc_info.value)

        # Agendar tercera cita en Sede B con 1h30m de diferencia (Éxito)
        res_viaje_ok = AppointmentService.book_appointment(c3, id_paciente, 'Paciente', id_paciente)
        assert res_viaje_ok is True

    finally:
        Database.release_connection(conn)
