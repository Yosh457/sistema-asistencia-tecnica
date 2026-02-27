# utils/decorators.py
from functools import wraps
from flask import abort, redirect, url_for, flash
from flask_login import current_user

def check_password_change(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if current_user.is_authenticated and current_user.cambio_clave_requerido:
            flash('Debes cambiar tu contraseña para continuar.', 'warning')
            return redirect(url_for('auth.cambiar_clave'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Solo permite acceso al Rol 'ADMIN'."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.rol or current_user.rol.nombre != 'ADMIN':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def tecnico_required(f):
    """Permite acceso a 'TECNICO' y 'ADMIN'."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        roles_permitidos = ['ADMIN', 'TECNICO']
        if not current_user.is_authenticated or not current_user.rol or current_user.rol.nombre not in roles_permitidos:
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

def requiere_permiso_asignar(f):
    """Permite acceso SOLO a 'TECNICO' con puede_asignar=True, y a 'ADMIN'."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.rol:
            abort(403)
            
        if current_user.rol.nombre == 'ADMIN':
            return f(*args, **kwargs)
            
        if current_user.rol.nombre == 'TECNICO' and current_user.puede_asignar:
            return f(*args, **kwargs)
            
        abort(403)
    return decorated_function