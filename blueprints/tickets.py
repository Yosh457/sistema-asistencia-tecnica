# ==========================================================
# BLUEPRINT: TICKETS
# Sistema de Asistencia Técnica
# Versión robusta con resolución y reporte técnico
# ==========================================================

import os

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, abort, jsonify, current_app, send_from_directory
)
from flask_login import login_required, current_user
from sqlalchemy import or_

from models import (
    db, Ticket, EstadoTicket, Usuario, Rol,
    ReporteTecnico, TipoMantencion, Categoria,
    TipoActividad, Actividad, Accion
)

from utils import (
    registrar_log,
    registrar_historial_ticket,
    enviar_aviso_nuevo_ticket,
    enviar_aviso_asignacion_ticket,
    enviar_aviso_resolucion_ticket,
    generar_informe_tecnico_pdf,
    tecnico_required,
    requiere_permiso_asignar,
    obtener_hora_chile
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
    """Todo el módulo requiere autenticación."""
    pass


# ==========================================================
# CONSTANTES DE ESTADO
# ==========================================================

ESTADO_CREADO = "CREADO"
ESTADO_ASIGNADO = "ASIGNADO"
ESTADO_EN_PROCESO = "EN_PROCESO"
ESTADO_FINALIZADO = "FINALIZADO"


# ==========================================================
# HELPERS INTERNOS
# ==========================================================

def obtener_estado(nombre_estado):
    """Obtiene un estado por nombre con validación defensiva."""
    estado = EstadoTicket.query.filter_by(nombre=nombre_estado).first()
    if not estado:
        registrar_log("Error Estado", f"Estado '{nombre_estado}' no encontrado.")
    return estado


def validar_estado(ticket, nombre_estado):
    """Valida estado comparando por ID (más robusto que string directo)."""
    estado = obtener_estado(nombre_estado)
    if not estado:
        return False
    return ticket.estado_id == estado.id


def puede_ver_ticket(usuario, ticket):
    """Control centralizado de autorización."""
    if usuario.rol.nombre == 'ADMIN':
        return True

    if usuario.rol.nombre == 'TECNICO' and usuario.puede_asignar:
        return True

    if usuario.rol.nombre == 'TECNICO':
        return ticket.usuario_id == usuario.id or ticket.tecnico_id == usuario.id

    if usuario.rol.nombre == 'FUNCIONARIO':
        return ticket.usuario_id == usuario.id

    return False


# ==========================================================
# 1. FUNCIONARIO
# ==========================================================

@tickets_bp.route('/')
def mis_tickets():
    page = request.args.get('page', 1, type=int)

    query = Ticket.query.filter_by(
        usuario_id=current_user.id
    ).order_by(Ticket.fecha_creacion.desc())

    pagination = query.paginate(page=page, per_page=10, error_out=False)

    return render_template('tickets/mis_tickets.html', pagination=pagination)


@tickets_bp.route('/nuevo', methods=['GET', 'POST'])
def crear_ticket():
    if request.method == 'POST':
        asunto = request.form.get('asunto')
        descripcion = request.form.get('descripcion')

        if not asunto or not descripcion:
            flash('Completa todos los campos obligatorios.', 'warning')
            return redirect(url_for('tickets.crear_ticket'))

        estado_creado = obtener_estado(ESTADO_CREADO)
        if not estado_creado:
            flash('Estado inicial no configurado.', 'danger')
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
                detalle={'asunto': asunto}
            )

            registrar_log(
                "Ingreso Ticket",
                f"TKT-{nuevo_ticket.id} creado por {current_user.nombre_completo}"
            )

            db.session.commit()

            # Aviso a TICs
            tics = Usuario.query.join(Rol).filter(
                Usuario.activo == True,
                (Usuario.puede_asignar == True) | (Rol.nombre == 'ADMIN')
            ).all()

            correos = [u.email for u in tics if u.email]
            if correos:
                enviar_aviso_nuevo_ticket(nuevo_ticket, correos)

            flash(f'Ticket TKT-{nuevo_ticket.id} creado exitosamente.', 'success')
            return redirect(url_for('tickets.ver_ticket', id=nuevo_ticket.id))

        except Exception as e:
            db.session.rollback()
            registrar_log("Error Creación Ticket", str(e))
            flash('Error al guardar el ticket.', 'danger')

    return render_template('tickets/crear.html')


# ==========================================================
# 2. VISTA DETALLE
# ==========================================================

@tickets_bp.route('/ver/<int:id>')
def ver_ticket(id):
    ticket = Ticket.query.get_or_404(id)

    if not puede_ver_ticket(current_user, ticket):
        abort(403)

    return render_template('tickets/ver.html', ticket=ticket)


# ==========================================================
# 3. ASIGNACIÓN
# ==========================================================

@tickets_bp.route('/bandeja-global')
@requiere_permiso_asignar
def bandeja_global():
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
    ticket = Ticket.query.get_or_404(id)

    tecnico_id = request.form.get('tecnico_id')
    tecnico = Usuario.query.get(tecnico_id)

    if not tecnico or tecnico.rol.nombre != 'TECNICO':
        flash('Técnico inválido.', 'danger')
        return redirect(url_for('tickets.bandeja_global'))

    estado_asignado = obtener_estado(ESTADO_ASIGNADO)

    ticket.tecnico_id = tecnico.id
    ticket.estado_id = estado_asignado.id

    try:
        registrar_historial_ticket(
            ticket_id=ticket.id,
            accion='ASIGNACION',
            detalle={'tecnico': tecnico.nombre_completo}
        )

        db.session.commit()
        enviar_aviso_asignacion_ticket(ticket)

        flash('Ticket asignado correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log("Error Asignación Ticket", str(e))
        flash('Error al asignar.', 'danger')

    return redirect(url_for('tickets.bandeja_global'))


# ==========================================================
# 4. CONFIRMACIÓN
# ==========================================================

@tickets_bp.route('/confirmar/<int:id>', methods=['POST'])
@tecnico_required
def confirmar_recepcion(id):
    ticket = Ticket.query.get_or_404(id)

    if ticket.tecnico_id != current_user.id:
        abort(403)

    if not validar_estado(ticket, ESTADO_ASIGNADO):
        flash('El ticket no está en estado ASIGNADO.', 'warning')
        return redirect(url_for('tickets.ver_ticket', id=id))

    estado_proceso = obtener_estado(ESTADO_EN_PROCESO)
    ticket.estado_id = estado_proceso.id

    try:
        registrar_historial_ticket(ticket.id, 'CONFIRMACION', {})
        db.session.commit()
        flash('Ticket en proceso.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log("Error Confirmación", str(e))
        flash('Error al confirmar.', 'danger')

    return redirect(url_for('tickets.ver_ticket', id=id))

# ==========================================================
# BANDEJA DEL TÉCNICO (Faltaba en el refactor)
# ==========================================================

@tickets_bp.route('/bandeja-tecnico')
@tecnico_required
def bandeja_tecnico():
    """Bandeja exclusiva para el técnico. Ve solo sus tickets asignados."""
    page = request.args.get('page', 1, type=int)
    
    query = Ticket.query.filter_by(
        tecnico_id=current_user.id
    ).order_by(Ticket.fecha_creacion.desc())
    
    pagination = query.paginate(page=page, per_page=10, error_out=False)
    
    return render_template('tickets/bandeja_tecnico.html', pagination=pagination)


# ==========================================================
# 5. API AJAX - ÁRBOL TÉCNICO
# ==========================================================

@tickets_bp.route('/api/actividades/<int:tipo_id>')
@tecnico_required
def get_actividades(tipo_id):
    actividades = Actividad.query.filter_by(
        tipo_actividad_id=tipo_id,
        activo=True
    ).all()

    return jsonify({
        'actividades': [{'id': a.id, 'nombre': a.nombre} for a in actividades]
    })


@tickets_bp.route('/api/acciones/<int:actividad_id>')
@tecnico_required
def get_acciones(actividad_id):
    acciones = Accion.query.filter_by(
        actividad_id=actividad_id,
        activo=True
    ).all()

    return jsonify({
        'acciones': [{'id': a.id, 'nombre': a.nombre} for a in acciones]
    })


# ==========================================================
# 6. RESOLUCIÓN DE TICKET (CON MODO BORRADOR / BITÁCORA)
# ==========================================================

@tickets_bp.route('/resolver/<int:id>', methods=['GET', 'POST'])
@tecnico_required
def resolver_ticket(id):

    ticket = Ticket.query.get_or_404(id)

    # 1. Validación de seguridad defensiva
    if ticket.tecnico_id != current_user.id:
        abort(403)

    if not validar_estado(ticket, ESTADO_EN_PROCESO):
        flash('Solo puedes gestionar tickets que estén en proceso.', 'warning')
        return redirect(url_for('tickets.ver_ticket', id=id))

    if request.method == 'POST':
        accion_submit = request.form.get('accion_submit')

        # Captura de datos del formulario
        tipo_mantencion_id = request.form.get('tipo_mantencion_id')
        categoria_id = request.form.get('categoria_id')
        categoria_otro = request.form.get('categoria_otro')
        tipo_actividad_id = request.form.get('tipo_actividad_id')
        actividad_id = request.form.get('actividad_id')
        accion_id = request.form.get('accion_id')
        observaciones = request.form.get('observaciones_generales')

        ahora = obtener_hora_chile()

        # ======================================================
        # RAMA A: GUARDAR AVANCE (BITÁCORA)
        # ======================================================
        if accion_submit == 'guardar':
            if not observaciones:
                flash('Para guardar un avance, debes escribir algo en las Observaciones.', 'warning')
                return redirect(url_for('tickets.resolver_ticket', id=id))

            try:
                # 1. Registramos en la línea de tiempo
                registrar_historial_ticket(
                    ticket.id, 
                    'AVANCE_TECNICO', 
                    {'mensaje': 'Avance registrado por el técnico.', 'observacion': observaciones}
                )

                # 2. Si el usuario llenó los combos obligatorios, guardamos el borrador del reporte
                if tipo_mantencion_id and categoria_id:
                    reporte = ticket.reporte_tecnico or ReporteTecnico(ticket_id=ticket.id)
                    reporte.fecha = ahora.date()
                    reporte.hora = ahora.time()
                    reporte.tipo_mantencion_id = int(tipo_mantencion_id)
                    reporte.categoria_id = int(categoria_id)
                    reporte.categoria_otro = categoria_otro if categoria_otro else None
                    reporte.tipo_actividad_id = int(tipo_actividad_id) if tipo_actividad_id else None
                    reporte.actividad_id = int(actividad_id) if actividad_id else None
                    reporte.accion_id = int(accion_id) if accion_id else None
                    
                    # ⚠️ ELIMINADA la asignación de reporte.observaciones_generales aquí.
                    # Así no sobreescribimos el reporte físico y dejamos el textarea limpio.
                    db.session.add(reporte)

                db.session.commit()
                flash('Avance guardado correctamente en la bitácora.', 'info')
                # 3. CAMBIO: Redirigir a la vista de detalles (ver_ticket)
                return redirect(url_for('tickets.ver_ticket', id=id))
                
            except Exception as e:
                db.session.rollback()
                registrar_log("Error Avance", str(e))
                flash('Error al guardar el avance.', 'danger')
                return redirect(url_for('tickets.resolver_ticket', id=id))


        # ======================================================
        # RAMA B: FINALIZAR Y CERRAR TICKET
        # ======================================================
        elif accion_submit == 'finalizar':
            
            # Validación estricta solo al finalizar
            if not tipo_mantencion_id or not categoria_id:
                flash('Debes completar la clasificación principal para finalizar el ticket.', 'danger')
                return redirect(url_for('tickets.resolver_ticket', id=id))

            try:
                # 1. UPSERT del Reporte Técnico Final
                reporte = ticket.reporte_tecnico or ReporteTecnico(ticket_id=ticket.id)
                reporte.fecha = ahora.date()
                reporte.hora = ahora.time()
                reporte.tipo_mantencion_id = int(tipo_mantencion_id)
                reporte.categoria_id = int(categoria_id)
                reporte.categoria_otro = categoria_otro if categoria_otro else None
                reporte.tipo_actividad_id = int(tipo_actividad_id) if tipo_actividad_id else None
                reporte.actividad_id = int(actividad_id) if actividad_id else None
                reporte.accion_id = int(accion_id) if accion_id else None
                reporte.observaciones_generales = observaciones
                
                db.session.add(reporte)

                # 2. Actualizamos Ticket y Estado
                estado_final = obtener_estado(ESTADO_FINALIZADO)
                ticket.estado_id = estado_final.id
                ticket.fecha_finalizacion = ahora

                # 3. Historial de Cierre
                registrar_historial_ticket(ticket.id, 'FINALIZACION', {'mensaje': 'Ticket resuelto y cerrado exitosamente.'})
                
                # 4. COMMIT ANTES DE GENERAR PDF (Sugerencia del asesor)
                db.session.commit()
                registrar_log("Cierre Ticket", f"TKT-{ticket.id} cerrado por {current_user.nombre_completo}")

                # 5. Generación segura del PDF
                pdf_dir = os.path.join(current_app.root_path, 'uploads', 'informes')
                os.makedirs(pdf_dir, exist_ok=True) # Defensa contra borrado de carpetas
                pdf_filename = f"TKT-{ticket.id}_Informe.pdf"
                pdf_path = os.path.join(pdf_dir, pdf_filename)
                
                pdf_generado = False
                try:
                    generar_informe_tecnico_pdf(ticket, pdf_path)
                    pdf_generado = True
                except Exception as pdf_error:
                    registrar_log("Error PDF", f"Falló generación PDF TKT-{ticket.id}: {str(pdf_error)}")
                    # No hacemos rollback porque ya está cerrado en BD, solo informamos en log

                # 6. Envío de Correos (Consulta optimizada)
                tics = Usuario.query.join(Rol).filter(
                    Usuario.activo == True,
                    or_(Usuario.puede_asignar == True, Rol.nombre == 'ADMIN')
                ).all()
                correos_tics = [u.email for u in tics if u.email]

                # Si falló el PDF, enviamos None en el path para que el correo salga igual pero sin adjunto roto
                enviar_aviso_resolucion_ticket(ticket, correos_tics, pdf_path if pdf_generado else None)

                flash('Ticket cerrado exitosamente.', 'success')
                if not pdf_generado:
                    flash('El ticket se cerró, pero hubo un error generando el PDF. Revisa los logs.', 'warning')

                return redirect(url_for('tickets.ver_ticket', id=id))

            except Exception as e:
                db.session.rollback()
                registrar_log("Error Resolución", str(e))
                flash('Error al procesar el cierre del ticket.', 'danger')
                return redirect(url_for('tickets.ver_ticket', id=id))


    # ======================================================
    # METODO GET: CARGAR VISTA Y DICCIONARIOS
    # ======================================================
    tipos_mantencion = TipoMantencion.query.filter_by(activo=True).all()
    categorias = Categoria.query.filter_by(activo=True).all()
    tipos_actividad = TipoActividad.query.filter_by(activo=True).all()
    
    actividades_precargadas = []
    acciones_precargadas = []
    
    if ticket.reporte_tecnico:
        if ticket.reporte_tecnico.tipo_actividad_id:
            actividades_precargadas = Actividad.query.filter_by(tipo_actividad_id=ticket.reporte_tecnico.tipo_actividad_id, activo=True).all()
        if ticket.reporte_tecnico.actividad_id:
            acciones_precargadas = Accion.query.filter_by(actividad_id=ticket.reporte_tecnico.actividad_id, activo=True).all()

    return render_template(
        'tickets/resolver.html',
        ticket=ticket,
        reporte=ticket.reporte_tecnico,
        tipos_mantencion=tipos_mantencion,
        categorias=categorias,
        tipos_actividad=tipos_actividad,
        actividades_precargadas=actividades_precargadas,
        acciones_precargadas=acciones_precargadas
    )

# ==========================================================
# 7. VISUALIZACIÓN Y DESCARGA DE INFORMES
# ==========================================================

@tickets_bp.route('/informe/<int:id>')
@login_required
def ver_informe(id):
    """Permite visualizar o descargar el PDF del informe técnico finalizado."""
    ticket = Ticket.query.get_or_404(id)
    
    # SEGURIDAD 1: El funcionario NO tiene acceso al acta técnica
    if current_user.rol.nombre == 'FUNCIONARIO':
        flash('No tienes permisos para visualizar informes técnicos.', 'danger')
        return redirect(url_for('tickets.ver_ticket', id=id))

    # SEGURIDAD 2: Validar que el técnico tenga permiso para ver este ticket
    if not puede_ver_ticket(current_user, ticket):
        abort(403)
        
    # Validar que el ticket esté finalizado
    if ticket.estado.nombre != ESTADO_FINALIZADO:
        flash('El informe aún no está disponible.', 'warning')
        return redirect(url_for('tickets.ver_ticket', id=id))

    pdf_filename = f"TKT-{ticket.id}_Informe.pdf"
    pdf_dir = os.path.join(current_app.root_path, 'uploads', 'informes')
    
    # Validar que el archivo físico exista
    if not os.path.exists(os.path.join(pdf_dir, pdf_filename)):
        flash('El archivo PDF no se encontró en el servidor.', 'danger')
        return redirect(url_for('tickets.ver_ticket', id=id))

    # Lógica dinámica: ¿Vista previa o descarga forzada?
    forzar_descarga = request.args.get('descargar', '0') == '1'
    
    return send_from_directory(pdf_dir, pdf_filename, as_attachment=forzar_descarga)