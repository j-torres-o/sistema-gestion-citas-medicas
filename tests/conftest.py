# ============================================================================
# ARCHIVO: tests/conftest.py
# PROPÓSITO: Configuración global de Pytest y fixture de inicialización de BD.
# ============================================================================

import os
from urllib.parse import urlparse
import pytest
from config import Config

# Detectar y parsear DATABASE_URL de forma dinámica para configuraciones de CI (GitHub Actions)
db_url = os.getenv('DATABASE_URL')
if db_url and db_url.startswith("postgresql://"):
    parsed = urlparse(db_url)
    Config.DB_USER = parsed.username or Config.DB_USER
    Config.DB_PASSWORD = parsed.password or Config.DB_PASSWORD
    Config.DB_HOST = parsed.hostname or Config.DB_HOST
    Config.DB_PORT = parsed.port or Config.DB_PORT
    Config.DB_NAME = parsed.path.lstrip('/') or Config.DB_NAME


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """
    Fixture de sesión que inicializa las tablas del esquema físico de la base de datos
    antes del inicio de la ejecución de las pruebas unitarias e integrales en CI/Staging.
    """
    # Si la base de datos es de pruebas, procedemos a inicializar las tablas
    if Config.DB_NAME.endswith('_test') or os.getenv('FLASK_ENV') == 'testing':
        from init_db import initialize_tables
        print(f"\n[TEST CONFIG] Inicializando tablas físicas en la base de datos de pruebas: {Config.DB_NAME}")
        initialize_tables()
    yield
