# utils/__init__.py
from .helpers import (
    obtener_hora_chile, 
    registrar_log, 
    registrar_historial_ticket, 
    es_rut_valido, 
    safe_int,
    guardar_adjunto_seguro
)
from .email import (
    enviar_correo_reseteo, 
    enviar_credenciales_nuevo_usuario,
    enviar_aviso_nuevo_ticket,
    enviar_aviso_asignacion_ticket,
    enviar_aviso_resolucion_ticket
)
from .pdf_actas import generar_informe_tecnico_pdf
from .decorators import check_password_change, admin_required, tecnico_required, requiere_permiso_asignar