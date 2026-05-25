# ============================================================================
# ARCHIVO: models/massive_cancellation.py
# PROPÓSITO: Modelo de Historial y Reporte de Cancelaciones Masivas.
# ============================================================================

from models.entidad_base import EntidadBase


class MassiveCancellation(EntidadBase):
    """
    Modelo de Auditoría de Cancelaciones Masivas y Generación de Reportes del SGCM.
    """

    TABLA = 'massive_cancellations'
    PK_COLUMNA = 'id_cancelacion'

    def __init__(self, id_cancelacion=None, id_sede=None, id_medico=None,
                 fecha_ejecucion=None, cantidad_canceladas=0, auto_reschedule=True,
                 reporte_path=None, ejecutado_por=None):
        # Mapea fecha_ejecucion a created_at internamente para mantener compatibilidad
        super().__init__(id=id_cancelacion, created_at=fecha_ejecucion)
        self.id_sede = id_sede
        self.id_medico = id_medico
        self.cantidad_canceladas = cantidad_canceladas
        self.auto_reschedule = auto_reschedule
        self.reporte_path = reporte_path
        self.ejecutado_por = ejecutado_por

    def validar(self):
        errores = []
        if not self.id_sede and not self.id_medico:
            errores.append("Debe especificar al menos un alcance para la cancelación masiva (sede o médico).")
        if self.cantidad_canceladas < 0:
            errores.append("La cantidad de citas canceladas no puede ser negativa.")
        if not self.reporte_path:
            errores.append("La ruta de almacenamiento local de la evidencia CSV es obligatoria.")
        if not self.ejecutado_por:
            errores.append("El usuario ejecutor de la cancelación masiva es obligatorio.")
        return errores

    def _get_campos_valores(self):
        campos = ['id_sede', 'id_medico', 'cantidad_canceladas', 'auto_reschedule', 'reporte_path', 'ejecutado_por']
        valores = [self.id_sede, self.id_medico, self.cantidad_canceladas, self.auto_reschedule, self.reporte_path, self.ejecutado_por]
        return campos, valores
