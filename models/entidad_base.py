# ============================================================================
# ARCHIVO: models/entidad_base.py
# PROPÓSITO: Clase base abstracta para todas las entidades del SGCM (PostgreSQL).
#
# Provee la herencia de persistencia para operaciones CRUD dinámicas,
# adaptadas para llaves primarias UUID y dialecto de PostgreSQL.
# ============================================================================

from database import Database


class EntidadBase:
    """
    Clase base abstracta que define la interfaz CRUD común para todas las
    entidades en PostgreSQL utilizando placeholders de psycopg2 (%s).
    """

    TABLA = None
    PK_COLUMNA = 'id'  # Nombre de la columna PK (específico por tabla, ej: 'id_paciente')

    def __init__(self, id=None, created_at=None, updated_at=None):
        self.id = id
        self.created_at = created_at
        self.updated_at = updated_at

    def validar(self):
        """
        Método plantilla para validaciones en clases hijas.
        Retorna lista de errores (vacía = válido).
        """
        raise NotImplementedError("La clase debe implementar el método validar().")

    def _get_campos_valores(self):
        """
        Retorna (lista_campos, lista_valores) para INSERT / UPDATE.
        """
        raise NotImplementedError("La clase debe implementar _get_campos_valores().")

    def guardar(self):
        """
        Inserta un nuevo registro en PostgreSQL (CREATE) y captura el UUID autogenerado.
        """
        errores = self.validar()
        if errores:
            raise ValueError(f"Errores de validación: {'; '.join(errores)}")

        campos, valores = self._get_campos_valores()
        placeholders = ', '.join(['%s'] * len(campos))
        nombres_campos = ', '.join(campos)

        # Usamos RETURNING en PostgreSQL para capturar el UUID generado automáticamente
        query = f"INSERT INTO {self.TABLA} ({nombres_campos}) VALUES ({placeholders}) RETURNING {self.PK_COLUMNA}"

        res = Database.execute_query(query, tuple(valores), fetch_one=True)
        if res and self.PK_COLUMNA in res:
            self.id = res[self.PK_COLUMNA]
        return self.id

    def actualizar(self):
        """
        Actualiza un registro existente en PostgreSQL (UPDATE).
        """
        if not self.id:
            raise ValueError("No se puede actualizar un registro sin ID.")

        errores = self.validar()
        if errores:
            raise ValueError(f"Errores de validación: {'; '.join(errores)}")

        campos, valores = self._get_campos_valores()
        set_clause = ', '.join([f"{campo} = %s" for campo in campos])
        query = f"UPDATE {self.TABLA} SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE {self.PK_COLUMNA} = %s"

        valores.append(self.id)
        return Database.execute_query(query, tuple(valores))

    @classmethod
    def eliminar(cls, id):
        """
        Elimina un registro por su ID (DELETE).
        """
        query = f"DELETE FROM {cls.TABLA} WHERE {cls.PK_COLUMNA} = %s"
        return Database.execute_query(query, (id,))

    @classmethod
    def obtener_todos(cls):
        """
        Obtiene todos los registros (SELECT *).
        """
        query = f"SELECT * FROM {cls.TABLA} ORDER BY created_at DESC"
        return Database.execute_query(query, fetch_all=True)

    @classmethod
    def obtener_por_id(cls, id):
        """
        Obtiene un registro por su ID (SELECT WHERE).
        """
        query = f"SELECT * FROM {cls.TABLA} WHERE {cls.PK_COLUMNA} = %s"
        return Database.execute_query(query, (id,), fetch_one=True)

    @classmethod
    def obtener_paginados(cls, page=1, limit=10):
        """
        Paginación optimizada para PostgreSQL.
        """
        offset = (page - 1) * limit
        count_query = f"SELECT COUNT(*) as total FROM {cls.TABLA}"
        total_res = Database.execute_query(count_query, fetch_one=True)
        total = total_res['total'] if total_res else 0

        query = f"SELECT * FROM {cls.TABLA} ORDER BY created_at DESC LIMIT %s OFFSET %s"
        resultado = Database.execute_query(query, (limit, offset), fetch_all=True)
        return resultado, total
