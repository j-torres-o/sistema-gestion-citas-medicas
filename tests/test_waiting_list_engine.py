# ============================================================================
# ARCHIVO: tests/test_waiting_list_engine.py
# PROPÓSITO: Pruebas unitarias e integrales para el motor LEA y AppointmentService.
# ============================================================================

import json
from datetime import datetime, timezone, timedelta
import pytest
from psycopg2.extras import RealDictCursor
from database import Database
from services.waiting_list_engine import WaitingListEngine
from services.appointment_service import AppointmentService


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
            cursor.execute("DELETE FROM patients;")
            cursor.execute("DELETE FROM doctors;")
            cursor.execute("DELETE FROM specialties;")
        conn.commit()
    finally:
        Database.release_connection(conn)


@pytest.fixture(autouse=True)
def setup_clean_db():
    clean_tables()
    yield
    clean_tables()


def test_lea_engine_fifo_assignment_success():
    """
    Valida que el motor LEA asigne un slot libre al primer paciente en cola de espera (FIFO).
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Crear Especialidad
            cursor.execute(
                "INSERT INTO specialties (nombre, descripcion) VALUES ('Oftalmologia', 'Cuidado de ojos') RETURNING id_especialidad;"
            )
            id_especialidad = cursor.fetchone()['id_especialidad']

            # 2. Crear Médico
            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad) VALUES ('Dr. Oftalmo', 'LIC-1002', %s) RETURNING id_medico;",
                (id_especialidad,)
            )
            id_medico = cursor.fetchone()['id_medico']

            # 3. Crear Pacientes
            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email) VALUES ('7010', 'Paciente Uno', '555-1111', 'uno@email.com') RETURNING id_paciente;"
            )
            id_paciente_1 = cursor.fetchone()['id_paciente']

            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email) VALUES ('7020', 'Paciente Dos', '555-2222', 'dos@email.com') RETURNING id_paciente;"
            )
            id_paciente_2 = cursor.fetchone()['id_paciente']

            # 4. Registrar en lista de espera (Paciente 1 se registra antes que Paciente 2 - FIFO)
            cursor.execute(
                "INSERT INTO waiting_list (id_paciente, id_especialidad, tipo_cola, estado, created_at) VALUES (%s, %s, 'FechaCercana', 'Pendiente', NOW() - INTERVAL '10 minutes') RETURNING id_espera;",
                (id_paciente_1, id_especialidad)
            )
            id_espera_1 = cursor.fetchone()['id_espera']

            cursor.execute(
                "INSERT INTO waiting_list (id_paciente, id_especialidad, tipo_cola, estado, created_at) VALUES (%s, %s, 'FechaCercana', 'Pendiente', NOW()) RETURNING id_espera;",
                (id_paciente_2, id_especialidad)
            )
            id_espera_2 = cursor.fetchone()['id_espera']

            # 5. Crear slot disponible (Cita para mañana - pasa regla de las 2 horas)
            tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
            tomorrow_start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
            tomorrow_end = tomorrow_start + timedelta(minutes=30)
            rango_cita_str = f"[{tomorrow_start.isoformat()}, {tomorrow_end.isoformat()}]"

            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, rango_cita, estado) VALUES (%s, NULL, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, rango_cita_str)
            )
            id_cita = cursor.fetchone()['id_cita']

        conn.commit()

        # 6. Disparar el motor LEA
        assigned_patient = WaitingListEngine.handle_liberated_slot(id_cita)

        # 7. Validar asignación FIFO al Paciente 1 (el más antiguo)
        assert assigned_patient == id_paciente_1

        # Validar base de datos
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Cita asignada a Paciente 1
            cursor.execute("SELECT id_paciente, estado FROM appointments WHERE id_cita = %s;", (id_cita,))
            apt = cursor.fetchone()
            assert apt['id_paciente'] == id_paciente_1
            assert apt['estado'] == 'Agendada'

            # Lista de espera del Paciente 1 marcada como Asignada
            cursor.execute("SELECT estado FROM waiting_list WHERE id_espera = %s;", (id_espera_1,))
            wl1 = cursor.fetchone()
            assert wl1['estado'] == 'Asignada'

            # Lista de espera del Paciente 2 sigue Pendiente
            cursor.execute("SELECT estado FROM waiting_list WHERE id_espera = %s;", (id_espera_2,))
            wl2 = cursor.fetchone()
            assert wl2['estado'] == 'Pendiente'

            # Historial de auditoría creado
            cursor.execute("SELECT tipo_accion, realizado_por, cambios FROM appointments_history WHERE id_cita = %s;", (id_cita,))
            hist = cursor.fetchone()
            assert hist['tipo_accion'] == 'Asignacion'
            assert hist['realizado_por'] == 'Sistema'
            cambios = hist['cambios']
            assert cambios['id_paciente']['new'] == str(id_paciente_1)

    finally:
        Database.release_connection(conn)


def test_lea_engine_two_hour_rule_prevents_assignment():
    """
    Valida que la regla de las 2 horas prevenga la auto-asignación si el slot inicia hoy en < 2h.
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
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
                "INSERT INTO patients (dni, nombre_completo, telefono, email) VALUES ('7030', 'Paciente Tres', '555-3333', 'tres@email.com') RETURNING id_paciente;"
            )
            id_paciente = cursor.fetchone()['id_paciente']

            cursor.execute(
                "INSERT INTO waiting_list (id_paciente, id_especialidad, tipo_cola, estado) VALUES (%s, %s, 'FechaCercana', 'Pendiente');",
                (id_paciente, id_especialidad)
            )

            # Slot que empieza hoy en 30 minutos (invalida asignación automática de las 2 horas)
            in_30_min = datetime.now(timezone.utc) + timedelta(minutes=30)
            in_60_min = in_30_min + timedelta(minutes=30)
            rango_cita_str = f"[{in_30_min.isoformat()}, {in_60_min.isoformat()}]"

            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, rango_cita, estado) VALUES (%s, NULL, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, rango_cita_str)
            )
            id_cita = cursor.fetchone()['id_cita']

        conn.commit()

        # Disparar motor LEA
        res = WaitingListEngine.handle_liberated_slot(id_cita)

        # No debe haber asignado a nadie
        assert res is None

        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # La cita sigue sin paciente
            cursor.execute("SELECT id_paciente, estado FROM appointments WHERE id_cita = %s;", (id_cita,))
            apt = cursor.fetchone()
            assert apt['id_paciente'] is None

    finally:
        Database.release_connection(conn)


def test_appointment_cancellation_24_hour_rule():
    """
    Valida la regla de las 24 horas para cancelaciones realizadas por el propio paciente.
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
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
                "INSERT INTO patients (dni, nombre_completo, telefono, email) VALUES ('7040', 'Paciente Cuatro', '555-4444', 'cuatro@email.com') RETURNING id_paciente;"
            )
            id_paciente = cursor.fetchone()['id_paciente']

            # Caso A: Cita en 5 horas (Debe fallar al cancelar como Paciente)
            in_5_hours = datetime.now(timezone.utc) + timedelta(hours=5)
            rango_cita_5h = f"[{in_5_hours.isoformat()}, {(in_5_hours + timedelta(minutes=30)).isoformat()}]"
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, rango_cita, estado) VALUES (%s, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, id_paciente, rango_cita_5h)
            )
            id_cita_corta = cursor.fetchone()['id_cita']

            # Caso B: Cita en 48 horas (Debe pasar exitosamente al cancelar como Paciente)
            in_48_hours = datetime.now(timezone.utc) + timedelta(days=2)
            rango_cita_48h = f"[{in_48_hours.isoformat()}, {(in_48_hours + timedelta(minutes=30)).isoformat()}]"
            cursor.execute(
                "INSERT INTO appointments (id_medico, id_paciente, rango_cita, estado) VALUES (%s, %s, %s::tstzrange, 'Agendada') RETURNING id_cita;",
                (id_medico, id_paciente, rango_cita_48h)
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
        assert "24 horas de anticipación" in str(exc_info.value)

        # Cancelar Caso A como Recepcionista (Debe tener permiso sin restricción de tiempo)
        res_recep = AppointmentService.cancel_appointment(
            id_cita=id_cita_corta,
            realizado_por='Recepcionista',
            usuario_identificador='admin@clinica.com'
        )
        assert res_recep is True

        # Cancelar Caso B como Paciente (Debe pasar exitosamente ya que faltan 48h)
        res_paciente = AppointmentService.cancel_appointment(
            id_cita=id_cita_larga,
            realizado_por='Paciente',
            usuario_identificador=id_paciente
        )
        assert res_paciente is True

        # Validar en base de datos que se liberó la cita de 48h (id_paciente = NULL, estado = 'Agendada')
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute("SELECT id_paciente, estado FROM appointments WHERE id_cita = %s;", (id_cita_larga,))
            apt = cursor.fetchone()
            assert apt['id_paciente'] is None
            assert apt['estado'] == 'Agendada'

    finally:
        Database.release_connection(conn)
