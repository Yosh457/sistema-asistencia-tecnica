# blueprints/tickets.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user

from models import db, Ticket, EstadoTicket, Usuario, Rol
from utils import (
    registrar_log,
    registrar_historial_ticket,
    enviar_aviso_nuevo_ticket,
    enviar_aviso_asignacion_ticket,
    tecnico_required,
    requiere_permiso_asignar
)

# ==========================================================
# CONFIGURACIÓN DEL BLUEPRINT
# ==========================================================

tickets_bp = Blueprint(
    'tickets',
    __name__,
    template_folder='../templates',
    url_prefix='/tickets'
)

@tickets_bp.before_request
@login_required
def before_request():
    """Garantiza que todo acceso al módulo requiere autenticación."""
    pass


# ==========================================================
# CONSTANTES DE ESTADO (Evita strings mágicos)
# ==========================================================

ESTADO_CREADO = "CREADO"
ESTADO_ASIGNADO = "ASIGNADO"
ESTADO_EN_PROCESO = "EN_PROCESO"


# ==========================================================
# HELPERS INTERNOS
# ==========================================================

def obtener_estado(nombre_estado):
    """
    Obtiene un estado por nombre con validación defensiva.
    Si no existe, registra error y devuelve None.
    """
    estado = EstadoTicket.query.filter_by(nombre=nombre_estado).first()
    if not estado:
        registrar_log("Error Estado", f"Estado '{nombre_estado}' no encontrado en BD.")
    return estado


def puede_ver_ticket(usuario, ticket):
    """
    Lógica centralizada de autorización para visualizar tickets.
    """
    # Admin ve todo
    if usuario.rol.nombre == 'ADMIN':
        return True

    # Técnico que puede asignar
    if usuario.rol.nombre == 'TECNICO' and usuario.puede_asignar:
        return True

    # Técnico normal
    if usuario.rol.nombre == 'TECNICO' and not usuario.puede_asignar:
        return (
            ticket.usuario_id == usuario.id or
            ticket.tecnico_id == usuario.id
        )

    # Funcionario
    if usuario.rol.nombre == 'FUNCIONARIO':
        return ticket.usuario_id == usuario.id

    return False


# ==========================================================
# 1. FUNCIONARIO (SOLICITANTE)
# ==========================================================

@tickets_bp.route('/')
def mis_tickets():
    """Bandeja del funcionario: muestra sus tickets creados."""
    page = request.args.get('page', 1, type=int)

    query = Ticket.query.filter_by(
        usuario_id=current_user.id
    ).order_by(Ticket.fecha_creacion.desc())

    pagination = query.paginate(page=page, per_page=10, error_out=False)

    return render_template('tickets/mis_tickets.html', pagination=pagination)


@tickets_bp.route('/nuevo', methods=['GET', 'POST'])
def crear_ticket():
    """Formulario para crear una nueva solicitud."""
    if request.method == 'POST':
        asunto = request.form.get('asunto')
        descripcion = request.form.get('descripcion')

        if not asunto or not descripcion:
            flash('Por favor, completa todos los campos obligatorios.', 'warning')
            return redirect(url_for('tickets.crear_ticket'))

        estado_creado = obtener_estado(ESTADO_CREADO)
        if not estado_creado:
            flash('Error crítico: Estado inicial no configurado.', 'danger')
            return redirect(url_for('tickets.mis_tickets'))

        nuevo_ticket = Ticket(
            usuario_id=current_user.id,
            estado_id=estado_creado.id,
            asunto=asunto,
            descripcion=descripcion
        )

        try:
            db.session.add(nuevo_ticket)
            db.session.flush()

            registrar_historial_ticket(
                ticket_id=nuevo_ticket.id,
                accion='CREACION',
                detalle={
                    'asunto': asunto,
                    'estado_inicial': ESTADO_CREADO
                }
            )

            registrar_log(
                "Ingreso Ticket",
                f"Ticket TKT-{nuevo_ticket.id} creado por {current_user.nombre_completo}"
            )

            db.session.commit()

            # Notificación a TICs
            tics = Usuario.query.join(Rol).filter(
                Usuario.activo == True,
                (Usuario.puede_asignar == True) | (Rol.nombre == 'ADMIN')
            ).all()

            correos_tics = [u.email for u in tics if u.email]

            if correos_tics:
                enviar_aviso_nuevo_ticket(nuevo_ticket, correos_tics)

            flash(
                f'Solicitud ingresada con éxito. Tu número de ticket es TKT-{nuevo_ticket.id}.',
                'success'
            )

            return redirect(url_for('tickets.ver_ticket', id=nuevo_ticket.id))

        except Exception as e:
            db.session.rollback()
            registrar_log("Error Creación Ticket", str(e))
            flash('Ocurrió un error al guardar la solicitud.', 'danger')

    return render_template('tickets/crear.html')


# ==========================================================
# 2. VISTA UNIVERSAL CON CONTROL DE ACCESO
# ==========================================================

@tickets_bp.route('/ver/<int:id>')
def ver_ticket(id):
    """Vista detallada del ticket con control centralizado de permisos."""
    ticket = Ticket.query.get_or_404(id)

    if not puede_ver_ticket(current_user, ticket):
        abort(403)

    return render_template('tickets/ver.html', ticket=ticket)


# ==========================================================
# 3. BANDEJA GLOBAL (TECNICO QUE ASIGNA TICKETS)
# ==========================================================

@tickets_bp.route('/bandeja-global')
@requiere_permiso_asignar
def bandeja_global():
    """Vista para gestión y asignación de tickets."""
    page = request.args.get('page', 1, type=int)
    estado_filtro = request.args.get('estado', '')

    query = Ticket.query.order_by(Ticket.fecha_creacion.desc())

    if estado_filtro:
        query = query.join(EstadoTicket).filter(
            EstadoTicket.nombre == estado_filtro
        )

    pagination = query.paginate(page=page, per_page=15, error_out=False)

    tecnicos = Usuario.query.join(Rol).filter(
        Rol.nombre == 'TECNICO',
        Usuario.activo == True
    ).order_by(Usuario.nombre_completo).all()

    estados = EstadoTicket.query.all()

    return render_template(
        'tickets/bandeja_global.html',
        pagination=pagination,
        tecnicos=tecnicos,
        estados=estados,
        estado_filtro=estado_filtro
    )


@tickets_bp.route('/asignar/<int:id>', methods=['POST'])
@requiere_permiso_asignar
def asignar_ticket(id):
    """Permite asignar un ticket a un técnico."""
    ticket = Ticket.query.get_or_404(id)

    tecnico_id = request.form.get('tecnico_id')
    tecnico = Usuario.query.get(tecnico_id)

    if not tecnico:
        flash('Técnico no válido.', 'danger')
        return redirect(url_for('tickets.bandeja_global'))

    estado_asignado = obtener_estado(ESTADO_ASIGNADO)
    if not estado_asignado:
        flash('Estado ASIGNADO no configurado.', 'danger')
        return redirect(url_for('tickets.bandeja_global'))

    ticket.tecnico_id = tecnico.id
    ticket.estado_id = estado_asignado.id

    try:
        registrar_historial_ticket(
            ticket_id=ticket.id,
            accion='ASIGNACION',
            detalle={
                'tecnico_asignado': tecnico.nombre_completo,
                'asignado_por': current_user.nombre_completo
            }
        )

        registrar_log(
            "Asignación Ticket",
            f"TKT-{ticket.id} asignado a {tecnico.nombre_completo}"
        )

        db.session.commit()

        enviar_aviso_asignacion_ticket(ticket)

        flash(
            f'Ticket TKT-{ticket.id} asignado a {tecnico.nombre_completo}.',
            'success'
        )

    except Exception as e:
        db.session.rollback()
        registrar_log("Error Asignación Ticket", str(e))
        flash('Error al asignar el ticket.', 'danger')

    return redirect(url_for('tickets.bandeja_global'))


# ==========================================================
# 4. BANDEJA DEL TÉCNICO
# ==========================================================

@tickets_bp.route('/bandeja-tecnico')
@tecnico_required
def bandeja_tecnico():
    """Muestra los tickets asignados al técnico actual."""
    page = request.args.get('page', 1, type=int)

    query = Ticket.query.filter_by(
        tecnico_id=current_user.id
    ).order_by(Ticket.fecha_creacion.desc())

    pagination = query.paginate(page=page, per_page=10, error_out=False)

    return render_template(
        'tickets/bandeja_tecnico.html',
        pagination=pagination
    )


@tickets_bp.route('/confirmar/<int:id>', methods=['POST'])
@tecnico_required
def confirmar_recepcion(id):
    """El técnico confirma recepción y pasa el ticket a EN_PROCESO."""
    ticket = Ticket.query.get_or_404(id)

    if ticket.tecnico_id != current_user.id:
        abort(403)

    if ticket.estado.nombre != ESTADO_ASIGNADO:
        flash('El ticket no está en estado ASIGNADO.', 'warning')
        return redirect(url_for('tickets.ver_ticket', id=ticket.id))

    estado_proceso = obtener_estado(ESTADO_EN_PROCESO)
    if not estado_proceso:
        flash('Estado EN_PROCESO no configurado.', 'danger')
        return redirect(url_for('tickets.ver_ticket', id=ticket.id))

    ticket.estado_id = estado_proceso.id

    try:
        registrar_historial_ticket(
            ticket_id=ticket.id,
            accion='CONFIRMACION',
            detalle={
                'mensaje': 'El técnico confirmó la recepción y está trabajando en el caso.'
            }
        )

        db.session.commit()

        flash(
            'Has confirmado la recepción del ticket. Ahora está En Proceso.',
            'success'
        )

    except Exception as e:
        db.session.rollback()
        registrar_log("Error Confirmación Ticket", str(e))
        flash('Error al confirmar el ticket.', 'danger')

    return redirect(url_for('tickets.ver_ticket', id=ticket.id))