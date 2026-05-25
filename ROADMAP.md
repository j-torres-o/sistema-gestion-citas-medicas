# 🗺️ Roadmap de Desarrollo: Sistema de Gestión de Citas Médicas (SGCM)

¡Bienvenido! Este documento actúa como la **Guía Maestra y Bitácora de Progreso** del proyecto, visible directamente en la raíz de tu espacio de trabajo. Sirve para coordinar las etapas del ciclo de desarrollo de software (SDLC) e identificar con precisión qué ha sido implementado, qué está en curso y qué falta por construir.

---

## 📊 Estado Actual del Proyecto

*   **Fase de Ingeniería Actual:** 🧠 Implementación de Reglas de Negocio Backend & QA Sólido (Completado) ➔ 🎨 Diseño y Desarrollo de Frontend UI/UX (Siguiente)
*   **Rama Activa de Git:** `develop`
*   **Estado de la Suite de Pruebas:** ✅ **11/11 tests aprobados (100% en verde)**
*   **Último Commit en develop:** `docs(diagramas): insertar diagramas de contexto, estados, DFD y secuencias en formato Mermaid`

---

## 🗺️ Matriz de Control de Fases y Progreso

A continuación se detalla la hoja de ruta del proyecto. Puedes usar este cuadro para validar el avance general del sistema:

| Fase de Desarrollo | Sub-componentes / Tareas | Estado | Ubicación del Código |
| :--- | :--- | :---: | :--- |
| **Fase 1: Esquema de Base de Datos y Semillado** | *   DDL físico unificado multi-sede, roles y exclusión GIST.<br>*   Configuración avanzada de Autovacuum e Índices GIST.<br>*   Seeding (datos semilla) de prueba completo. | 🟢 **100%** | [init_db.py](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/init_db.py)<br>[database.py](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/database.py) |
| **Fase 2: Modelos de Dominio OOP** | *   Unificación de la tabla relacional `users` para login.<br>*   Modelos nuevos en `models/` (`user`, `branch`, `system_parameter`, etc.).<br>*   Exportador unificado en paquete de modelos. | 🟢 **100%** | [models/](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/models/) |
| **Fase 3: Servicios y Lógica de Negocio** | *   **Seguridad y ABAC:** Servicio de permisos y delegaciones temporales.<br>*   **Motor LEA Dinámico:** Asignación reactiva de slots con coincidencia exacta y lookahead en caliente vía CTE.<br>*   **Citas Médicas:** Geografía estricta, traslado 1h, bloqueo por inasistencias y derivaciones recurrentes.<br>*   **Cancelación Masiva:** CSV en disco local simulated blob y prioridad cronológica LEA. | 🟢 **100%** | [services/](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/services/) |
| **Fase 4: Suite de Pruebas y Aseguramiento QA** | *   Validación transaccional con PostgreSQL real de pruebas.<br>*   Tests unitarios y de integración para todas las reglas de negocio.<br>*   Pipeline de CI en GitHub Actions estabilizado. | 🟢 **100%** | [tests/](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/tests/)<br>[.github/workflows/ci.yml](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/.github/workflows/ci.yml) |
| **Fase 5: Interfaz de Usuario (Frontend UI/UX)** | *   **Sistema visual:** Selector Claro/Oscuro/Alto Contraste y Outfit/Inter.<br>*   **Paciente:** Flujo guiado paso a paso con botones grandes y soporte de voz interactivo.<br>*   **Personal Clínico:** Dashboard diario, check-in, buscadores inteligentes y sala virtual del médico. | 🟡 **0%** | *Siguiente etapa a implementar (PASO 5)* |
| **Fase 6: Despliegue en la Nube y Costos** | *   Contenedores Docker y scripting de automatización.<br>*   Configuración serverless en Google Cloud Platform (Cloud Run + Cloud SQL).<br>*   Plan de Disaster Recovery, backups PITR y RPO/RTO. | 🔴 **0%** | *Por implementar (PASO 6)* |

---

## 📖 Documentación Centralizada

Toda la documentación técnica formal de arquitectura se encuentra indexada y organizada de forma modular:

*   **Índice Maestro:** [documentacion_tecnica/README.md](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/documentacion_tecnica/README.md) (Incluye el **Diagrama de Contexto del Sistema**).
*   **Capítulo 1: Diseño de Base de Datos:** [documentacion_tecnica/01-Database-Design.md](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/documentacion_tecnica/01-Database-Design.md) (Esquema físico e Índices).
*   **Capítulo 2: Lógica de Negocio y LEA:** [documentacion_tecnica/02-Business-Logic.md](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/documentacion_tecnica/02-Business-Logic.md) (Incluye **DFD, Diagrama de Estados y Diagramas de Secuencia**).
*   **Capítulo 3: Infraestructura Cloud y Costos:** [documentacion_tecnica/03-Infrastructure.md](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/documentacion_tecnica/03-Infrastructure.md) (Comparativa y Presupuesto).
*   **Capítulo 4: Accesibilidad, Roles y Seguridad:** [documentacion_tecnica/04-Security-Compliance.md](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/documentacion_tecnica/04-Security-Compliance.md) (Matriz de Accesos y Delegaciones).
*   **Capítulo 5: Aseguramiento de Calidad:** [documentacion_tecnica/05-Testing-QA.md](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/documentacion_tecnica/05-Testing-QA.md) (Casos de prueba Pytest).
*   **Capítulo 6: Gobierno de Código y Operaciones:** [documentacion_tecnica/06-Operations.md](file:///c:/Projects/desarrollo_de_sistemas_de_informacion/documentacion_tecnica/06-Operations.md) (GitFlow y Convenciones).

---

## 🛠️ Notas de Operación y Soporte Rápido

### Ejecutar Base de Datos Local y Semillado
```powershell
# Recrear tablas e inyectar datos de prueba
python init_db.py
```

### Ejecutar Suite de Pruebas
```powershell
# Correr todas las validaciones unitarias y de integración
.\venv\Scripts\python -m pytest -v
```

---
*Este documento se mantendrá actualizado en cada hito relevante del desarrollo del SGCM.*
