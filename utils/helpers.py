# utils/helpers.py

import os
import uuid
import re
from itertools import cycle
from datetime import datetime

import pytz
from werkzeug.utils import secure_filename
from flask import current_app
from flask_login import current_user


def obtener_hora_chile():
    """
    Retorna la fecha y hora actual en la zona horaria de Santiago de Chile.
    """
    cl_tz = pytz.timezone('America/Santiago')
    return datetime.now(cl_tz)


# ==============================================================================
# AUDITORÍA Y TRAZABILIDAD
# ==============================================================================

def registrar_log(accion, detalles, usuario=None):
    """
    Registra un evento en la tabla de logs del sistema.

    IMPORTANTE:
    - Esta función YA NO hace db.session.commit().
    - Solo agrega el log a la sesión activa.
    - El commit debe hacerlo la función o vista que invoca este helper.

    ¿Por qué?
    Porque así el log participa en la misma transacción del proceso principal.
    Si luego falla la operación de negocio y se hace rollback, el log también
    se revierte junto con el resto, manteniendo consistencia transaccional.
    """
    from models import db, Log  # Lazy import para evitar ciclos

    try:
        user_id = None
        user_nombre = "Sistema/Anónimo"

        # Si se recibe usuario explícito, se usa ese
        if usuario:
            user_id = usuario.id
            user_nombre = usuario.nombre_completo

        # Si no, intentamos usar current_user autenticado
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

        # Solo se agrega a sesión, SIN commit
        db.session.add(nuevo_log)

        # Devolvemos el objeto por si a futuro quieres inspeccionarlo
        return nuevo_log

    except Exception as e:
        # No levantamos excepción aquí para no romper el flujo principal
        print(f"Error al preparar log general: {e}")
        return None


def registrar_historial_ticket(ticket_id, accion, detalle=None):
    """
    Registra un movimiento en el historial de un ticket.

    IMPORTANTE:
    - Esta función YA NO hace db.session.commit().
    - Solo agrega el historial a la sesión activa.
    - El commit lo controla la operación principal que está gestionando el ticket.

    Parámetros:
    - ticket_id: ID del ticket afectado
    - accion: tipo de movimiento (CREACION, ASIGNACION, CONFIRMACION, etc.)
    - detalle: diccionario con datos adicionales, se guarda como JSON
    """
    from models import db, HistorialTicket  # Lazy import para evitar ciclos

    try:
        user_id = current_user.id if current_user and current_user.is_authenticated else None

        nuevo_historial = HistorialTicket(
            ticket_id=ticket_id,
            usuario_id=user_id,
            accion=accion,
            detalle=detalle,
            fecha=obtener_hora_chile()
        )

        # Solo se agrega a sesión, SIN commit
        db.session.add(nuevo_historial)

        return nuevo_historial

    except Exception as e:
        print(f"Error al preparar historial del ticket {ticket_id}: {e}")
        return None


# ==============================================================================
# VALIDACIONES GENERALES
# ==============================================================================

def es_rut_valido(rut: str) -> bool:
    """
    Valida formato y dígito verificador de un RUT chileno.
    """
    if not rut:
        return False

    rut = rut.replace(".", "").replace("-", "").upper().strip()

    if not re.match(r"^\d{7,8}[0-9K]$", rut):
        return False

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
    """
    Convierte un valor a entero de forma segura.
    Devuelve None si no se puede convertir.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


# ==============================================================================
# MOTOR DE ARCHIVOS ADJUNTOS
# ==============================================================================

ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'docx', 'xlsx', 'xls', 'doc'}


def allowed_file(filename):
    """
    Verifica si la extensión del archivo está permitida.
    """
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def guardar_adjunto_seguro(file, ticket_id, fase, usuario_id):
    """
    Guarda un archivo físicamente con un nombre seguro y retorna
    una instancia del modelo Adjunto lista para insertar en BD.

    Notas:
    - El nombre físico se reemplaza por uno único basado en UUID.
    - Se conserva el nombre original solo para mostrarlo al usuario.
    - Esta función NO hace db.session.add() ni commit(); eso lo hace quien la invoca.
    """
    from models import Adjunto  # Lazy import

    if not file or not file.filename or not allowed_file(file.filename):
        return None

    filename_original = secure_filename(file.filename)

    # Si el archivo no trae extensión, usamos bin como fallback defensivo
    if '.' in filename_original:
        ext = filename_original.rsplit('.', 1)[1].lower()
    else:
        ext = 'bin'

    # Nombre físico seguro y único
    nombre_fisico = f"tkt_{ticket_id}_{uuid.uuid4().hex[:8]}.{ext}"

    # Carpeta física de adjuntos
    upload_folder = os.path.join(current_app.root_path, 'uploads', 'adjuntos')
    os.makedirs(upload_folder, exist_ok=True)

    file_path = os.path.join(upload_folder, nombre_fisico)

    try:
        file.save(file_path)

        nuevo_adjunto = Adjunto(
            ticket_id=ticket_id,
            usuario_id=usuario_id,
            nombre_archivo=file.filename,   # nombre visible al usuario
            ruta_archivo=nombre_fisico,     # nombre físico interno
            tipo_mime=file.content_type,
            fase=fase
        )

        return nuevo_adjunto

    except Exception as e:
        print(f"Error guardando archivo físico: {e}")
        return None