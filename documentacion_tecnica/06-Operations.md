# 📦 Capítulo 6: Gobierno de Código, Git Workflow y Operaciones

**ID del Documento:** `DOC-06`  
**Estado:** `APPROVED`  
**Esquema de Versionado:** Semantic Versioning (SemVer)  
**Flujo de Ramas:** GitFlow estructurado para entornos estables.

---

## 1. Estrategia de Control de Versiones: GitFlow

Para asegurar un desarrollo limpio, coordinado y auditable de los componentes de negocio médicos en GitHub, adoptaremos el modelo **GitFlow**. Este flujo separa de manera estricta el código en desarrollo activo, las fases de preparación de lanzamientos y el código en producción estable.

```
  main      ________________________[v1.0.0]___________________ (Producción)
                       /               \
  release/            /_____[v1.0.0-rc1]_____ (Staging/QA)
                     /         /
  develop   ________/_________/________________________________ (Integración)
              \             /
  feature/     \__[feat-1]_/___________________________________ (Desarrollo)
```

### 1.1. Ramas del Repositorio y su Propósito:
*   **`main`:** Almacena únicamente el código estable de producción. Cada commit en esta rama es un lanzamiento oficial y debe estar etiquetado con su respectiva etiqueta de versión (`v1.0.0`). Nadie realiza commits directos a `main`.
*   **`develop`:** Rama de integración para las nuevas funcionalidades. Contiene el código listo para la siguiente release.
*   **`feature/*`:** Ramas temporales creadas a partir de `develop` para desarrollar una funcionalidad específica (ej: `feature/waiting-list`). Al terminar, se integran de regreso a `develop` mediante un Pull Request (PR) con revisión de código obligatoria.
*   **`release/*`:** Ramas temporales para preparar un despliegue en producción (QA/Staging). Se extraen de `develop` y solo se permiten correcciones de bugs menores antes de fusionarse a `main` y `develop`.
*   **`hotfix/*`:** Ramas urgentes creadas directamente de `main` para solucionar fallos críticos en producción (ej. fallos en la cola LEA). Se fusionan de inmediato a `main` y a `develop`.

---

## 2. Estándar de Mensajes de Commit (Conventional Commits)

Todos los mensajes de confirmación de cambios (*commits*) en el repositorio de GitHub seguirán el estándar estructurado **Conventional Commits (v1.0.0)**. Esto permite generar CHANGELOGs automáticos y facilita la auditoría del historial de desarrollo:

### 2.1. Estructura General:
```
<type>(<scope>): <description>

[body]

[footer]
```

### 2.2. Tipos Admitidos (`type`):
*   **`feat`:** Incorporación de una nueva funcionalidad al sistema (ej: `feat(waiting-list): implement 2-hour rule for automatic slot assignment`).
*   **`fix`:** Solución de un bug o error en el sistema (ej: `fix(db): correct exclusion GIST overlap constraint syntax`).
*   **`docs`:** Cambios exclusivos en la documentación técnica (ej: `docs(cloud): update GCP pricing metrics`).
*   **`style`:** Cambios visuales o de formato que no alteran la lógica del código (espaciados, formateo con linter).
*   **`refactor`:** Modificación del código que no añade funcionalidad ni corrige bugs, pero mejora su legibilidad y diseño.
*   **`test`:** Creación o modificación de la suite de pruebas unitarias o de integración en Pytest.
*   **`chore`:** Actualización de tareas de empaquetado, dependencias de pip (`requirements.txt`), archivos de entorno o configuración de red.

---

## 3. Versionamiento Semántico (SemVer)

La numeración de las versiones del sistema utilizará la notación estándar **`MAJOR.MINOR.PATCH`** (ej: `v1.2.3`):
*   **MAJOR (Incremento de la primera cifra):** Cambios incompatibles con versiones anteriores (ej: migración del esquema de base de datos que destruye tablas previas o cambios en las rutas de la API REST que rompen la SPA).
*   **MINOR (Incremento de la segunda cifra):** Nuevas funcionalidades compatibles hacia atrás (ej: agregar la Web Speech API de voz para adultos mayores o añadir un nuevo tipo de reporte en el dashboard).
*   **PATCH (Incremento de la tercera cifra):** Corrección de bugs y parches de seguridad compatibles (ej: solucionar la latencia de un índice parcial GIST o ajustar el factor de reintentos del SMS).

---

## 4. Operaciones, Backups y Disaster Recovery

Para garantizar la alta disponibilidad de un sistema de salud crítico:

### 4.1. Estrategia de Backups Automáticos
*   **Frecuencia:** Copias de seguridad automáticas diarias administradas por **GCP Cloud SQL** con retención de **7 a 30 días**.
*   **Point-in-Time Recovery (PITR):** Habilitación del registro de transacciones (*Write-Ahead Logging* / WAL) para permitir restaurar la base de datos a cualquier segundo específico del pasado, previniendo pérdida de datos clínicos ante fallos de usuario o de sistema.

### 4.2. Recovery Point Objective (RPO) y Recovery Time Objective (RTO)
*   **RPO (Pérdida Máxima de Datos Aceptable):** `5 minutos` (Mitigado por el almacenamiento regional redundante de Cloud SQL y el PITR).
*   **RTO (Tiempo de Recuperación Máximo del Sistema):** `15 minutos` (Mitigado por el failover regional automático de Alta Disponibilidad de GCP y la arquitectura Serverless en contenedores de Cloud Run).
