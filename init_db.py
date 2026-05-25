# ============================================================================
# ARCHIVO: init_db.py
# PROPÓSITO: Inicialización automatizada e idempotente de PostgreSQL local (SGCM).
#
# Recrea desde cero la base de datos 'sgcm_db' y aplica el nuevo esquema DDL
# robustecido con multi-sede, autenticación unificada, parámetros dinámicos,
# exclusión GIST de solapamiento y semillas de prueba completas.
# ============================================================================

import psycopg2
from psycopg2 import Error as PGError
from config import Config
from database import Database


def create_database_if_not_exists():
    """
    Se conecta al motor PostgreSQL por defecto y crea la base de datos 'sgcm_db' si no existe.
    """
    conn = None
    try:
        # Nos conectamos a la BD por defecto 'postgres' para crear la nueva BD
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            user=Config.DB_USER,
            password=Config.DB_PASSWORD,
            database="postgres"
        )
        conn.autocommit = True  # CREATE DATABASE no puede correr dentro de una transacción
        cursor = conn.cursor()

        # Verificar si la base de datos ya existe
        cursor.execute("SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s;", (Config.DB_NAME,))
        exists = cursor.fetchone()

        if not exists:
            print(f"La base de datos '{Config.DB_NAME}' no existe. Creándola...")
            cursor.execute(f"CREATE DATABASE {Config.DB_NAME} WITH OWNER = {Config.DB_USER} ENCODING = 'UTF8';")
            print(f"Base de datos '{Config.DB_NAME}' creada con éxito.")
        else:
            print(f"La base de datos '{Config.DB_NAME}' ya existe.")

    except PGError as e:
        print(f"Error al verificar/crear la base de datos: {e}")
        raise
    finally:
        if conn:
            conn.close()


def initialize_tables():
    """
    Inicializa el esquema físico de tablas relacionales de forma limpia.
    """
    # 1. Eliminación y recreación limpia de tablas en cascada
    drop_script = """
    DROP TABLE IF EXISTS appointments_history CASCADE;
    DROP TABLE IF EXISTS appointments CASCADE;
    DROP TABLE IF EXISTS waiting_list CASCADE;
    DROP TABLE IF EXISTS medical_authorizations CASCADE;
    DROP TABLE IF EXISTS massive_cancellations CASCADE;
    DROP TABLE IF EXISTS permissions_delegation CASCADE;
    DROP TABLE IF EXISTS system_parameters CASCADE;
    DROP TABLE IF EXISTS patients CASCADE;
    DROP TABLE IF EXISTS doctors CASCADE;
    DROP TABLE IF EXISTS specialties CASCADE;
    DROP TABLE IF EXISTS users CASCADE;
    DROP TABLE IF EXISTS branches CASCADE;
    """

    # 2. Definición de la estructura DDL física unificada
    ddl_script = """
    -- Habilitar extensiones necesarias
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS "btree_gist";

    -- 1. Tabla de Especialidades Médicas
    CREATE TABLE specialties (
        id_especialidad UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        nombre VARCHAR(100) NOT NULL UNIQUE,
        descripcion TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 2. Tabla de Sedes (Multi-sede)
    CREATE TABLE branches (
        id_sede UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        nombre VARCHAR(150) NOT NULL UNIQUE, -- Ej: "Sede Medellín - El Poblado"
        ciudad VARCHAR(100) NOT NULL,
        direccion TEXT NOT NULL,
        activa BOOLEAN DEFAULT TRUE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 3. Tabla de Usuarios (Seguridad y Autenticación Unificada)
    CREATE TABLE users (
        id_usuario UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        username VARCHAR(50) UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        email VARCHAR(150) UNIQUE NOT NULL,
        rol VARCHAR(30) NOT NULL CHECK (rol IN ('Admin', 'Recepcionista', 'Medico', 'Paciente')),
        id_sede UUID REFERENCES branches(id_sede) ON UPDATE CASCADE ON DELETE SET NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 4. Parámetros Globales del Sistema (Configuración en Caliente)
    CREATE TABLE system_parameters (
        param_key VARCHAR(50) PRIMARY KEY,
        param_value TEXT NOT NULL,
        descripcion TEXT,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 5. Delegación de Permisos Dinámicos y Temporales
    CREATE TABLE permissions_delegation (
        id_delegacion UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        id_usuario_receptor UUID NOT NULL REFERENCES users(id_usuario) ON DELETE CASCADE,
        permiso_nombre VARCHAR(100) NOT NULL,
        fecha_inicio TIMESTAMP WITH TIME ZONE NOT NULL,
        fecha_expiracion TIMESTAMP WITH TIME ZONE, -- NULL si es permanente
        creado_por UUID REFERENCES users(id_usuario) ON DELETE SET NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 6. Tabla de Pacientes (Dominio Clínico)
    CREATE TABLE patients (
        id_paciente UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        id_usuario UUID UNIQUE REFERENCES users(id_usuario) ON DELETE SET NULL,
        dni VARCHAR(20) NOT NULL UNIQUE,
        nombre_completo VARCHAR(150) NOT NULL,
        telefono VARCHAR(20) NOT NULL,
        email VARCHAR(150) NOT NULL UNIQUE,
        ciudad_origen VARCHAR(100) NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 7. Tabla de Médicos (Dominio Clínico)
    CREATE TABLE doctors (
        id_medico UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        id_usuario UUID UNIQUE REFERENCES users(id_usuario) ON DELETE SET NULL,
        numero_licencia VARCHAR(50) NOT NULL UNIQUE,
        nombre_completo VARCHAR(150) NOT NULL,
        id_especialidad UUID NOT NULL REFERENCES specialties(id_especialidad) ON DELETE RESTRICT,
        duracion_defecto INTERVAL NOT NULL DEFAULT '30 minutes',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 8. Tabla de Citas Médicas con Restricciones Multisede
    CREATE TABLE appointments (
        id_cita UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        id_medico UUID NOT NULL REFERENCES doctors(id_medico) ON DELETE CASCADE,
        id_paciente UUID REFERENCES patients(id_paciente) ON DELETE SET NULL,
        id_sede UUID NOT NULL REFERENCES branches(id_sede) ON DELETE CASCADE,
        rango_cita TSTZRANGE NOT NULL,
        estado VARCHAR(50) NOT NULL DEFAULT 'Agendada' 
            CONSTRAINT chk_estado CHECK (estado IN ('Agendada', 'Confirmada', 'EnCurso', 'Finalizada', 'Cancelada', 'NoAsistio')),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

        -- RESTRICCIÓN DE EXCLUSIÓN: Ningún médico puede atender dos citas en rangos solapados
        CONSTRAINT exclude_overlapping_appointments EXCLUDE USING gist (
            id_medico WITH =,
            rango_cita WITH &&
        )
    );

    -- 9. Tabla de Solicitudes en Lista de Espera (LEA)
    CREATE TABLE waiting_list (
        id_espera UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        id_paciente UUID NOT NULL REFERENCES patients(id_paciente) ON DELETE CASCADE,
        id_especialidad UUID NOT NULL REFERENCES specialties(id_especialidad) ON DELETE CASCADE,
        id_sede UUID NOT NULL REFERENCES branches(id_sede) ON DELETE CASCADE,
        tipo_cola VARCHAR(30) NOT NULL DEFAULT 'FechaCercana'
            CONSTRAINT chk_tipo_cola CHECK (tipo_cola IN ('FechaCercana', 'RangoEspecifico')),
        rango_deseado DATERANGE,
        estado VARCHAR(30) NOT NULL DEFAULT 'Pendiente'
            CONSTRAINT chk_estado_espera CHECK (estado IN ('Pendiente', 'Asignada', 'Cancelada', 'Expirada')),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 10. Tabla de Historial y Auditoría Transaccional de Citas (Inmutable)
    CREATE TABLE appointments_history (
        id_historial UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        id_cita UUID NOT NULL REFERENCES appointments(id_cita) ON DELETE CASCADE,
        estado_anterior VARCHAR(20) CONSTRAINT chk_est_ant CHECK (estado_anterior IN ('Agendada', 'Confirmada', 'EnCurso', 'Finalizada', 'Cancelada', 'NoAsistio')),
        estado_nuevo VARCHAR(20) NOT NULL CONSTRAINT chk_est_nue CHECK (estado_nuevo IN ('Agendada', 'Confirmada', 'EnCurso', 'Finalizada', 'Cancelada', 'NoAsistio')),
        tipo_accion VARCHAR(20) NOT NULL CONSTRAINT chk_tipo_accion CHECK (tipo_accion IN ('Creacion', 'Asignacion', 'Modificacion', 'Cancelacion')),
        realizado_por VARCHAR(20) NOT NULL CONSTRAINT chk_realizado_por CHECK (realizado_por IN ('Paciente', 'Recepcionista', 'Medico', 'Sistema')),
        usuario_identificador VARCHAR(150) NOT NULL,
        cambios JSONB DEFAULT '{}'::jsonb,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 11. Tabla de Autorizaciones Médicas (Derivaciones para Agendamientos Múltiples)
    CREATE TABLE medical_authorizations (
        id_autorizacion UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        id_paciente UUID NOT NULL REFERENCES patients(id_paciente) ON DELETE CASCADE,
        id_medico_emisor UUID NOT NULL REFERENCES doctors(id_medico) ON DELETE CASCADE,
        id_especialidad_dest UUID NOT NULL REFERENCES specialties(id_especialidad) ON DELETE CASCADE,
        sesiones_totales INT NOT NULL CHECK (sesiones_totales > 0),
        sesiones_consumidas INT DEFAULT 0 CHECK (sesiones_consumidas >= 0),
        frecuencia_dias INT NOT NULL CHECK (frecuencia_dias > 0),
        estado VARCHAR(20) DEFAULT 'Activa' CHECK (estado IN ('Activa', 'Consumida', 'Cancelada')),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 12. Tabla de Auditoría de Cancelaciones Masivas
    CREATE TABLE massive_cancellations (
        id_cancelacion UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        id_sede UUID REFERENCES branches(id_sede) ON DELETE SET NULL,
        id_medico UUID REFERENCES doctors(id_medico) ON DELETE SET NULL,
        fecha_ejecucion TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        cantidad_canceladas INT DEFAULT 0,
        auto_reschedule BOOLEAN DEFAULT TRUE,
        reporte_path TEXT,
        ejecutado_por UUID REFERENCES users(id_usuario) ON DELETE SET NULL
    );
    """
    
    connection = None
    try:
        connection = Database.get_connection()
        cursor = connection.cursor()
        
        # 1. Limpiar esquema existente
        print("Eliminando tablas previas en cascada...")
        cursor.execute(drop_script)
        
        # 2. Crear las nuevas tablas físicas
        print("Creando el nuevo esquema DDL del SGCM...")
        cursor.execute(ddl_script)
        
        # 3. Crear índices de rendimiento optimizados
        print("Creando índices optimizados e índices parciales GIST...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_active_appointments ON appointments USING GIST (rango_cita);
            CREATE INDEX IF NOT EXISTS idx_patients_dni ON patients(dni);
            CREATE INDEX IF NOT EXISTS idx_waiting_list_status ON waiting_list(estado) WHERE estado = 'Pendiente';
            CREATE INDEX IF NOT EXISTS idx_history_cita_fecha ON appointments_history(id_cita, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
        """)
        
        # 4. Configuración del autovacuum regional en appointments
        cursor.execute("""
            ALTER TABLE appointments SET (
                autovacuum_vacuum_scale_factor = 0.05,
                autovacuum_analyze_scale_factor = 0.02,
                autovacuum_vacuum_cost_limit = 1000
            );
        """)
        
        connection.commit()
        print("Tablas físicas, restricciones e índices creados con éxito en 'sgcm_db'.")
    except PGError as e:
        if connection:
            connection.rollback()
        print(f"Error crítico al inicializar el esquema de base de datos: {e}")
        raise
    finally:
        if connection:
            Database.release_connection(connection)


def inject_seed_data():
    """
    Inyecta datos semilla (seeding) de prueba de forma idempotente para la multisede,
    usuarios, especialidades, médicos, pacientes y parámetros iniciales.
    """
    connection = None
    try:
        connection = Database.get_connection()
        cursor = connection.cursor()
        print("Inyectando datos semilla actualizados...")

        # 1. Parámetros Iniciales del Sistema
        parameters = [
            ("buffer_horas", "2", "Límite de amortiguación horaria para LEA y cancelación de pacientes"),
            ("lookahead_dias", "7", "Días máximos permitidos para la regla de los días siguientes (Lookahead)"),
            ("tolerancia_retraso_minutos", "15", "Tolerancia de retraso del paciente antes de inasistencia automática"),
            ("minutos_traslado_sedes", "60", "Intervalo mínimo requerido para traslado de pacientes entre sedes el mismo día"),
            ("max_inasistencias_consecutivas", "3", "Número de inasistencias consecutivas permitidas antes de bloquear auto-agendamiento"),
            ("dias_bloqueo_inasistencia", "15", "Días de suspensión temporal de reserva en el portal por inasistencia reiterada"),
            ("dias_alerta_vencimiento", "5", "Días tras el vencimiento de lista de espera para emitir alerta en el dashboard")
        ]
        for key, val, desc in parameters:
            cursor.execute(
                "INSERT INTO system_parameters (param_key, param_value, descripcion) VALUES (%s, %s, %s);",
                (key, val, desc)
            )

        # 2. Especialidades
        specialties = [
            ("Medicina General", "Atención primaria."),
            ("Pediatria", "Infantes y niños."),
            ("Cardiologia", "Cuidado del corazón."),
            ("Dermatologia", "Enfermedades de la piel.")
        ]
        specialty_ids = {}
        for name, desc in specialties:
            cursor.execute(
                "INSERT INTO specialties (nombre, descripcion) VALUES (%s, %s) RETURNING id_especialidad;",
                (name, desc)
            )
            specialty_ids[name] = cursor.fetchone()[0]

        # 3. Sedes Clínicas (Multi-sede)
        branches = [
            ("Sede Medellin - El Poblado", "Medellin", "Carrera 43A #10-45"),
            ("Sede Medellin - Laureles", "Medellin", "Avenida Nutibara #74-20"),
            ("Sede Bogota - Chapinero", "Bogota", "Calle 58 #13-05"),
            ("Sede Cali - Centenario", "Cali", "Avenida 4 Norte #8-12")
        ]
        branch_ids = {}
        for name, city, addr in branches:
            cursor.execute(
                "INSERT INTO branches (nombre, ciudad, direccion) VALUES (%s, %s, %s) RETURNING id_sede;",
                (name, city, addr)
            )
            branch_ids[name] = cursor.fetchone()[0]

        # 4. Usuarios del Sistema y Perfiles Clínicos/Personales
        # 4.1. Cuentas de Usuarios Base
        users = [
            ("admin", "pbkdf2:sha256:260000$admin_hash", "admin@clinicasalud.com", "Admin", branch_ids["Sede Medellin - El Poblado"]),
            ("recep_poblado", "pbkdf2:sha256:260000$recep_hash", "recepcion.poblado@clinicasalud.com", "Recepcionista", branch_ids["Sede Medellin - El Poblado"]),
            ("medico_carlos", "pbkdf2:sha256:260000$carlos_hash", "carlos.gomez@clinicasalud.com", "Medico", branch_ids["Sede Medellin - El Poblado"]),
            ("medico_maria", "pbkdf2:sha256:260000$maria_hash", "maria.restrepo@clinicasalud.com", "Medico", branch_ids["Sede Medellin - El Poblado"]),
            ("11223344", "pbkdf2:sha256:260000$carmen_hash", "carmen.rojas@email.com", "Paciente", branch_ids["Sede Medellin - El Poblado"]),
            ("98765432", "pbkdf2:sha256:260000$andres_hash", "andres.mejia@email.com", "Paciente", branch_ids["Sede Bogota - Chapinero"])
        ]
        user_ids = {}
        for username, password_hash, email, rol, branch_id in users:
            cursor.execute(
                "INSERT INTO users (username, password_hash, email, rol, id_sede) VALUES (%s, %s, %s, %s, %s) RETURNING id_usuario;",
                (username, password_hash, email, rol, branch_id)
            )
            user_ids[username] = cursor.fetchone()[0]

        # 4.2. Perfiles de Médicos en doctors
        doctors = [
            ("Dr. Carlos Gómez", "LIC-482094", specialty_ids["Medicina General"], "20 minutes", user_ids["medico_carlos"]),
            ("Dra. María Restrepo", "LIC-902183", specialty_ids["Pediatria"], "30 minutes", user_ids["medico_maria"])
        ]
        for name, lic, spec_id, duration, user_id in doctors:
            cursor.execute(
                "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad, duracion_defecto, id_usuario) "
                "VALUES (%s, %s, %s, %s, %s);",
                (name, lic, spec_id, duration, user_id)
            )

        # 4.3. Perfiles de Pacientes en patients
        patients = [
            ("11223344", "Carmen Alicia Rojas", "555-2201", "carmen.rojas@email.com", "Medellin", user_ids["11223344"]),
            ("98765432", "Andrés Felipe Mejía", "555-8839", "andres.mejia@email.com", "Bogota", user_ids["98765432"])
        ]
        for dni, name, phone, email, city, user_id in patients:
            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen, id_usuario) "
                "VALUES (%s, %s, %s, %s, %s, %s);",
                (dni, name, phone, email, city, user_id)
            )

        connection.commit()
        print("Datos semilla del SGCM inyectados con éxito de forma unificada.")

    except PGError as e:
        if connection:
            connection.rollback()
        print(f"Error al inyectar datos semilla: {e}")
        raise
    finally:
        if connection:
            Database.release_connection(connection)


if __name__ == "__main__":
    print("--- INICIANDO CONFIGURACIÓN DE POSTGRESQL MULTI-SEDE DESDE CERO ---")
    create_database_if_not_exists()
    initialize_tables()
    inject_seed_data()
    print("--- PROCESO DE INICIALIZACIÓN COMPLETADO CON ÉXITO ---")
