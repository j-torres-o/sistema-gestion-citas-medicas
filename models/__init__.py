# ============================================================================
# ARCHIVO: models/__init__.py
# PROPÓSITO: Inicializador del paquete de modelos clínicos.
#
# Exporta de forma unificada todas las entidades del sistema clínico
# para facilitar su importación desde rutas, workers y pruebas.
# ============================================================================

from models.entidad_base import EntidadBase
from models.specialty import Specialty
from models.doctor import Doctor
from models.patient import Patient
from models.appointment import Appointment
from models.waiting_list import WaitingList
from models.audit import AppointmentHistory

# Declaramos los exportados oficiales del paquete
__all__ = [
    'EntidadBase',
    'Specialty',
    'Doctor',
    'Patient',
    'Appointment',
    'WaitingList',
    'AppointmentHistory'
]
