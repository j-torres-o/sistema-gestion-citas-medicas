# ============================================================================
# ARCHIVO: database.py
# PROPÓSITO: Gestión de la conexión a la base de datos PostgreSQL.
#
# Este módulo implementa el patrón "Singleton" para PostgreSQL mediante
# un SimpleConnectionPool de psycopg2, optimizando las consultas.
# Retorna registros en formato de diccionario (RealDictCursor) para mantener
# la consistencia en el backend.
# ============================================================================

import psycopg2
from psycopg2 import pool, Error as PGError
from psycopg2.extras import RealDictCursor
from config import Config


class Database:
    """
    Gestor Singleton de conexión a la base de datos PostgreSQL.

    Utiliza SimpleConnectionPool y Context Managers para la liberación de recursos.
    """

    _pool = None

    @classmethod
    def _init_pool(cls):
        """
        Inicializa el pool de conexiones a PostgreSQL si no existe.
        """
        if cls._pool is None:
            try:
                cls._pool = pool.SimpleConnectionPool(
                    minconn=1,
                    maxconn=10,  # Pool de hasta 10 conexiones simultáneas
                    host=Config.DB_HOST,
                    port=Config.DB_PORT,
                    user=Config.DB_USER,
                    password=Config.DB_PASSWORD,
                    database=Config.DB_NAME
                )
                print(f"Pool de conexiones PostgreSQL creado: {Config.DB_HOST}:{Config.DB_PORT}/{Config.DB_NAME}")
            except PGError as e:
                print(f"Error al inicializar pool PostgreSQL: {e}")
                raise

    @classmethod
    def get_connection(cls):
        """
        Obtiene una conexión activa del pool.
        """
        cls._init_pool()
        return cls._pool.get_conn()

    @classmethod
    def release_connection(cls, connection):
        """
        Devuelve una conexión al pool.
        """
        if cls._pool and connection:
            cls._pool.putconn(connection)

    @classmethod
    def execute_query(cls, query, params=None, fetch_one=False, fetch_all=False):
        """
        Ejecuta consultas de forma segura para evitar inyecciones SQL.
        Retorna registros en formato diccionario (RealDictCursor).
        """
        connection = None
        cursor = None
        try:
            connection = cls.get_connection()
            # RealDictCursor retorna filas como diccionarios {'columna': valor}
            cursor = connection.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params or ())

            if fetch_one:
                resultado = cursor.fetchone()
                return dict(resultado) if resultado else None
            elif fetch_all:
                resultado = cursor.fetchall()
                return [dict(row) for row in resultado] if resultado else []
            else:
                connection.commit()
                # Retorna el ID de la fila afectada en caso de INSERT con RETURNING
                try:
                    returning_val = cursor.fetchone()
                    return dict(returning_val) if returning_val else cursor.rowcount
                except psycopg2.ProgrammingError:
                    # No hay filas que retornar (UPDATE, DELETE estándar)
                    return cursor.rowcount

        except PGError as e:
            if connection:
                connection.rollback()
            print(f"Error en consulta SQL (PostgreSQL): {e}")
            print(f"   Query: {query}")
            print(f"   Params: {params}")
            raise

        finally:
            if cursor:
                cursor.close()
            if connection:
                cls.release_connection(connection)
