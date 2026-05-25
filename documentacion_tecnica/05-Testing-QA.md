# 🧪 Capítulo 5: Estrategia de Aseguramiento de Calidad (QA & Testing)

**ID del Documento:** `DOC-05`  
**Estado:** `APPROVED`  
**Entorno de Pruebas:** `staging`  
**Métrica de Calidad Exigida:** Cobertura de código (Code Coverage) `> 85%` en la capa de servicios e integración.

---

## 1. Pirámide de Pruebas con Pytest

Para garantizar la estabilidad absoluta y evitar regresiones en un sistema transaccional médico, el ecosistema de pruebas automatizadas se estructurará en tres niveles integrados en el pipeline de CI/CD:

```
      / \
     /   \      E2E (Navegador/Playwright) - Journey del Paciente (~5%)
    /     \
   /-------\    Integración (API / DB PostgreSQL / Concurrencia) (~30%)
  /         \
 /-----------\  Unitarias (Modelos / Validaciones / Regla 2H) (~65%)
/_____________\
```

### 1.1. Pruebas Unitarias
Focalizadas en validar la lógica pura de negocio y las restricciones de formato en total aislamiento, utilizando `pytest-mock` para mockear llamadas externas:
*   Validación de formato de DNI mediante algoritmo de módulo.
*   Validación de la **Regla de las 2 Horas** en la capa de servicio (inyección de horas frontera con la librería `freezegun`).
*   Validación del cálculo de solapamiento de rangos de citas médicas en Python.

### 1.2. Pruebas de Integración (PostgreSQL Real)
Validación de los endpoints de la API REST (`/api/citas`) interactuando contra una base de datos real de pruebas aislada (`sgcm_test`):
*   Validación de la restricción de exclusión física en base de datos PostgreSQL ante intentos de insertar citas cruzadas para el mismo médico.
*   Inserción exitosa de pacientes y asignación de citas, verificando que los registros se graben con sus zonas horarias (UTC) correspondientes.
*   Registro y validación de las tablas de logs de auditoría ante mutaciones CRUD.

---

## 2. Automatización de Pruebas de Concurrencia (Race Conditions)

Como pauta obligatoria de aseguramiento de calidad, se implementará la automatización de pruebas que validen la resiliencia del sistema ante race conditions. Utilizaremos hilos concurrentes en Python (`threading` o `pytest-asyncio`) para simular múltiples pacientes intentando agendar el mismo slot de cita o ser procesados en la cola LEA al mismo tiempo.

El siguiente test valida que nuestro uso de `FOR UPDATE SKIP LOCKED` y las exclusiones en PostgreSQL manejen correctamente el agendamiento concurrente sin generar duplicados:

```python
import pytest
import threading
from database import db
from models import Appointment

def attempt_booking(appointment_id, patient_id, result_list):
    """
    Función helper que corre en un hilo independiente.
    Simula a un paciente intentando reservar el slot liberado.
    """
    # Crear una nueva sesión de base de datos para este hilo
    session = db.create_scoped_session()
    try:
        # Iniciar transacción con nivel de aislamiento adecuado
        session.execute("BEGIN;")
        
        # Buscar el slot y bloquearlo
        slot = session.query(Appointment)\
            .filter(Appointment.id_cita == appointment_id)\
            .with_for_update(skip_locked=True)\
            .first()
            
        if slot and slot.id_paciente is None:
            # Reservar el slot de forma atómica
            slot.id_paciente = patient_id
            slot.estado = 'Agendada'
            session.commit()
            result_list.append((patient_id, "SUCCESS"))
        else:
            session.rollback()
            result_list.append((patient_id, "SKIPPED"))
    except Exception as e:
        session.rollback()
        result_list.append((patient_id, f"ERROR: {str(e)}"))
    finally:
        session.remove()

def test_concurrent_booking_race_condition(setup_test_db):
    """
    Test de concurrencia avanzado.
    Simula 5 hilos intentando reservar el mismo slot libre a la vez.
    """
    # 1. Crear un slot libre en la base de datos de pruebas
    slot_id = "d87a71f7-e7fd-4d2a-a9fa-0797179047cb"  # UUID de prueba
    create_test_free_slot(slot_id)

    results = []
    threads = []
    
    # 2. Levantar 5 hilos concurrentes simulando 5 pacientes distintos
    for i in range(5):
        patient_id = f"paciente-uuid-{i}"
        t = threading.Thread(target=attempt_booking, args=(slot_id, patient_id, results))
        threads.append(t)
        t.start()

    # 3. Esperar a que terminen todos los hilos
    for t in threads:
        t.join()

    # 4. ASERCIONES DE QA:
    # - Solo un paciente debió haber reservado la cita con éxito (Rows affected = 1).
    # - Los 4 restantes debieron haber sido salteados (SKIPPED) de forma segura.
    success_bookings = [r for r in results if r[1] == "SUCCESS"]
    skipped_bookings = [r for r in results if r[1] == "SKIPPED"]

    assert len(success_bookings) == 1, "ERROR: ¡Más de un paciente logró reservar el mismo slot!"
    assert len(skipped_bookings) == 4, "ERROR: Los pacientes restantes no fueron salteados de forma segura."
```

---

## 3. Pruebas Automatizadas de Accesibilidad (WCAG)

Para asegurar que los lineamientos de accesibilidad para adultos mayores se mantengan estables y no se degraden durante el desarrollo, integraremos auditorías automatizadas del DOM en nuestras pruebas E2E utilizando **Playwright** y el motor de accesibilidad **`axe-core`**:

```javascript
// Prueba de integración E2E de Accesibilidad con Playwright (JavaScript)
const { test, expect } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;

test.describe('Módulo de Agendamiento - Accesibilidad Inclusiva', () => {
  test('El formulario Linear Wizard no debe violar directrices WCAG 2.1 AA', async ({ page }) => {
    // 1. Navegar al formulario de agendamiento guiado
    await page.goto('/agendar-cita');

    // 2. Ejecutar el análisis de accesibilidad axe
    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag21aa']) // Validar WCAG 2.0 y 2.1 Nivel AA
      .analyze();

    // 3. ASERCIÓN DE QA: Cero violaciones detectadas
    expect(accessibilityScanResults.violations).toEqual([]);
  });
});
```
