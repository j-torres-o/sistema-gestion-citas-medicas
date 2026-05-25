# 🧪 Capítulo 5: Estrategia de Aseguramiento de Calidad (QA & Testing)

**ID del Documento:** `DOC-05`  
**Estado:** `APPROVED`  
**Entorno de Pruebas:** `testing`  
**Métrica de Calidad Exigida:** Cobertura de código (Code Coverage) `100%` en la capa de servicios core e integrales del motor LEA.

---

## 1. Pirámide de Pruebas en Pytest

El ecosistema de pruebas automatizadas está diseñado para garantizar la integridad y confiabilidad transaccional del backend médico, integrando un entorno real PostgreSQL bajo Pytest.

```
       / \
      /   \      E2E (Navegador/Playwright) - Journey del Paciente (~5%)
     /     \
    /-------\    Integración (Servicios / PostgreSQL Real / Concurrencia) (~35%)
   /         \
  /-----------\  Unitarias (Modelos OOP / Validaciones de Campos) (~60%)
 /_____________\
```

---

## 2. Cobertura de Pruebas de Integración Clínica y Reglas de Negocio

La suite de pruebas automatizadas en `tests/test_waiting_list_engine.py` utiliza una conexión real a la base de datos de pruebas PostgreSQL configurada a través de `tests/conftest.py` y aplica fixtures deterministas de limpieza de tablas (`clean_tables`).

### 2.1. Lista de Casos de Prueba Implementados e Integrados:

1.  **`test_lea_engine_fifo_assignment_success`:** Valida que el motor LEA asigne un slot liberado de forma atómica al paciente más antiguo de la cola de espera de la misma especialidad y sede (estricto FIFO).
2.  **`test_lea_engine_two_hour_rule_prevents_assignment`:** Verifica que la regla de amortiguación horaria dinámica prevenga la asignación automática por LEA si el slot empieza hoy en menos de `buffer_horas` (ej. 2 horas).
3.  **`test_appointment_cancellation_buffer_rule`:** Valida que las cancelaciones del paciente autónomo fallen si faltan menos de `buffer_horas` para la cita, pero que las Recepcionistas puedan cancelarlas libremente a cualquier hora.
4.  **`test_appointment_branch_change_geography`:** Evalúa la restricción de geografía estricta. Asegura que reubicar una cita a una sede de otra ciudad falle con un `ValueError`, pero pase si es en la misma ciudad de origen del paciente.
5.  **`test_execute_massive_cancellation_and_chronological_priority`:** Valida la cancelación en lote de agendas futuras de médicos o sedes, la escritura física del reporte de evidencia CSV en `storage/reports/` y la reinserción de pacientes a la lista de espera respetando su prioridad cronológica.
6.  **`test_coincidencia_exacta_priority`:** Valida la regla de "Coincidencia Exacta". Si un slot se cancela masivamente y luego se abre con otro médico en la misma hora, sede y especialidad, el motor LEA prioriza de forma absoluta asignar el slot al paciente afectado, saltándose el FIFO general.
7.  **`test_double_booking_and_medical_authorization`:** Verifica que un paciente no pueda tener dos reservas activas para la misma especialidad simultáneamente, a menos que exista una autorización clínica registrada (`medical_authorizations`), consumiendo sus sesiones de forma atómica.
8.  **`test_consecutive_no_show_suspension`:** Verifica la penalización por inasistencia. Si un paciente acumula 3 marcas `'NoAsistio'` seguidas, se bloquea su auto-agendamiento autónomo en el portal, permitiendo únicamente agendamiento asistido por Recepcionista.
9.  **`test_travel_time_inter_branch`:** Valida la restricción de tiempo de traslado inter-sede. Exige al menos 60 minutos de diferencia si el paciente tiene dos citas el mismo día en sedes físicas distintas.

---

## 3. Implementación de una Prueba de Integración Real (Pytest/psycopg2)

El siguiente fragmento de código ilustra cómo se estructura la validación de las reglas avanzadas interactuando directamente con PostgreSQL y la capa de servicios:

```python
def test_appointment_branch_change_geography():
    """
    Valida la restricción geográfica estricta al cambiar la sede de una cita.
    """
    conn = Database.get_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # 1. Crear sedes de prueba en ciudades diferentes
            cursor.execute("INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede Poblado', 'Medellin', 'Calle 10') RETURNING id_sede;")
            id_sede_med = cursor.fetchone()['id_sede']

            cursor.execute("INSERT INTO branches (nombre, ciudad, direccion) VALUES ('Sede Chapinero', 'Bogota', 'Calle 60') RETURNING id_sede;")
            id_sede_bog = cursor.fetchone()['id_sede']

            # 2. Registrar paciente en Medellín
            cursor.execute(
                "INSERT INTO patients (dni, nombre_completo, telefono, email, ciudad_origen) "
                "VALUES ('7050', 'Carmen Medellin', '555-5555', 'carmen.med@email.com', 'Medellin') RETURNING id_paciente;"
            )
            id_paciente = cursor.fetchone()['id_paciente']

            # 3. Crear doctor y cita
            ...
            
        conn.commit()

        # 4. ASERCIÓN DE QA: Intentar trasladar cita a sede de Bogotá (Debe fallar)
        with pytest.raises(ValueError) as exc_info:
            AppointmentService.change_appointment_branch(
                id_cita=id_cita,
                id_sede_destino=id_sede_bog,
                realizado_por='Recepcionista',
                usuario_identificador='recep1@email.com'
            )
        assert "Restricción geográfica" in str(exc_info.value)
        
    finally:
        Database.release_connection(conn)
```

---

## 4. Ejecución de la Suite de Pruebas localmente

Para ejecutar el plan de pruebas unitarias y de integración y verificar la cobertura:

```bash
# Ejecutar todas las pruebas en modo detallado
.\venv\Scripts\python -m pytest -v
```
*Todas las pruebas deben finalizar de forma exitosa (Conclusion: `success` en el pipeline de GitHub Actions).*
