# utils/email.py
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.utils import formataddr
from flask import url_for

def get_email_template(titulo, contenido):
    return f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; color: #333; max-width: 600px; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden; margin: 0 auto;">
        <div style="background-color: #275c80; padding: 20px; text-align: center;">
            <h2 style="color: white; margin: 0; font-size: 20px;">{titulo}</h2>
        </div>
        <div style="padding: 20px; background-color: #ffffff;">
            {contenido}
        </div>
        <div style="background-color: #f1f1f1; padding: 15px; text-align: center; font-size: 11px; color: #888; border-top: 1px solid #eee;">
            <p style="margin: 0;">Red de Atención Primaria de Salud Municipal - Alto Hospicio</p>
            <p style="margin: 5px 0 0;">Este es un mensaje automático del Sistema de Asistencia Técnica, por favor no responder.</p>
        </div>
    </div>
    """

def enviar_correo_generico(destinatarios, asunto, cuerpo_html, adjunto_path=None, bcc=None):
    """
    Envía un correo utilizando SMTP (Gmail) de forma segura y consistente.

    - 'destinatarios' (To): lista o string. Visible en el correo.
    - 'bcc' (BCC): lista o string. NO visible en el correo (privacidad).
    - Importante: usamos server.send_message(..., to_addrs=...) para controlar
      el "envelope" SMTP y NO depender de headers Bcc.

    Esto evita:
    - exponer correos en envíos masivos
    - depender de que 'send_message' elimine headers Bcc
    """
    remitente = os.getenv("EMAIL_USUARIO")
    contrasena = os.getenv("EMAIL_CONTRASENA")

    # Validación mínima de credenciales
    if not remitente or not contrasena:
        print("ERROR: Faltan credenciales EMAIL_USUARIO / EMAIL_CONTRASENA en .env")
        return False

    # -----------------------------
    # 1) Normalizar inputs a listas
    # -----------------------------
    if destinatarios is None:
        destinatarios = []
    if isinstance(destinatarios, str):
        destinatarios = [destinatarios]

    if bcc is None:
        bcc = []
    if isinstance(bcc, str):
        bcc = [bcc]

    # -------------------------------------------------
    # 2) Limpiar vacíos/None y quitar duplicados (orden)
    # -------------------------------------------------
    destinatarios = [d.strip() for d in destinatarios if d and str(d).strip()]
    bcc = [d.strip() for d in bcc if d and str(d).strip()]

    # Deduplicar manteniendo el orden
    destinatarios = list(dict.fromkeys(destinatarios))
    bcc = list(dict.fromkeys(bcc))

    # Si no hay nadie en To ni Bcc, no tiene sentido enviar
    if not destinatarios and not bcc:
        print("ERROR: Faltan destinatarios (To/Bcc).")
        return False

    # -------------------------------------------------------------
    # 3) Construir el mensaje (headers visibles)
    # -------------------------------------------------------------
    msg = MIMEMultipart()
    msg["Subject"] = asunto
    msg["From"] = formataddr(("Asistencia Técnica Notificaciones", remitente))

    # "To" visible: si no hay destinatarios, ponemos el remitente
    # (así el correo no queda con To vacío)
    msg["To"] = ", ".join(destinatarios) if destinatarios else remitente

    # OJO: NO seteamos msg["Bcc"] a propósito.
    # La privacidad la manejamos con "to_addrs" en send_message.

    # Cuerpo HTML
    msg.attach(MIMEText(cuerpo_html, "html"))

    # Adjuntar archivo si corresponde
    if adjunto_path and os.path.exists(adjunto_path):
        try:
            with open(adjunto_path, "rb") as f:
                part = MIMEApplication(f.read(), Name=os.path.basename(adjunto_path))
                part["Content-Disposition"] = f'attachment; filename="{os.path.basename(adjunto_path)}"'
                msg.attach(part)
        except Exception as e:
            print(f"Error adjuntando archivo: {e}")

    # -------------------------------------------------------------
    # 4) Enviar: definimos explícitamente el "sobre" (envelope SMTP)
    # -------------------------------------------------------------
    # Los receptores reales son: To visibles + BCC ocultos
    # Si To estaba vacío, el header To quedó como remitente, pero igual
    # garantizamos que el remitente esté en recipients para que el envío tenga
    # un destinatario visible coherente.
    recipients = []
    if destinatarios:
        recipients.extend(destinatarios)
    else:
        recipients.append(remitente)

    if bcc:
        recipients.extend(bcc)

    # Deduplicar recipients por si se repiten
    recipients = list(dict.fromkeys([r for r in recipients if r]))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(remitente, contrasena)

            # MODERNO + CONTROL:
            # - send_message es moderno
            # - to_addrs controla a quién se envía realmente (incluye BCC)
            # - No dependemos del header Bcc (ni lo exponemos)
            server.send_message(
                msg,
                from_addr=remitente,
                to_addrs=recipients
            )

        return True

    except Exception as e:
        print(f"Error enviando correo '{asunto}': {e}")
        return False

# --- FUNCIONES DE AUTENTICACIÓN ---
def enviar_correo_reseteo(usuario, token):
    url = url_for('auth.resetear_clave', token=token, _external=True)
    contenido = f"""
        <p>Hola <strong>{usuario.nombre_completo}</strong>,</p>
        <p>Hemos recibido una solicitud para restablecer tu contraseña.</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{url}" style="background-color: #275c80; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                Restablecer Contraseña
            </a>
        </div>
        <p style="font-size: 13px; color: #666;">El enlace expirará en 1 hora.</p>
    """
    html = get_email_template("Recuperación de Contraseña", contenido)
    enviar_correo_generico(usuario.email, 'Restablecimiento de Contraseña - Asistencia Técnica', html)

def enviar_credenciales_nuevo_usuario(usuario, password_texto_plano):
    """
    Envía correo de bienvenida con credenciales al nuevo usuario.
    """
    url_login = url_for('auth.login', _external=True)
    
    contenido = f"""
        <p>Hola <strong>{usuario.nombre_completo}</strong>,</p>
        <p>Bienvenido al <strong>Sistema de Asistencia Técnica</strong>. Se ha creado tu cuenta de acceso.</p>
        
        <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #275c80; margin: 20px 0; border-radius: 4px;">
            <p style="margin: 5px 0;"><strong>Usuario (Email):</strong> {usuario.email}</p>
            <p style="margin: 5px 0;"><strong>Contraseña Temporal:</strong> {password_texto_plano}</p>
        </div>

        <div style="text-align: center; margin: 30px 0;">
            <a href="{url_login}" style="background-color: #275c80; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                Ingresar al Sistema
            </a>
        </div>
        
        <p style="color: #d9534f; font-size: 13px;"><strong>Importante:</strong> Por seguridad, el sistema te solicitará cambiar esta contraseña al iniciar sesión por primera vez.</p>
    """
    html = get_email_template("Bienvenido al Sistema", contenido)
    return enviar_correo_generico(usuario.email, "Bienvenido - Credenciales de Acceso", html)

# --- FUNCIONES DE TICKETS ---

def enviar_aviso_nuevo_ticket(ticket, destinatarios_tics):
    """Avisa a la unidad TICs que hay un nuevo ticket."""
    url = url_for('tickets.ver_ticket', id=ticket.id, _external=True)
    contenido = f"""
        <p>Se ha ingresado una nueva solicitud de asistencia técnica.</p>
        <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #d9534f; margin: 20px 0;">
            <p><strong>Ticket ID:</strong> TKT-{ticket.id}</p>
            <p><strong>Solicitante:</strong> {ticket.solicitante.nombre_completo}</p>
            <p><strong>Asunto:</strong> {ticket.asunto}</p>
        </div>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{url}" style="background-color: #275c80; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px;">Ver Ticket</a>
        </div>
    """
    html = get_email_template(f"Nueva Solicitud: TKT-{ticket.id}", contenido)
    enviar_correo_generico(destinatarios_tics, f"Nueva Solicitud de Asistencia - TKT-{ticket.id}", html)

def enviar_aviso_asignacion_ticket(ticket):
    """Avisa al técnico que se le asignó un ticket."""
    if not ticket.tecnico: return False
    url = url_for('tickets.ver_ticket', id=ticket.id, _external=True)
    contenido = f"""
        <p>Hola <strong>{ticket.tecnico.nombre_completo}</strong>,</p>
        <p>Se te ha asignado un nuevo ticket de asistencia técnica.</p>
        <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #f0ad4e; margin: 20px 0;">
            <p><strong>Ticket ID:</strong> TKT-{ticket.id}</p>
            <p><strong>Asunto:</strong> {ticket.asunto}</p>
            <p><strong>Solicitante:</strong> {ticket.solicitante.nombre_completo}</p>
        </div>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{url}" style="background-color: #275c80; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px;">Confirmar Recepción</a>
        </div>
    """
    html = get_email_template(f"Ticket Asignado: TKT-{ticket.id}", contenido)
    return enviar_correo_generico(ticket.tecnico.email, f"Ticket Asignado - TKT-{ticket.id}", html)

def enviar_aviso_resolucion_ticket(ticket, correo_tics, pdf_path=None):
    """Avisa al solicitante y a TICs que el ticket finalizó."""
    destinatarios = [ticket.solicitante.email, correo_tics]
    url = url_for('tickets.ver_ticket', id=ticket.id, _external=True)
    contenido = f"""
        <p>El ticket de asistencia técnica ha sido resuelto y cerrado.</p>
        <div style="background-color: #f8f9fa; padding: 15px; border-left: 4px solid #5cb85c; margin: 20px 0;">
            <p><strong>Ticket ID:</strong> TKT-{ticket.id}</p>
            <p><strong>Asunto:</strong> {ticket.asunto}</p>
            <p><strong>Atendido por:</strong> {ticket.tecnico.nombre_completo if ticket.tecnico else 'N/A'}</p>
        </div>
        <p>El Informe Técnico está adjunto a este correo y disponible en el sistema.</p>
        <div style="text-align: center; margin: 30px 0;">
            <a href="{url}" style="background-color: #275c80; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px;">Ver Detalle en Sistema</a>
        </div>
    """
    html = get_email_template(f"Ticket Finalizado: TKT-{ticket.id}", contenido)
    return enviar_correo_generico(destinatarios, f"Ticket Finalizado - TKT-{ticket.id}", html, adjunto_path=pdf_path)