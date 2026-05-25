# 🗄️ Capítulo 1: Diseño de Base de Datos (PostgreSQL Nativo)

**ID del Documento:** `DOC-01`  
**Estado:** `APPROVED`  
**Mantenedor:** Equipo de Ingeniería de Datos / DBA  
**Presupuesto de Rendimiento:** Latencia de consulta `p95 < 100ms` para operaciones CRUD.

---

## 1. Introducción y Elección del Motor

Para el **Sistema de Gestión de Citas Médicas (SGCM)** en producción, la persistencia se delega a **PostgreSQL (v15+)**. A diferencia de MySQL, PostgreSQL ofrece:
1. **Multi-Version Concurrency Control (MVCC) avanzado:** Permite lecturas no bloqueantes y excelente gestión de transacciones simultáneas.
2. **Tipos de datos de Rango Temporal (`tstzrange`):** Permite modelar citas médicas como un intervalo continuo con zona horaria (UTC), facilitando cálculos de intersección en lugar de complejas e inestables validaciones a nivel de aplicación.
3. **Restricción de Exclusión (Exclusion Constraints):** Garantiza a nivel de motor de base de datos que **ningún médico sea agendado dos veces en el mismo bloque horario**.

---

## 2. Diagrama de la Arquitectura de Base de Datos (DER)

El siguiente Diagrama Entidad-Relación (DER) ilustra el modelado lógico de la persistencia de datos, las relaciones y la cardinalidad entre los componentes del sistema clínico, la lista de espera y los logs transaccionales inmutables:

```mermaid
erDiagram
    ESPECIALIDADES {
        UUID id_especialidad PK
        VARCHAR nombre UNIQUE
        TEXT descripcion
    }
    MEDICOS {
        UUID id_medico PK
        VARCHAR numero_licencia UNIQUE
        VARCHAR nombre_completo
        UUID id_especialidad FK
        INTERVAL duracion_defecto
    }
    PACIENTES {
        UUID id_paciente PK
        VARCHAR dni UNIQUE
        VARCHAR nombre_completo
        VARCHAR telefono
        VARCHAR email UNIQUE
    }
    CITAS {
        UUID id_cita PK
        UUID id_medico FK
        UUID id_paciente FK
        TSTZRANGE rango_cita
        VARCHAR estado
    }
    COLA_ESPERA {
        UUID id_espera PK
        UUID id_paciente FK
        UUID id_especialidad FK
        VARCHAR tipo_cola
        DATERANGE rango_deseado
        VARCHAR estado
    }
    HISTORIAL_CITAS {
        UUID id_historial PK
        UUID id_cita FK
        VARCHAR estado_anterior
        VARCHAR estado_nuevo
        VARCHAR tipo_accion
        VARCHAR realizado_por
        VARCHAR usuario_identificador
        TEXT detalle
        TIMESTAMP created_at
    }

    ESPECIALIDADES ||--|{ MEDICOS : "pertenece"
    MEDICOS ||--o{ CITAS : "atiende"
    PACIENTES ||--o{ CITAS : "agenda"
    PACIENTES ||--o{ COLA_ESPERA : "se registra"
    ESPECIALIDADES ||--o{ COLA_ESPERA : "solicita"
    CITAS ||--o{ HISTORIAL_CITAS : "registra cambios"
```

---

## 3. Esquema Físico DDL (PostgreSQL)

El siguiente script de inicialización crea la estructura relacional e inyecta las restricciones de exclusión. Se requiere la extensión `btree_gist` para poder mezclar tipos primitivos como `UUID` con tipos de rango en el índice GIST.

Incluye la tabla robustecida de **Historial de Citas (`appointments_history`)** para registrar cada cambio de estado, quién lo realizó (Paciente, Médico, Recepcionista, o automáticamente el Sistema) y qué campos fueron modificados para auditoría inmutable.

```sql
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

-- 2. Tabla de Médicos
CREATE TABLE doctors (
    id_medico UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    numero_licencia VARCHAR(50) NOT NULL UNIQUE,
    nombre_completo VARCHAR(150) NOT NULL,
    id_especialidad UUID NOT NULL REFERENCES specialties(id_especialidad) ON DELETE RESTRICT,
    duracion_defecto INTERVAL NOT NULL DEFAULT '30 minutes', -- Duración parametrizable por médico
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Tabla de Pacientes
CREATE TABLE patients (
    id_paciente UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dni VARCHAR(20) NOT NULL UNIQUE,
    nombre_completo VARCHAR(150) NOT NULL,
    telefono VARCHAR(20) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Tabla de Citas Médicas con Restricción de Solapamiento
CREATE TABLE appointments (
    id_cita UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    id_medico UUID NOT NULL REFERENCES doctors(id_medico) ON DELETE CASCADE,
    id_paciente UUID REFERENCES patients(id_paciente) ON DELETE SET NULL,
    -- Rango de tiempo de la cita (UTC con Zona Horaria)
    rango_cita TSTZRANGE NOT NULL,
    estado VARCHAR(50) NOT NULL DEFAULT 'Agendada' 
        CONSTRAINT chk_estado CHECK (estado IN ('Agendada', 'Confirmada', 'EnCurso', 'Finalizada', 'Cancelada', 'NoAsistio')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,

    -- RESTRICCIÓN DE EXCLUSIÓN: Ningún médico puede tener citas solapadas (&&)
    -- El operador '=' asegura que sea para el mismo médico, y '&&' verifica el cruce de rangos
    CONSTRAINT exclude_overlapping_appointments EXCLUDE USING gist (
        id_medico WITH =,
        rango_cita WITH &&
    )
);

-- 5. Tabla de Solicitudes en Lista de Espera (LEA)
CREATE TABLE waiting_list (
    id_espera UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    id_paciente UUID NOT NULL REFERENCES patients(id_paciente) ON DELETE CASCADE,
    id_especialidad UUID NOT NULL REFERENCES specialties(id_especialidad) ON DELETE CASCADE,
    tipo_cola VARCHAR(30) NOT NULL DEFAULT 'FechaCercana'
        CONSTRAINT chk_tipo_cola CHECK (tipo_cola IN ('FechaCercana', 'RangoEspecifico')),
    rango_deseado DATERANGE, -- Rango de fechas estimado (solo aplica para RangoEspecifico)
    estado VARCHAR(30) NOT NULL DEFAULT 'Pendiente'
        CONSTRAINT chk_estado_espera CHECK (estado IN ('Pendiente', 'Asignada', 'Cancelada', 'Expirada')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Tabla de Historial y Auditoría Transaccional de Citas (Inmutable)
CREATE TABLE appointments_history (
    id_historial UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    id_cita UUID NOT NULL REFERENCES appointments(id_cita) ON DELETE CASCADE,
    estado_anterior VARCHAR(50) 
        CONSTRAINT chk_est_ant CHECK (estado_anterior IN ('Agendada', 'Confirmada', 'EnCurso', 'Finalizada', 'Cancelada', 'NoAsistio', NULL)),
    estado_nuevo VARCHAR(50) NOT NULL
        CONSTRAINT chk_est_nue CHECK (estado_nuevo IN ('Agendada', 'Confirmada', 'EnCurso', 'Finalizada', 'Cancelada', 'NoAsistio')),
    tipo_accion VARCHAR(50) NOT NULL -- 'Creación', 'Asignación', 'Modificación', 'Cancelación'
        CONSTRAINT chk_tipo_accion CHECK (tipo_accion IN ('Creacion', 'Asignacion', 'Modificacion', 'Cancelacion')),
    realizado_por VARCHAR(50) NOT NULL -- 'Paciente', 'Recepcionista', 'Medico', 'Sistema'
        CONSTRAINT chk_realizado_por CHECK (realizado_por IN ('Paciente', 'Recepcionista', 'Medico', 'Sistema')),
    usuario_identificador VARCHAR(150) NOT NULL, -- Email o DNI del usuario de la acción, o 'SYSTEM'
    detalle TEXT, -- Detalle del cambio (ej: "Reprogramado slot de 14:00 a 15:30")
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. Optimización del Rendimiento en Producción

### 4.1. Mitigación del Costo del Índice GIST (Write Amplification)
Los índices GIST imponen una sobrecarga de escritura debido a la complejidad espacial. Para mitigar esto, implementamos un **índice parcial** enfocado únicamente en optimizar la búsqueda de citas activas o futuras:

```sql
-- Índice parcial GIST para citas activas (futuras o del último mes)
CREATE INDEX idx_active_appointments ON appointments USING GIST (rango_cita)
WHERE lower(rango_cita) > NOW() - INTERVAL '30 days';
```

### 4.2. Configuración Agresiva de Autovacuum
El agendamiento y liberación constante de citas médicas produce fragmentación rápida y tuplas muertas en la base de datos (Bloat). Para evitar la degradación del rendimiento, la tabla `appointments` se configurará con un ciclo de autovacuum altamente receptivo:

```sql
ALTER TABLE appointments SET (
    autovacuum_vacuum_scale_factor = 0.05,  -- Activa vacuum cuando se altera el 5% de las filas
    autovacuum_analyze_scale_factor = 0.02, -- Recalcula estadísticas al alterar el 2%
    autovacuum_vacuum_cost_limit = 1000     -- Asigna más prioridad y recursos al autovacuum
);
```

### 4.3. Índices Complementarios B-Tree
Para agilizar las búsquedas en los módulos de login, filtros de pacientes y auditoría:
```sql
CREATE INDEX idx_patients_dni ON patients(dni);
CREATE INDEX idx_waiting_list_status ON waiting_list(estado) WHERE estado = 'Pendiente';
CREATE INDEX idx_appointments_history_cita ON appointments_history(id_cita);
```
