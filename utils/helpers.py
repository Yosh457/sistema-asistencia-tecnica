# utils/helpers.py
import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app
from datetime import datetime
import pytz
from flask_login import current_user
import re
from itertools import cycle

def obtener_hora_chile():
    """Retorna la fecha y hora actual en Santiago de Chile."""
    cl_tz = pytz.timezone('America/Santiago')
    return datetime.now(cl_tz)

def registrar_log(accion, detalles, usuario=None):
    """Registra un evento en la tabla 'logs' del sistema (Auditoría General)."""
    from models import db, Log  # Lazy Import

    try:
        user_id = None
        user_nombre = "Sistema/Anónimo"

        if usuario:
            user_id = usuario.id
            user_nombre = usuario.nombre_completo
        elif current_user and current_user.is_authenticated:
            user_id = current_user.id
            user_nombre = current_user.nombre_completo

        nuevo_log = Log(
            usuario_id=user_id,
            usuario_nombre=user_nombre,
            accion=accion,
            detalles=detalles,
            timestamp=obtener_hora_chile()
        )
        db.session.add(nuevo_log)
        db.session.commit()
    except Exception as e:
        print(f"Error al registrar log general: {e}")

def registrar_historial_ticket(ticket_id, accion, detalle=None):
    """
    Registra un movimiento específico en el historial del ticket.
    'detalle' debe ser un diccionario (se guardará como JSON).
    """
    from models import db, HistorialTicket  # Lazy Import

    try:
        user_id = current_user.id if current_user and current_user.is_authenticated else None
        
        nuevo_historial = HistorialTicket(
            ticket_id=ticket_id,
            usuario_id=user_id,
            accion=accion,
            detalle=detalle,
            fecha=obtener_hora_chile()
        )
        db.session.add(nuevo_historial)
        db.session.commit()
    except Exception as e:
        print(f"Error al registrar historial del ticket {ticket_id}: {e}")

def es_rut_valido(rut: str) -> bool:
    if not rut: return False
    rut = rut.replace(".", "").replace("-", "").upper().strip()
    if not re.match(r"^\d{7,8}[0-9K]$", rut): return False
    cuerpo = rut[:-1]
    dv_ingresado = rut[-1]
    try:
        revertido = map(int, reversed(cuerpo))
        factors = cycle(range(2, 8))
        s = sum(d * f for d, f in zip(revertido, factors))
        res = (-s) % 11
        dv_calculado = "K" if res == 10 else str(res)
        return dv_ingresado == dv_calculado
    except (ValueError, TypeError):
        return False
    
def safe_int(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

# ==============================================================================
# MOTOR DE ARCHIVOS ADJUNTOS
# ==============================================================================

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'docx', 'xlsx', 'xls', 'doc'}

def allowed_file(filename):
    """Verifica si la extensión del archivo está permitida."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def guardar_adjunto_seguro(file, ticket_id, fase, usuario_id):
    """
    Guarda un archivo físicamente con un nombre seguro y devuelve 
    la instancia del modelo Adjunto para insertarla en la BD.
    """
    from models import Adjunto  # Lazy Import
    
    if not file or not file.filename or not allowed_file(file.filename):
        return None
        
    filename_original = secure_filename(file.filename)
    
    # Mejora de seguridad: Prevenir error si el archivo no tiene extensión
    if '.' in filename_original:
        ext = filename_original.rsplit('.', 1)[1].lower()
    else:
        ext = 'bin'
    
    # Generamos un nombre físico único: tkt_ID_codigo.ext
    nombre_fisico = f"tkt_{ticket_id}_{uuid.uuid4().hex[:8]}.{ext}"
    
    # Aseguramos que exista la carpeta
    upload_folder = os.path.join(current_app.root_path, 'uploads', 'adjuntos')
    os.makedirs(upload_folder, exist_ok=True)
    
    file_path = os.path.join(upload_folder, nombre_fisico)
    
    try:
        file.save(file_path)
        
        nuevo_adjunto = Adjunto(
            ticket_id=ticket_id,
            usuario_id=usuario_id,
            nombre_archivo=file.filename, # Nombre original para el usuario
            ruta_archivo=nombre_fisico,   # Nombre seguro físico
            tipo_mime=file.content_type,
            fase=fase
        )
        return nuevo_adjunto
    except Exception as e:
        print(f"Error guardando archivo físico: {e}")
        return None