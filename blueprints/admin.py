# blueprints/admin.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from sqlalchemy import or_

# Modelos actualizados
from models import db, Usuario, Rol, Log, Ticket, Establecimiento, Departamento, Seccion
from utils import registrar_log, admin_required, enviar_credenciales_nuevo_usuario

admin_bp = Blueprint('admin', __name__, template_folder='../templates', url_prefix='/admin')

@admin_bp.before_request
@login_required
@admin_required
def before_request():
    """Protege todo el blueprint para solo ADMIN"""
    pass

@admin_bp.route('/panel')
def panel():
    page = request.args.get('page', 1, type=int)
    busqueda = request.args.get('busqueda', '')
    rol_filtro = request.args.get('rol_filtro', '')
    estado_filtro = request.args.get('estado_filtro', '')
    
    query = Usuario.query

    if busqueda:
        query = query.filter(
            or_(Usuario.nombre_completo.ilike(f'%{busqueda}%'),
                Usuario.email.ilike(f'%{busqueda}%'))
        )
    
    if rol_filtro:
        query = query.filter(Usuario.rol_id == rol_filtro)
    
    if estado_filtro == 'activo':
        query = query.filter(Usuario.activo == True)
    elif estado_filtro == 'inactivo':
        query = query.filter(Usuario.activo == False)
    
    pagination = query.order_by(Usuario.id).paginate(page=page, per_page=10, error_out=False)
    roles_para_filtro = Rol.query.order_by(Rol.nombre).all()
    
    stats = {
        'total_usuarios': Usuario.query.count(),
        'total_tickets': Ticket.query.count(),
        'tickets_pendientes': Ticket.query.join(Ticket.estado).filter(Ticket.estado.has(nombre='CREADO')).count()
    }

    return render_template('admin/panel.html', 
                           pagination=pagination,
                           roles_para_filtro=roles_para_filtro,
                           busqueda=busqueda,
                           rol_filtro=rol_filtro,
                           estado_filtro=estado_filtro,
                           stats=stats)

@admin_bp.route('/crear_usuario', methods=['GET', 'POST'])
def crear_usuario():
    roles = Rol.query.order_by(Rol.nombre).all()
    establecimientos = Establecimiento.query.order_by(Establecimiento.nombre).all()

    if request.method == 'POST':
        nombre = request.form.get('nombre_completo')
        email = request.form.get('email')
        password = request.form.get('password')
        rol_id = request.form.get('rol_id')
        forzar_cambio = request.form.get('forzar_cambio_clave') == '1'
        puede_asignar = request.form.get('puede_asignar') == '1' # NUEVO
        
        # Validaciones de jerarquía organizacional
        est_id = request.form.get('establecimiento_id')
        dep_id = request.form.get('departamento_id')
        sec_id = request.form.get('seccion_id')

        if Usuario.query.filter_by(email=email).first():
            flash('Error: El correo ya está registrado.', 'danger')
            return render_template('admin/crear_usuario.html', roles=roles, establecimientos=establecimientos, datos_previos=request.form)

        nuevo_usuario = Usuario(
            nombre_completo=nombre, 
            email=email, 
            rol_id=rol_id,
            establecimiento_id=int(est_id) if est_id else None,
            departamento_id=int(dep_id) if dep_id else None,
            seccion_id=int(sec_id) if sec_id else None,
            cambio_clave_requerido=forzar_cambio,
            puede_asignar=puede_asignar,
            activo=True
        )
        nuevo_usuario.set_password(password)
        
        try:
            db.session.add(nuevo_usuario)
            registrar_log("Creación Usuario", f"Admin creó a {nombre} ({email})")
            db.session.commit() # TRANSACCIONAL: Guarda usuario y log
            
            if enviar_credenciales_nuevo_usuario(nuevo_usuario, password):
                flash(f'Usuario creado con éxito. Credenciales enviadas a {email}.', 'success')
            else:
                flash(f'Usuario creado, pero FALLÓ el envío del correo. Entregue la clave manualmente: {password}', 'warning')
            
            return redirect(url_for('admin.panel'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al crear usuario: {str(e)}', 'danger')

    return render_template('admin/crear_usuario.html', roles=roles, establecimientos=establecimientos)

@admin_bp.route('/editar_usuario/<int:id>', methods=['GET', 'POST'])
def editar_usuario(id):
    usuario = Usuario.query.get_or_404(id)
    roles = Rol.query.order_by(Rol.nombre).all()
    establecimientos = Establecimiento.query.order_by(Establecimiento.nombre).all()
    
    # Necesitamos cargar los departamentos y secciones correspondientes para el dropdown
    departamentos = Departamento.query.filter_by(establecimiento_id=usuario.establecimiento_id).all() if usuario.establecimiento_id else []
    secciones = Seccion.query.filter_by(departamento_id=usuario.departamento_id).all() if usuario.departamento_id else []

    if request.method == 'POST':
        email_nuevo = request.form.get('email')
        
        usuario_existente = Usuario.query.filter_by(email=email_nuevo).first()
        if usuario_existente and usuario_existente.id != id:
            flash('Error: Ese correo ya pertenece a otro usuario.', 'danger')
            return render_template('admin/editar_usuario.html', usuario=usuario, roles=roles, establecimientos=establecimientos, departamentos=departamentos, secciones=secciones)

        usuario.nombre_completo = request.form.get('nombre_completo')
        usuario.email = email_nuevo
        usuario.rol_id = request.form.get('rol_id')
        
        est_id = request.form.get('establecimiento_id')
        dep_id = request.form.get('departamento_id')
        sec_id = request.form.get('seccion_id')
        
        usuario.establecimiento_id = int(est_id) if est_id else None
        usuario.departamento_id = int(dep_id) if dep_id else None
        usuario.seccion_id = int(sec_id) if sec_id else None
        
        usuario.cambio_clave_requerido = request.form.get('forzar_cambio_clave') == '1'
        usuario.puede_asignar = request.form.get('puede_asignar') == '1'

        password = request.form.get('password')
        if password and password.strip():
            usuario.set_password(password)
            flash('Contraseña actualizada.', 'info')

        try:
            registrar_log("Edición Usuario", f"Admin editó a {usuario.nombre_completo}")
            db.session.commit() # TRANSACCIONAL: Guarda edición de usuario y log
            flash('Usuario actualizado con éxito.', 'success')
            return redirect(url_for('admin.panel'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error al actualizar: {str(e)}', 'danger')

    return render_template('admin/editar_usuario.html', usuario=usuario, roles=roles, establecimientos=establecimientos, departamentos=departamentos, secciones=secciones)

@admin_bp.route('/toggle_activo/<int:id>', methods=['POST'])
def toggle_activo(id):
    usuario = Usuario.query.get_or_404(id)
    if usuario.id == current_user.id:
        flash('No puedes desactivar tu propia cuenta.', 'danger')
        return redirect(url_for('admin.panel'))
        
    usuario.activo = not usuario.activo
    estado = "activado" if usuario.activo else "desactivado"
    
    registrar_log("Cambio Estado", f"Usuario {usuario.nombre_completo} fue {estado}.")
    db.session.commit() # TRANSACCIONAL: Guarda cambio de estado y log
    
    flash(f'Usuario {usuario.nombre_completo} {estado}.', 'success')
    return redirect(url_for('admin.panel'))

@admin_bp.route('/ver_logs')
def ver_logs():
    page = request.args.get('page', 1, type=int)
    usuario_filtro = request.args.get('usuario_id')
    accion_filtro = request.args.get('accion')

    query = Log.query.order_by(Log.timestamp.desc())

    if usuario_filtro and usuario_filtro.isdigit():
        query = query.filter(Log.usuario_id == int(usuario_filtro))
    if accion_filtro:
        query = query.filter(Log.accion == accion_filtro)

    pagination = query.paginate(page=page, per_page=15, error_out=False)
    todos_los_usuarios = Usuario.query.order_by(Usuario.nombre_completo).all()
    
    # Adaptado a las acciones del nuevo sistema
    acciones_posibles = [
        "Inicio de Sesión", "Cierre de Sesión", "Cierre de Sesión Automático", 
        "Creación Usuario", "Edición Usuario", "Cambio Estado", "Cambio de Clave", 
        "Login Fallido", "Solicitud Reseteo", "Solicitud Reseteo Fallida", 
        "Recuperación Clave"
    ]

    return render_template('admin/ver_logs.html', pagination=pagination,
                           todos_los_usuarios=todos_los_usuarios,
                           acciones_posibles=acciones_posibles,
                           filtros={'usuario_id': usuario_filtro, 'accion': accion_filtro})

# --- Endpoints AJAX para cascada de organización ---
@admin_bp.route('/api/departamentos/<int:establecimiento_id>')
def get_departamentos(establecimiento_id):
    departamentos = Departamento.query.filter_by(establecimiento_id=establecimiento_id, activo=True).all()
    return {'departamentos': [{'id': d.id, 'nombre': d.nombre} for d in departamentos]}

@admin_bp.route('/api/secciones/<int:departamento_id>')
def get_secciones(departamento_id):
    secciones = Seccion.query.filter_by(departamento_id=departamento_id, activo=True).all()
    return {'secciones': [{'id': s.id, 'nombre': s.nombre} for s in secciones]}