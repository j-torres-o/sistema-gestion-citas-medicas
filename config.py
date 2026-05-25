# ============================================================================
# ARCHIVO: config.py
# PROPÓSITO: Configuración centralizada del SGCM (Flask & PostgreSQL).
#
# Este módulo implementa el patrón "12-Factor App" para la configuración.
# Lee las credenciales y configuraciones sensibles desde variables de entorno
# o un archivo local (.env) que nunca se publica en GitHub (ver .gitignore).
# ============================================================================

import os
from dotenv import load_dotenv

# Cargar variables del archivo .env local
load_dotenv()


class Config:
    """
    Clase de configuración para la aplicación Flask y base de datos PostgreSQL.
    """

    # Flask necesita una clave secreta para firmar y validar cookies de sesión.
    SECRET_KEY = os.getenv('SECRET_KEY', 'sgcm-dev-secret-key-2026-human-senior-standard')

    # Parámetros de conexión a la base de datos PostgreSQL.
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 5432))
    DB_USER = os.getenv('DB_USER', 'postgres')
    DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres')
    DB_NAME = os.getenv('DB_NAME', 'sgcm_db')

    # Configuración de Sesiones de Flask (Seguridad)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = 1800  # 30 minutos de inactividad
