# ==========================================================
# BLUEPRINT: TICKETS
# Sistema de Asistencia Técnica
# ----------------------------------------------------------
# Este módulo gestiona:
# - Creación de tickets por funcionarios
# - Visualización de tickets según permisos
# - Asignación / reasignación por gestores
# - Confirmación de recepción por técnicos
# - Guardado de avances técnicos
# - Cierre de tickets con generación de PDF
# - Descarga segura de adjuntos e informes
# ==========================================================

import os

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, abort, jsonify, current_app, send_from_directory
)
from flask_login import login_required, current_user

from models import (
    db, Ticket, EstadoTicket, Usuario, Rol,
    ReporteTecnico, TipoMantencion, Categoria,
    TipoActividad, Actividad, Accion, Adjunto
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
    obtener_hora_chile,
    guardar_adjunto_seguro
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


# ==========================================================
# HELPERS LOCALES
# ==========================================================

def registrar_log_y_confirmar(accion, detalle):
    """
    Registra un log y lo confirma inmediatamente en base de datos.

    ¿Cuándo se usa?
    - Cuando la transacción principal ya terminó con commit.
    - Cuando hubo rollback y aun así queremos guardar el error.
    - Cuando queremos dejar trazabilidad aunque falle otra parte del flujo.

    Esto evita perder logs importantes después de haber eliminado
    los commit() internos de registrar_log().
    """
    try:
        registrar_log(accion, detalle)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error persistiendo log '{accion}': {e}")


def registrar_fallo_correo(accion, ticket_id):
    """
    Helper de conveniencia para dejar trazabilidad cuando falle
    el envío de un correo, sin romper el flujo principal.
    """
    registrar_log_y_confirmar(
        accion,
        f"No se pudo enviar notificación para TKT-{ticket_id}"
    )


# ==========================================================
# PROTECCIÓN GLOBAL DEL BLUEPRINT
# ==========================================================

@tickets_bp.before_request
@login_required
def before_request():
    """
    Todo el módulo de tickets requiere usuario autenticado.
    """
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
    """
    Busca un estado por nombre.

    Si no existe, se registra un log persistente porque esto
    representa un problema de configuración del sistema.
    """
    estado = EstadoTicket.query.filter_by(nombre=nombre_estado).first()

    if not estado:
        registrar_log_y_confirmar(
            "Error Estado",
            f"Estado '{nombre_estado}' no encontrado."
        )

    return estado


def validar_estado(ticket, nombre_estado):
    """
    Valida el estado actual del ticket comparando por ID.
    Esto es más seguro que depender de strings directos.
    """
    estado = obtener_estado(nombre_estado)
    if not estado:
        return False
    return ticket.estado_id == estado.id


def puede_ver_ticket(usuario, ticket):
    """
    Control centralizado de acceso a tickets.

    Reglas:
    - ADMIN puede ver todo.
    - TÉCNICO con permiso de asignar puede ver todo.
    - TÉCNICO normal puede ver:
        * tickets creados por él (si aplica en tu flujo)
        * tickets asignados a él
    - FUNCIONARIO solo puede ver sus propios tickets.
    """
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
# 1. BANDEJA DE FUNCIONARIO
# ==========================================================

@tickets_bp.route('/')
def mis_tickets():
    """
    Muestra los tickets creados por el funcionario autenticado.
    """
    page = request.args.get('page', 1, type=int)

    query = Ticket.query.filter_by(
        usuario_id=current_user.id
    ).order_by(Ticket.fecha_creacion.desc())

    pagination = query.paginate(page=page, per_page=10, error_out=False)

    return render_template('tickets/mis_tickets.html', pagination=pagination)


# ==========================================================
# 2. CREAR TICKET
# ==========================================================

@tickets_bp.route('/nuevo', methods=['GET', 'POST'])
def crear_ticket():
    """
    Permite al funcionario crear una nueva solicitud.

    Flujo:
    1. Valida asunto y descripción
    2. Crea ticket en estado CREADO
    3. Guarda adjuntos de solicitud
    4. Registra historial + log
    5. Confirma transacción
    6. Notifica solo a gestores/admins activos
    """
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
            # 1) Insertar ticket
            db.session.add(nuevo_ticket)

            # 2) Flush para obtener ID antes de adjuntos/historial
            db.session.flush()

            # 3) Procesar adjuntos de la solicitud
            archivos = request.files.getlist('adjuntos')
            for file in archivos:
                if file.filename:
                    adjunto_obj = guardar_adjunto_seguro(
                        file=file,
                        ticket_id=nuevo_ticket.id,
                        fase='SOLICITUD',
                        usuario_id=current_user.id
                    )
                    if adjunto_obj:
                        db.session.add(adjunto_obj)

            # 4) Registrar historial
            registrar_historial_ticket(
                ticket_id=nuevo_ticket.id,
                accion='CREACION',
                detalle={'asunto': asunto}
            )

            # 5) Registrar log dentro de la misma transacción
            registrar_log(
                "Ingreso Ticket",
                f"TKT-{nuevo_ticket.id} creado por {current_user.nombre_completo}"
            )

            # 6) Confirmar todo junto
            db.session.commit()

            # 7) Notificar SOLO a Técnicos con permiso de gestor (Excluimos al ADMIN)
            gestores = Usuario.query.join(Rol).filter(
                Usuario.activo == True,
                Usuario.puede_asignar == True,
                Rol.nombre == 'TECNICO'
            ).all()

            correos_gestores = [u.email for u in gestores if u.email]

            if correos_gestores:
                ok = enviar_aviso_nuevo_ticket(nuevo_ticket, correos_gestores)
                if not ok:
                    registrar_fallo_correo("Error Email Nuevo Ticket", nuevo_ticket.id)

            flash(f'Ticket TKT-{nuevo_ticket.id} creado exitosamente.', 'success')
            return redirect(url_for('tickets.ver_ticket', id=nuevo_ticket.id))

        except Exception as e:
            db.session.rollback()
            registrar_log_y_confirmar("Error Creación Ticket", str(e))
            flash('Error al guardar el ticket.', 'danger')

    return render_template('tickets/crear.html')


# ==========================================================
# 3. VER DETALLE TICKET
# ==========================================================

@tickets_bp.route('/ver/<int:id>')
def ver_ticket(id):
    """
    Muestra el detalle del ticket si el usuario tiene permisos.
    """
    ticket = Ticket.query.get_or_404(id)

    if not puede_ver_ticket(current_user, ticket):
        abort(403)

    return render_template('tickets/ver.html', ticket=ticket)


# ==========================================================
# 4. BANDEJA GLOBAL
# ==========================================================

@tickets_bp.route('/bandeja-global')
@requiere_permiso_asignar
def bandeja_global():
    """
    Bandeja global para gestores/admins.

    Permite:
    - ver todos los tickets
    - filtrar por estado
    - asignar / reasignar técnicos
    """
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


# ==========================================================
# 5. ASIGNAR / REASIGNAR TICKET
# ==========================================================

@tickets_bp.route('/asignar/<int:id>', methods=['POST'])
@requiere_permiso_asignar
def asignar_ticket(id):
    """
    Asigna o reasigna un ticket a un técnico.

    Flujo:
    - valida técnico
    - cambia estado a ASIGNADO
    - registra historial y log
    - commit
    - notifica al técnico asignado
    """
    ticket = Ticket.query.get_or_404(id)

    tecnico_id = request.form.get('tecnico_id')
    tecnico = Usuario.query.get(tecnico_id)

    if not tecnico or tecnico.rol.nombre != 'TECNICO':
        flash('Técnico inválido.', 'danger')
        return redirect(url_for('tickets.bandeja_global'))

    estado_asignado = obtener_estado(ESTADO_ASIGNADO)
    if not estado_asignado:
        flash('No se encontró el estado ASIGNADO.', 'danger')
        return redirect(url_for('tickets.bandeja_global'))

    try:
        ticket.tecnico_id = tecnico.id
        ticket.estado_id = estado_asignado.id

        registrar_historial_ticket(
            ticket_id=ticket.id,
            accion='ASIGNACION',
            detalle={'tecnico': tecnico.nombre_completo}
        )

        registrar_log(
            "Asignación Ticket",
            f"TKT-{ticket.id} asignado a {tecnico.nombre_completo} por {current_user.nombre_completo}"
        )

        db.session.commit()

        ok = enviar_aviso_asignacion_ticket(ticket)
        if not ok:
            registrar_fallo_correo("Error Email Asignación", ticket.id)

        flash('Ticket asignado correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Asignación Ticket", str(e))
        flash('Error al asignar.', 'danger')

    return redirect(url_for('tickets.bandeja_global'))


# ==========================================================
# 6. CONFIRMAR RECEPCIÓN
# ==========================================================

@tickets_bp.route('/confirmar/<int:id>', methods=['POST'])
@tecnico_required
def confirmar_recepcion(id):
    """
    El técnico asignado confirma recepción del ticket.

    Esto cambia el estado desde ASIGNADO a EN_PROCESO.
    """
    ticket = Ticket.query.get_or_404(id)

    if ticket.tecnico_id != current_user.id:
        abort(403)

    if not validar_estado(ticket, ESTADO_ASIGNADO):
        flash('El ticket no está en estado ASIGNADO.', 'warning')
        return redirect(url_for('tickets.ver_ticket', id=id))

    estado_proceso = obtener_estado(ESTADO_EN_PROCESO)
    if not estado_proceso:
        flash('No se encontró el estado EN_PROCESO.', 'danger')
        return redirect(url_for('tickets.ver_ticket', id=id))

    try:
        ticket.estado_id = estado_proceso.id

        registrar_historial_ticket(
            ticket_id=ticket.id,
            accion='CONFIRMACION',
            detalle={}
        )

        registrar_log(
            "Confirmación Ticket",
            f"TKT-{ticket.id} confirmado por {current_user.nombre_completo}"
        )

        db.session.commit()
        flash('Ticket en proceso.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Confirmación", str(e))
        flash('Error al confirmar.', 'danger')

    return redirect(url_for('tickets.ver_ticket', id=id))


# ==========================================================
# 7. BANDEJA DEL TÉCNICO
# ==========================================================

@tickets_bp.route('/bandeja-tecnico')
@tecnico_required
def bandeja_tecnico():
    """
    Muestra solo los tickets asignados al técnico autenticado.
    """
    page = request.args.get('page', 1, type=int)

    query = Ticket.query.filter_by(
        tecnico_id=current_user.id
    ).order_by(Ticket.fecha_creacion.desc())

    pagination = query.paginate(page=page, per_page=10, error_out=False)

    return render_template('tickets/bandeja_tecnico.html', pagination=pagination)


# ==========================================================
# 8. API AJAX PARA CARGA DINÁMICA DE CATÁLOGOS
# ==========================================================

@tickets_bp.route('/api/actividades/<int:tipo_id>')
@tecnico_required
def get_actividades(tipo_id):
    """
    Retorna actividades asociadas a un tipo de actividad.
    """
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
    """
    Retorna acciones asociadas a una actividad.
    """
    acciones = Accion.query.filter_by(
        actividad_id=actividad_id,
        activo=True
    ).all()

    return jsonify({
        'acciones': [{'id': a.id, 'nombre': a.nombre} for a in acciones]
    })


# ==========================================================
# 9. RESOLVER TICKET
# ==========================================================

@tickets_bp.route('/resolver/<int:id>', methods=['GET', 'POST'])
@tecnico_required
def resolver_ticket(id):
    """
    Vista principal de trabajo técnico.

    Permite dos acciones:
    - guardar avance
    - finalizar ticket

    Solo el técnico asignado puede acceder.
    Solo se puede gestionar si el ticket está EN_PROCESO.
    """
    ticket = Ticket.query.get_or_404(id)

    # Seguridad: solo el técnico asignado puede operar el ticket
    if ticket.tecnico_id != current_user.id:
        abort(403)

    # Seguridad de flujo: solo se trabaja tickets en proceso
    if not validar_estado(ticket, ESTADO_EN_PROCESO):
        flash('Solo puedes gestionar tickets que estén en proceso.', 'warning')
        return redirect(url_for('tickets.ver_ticket', id=id))

    if request.method == 'POST':
        accion_submit = request.form.get('accion_submit')

        # Datos del formulario
        tipo_mantencion_id = request.form.get('tipo_mantencion_id')
        categoria_id = request.form.get('categoria_id')
        categoria_otro = request.form.get('categoria_otro')
        tipo_actividad_id = request.form.get('tipo_actividad_id')
        actividad_id = request.form.get('actividad_id')
        accion_id = request.form.get('accion_id')
        observaciones = request.form.get('observaciones_generales')

        ahora = obtener_hora_chile()

        # ------------------------------------------------------
        # A) GUARDAR AVANCE
        # ------------------------------------------------------
        if accion_submit == 'guardar':
            if not observaciones:
                flash('Para guardar un avance, debes escribir algo en las Observaciones.', 'warning')
                return redirect(url_for('tickets.resolver_ticket', id=id))

            try:
                # 1) Registrar avance en historial
                registrar_historial_ticket(
                    ticket_id=ticket.id,
                    accion='AVANCE_TECNICO',
                    detalle={
                        'mensaje': 'Avance registrado por el técnico.',
                        'observacion': observaciones
                    }
                )

                # 2) Si ya hay datos técnicos base, guardamos/actualizamos borrador de reporte
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

                    db.session.add(reporte)

                # 3) Adjuntos de resolución / trabajo técnico
                archivos = request.files.getlist('adjuntos')
                for file in archivos:
                    if file.filename:
                        adjunto_obj = guardar_adjunto_seguro(
                            file=file,
                            ticket_id=ticket.id,
                            fase='RESOLUCION',
                            usuario_id=current_user.id
                        )
                        if adjunto_obj:
                            db.session.add(adjunto_obj)

                # 4) Log del avance dentro de la misma transacción
                registrar_log(
                    "Avance Ticket",
                    f"TKT-{ticket.id} registró avance por {current_user.nombre_completo}"
                )

                db.session.commit()

                flash('Avance guardado correctamente en la bitácora.', 'info')
                return redirect(url_for('tickets.ver_ticket', id=id))

            except Exception as e:
                db.session.rollback()
                registrar_log_y_confirmar("Error Avance", str(e))
                flash('Error al guardar el avance.', 'danger')
                return redirect(url_for('tickets.resolver_ticket', id=id))

        # ------------------------------------------------------
        # B) FINALIZAR TICKET
        # ------------------------------------------------------
        elif accion_submit == 'finalizar':
            if not tipo_mantencion_id or not categoria_id:
                flash('Debes completar la clasificación principal para finalizar el ticket.', 'danger')
                return redirect(url_for('tickets.resolver_ticket', id=id))

            try:
                # 1) Crear o actualizar reporte técnico final
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

                # 2) Cambiar estado a FINALIZADO
                estado_final = obtener_estado(ESTADO_FINALIZADO)
                if not estado_final:
                    flash('No se encontró el estado FINALIZADO.', 'danger')
                    return redirect(url_for('tickets.resolver_ticket', id=id))

                ticket.estado_id = estado_final.id
                ticket.fecha_finalizacion = ahora

                # 3) Registrar historial de cierre
                registrar_historial_ticket(
                    ticket_id=ticket.id,
                    accion='FINALIZACION',
                    detalle={'mensaje': 'Ticket resuelto y cerrado exitosamente.'}
                )

                # 4) Guardar adjuntos finales de resolución
                archivos = request.files.getlist('adjuntos')
                for file in archivos:
                    if file.filename:
                        adjunto_obj = guardar_adjunto_seguro(
                            file=file,
                            ticket_id=ticket.id,
                            fase='RESOLUCION',
                            usuario_id=current_user.id
                        )
                        if adjunto_obj:
                            db.session.add(adjunto_obj)

                # 5) Log del cierre dentro del commit principal
                registrar_log(
                    "Cierre Ticket",
                    f"TKT-{ticket.id} cerrado por {current_user.nombre_completo}"
                )

                # 6) Confirmar cierre completo
                db.session.commit()

                # 7) Generar PDF interno del informe
                pdf_dir = os.path.join(current_app.root_path, 'uploads', 'informes')
                os.makedirs(pdf_dir, exist_ok=True)

                pdf_filename = f"TKT-{ticket.id}_Informe.pdf"
                pdf_path = os.path.join(pdf_dir, pdf_filename)

                pdf_generado = False
                try:
                    generar_informe_tecnico_pdf(ticket, pdf_path)
                    pdf_generado = True
                except Exception as pdf_error:
                    # El ticket ya fue cerrado; este error se loguea aparte
                    registrar_log_y_confirmar(
                        "Error PDF",
                        f"Falló generación PDF TKT-{ticket.id}: {str(pdf_error)}"
                    )

                # 8) Enviar correo final solo a:
                #    - solicitante
                #    - técnico resolutor
                #    Sin adjuntar PDF
                ok = enviar_aviso_resolucion_ticket(ticket)
                if not ok:
                    registrar_fallo_correo("Error Email Resolución", ticket.id)

                flash('Ticket cerrado exitosamente.', 'success')

                if not pdf_generado:
                    flash(
                        'El ticket se cerró, pero hubo un error generando el PDF. Revisa los logs.',
                        'warning'
                    )

                return redirect(url_for('tickets.ver_ticket', id=id))

            except Exception as e:
                db.session.rollback()
                registrar_log_y_confirmar("Error Resolución", str(e))
                flash('Error al procesar el cierre del ticket.', 'danger')
                return redirect(url_for('tickets.ver_ticket', id=id))

    # ------------------------------------------------------
    # GET: cargar catálogos y datos para render de formulario
    # ------------------------------------------------------
    tipos_mantencion = TipoMantencion.query.filter_by(activo=True).all()
    categorias = Categoria.query.filter_by(activo=True).all()
    tipos_actividad = TipoActividad.query.filter_by(activo=True).all()

    actividades_precargadas = []
    acciones_precargadas = []

    if ticket.reporte_tecnico:
        if ticket.reporte_tecnico.tipo_actividad_id:
            actividades_precargadas = Actividad.query.filter_by(
                tipo_actividad_id=ticket.reporte_tecnico.tipo_actividad_id,
                activo=True
            ).all()

        if ticket.reporte_tecnico.actividad_id:
            acciones_precargadas = Accion.query.filter_by(
                actividad_id=ticket.reporte_tecnico.actividad_id,
                activo=True
            ).all()

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
# 10. VER / DESCARGAR INFORME PDF
# ==========================================================

@tickets_bp.route('/informe/<int:id>')
@login_required
def ver_informe(id):
    """
    Permite visualizar o descargar el PDF del informe técnico.

    Restricciones:
    - El funcionario no puede acceder al informe técnico.
    - Solo perfiles autorizados pueden verlo.
    - El ticket debe estar finalizado.
    """
    ticket = Ticket.query.get_or_404(id)

    if current_user.rol.nombre == 'FUNCIONARIO':
        flash('No tienes permisos para visualizar informes técnicos.', 'danger')
        return redirect(url_for('tickets.ver_ticket', id=id))

    if not puede_ver_ticket(current_user, ticket):
        abort(403)

    if ticket.estado.nombre != ESTADO_FINALIZADO:
        flash('El informe aún no está disponible.', 'warning')
        return redirect(url_for('tickets.ver_ticket', id=id))

    pdf_filename = f"TKT-{ticket.id}_Informe.pdf"
    pdf_dir = os.path.join(current_app.root_path, 'uploads', 'informes')

    if not os.path.exists(os.path.join(pdf_dir, pdf_filename)):
        flash('El archivo PDF no se encontró en el servidor.', 'danger')
        return redirect(url_for('tickets.ver_ticket', id=id))

    forzar_descarga = request.args.get('descargar', '0') == '1'

    return send_from_directory(
        pdf_dir,
        pdf_filename,
        as_attachment=forzar_descarga
    )


# ==========================================================
# 11. DESCARGA SEGURA DE ADJUNTOS
# ==========================================================

@tickets_bp.route('/adjunto/<int:id>')
@login_required
def descargar_adjunto(id):
    """
    Descarga segura de archivos adjuntos.

    Reglas:
    - solo usuarios autorizados sobre el ticket pueden descargar
    - se sirve el archivo físico con el nombre visible original
    """
    adjunto = Adjunto.query.get_or_404(id)

    if not puede_ver_ticket(current_user, adjunto.ticket):
        abort(403)

    adjuntos_dir = os.path.join(current_app.root_path, 'uploads', 'adjuntos')

    if not os.path.exists(os.path.join(adjuntos_dir, adjunto.ruta_archivo)):
        flash('El archivo solicitado ya no se encuentra en el servidor.', 'danger')
        return redirect(url_for('tickets.ver_ticket', id=adjunto.ticket_id))

    return send_from_directory(
        adjuntos_dir,
        adjunto.ruta_archivo,
        as_attachment=True,
        download_name=adjunto.nombre_archivo
    )