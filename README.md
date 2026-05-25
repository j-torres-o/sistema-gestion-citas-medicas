# 🗓️ Sistema de Gestión de Citas Médicas (SGCM)

[![SGCM CI Pipeline](https://github.com/j-torres-o/sistema-gestion-citas-medicas/actions/workflows/ci.yml/badge.svg)](https://github.com/j-torres-o/sistema-gestion-citas-medicas/actions/workflows/ci.yml)
[![PostgreSQL](https://img.shields.io/badge/Database-PostgreSQL-blue.svg)](https://www.postgresql.org/)
[![Python](https://img.shields.io/badge/Backend-Python_Flask-green.svg)](https://flask.palletsprojects.com/)
[![Axe Accessibility](https://img.shields.io/badge/WCAG_2.1-AA_Compliant-orange.svg)](https://www.w3.org/WAI/standards-guidelines/wcag/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Bienvenido a la plataforma del **Sistema de Gestión de Citas Médicas (SGCM)**, una aplicación web full-stack de grado profesional diseñada para centralizar, automatizar y optimizar el proceso de agendamiento clínico de la clínica "Salud Integral". 

Este proyecto representa la **etapa final de Transferencia** de la materia Diseño de Sistemas, consolidando un producto transaccional de alta robustez, accesibilidad inclusiva y preparación para despliegue en la nube.

---

## 📂 Índice de Documentación Técnica

Para mantener la raíz limpia y evitar la saturación del contexto del código, toda la arquitectura del sistema ha sido dividida en **capítulos técnicos modulares e independientes**. Puedes acceder a cada uno de ellos a través de los siguientes enlaces:

### 📖 [Índice Maestro de la Documentación (README)](documentacion_tecnica/README.md)

1.  **[Capítulo 1: Diseño de Base de Datos (PostgreSQL Nativo)](documentacion_tecnica/01-Database-Design.md)**  
    *Esquema DDL relacional normalizado, restricciones de exclusión GIST para colisiones y tuning de autovacuum.*
2.  **[Capítulo 2: Lógica de Negocio y Motor de Lista de Espera (LEA)](documentacion_tecnica/02-Business-Logic.md)**  
    *Algoritmo FIFO transaccional (`FOR UPDATE SKIP LOCKED`), regla de las 2 horas y lookahead de 7 días.*
3.  **[Capítulo 3: Mapeo de Infraestructura Cloud y Costos](documentacion_tecnica/03-Infrastructure.md)**  
    *Comparativa AWS vs. GCP vs. Azure y recomendación de despliegue serverless (Cloud Run + Cloud SQL).*
4.  **[Capítulo 4: Accesibilidad, Roles y Seguridad (WCAG 2.1 AA)](documentacion_tecnica/04-Security-Compliance.md)**  
    *Linear Wizard Pattern, botones de 48x48dp, Web Speech API condicional, RBAC y Habeas Data.*
5.  **[Capítulo 5: Estrategia de Aseguramiento de Calidad (QA & Testing)](documentacion_tecnica/05-Testing-QA.md)**  
    *Ecosistema de Pytest, simulación de race conditions y auditorías de accesibilidad con axe-core.*
6.  **[Capítulo 6: Gobierno de Código, Git Workflow y Operaciones](documentacion_tecnica/06-Operations.md)**  
    *Uso de GitFlow, Conventional Commits y versionamiento semántico SemVer (v1.0.0).*

---

## ✨ Características Destacadas del SGCM

*   **Integridad Atómica de Agendamiento:** Exclusión física de colisiones a nivel de motor de datos en PostgreSQL para impedir doble reservación de especialistas.
*   **Motor Inteligente de Lista de Espera (LEA):** Asignación automática de slots cancelados a pacientes en lista de espera bajo criterios FIFO y coincidencia de rangos temporales.
*   **Accesibilidad Inclusiva (Adultos Mayores):** Diseño UI/UX optimizado con botones de escala táctil expandida (48x48px), navegación paso a paso lineal y asistencia de voz interactiva opcional.
*   **Seguridad PHI & Habeas Data:** Enmascaramiento automático de información confidencial en logs y registros de auditoría transaccionales inmutables.

---

## 🛠️ Stack Tecnológico Seleccionado

*   **Presentación:** HTML5, CSS3 (Vanilla Premium), Vanilla JavaScript (SPA asíncrona).
*   **Lógica de Negocio:** Python 3.10+, Flask, SQLAlchemy (ORM).
*   **Persistencia:** PostgreSQL v15+ (Local: Docker o Postgres Service).
*   **Calidad (QA):** Pytest, Playwright, Axe-core.

---
*Desarrollado bajo los más altos estándares de ingeniería de software para el cierre del semestre.*
