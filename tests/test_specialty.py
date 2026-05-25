# ============================================================================
# ARCHIVO: tests/test_specialty.py
# PROPÓSITO: Pruebas unitarias para el modelo Specialty.
# ============================================================================

from models.specialty import Specialty


def test_specialty_validation_success():
    """
    Verifica que una especialidad con datos válidos pase la validación.
    """
    especialidad = Specialty(nombre="Cardiologia", descripcion="Especialidad del corazon")
    errores = especialidad.validar()
    assert len(errores) == 0


def test_specialty_validation_too_short():
    """
    Verifica que falle la validación si el nombre es demasiado corto.
    """
    especialidad = Specialty(nombre="Ca", descripcion="Nombre demasiado corto")
    errores = especialidad.validar()
    assert len(errores) == 1
    assert "El nombre de la especialidad debe tener al menos 3 caracteres." in errores[0]
