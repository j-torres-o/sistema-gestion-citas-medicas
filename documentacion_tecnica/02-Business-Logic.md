# 🧠 Capítulo 2: Lógica de Negocio y Motor de Lista de Espera

**ID del Documento:** `DOC-02`  
**Estado:** `APPROVED`  
**Garantía de Idempotencia:** Requerido para todas las asignaciones automáticas de slots.  
**Estrategia contra Race Conditions:** Bloqueo pesimista a nivel de fila (`FOR UPDATE SKIP LOCKED`).

---

## 1. Algoritmo de Lista de Espera Automática (LEA)

El motor de asignación opera de manera reactiva ante la liberación de disponibilidad médica. Su propósito es capturar de forma ordenada y consistente el primer paciente de la lista de espera elegible para ocupar el espacio vacante.

### 1.1. Reglas de Negocio Implementadas:
1.  **Prioridad FIFO:** Los pacientes en cola son atendidos por estricto orden de solicitud (`created_at ASC`).
2.  **Regla de las 2 Horas:** Si un espacio se libera para el **día de hoy**, solo se asignará automáticamente si existe una diferencia de **al menos 2 horas** entre la hora actual (`clock_timestamp()`) y el inicio de la cita. Esto previene asignar citas a las que el paciente físicamente no alcanzará a asistir.
3.  **Regla de los Días Siguientes (Lookahead Limitado):** Si no hay un paciente con un rango de fechas que cubra exactamente el slot liberado, se permite asignar el espacio a un paciente de rango específico (`RangoEspecifico`) si la cita liberada cae en los **días posteriores** a su rango, con un **límite estricto de hasta 7 días posteriores**. Esto evita asignarle citas muy lejanas en el futuro.
4.  **Asignación Directa:** La cita se asigna de manera directa a la cuenta del paciente. El sistema no requiere confirmación previa de 15 minutos (reduciendo la barrera digital para adultos mayores). La persona simplemente recibe la notificación y tiene la opción de cancelarla libremente desde su portal si no le resulta conveniente.

---

## 2. Implementación de Consulta y Bloqueo Concurrente (SQL)

Para mitigar las condiciones de carrera (*Race Conditions*) en las que múltiples workers asíncronos concurrentes intenten tomar el mismo slot libre y asignárselo a distintos pacientes, utilizaremos el comando **`FOR UPDATE SKIP LOCKED`** de PostgreSQL. 

Esta instrucción bloquea de forma pesimista el registro de la lista de espera evaluado en la transacción actual, y le indica a las transacciones simultáneas que "salten" el registro si ya está bloqueado, previniendo cuellos de botella (*deadlocks*) y garantizando una asignación atómica única.

```sql
-- Transacción atómica de asignación de slot liberado
BEGIN;

-- 1. Capturar y bloquear al primer paciente en cola elegible para el slot liberado
WITH next_patient AS (
    SELECT id_espera, id_paciente, rango_deseado, tipo_cola
    FROM waiting_list
    WHERE estado = 'Pendiente'
      AND id_especialidad = :id_especialidad_liberada
      AND (
          -- Condición A: Tipo FIFO general (sin rango)
          tipo_cola = 'FechaCercana'
          OR
          -- Condición B: Rango deseado intersecta con la fecha del slot liberado
          (tipo_cola = 'RangoEspecifico' AND rango_deseado @> :fecha_slot_liberada::date)
          OR
          -- Condición C (Regla Días Siguientes): Slot cae dentro de los 7 días posteriores a su rango deseado
          (tipo_cola = 'RangoEspecifico' 
           AND :fecha_slot_liberada::date > upper(rango_deseado) 
           AND :fecha_slot_liberada::date <= upper(rango_deseado) + INTEGER '7')
      )
    ORDER BY created_at ASC -- FIFO estricto
    LIMIT 1
    FOR UPDATE SKIP LOCKED -- Bloqueo pesimista concurrente y seguro
)
-- 2. Actualizar el estado del registro seleccionado a 'Asignada'
UPDATE waiting_list 
SET estado = 'Asignada', updated_at = CURRENT_TIMESTAMP
WHERE id_espera = (SELECT id_espera FROM next_patient)
RETURNING id_paciente, tipo_cola;

-- 3. Si se halló un paciente en el paso anterior, asociarlo a la cita
UPDATE appointments
SET id_paciente = :id_paciente, estado = 'Agendada', updated_at = CURRENT_TIMESTAMP
WHERE id_cita = :id_cita_liberada 
  AND id_paciente IS NULL;

-- 4. Registrar la transacción en el Log de Auditoría para trazabilidad inmutable
INSERT INTO audit_logs (usuario_email, operacion, detalle)
VALUES (
    'system_engine@clinicasalud.com', 
    'UPDATE', 
    'Asignación automática de slot de cita libre a paciente ' || :id_paciente || ' por motor LEA.'
);

COMMIT;
```

---

## 3. Lógica del Backend en Python (Capa de Servicio)

El siguiente script en Python/Flask implementa la validación transaccional complementaria y la regla de las 2 horas utilizando el micro-framework y SQLAlchemy:

```python
from datetime import datetime, timedelta
from database import db
from models import Appointment, WaitingList, AuditLog

def handle_liberated_slot(appointment_id: str):
    """
    Controlador central del motor LEA.
    Se activa al detectar la cancelación de una cita o la apertura de nueva disponibilidad.
    """
    current_time = datetime.now(timezone.utc)
    
    # Obtener el slot liberado
    slot = Appointment.query.get(appointment_id)
    if not slot or slot.id_paciente is not None:
        return  # Slot no existe o ya está ocupado

    slot_start = slot.rango_cita.lower
    
    # REGLA DE LAS 2 HORAS: 
    # Si la cita es para el día de hoy, debe existir un margen mínimo de 2 horas.
    if slot_start.date() == current_time.date():
        if (slot_start - current_time) < timedelta(hours=2):
            # El slot queda libre en el pool público, no se asigna automáticamente a cola.
            return

    # Buscar el especialista y la especialidad correspondiente
    doctor = slot.doctor
    id_especialidad = doctor.id_especialidad
    fecha_slot = slot_start.date()

    # Ejecutar la lógica de asignación pesimista
    # Se utiliza 'FOR UPDATE SKIP LOCKED' nativo en SQLAlchemy
    patient_in_wait = db.session.query(WaitingList)\
        .filter(WaitingList.estado == 'Pendiente')\
        .filter(WaitingList.id_especialidad == id_especialidad)\
        .filter(
            (WaitingList.tipo_cola == 'FechaCercana') |
            (WaitingList.rango_deseado.contains(fecha_slot)) |
            (
                (fecha_slot > WaitingList.rango_deseado.upper) &
                (fecha_slot <= WaitingList.rango_deseado.upper + timedelta(days=7))
            )
        )\
        .order_by(WaitingList.created_at.asc())\
        .with_for_update(skip_locked=True)\
        .first()

    if patient_in_wait:
        # 1. Asignar paciente al slot de cita
        slot.id_paciente = patient_in_wait.id_paciente
        slot.estado = 'Agendada'
        
        # 2. Actualizar registro en lista de espera
        patient_in_wait.estado = 'Asignada'
        patient_in_wait.updated_at = current_time

        # 3. Registrar auditoría inmutable
        audit = AuditLog(
            usuario_email='sistema_automatizacion@clinica.com',
            operacion='UPDATE',
            detalle=f"Cita {appointment_id} asignada automáticamente a Paciente {patient_in_wait.id_paciente} vía cola de espera."
        )
        db.session.add(audit)
        
        # 4. Confirmar cambios atómicamente
        db.session.commit()

        # 5. Lanzar envío de SMS simulado asíncrono
        trigger_sms_notification(patient_in_wait.id_paciente, slot_start)
    else:
        db.session.rollback()
```

---

## 4. Módulo de Modificación y Cancelación de Citas

El sistema provee interfaces para cambiar o cancelar las citas, siguiendo las siguientes reglas estrictas:
*   **Cancelación por el Paciente:** El paciente puede cancelar su cita libremente hasta **24 horas antes** del inicio del evento. Esto se realiza asíncronamente y dispara inmediatamente el evento `SLOT_CREATED` para el motor LEA.
*   **Modificación de Cita (Reprogramación):** Para evitar solapamientos, la reprogramación es tratada atómicamente como una cancelación de la cita actual y la creación de una nueva en el nuevo bloque deseado.
