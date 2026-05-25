# ============================================================================
# ARCHIVO: init_db.py
# PROPÓSITO: Inicialización automatizada e idempotente de PostgreSQL local.
#
# Este script:
# 1. Se conecta al servidor local de PostgreSQL.
# 2. Crea la base de datos 'sgcm_db' si no existe.
# 3. Crea las extensiones y tablas relacionales clínicas con exclusiones GIST.
# 4. Inyecta datos semilla (seeding) de prueba de forma controlada.
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
    Inicializa el esquema físico de tablas relacionales e inyecta las restricciones de exclusión.
    """
    # 1. Definición de la estructura DDL física
    ddl_script = """
    -- Habilitar extensiones necesarias
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS "btree_gist";

    -- 1. Tabla de Especialidades Médicas
    CREATE TABLE IF NOT EXISTS specialties (
        id_especialidad UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        nombre VARCHAR(100) NOT NULL UNIQUE,
        descripcion TEXT,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 2. Tabla de Médicos
    CREATE TABLE IF NOT EXISTS doctors (
        id_medico UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        numero_licencia VARCHAR(50) NOT NULL UNIQUE,
        nombre_completo VARCHAR(150) NOT NULL,
        id_especialidad UUID NOT NULL REFERENCES specialties(id_especialidad) ON DELETE RESTRICT,
        duracion_defecto INTERVAL NOT NULL DEFAULT '30 minutes',
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 3. Tabla de Pacientes
    CREATE TABLE IF NOT EXISTS patients (
        id_paciente UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        dni VARCHAR(20) NOT NULL UNIQUE,
        nombre_completo VARCHAR(150) NOT NULL,
        telefono VARCHAR(20) NOT NULL,
        email VARCHAR(150) NOT NULL UNIQUE,
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 4. Tabla de Citas Médicas
    CREATE TABLE IF NOT EXISTS appointments (
        id_cita UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        id_medico UUID NOT NULL REFERENCES doctors(id_medico) ON DELETE CASCADE,
        id_paciente UUID REFERENCES patients(id_paciente) ON DELETE SET NULL,
        rango_cita TSTZRANGE NOT NULL,
        estado VARCHAR(50) NOT NULL DEFAULT 'Agendada' 
            CONSTRAINT chk_estado CHECK (estado IN ('Agendada', 'Confirmada', 'EnCurso', 'Finalizada', 'Cancelada', 'NoAsistio')),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

        -- Restricción de exclusión física contra solapamientos de citas del mismo médico
        CONSTRAINT exclude_overlapping_appointments EXCLUDE USING gist (
            id_medico WITH =,
            rango_cita WITH &&
        )
    );

    -- 5. Tabla de Lista de Espera (LEA)
    CREATE TABLE IF NOT EXISTS waiting_list (
        id_espera UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
        id_paciente UUID NOT NULL REFERENCES patients(id_paciente) ON DELETE CASCADE,
        id_especialidad UUID NOT NULL REFERENCES specialties(id_especialidad) ON DELETE CASCADE,
        tipo_cola VARCHAR(30) NOT NULL DEFAULT 'FechaCercana'
            CONSTRAINT chk_tipo_cola CHECK (tipo_cola IN ('FechaCercana', 'RangoEspecifico')),
        rango_deseado DATERANGE,
        estado VARCHAR(30) NOT NULL DEFAULT 'Pendiente'
            CONSTRAINT chk_estado_espera CHECK (estado IN ('Pendiente', 'Asignada', 'Cancelada', 'Expirada')),
        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );

    -- 6. Tabla de Historial y Auditoría Transaccional (Inmutable)
    CREATE TABLE IF NOT EXISTS appointments_history (
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
    """
    
    connection = None
    try:
        connection = Database.get_connection()
        cursor = connection.cursor()
        print("Ejecutando DDL de base de datos PostgreSQL...")
        cursor.execute(ddl_script)
        
        # Crear los índices de rendimiento complementarios
        print("Creando índices optimizados e índices parciales GIST...")
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_active_appointments ON appointments USING GIST (rango_cita);
            
            CREATE INDEX IF NOT EXISTS idx_patients_dni ON patients(dni);
            CREATE INDEX IF NOT EXISTS idx_waiting_list_status ON waiting_list(estado) WHERE estado = 'Pendiente';
            CREATE INDEX IF NOT EXISTS idx_history_cita_fecha ON appointments_history(id_cita, created_at DESC);
        """)
        
        # Configuración agresiva del autovacuum regional
        cursor.execute("""
            ALTER TABLE appointments SET (
                autovacuum_vacuum_scale_factor = 0.05,
                autovacuum_analyze_scale_factor = 0.02,
                autovacuum_vacuum_cost_limit = 1000
            );
        """)
        
        connection.commit()
        print("Tablas físicas e índices creados con éxito en 'sgcm_db'.")
    except PGError as e:
        if connection:
            connection.rollback()
        print(f"Error al inicializar tablas físicas: {e}")
        raise
    finally:
        if connection:
            Database.release_connection(connection)


def inject_seed_data():
    """
    Inyecta datos de prueba iniciales (seeding) de forma idempotente para evitar duplicados.
    """
    connection = None
    try:
        connection = Database.get_connection()
        cursor = connection.cursor()
        print("Inyectando datos semilla en la base de datos...")

        # 1. Especialidades Semilla
        specialties = [
            ("Medicina General", "Consultas básicas de atención primaria."),
            ("Pediatria", "Especialidad en el cuidado de infantes y niños."),
            ("Cardiologia", "Diagnóstico y tratamiento de afecciones del corazón."),
            ("Dermatologia", "Cuidado de la piel, cabello y uñas.")
        ]
        
        specialty_ids = {}
        for name, desc in specialties:
            cursor.execute("SELECT id_especialidad FROM specialties WHERE nombre = %s;", (name,))
            res = cursor.fetchone()
            if not res:
                cursor.execute(
                    "INSERT INTO specialties (nombre, descripcion) VALUES (%s, %s) RETURNING id_especialidad;",
                    (name, desc)
                )
                specialty_ids[name] = cursor.fetchone()[0]
            else:
                specialty_ids[name] = res[0]

        # 2. Médicos Semilla
        doctors = [
            ("Dr. Carlos Gómez", "LIC-482094", specialty_ids["Medicina General"], "20 minutes"),
            ("Dra. María Restrepo", "LIC-902183", specialty_ids["Pediatria"], "30 minutes"),
            ("Dr. Juan Fernando López", "LIC-302198", specialty_ids["Cardiologia"], "40 minutes"),
            ("Dra. Paula Martínez", "LIC-883012", specialty_ids["Dermatologia"], "30 minutes")
        ]

        for name, lic, spec_id, duration in doctors:
            cursor.execute("SELECT id_medico FROM doctors WHERE numero_licencia = %s;", (lic,))
            res = cursor.fetchone()
            if not res:
                cursor.execute(
                    "INSERT INTO doctors (nombre_completo, numero_licencia, id_especialidad, duracion_defecto) "
                    "VALUES (%s, %s, %s, %s);",
                    (name, lic, spec_id, duration)
                )

        # 3. Pacientes Semilla de Prueba
        patients = [
            ("10203040", "Sofía Valentina Toro", "555-0192", "sofia.toro@email.com"),
            ("98765432", "Andrés Felipe Mejía", "555-8839", "andres.mejia@email.com"),
            ("11223344", "Carmen Alicia Rojas", "555-2201", "carmen.rojas@email.com") # Adulto mayor
        ]

        for dni, name, phone, email in patients:
            cursor.execute("SELECT id_paciente FROM patients WHERE dni = %s;", (dni,))
            res = cursor.fetchone()
            if not res:
                cursor.execute(
                    "INSERT INTO patients (dni, nombre_completo, telefono, email) VALUES (%s, %s, %s, %s);",
                    (dni, name, phone, email)
                )

        connection.commit()
        print("Datos semilla inyectados con éxito. Base de datos lista para pruebas locales.")

    except PGError as e:
        if connection:
            connection.rollback()
        print(f"Error al inyectar datos semilla: {e}")
        raise
    finally:
        if connection:
            Database.release_connection(connection)


if __name__ == "__main__":
    print("--- INICIANDO PROCESO DE CONFIGURACIÓN DE POSTGRESQL LOCAL ---")
    create_database_if_not_exists()
    initialize_tables()
    inject_seed_data()
    print("--- PROCESO DE INICIALIZACIÓN COMPLETADO CON ÉXITO ---")
