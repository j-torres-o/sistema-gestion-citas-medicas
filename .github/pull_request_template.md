## 📋 Descripción del Cambio
*Por favor, proporciona un resumen claro de los cambios introducidos y la justificación del negocio.*

**ID de la Tarea/Feature:** `feat(scope)` / `fix(scope)`

---

## 🛠️ Tipo de Cambio
- [ ] **feat**: Nueva funcionalidad para el sistema.
- [ ] **fix**: Corrección de un error o bug.
- [ ] **docs**: Cambios exclusivos en la documentación.
- [ ] **refactor**: Optimización de código sin alterar comportamiento.
- [ ] **test**: Modificación o agregado de pruebas.
- [ ] **chore**: Tareas de empaquetado, variables de entorno o dependencias.

---

## 🧪 Lista de Verificación de Aseguramiento de Calidad (QA)

### 1. Pruebas Automatizadas y Cobertura (Pytest)
- [ ] ¿Se han agregado pruebas unitarias o de integración en Pytest que cubran los nuevos flujos?
- [ ] ¿El reporte de cobertura local supera el **85%** en los archivos modificados?
- [ ] ¿Se ejecutaron las pruebas locales de concurrencia y no hay fallas ni duplicados?
- [ ] ¿Todas las pruebas del pipeline de integración pasan exitosamente?

### 2. Integridad de Base de Datos y Concurrencia (PostgreSQL)
- [ ] Si hay cambios de esquema, ¿se agregaron las restricciones de exclusión `EXCLUDE` o llaves foráneas correspondientes?
- [ ] ¿Las consultas críticas de asignación implementan bloqueo pesimista con `FOR UPDATE SKIP LOCKED`?
- [ ] ¿Los logs de auditoría inmutables se registran ante cada mutación?

### 3. Accesibilidad Inclusiva (WCAG 2.1 AA)
- [ ] ¿Los botones interactivos modificados/agregados cumplen con el tamaño mínimo de **48x48 píxeles**?
- [ ] ¿Se garantizó la legibilidad, fuentes sans-serif y relación de contraste 7:1 en la UI?
- [ ] ¿El flujo se mantiene estrictamente secuencial (**Linear Wizard Pattern**)?
- [ ] ¿Se probó el fallback e interactividad en caso de deshabilitar los comandos de voz?

### 4. Seguridad de Datos (Habeas Data / PHI)
- [ ] ¿Se aseguró que **ningún dato sensible de salud (DNI, nombres, teléfonos)** se escriba en los logs públicos?
- [ ] ¿Las contraseñas de las nuevas cuentas de prueba se procesan de forma segura con `bcrypt`?

---

## 📷 Capturas de Pantalla / Demostraciones
*(Si aplica, arrastra y suelta imágenes o grabaciones que demuestren visualmente los cambios en la UI/UX)*
