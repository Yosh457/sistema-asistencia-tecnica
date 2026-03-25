# blueprints/catalogos.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required

from models import (
    db,
    TipoMantencion,
    Categoria,
    TipoActividad,
    Actividad,
    Accion,
    ReporteTecnico
)
from utils import admin_required, registrar_log

# ==========================================================
# BLUEPRINT DE CATÁLOGOS
# ----------------------------------------------------------
# Este módulo administra los diccionarios técnicos del sistema:
# - Tipos de Mantención
# - Categorías
# - Árbol Técnico:
#     Nivel 1 -> TipoActividad
#     Nivel 2 -> Actividad
#     Nivel 3 -> Accion
# ==========================================================

catalogos_bp = Blueprint(
    'catalogos',
    __name__,
    template_folder='../templates',
    url_prefix='/admin/catalogos'
)


# ==========================================================
# HELPERS LOCALES
# ==========================================================

def registrar_log_y_confirmar(accion, detalle):
    """
    Registra un log y lo confirma inmediatamente.

    Se usa especialmente cuando:
    - ya hicimos rollback de la operación principal
    - queremos dejar trazabilidad del error igual
    """
    try:
        registrar_log(accion, detalle)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Error persistiendo log '{accion}': {e}")


def nombre_obligatorio(nombre, tab):
    """
    Valida que el nombre no venga vacío.
    """
    if not nombre:
        flash('El nombre es obligatorio.', 'danger')
        return redirect(url_for('catalogos.index', tab=tab))
    return None


def nombre_simple_duplicado(modelo, nombre, tab, mensaje):
    """
    Valida duplicidad simple para catálogos sin padre.
    """
    if modelo.query.filter_by(nombre=nombre).first():
        flash(mensaje, 'danger')
        return redirect(url_for('catalogos.index', tab=tab))
    return None


def nombre_simple_duplicado_excluyendo_actual(modelo, nombre, current_id, tab, mensaje):
    """
    Valida duplicidad simple excluyendo el registro actual.
    """
    existente = modelo.query.filter_by(nombre=nombre).first()
    if existente and existente.id != current_id:
        flash(mensaje, 'danger')
        return redirect(url_for('catalogos.index', tab=tab))
    return None


def validar_relacion_obligatoria(relacion_id, tab, mensaje='Debes seleccionar una relación padre válida.'):
    """
    Valida que venga informado el padre en catálogos jerárquicos.
    """
    if not relacion_id:
        flash(mensaje, 'danger')
        return redirect(url_for('catalogos.index', tab=tab))
    return None


def actividad_duplicada(nombre, tipo_actividad_id, current_id=None):
    """
    Valida unicidad compuesta de Actividad por:
    (tipo_actividad_id, nombre)
    """
    q = Actividad.query.filter_by(nombre=nombre, tipo_actividad_id=tipo_actividad_id)
    existente = q.first()
    if existente and (current_id is None or existente.id != current_id):
        return True
    return False


def accion_duplicada(nombre, actividad_id, current_id=None):
    """
    Valida unicidad compuesta de Acción por:
    (actividad_id, nombre)
    """
    q = Accion.query.filter_by(nombre=nombre, actividad_id=actividad_id)
    existente = q.first()
    if existente and (current_id is None or existente.id != current_id):
        return True
    return False


def esta_en_uso_en_reportes(entidad, item_id):
    """
    Determina si un catálogo está siendo usado en ReporteTecnico.
    Evita desactivar catálogos ya utilizados en tickets cerrados / reportados.
    """
    if entidad == 'tipo_mantencion':
        return ReporteTecnico.query.filter_by(tipo_mantencion_id=item_id).first() is not None
    if entidad == 'categoria':
        return ReporteTecnico.query.filter_by(categoria_id=item_id).first() is not None
    if entidad == 'tipo_actividad':
        return ReporteTecnico.query.filter_by(tipo_actividad_id=item_id).first() is not None
    if entidad == 'actividad':
        return ReporteTecnico.query.filter_by(actividad_id=item_id).first() is not None
    if entidad == 'accion':
        return ReporteTecnico.query.filter_by(accion_id=item_id).first() is not None
    return False


# ==========================================================
# PROTECCIÓN GLOBAL
# ==========================================================

@catalogos_bp.before_request
@login_required
@admin_required
def before_request():
    """
    Todo el módulo queda restringido a ADMIN.
    """
    pass


# ==========================================================
# VISTA PRINCIPAL
# ==========================================================

@catalogos_bp.route('/')
def index():
    """
    Vista principal del módulo de catálogos.
    Usa ?tab= para dejar activa la pestaña correspondiente.
    """
    tab_activa = request.args.get('tab', 'mantencion')

    tipos_mantencion = TipoMantencion.query.order_by(TipoMantencion.nombre).all()
    categorias = Categoria.query.order_by(Categoria.nombre).all()
    tipos_actividad = TipoActividad.query.order_by(TipoActividad.nombre).all()
    actividades = Actividad.query.order_by(Actividad.tipo_actividad_id, Actividad.nombre).all()
    acciones = Accion.query.order_by(Accion.actividad_id, Accion.nombre).all()

    return render_template(
        'admin/catalogos/index.html',
        tab_activa=tab_activa,
        tipos_mantencion=tipos_mantencion,
        categorias=categorias,
        tipos_actividad=tipos_actividad,
        actividades=actividades,
        acciones=acciones
    )


# ==========================================================
# CRUD: TIPOS DE MANTENCIÓN
# ==========================================================

@catalogos_bp.route('/mantencion/crear', methods=['POST'])
def crear_mantencion():
    """
    Crea un nuevo tipo de mantención.
    """
    nombre = request.form.get('nombre', '').strip().upper()

    # Validación explícita de obligatorio
    error = nombre_obligatorio(nombre, 'mantencion')
    if error:
        return error

    # Validación de duplicidad
    error = nombre_simple_duplicado(
        TipoMantencion,
        nombre,
        'mantencion',
        f'El tipo de mantención "{nombre}" ya existe.'
    )
    if error:
        return error

    try:
        nuevo = TipoMantencion(nombre=nombre, activo=True)
        db.session.add(nuevo)

        # Log dentro de la misma transacción
        registrar_log("Creación Catálogo", f"Creado Tipo Mantención: {nombre}")
        db.session.commit()

        flash('Tipo de mantención creado exitosamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error creando Tipo Mantención '{nombre}': {str(e)}")
        flash('Error al crear el registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='mantencion'))


@catalogos_bp.route('/mantencion/editar/<int:id>', methods=['POST'])
def editar_mantencion(id):
    item = TipoMantencion.query.get_or_404(id)
    nuevo_nombre = request.form.get('nombre', '').strip().upper()

    # Validación explícita de obligatorio
    error = nombre_obligatorio(nuevo_nombre, 'mantencion')
    if error:
        return error

    # Validación de duplicidad excluyendo el actual
    error = nombre_simple_duplicado_excluyendo_actual(
        TipoMantencion,
        nuevo_nombre,
        id,
        'mantencion',
        f'El nombre "{nuevo_nombre}" ya está en uso.'
    )
    if error:
        return error

    try:
        nombre_anterior = item.nombre
        item.nombre = nuevo_nombre

        registrar_log(
            "Edición Catálogo",
            f"Editado Tipo Mantención ID {id}: '{nombre_anterior}' -> '{nuevo_nombre}'"
        )
        db.session.commit()

        flash('Registro actualizado correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error editando Tipo Mantención ID {id}: {str(e)}")
        flash('Error al actualizar el registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='mantencion'))


@catalogos_bp.route('/mantencion/toggle/<int:id>', methods=['POST'])
def toggle_mantencion(id):
    """
    Activa o desactiva un tipo de mantención.
    """
    item = TipoMantencion.query.get_or_404(id)

    # Solo bloqueamos la desactivación si ya está en uso
    if item.activo and esta_en_uso_en_reportes('tipo_mantencion', item.id):
        flash('No puedes desactivar este tipo de mantención porque ya está en uso en reportes técnicos.', 'warning')
        return redirect(url_for('catalogos.index', tab='mantencion'))

    try:
        item.activo = not item.activo
        estado = "activado" if item.activo else "desactivado"

        registrar_log("Estado Catálogo", f"Tipo Mantención '{item.nombre}' fue {estado}.")
        db.session.commit()

        flash(f'Registro {estado} correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error cambiando estado de Tipo Mantención ID {id}: {str(e)}")
        flash('Error al cambiar el estado del registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='mantencion'))


# ==========================================================
# CRUD: CATEGORÍAS
# ==========================================================

@catalogos_bp.route('/categoria/crear', methods=['POST'])
def crear_categoria():
    """
    Crea una nueva categoría.
    """
    nombre = request.form.get('nombre', '').strip().upper()

    # Validación explícita de obligatorio
    error = nombre_obligatorio(nombre, 'categorias')
    if error:
        return error

    # Validación de duplicidad
    error = nombre_simple_duplicado(
        Categoria,
        nombre,
        'categorias',
        f'La categoría "{nombre}" ya existe.'
    )
    if error:
        return error

    try:
        nueva = Categoria(nombre=nombre, activo=True)
        db.session.add(nueva)

        registrar_log("Creación Catálogo", f"Creada Categoría: {nombre}")
        db.session.commit()

        flash('Categoría creada exitosamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error creando Categoría '{nombre}': {str(e)}")
        flash('Error al crear el registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='categorias'))


@catalogos_bp.route('/categoria/editar/<int:id>', methods=['POST'])
def editar_categoria(id):
    """
    Edita una categoría existente.
    """
    item = Categoria.query.get_or_404(id)
    nuevo_nombre = request.form.get('nombre', '').strip().upper()

    # Validación explícita de obligatorio
    error = nombre_obligatorio(nuevo_nombre, 'categorias')
    if error:
        return error

    # Validación de duplicidad excluyendo el actual
    error = nombre_simple_duplicado_excluyendo_actual(
        Categoria,
        nuevo_nombre,
        id,
        'categorias',
        f'El nombre "{nuevo_nombre}" ya está en uso.'
    )
    if error:
        return error

    try:
        nombre_anterior = item.nombre
        item.nombre = nuevo_nombre

        registrar_log(
            "Edición Catálogo",
            f"Editada Categoría ID {id}: '{nombre_anterior}' -> '{nuevo_nombre}'"
        )
        db.session.commit()

        flash('Registro actualizado correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error editando Categoría ID {id}: {str(e)}")
        flash('Error al actualizar el registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='categorias'))


@catalogos_bp.route('/categoria/toggle/<int:id>', methods=['POST'])
def toggle_categoria(id):
    """
    Activa o desactiva una categoría.
    """
    item = Categoria.query.get_or_404(id)

    if item.activo and esta_en_uso_en_reportes('categoria', item.id):
        flash('No puedes desactivar esta categoría porque ya está en uso en reportes técnicos.', 'warning')
        return redirect(url_for('catalogos.index', tab='categorias'))

    try:
        item.activo = not item.activo
        estado = "activado" if item.activo else "desactivado"

        registrar_log("Estado Catálogo", f"Categoría '{item.nombre}' fue {estado}.")
        db.session.commit()

        flash(f'Registro {estado} correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error cambiando estado de Categoría ID {id}: {str(e)}")
        flash('Error al cambiar el estado del registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='categorias'))


# ==========================================================
# CRUD: TIPO DE ACTIVIDAD (NIVEL 1)
# ==========================================================

@catalogos_bp.route('/tipo_actividad/crear', methods=['POST'])
def crear_tipo_actividad():
    nombre = request.form.get('nombre', '').strip()

    error = nombre_obligatorio(nombre, 'tipo_actividad')
    if error:
        return error

    error = nombre_simple_duplicado(
        TipoActividad,
        nombre,
        'tipo_actividad',
        f'El tipo de actividad "{nombre}" ya existe.'
    )
    if error:
        return error

    try:
        nuevo = TipoActividad(nombre=nombre, activo=True)
        db.session.add(nuevo)

        registrar_log("Creación Catálogo", f"Creado Tipo Actividad: {nombre}")
        db.session.commit()

        flash('Tipo de actividad creado exitosamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error creando Tipo Actividad '{nombre}': {str(e)}")
        flash('Error al crear el registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='tipo_actividad'))


@catalogos_bp.route('/tipo_actividad/editar/<int:id>', methods=['POST'])
def editar_tipo_actividad(id):
    item = TipoActividad.query.get_or_404(id)
    nuevo_nombre = request.form.get('nombre', '').strip()

    error = nombre_obligatorio(nuevo_nombre, 'tipo_actividad')
    if error:
        return error

    error = nombre_simple_duplicado_excluyendo_actual(
        TipoActividad,
        nuevo_nombre,
        id,
        'tipo_actividad',
        f'El nombre "{nuevo_nombre}" ya está en uso.'
    )
    if error:
        return error

    try:
        nombre_anterior = item.nombre
        item.nombre = nuevo_nombre

        registrar_log(
            "Edición Catálogo",
            f"Editado Tipo Actividad ID {id}: '{nombre_anterior}' -> '{nuevo_nombre}'"
        )
        db.session.commit()

        flash('Registro actualizado correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error editando Tipo Actividad ID {id}: {str(e)}")
        flash('Error al actualizar el registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='tipo_actividad'))


@catalogos_bp.route('/tipo_actividad/toggle/<int:id>', methods=['POST'])
def toggle_tipo_actividad(id):
    item = TipoActividad.query.get_or_404(id)

    if item.activo and esta_en_uso_en_reportes('tipo_actividad', item.id):
        flash('No puedes desactivar este tipo de actividad porque ya está en uso en reportes técnicos.', 'warning')
        return redirect(url_for('catalogos.index', tab='tipo_actividad'))

    try:
        item.activo = not item.activo
        estado = "activado" if item.activo else "desactivado"

        registrar_log("Estado Catálogo", f"Tipo Actividad '{item.nombre}' fue {estado}.")
        db.session.commit()

        flash(f'Registro {estado} correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error cambiando estado de Tipo Actividad ID {id}: {str(e)}")
        flash('Error al cambiar el estado del registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='tipo_actividad'))


# ==========================================================
# CRUD: ACTIVIDAD (NIVEL 2)
# ==========================================================

@catalogos_bp.route('/actividad/crear', methods=['POST'])
def crear_actividad():
    nombre = request.form.get('nombre', '').strip()
    tipo_actividad_id = request.form.get('relacion_id')

    error = nombre_obligatorio(nombre, 'actividad')
    if error:
        return error

    error = validar_relacion_obligatoria(
        tipo_actividad_id,
        'actividad',
        'El nombre y el Tipo de Actividad padre son obligatorios.'
    )
    if error:
        return error

    try:
        tipo_actividad_id_int = int(tipo_actividad_id)
    except (ValueError, TypeError):
        flash('El Tipo de Actividad seleccionado no es válido.', 'danger')
        return redirect(url_for('catalogos.index', tab='actividad'))

    if actividad_duplicada(nombre, tipo_actividad_id_int):
        flash(f'La actividad "{nombre}" ya existe para ese Tipo de Actividad.', 'danger')
        return redirect(url_for('catalogos.index', tab='actividad'))

    try:
        nueva = Actividad(
            nombre=nombre,
            tipo_actividad_id=tipo_actividad_id_int,
            activo=True
        )
        db.session.add(nueva)

        registrar_log(
            "Creación Catálogo",
            f"Creada Actividad: {nombre} (TipoActividad ID: {tipo_actividad_id_int})"
        )
        db.session.commit()

        flash('Actividad creada exitosamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error creando Actividad '{nombre}': {str(e)}")
        flash('Error al crear el registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='actividad'))


@catalogos_bp.route('/actividad/editar/<int:id>', methods=['POST'])
def editar_actividad(id):
    item = Actividad.query.get_or_404(id)
    nuevo_nombre = request.form.get('nombre', '').strip()
    nuevo_tipo_actividad_id = request.form.get('relacion_id')

    error = nombre_obligatorio(nuevo_nombre, 'actividad')
    if error:
        return error

    error = validar_relacion_obligatoria(
        nuevo_tipo_actividad_id,
        'actividad',
        'El nombre y el Tipo de Actividad padre son obligatorios.'
    )
    if error:
        return error

    try:
        nuevo_tipo_actividad_id_int = int(nuevo_tipo_actividad_id)
    except (ValueError, TypeError):
        flash('El Tipo de Actividad seleccionado no es válido.', 'danger')
        return redirect(url_for('catalogos.index', tab='actividad'))

    if actividad_duplicada(nuevo_nombre, nuevo_tipo_actividad_id_int, current_id=id):
        flash(f'El nombre "{nuevo_nombre}" ya está en uso para ese Tipo de Actividad.', 'danger')
        return redirect(url_for('catalogos.index', tab='actividad'))

    try:
        nombre_anterior = item.nombre
        padre_anterior = item.tipo_actividad_id

        item.nombre = nuevo_nombre
        item.tipo_actividad_id = nuevo_tipo_actividad_id_int

        registrar_log(
            "Edición Catálogo",
            f"Editada Actividad ID {id}: '{nombre_anterior}' -> '{nuevo_nombre}' (Padre {padre_anterior} -> {nuevo_tipo_actividad_id_int})"
        )
        db.session.commit()

        flash('Registro actualizado correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error editando Actividad ID {id}: {str(e)}")
        flash('Error al actualizar el registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='actividad'))


@catalogos_bp.route('/actividad/toggle/<int:id>', methods=['POST'])
def toggle_actividad(id):
    item = Actividad.query.get_or_404(id)

    if item.activo and esta_en_uso_en_reportes('actividad', item.id):
        flash('No puedes desactivar esta actividad porque ya está en uso en reportes técnicos.', 'warning')
        return redirect(url_for('catalogos.index', tab='actividad'))

    try:
        item.activo = not item.activo
        estado = "activado" if item.activo else "desactivado"

        registrar_log("Estado Catálogo", f"Actividad '{item.nombre}' fue {estado}.")
        db.session.commit()

        flash(f'Registro {estado} correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error cambiando estado de Actividad ID {id}: {str(e)}")
        flash('Error al cambiar el estado del registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='actividad'))


# ==========================================================
# CRUD: ACCIÓN (NIVEL 3)
# ==========================================================

@catalogos_bp.route('/accion/crear', methods=['POST'])
def crear_accion():
    nombre = request.form.get('nombre', '').strip()
    actividad_id = request.form.get('relacion_id')

    error = nombre_obligatorio(nombre, 'accion')
    if error:
        return error

    error = validar_relacion_obligatoria(
        actividad_id,
        'accion',
        'El nombre y la Actividad padre son obligatorios.'
    )
    if error:
        return error

    try:
        actividad_id_int = int(actividad_id)
    except (ValueError, TypeError):
        flash('La Actividad seleccionada no es válida.', 'danger')
        return redirect(url_for('catalogos.index', tab='accion'))

    if accion_duplicada(nombre, actividad_id_int):
        flash(f'La acción "{nombre}" ya existe para esa Actividad.', 'danger')
        return redirect(url_for('catalogos.index', tab='accion'))

    try:
        nueva = Accion(
            nombre=nombre,
            actividad_id=actividad_id_int,
            activo=True
        )
        db.session.add(nueva)

        registrar_log(
            "Creación Catálogo",
            f"Creada Acción: {nombre} (Actividad ID: {actividad_id_int})"
        )
        db.session.commit()

        flash('Acción creada exitosamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error creando Acción '{nombre}': {str(e)}")
        flash('Error al crear el registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='accion'))


@catalogos_bp.route('/accion/editar/<int:id>', methods=['POST'])
def editar_accion(id):
    item = Accion.query.get_or_404(id)
    nuevo_nombre = request.form.get('nombre', '').strip()
    nueva_actividad_id = request.form.get('relacion_id')

    error = nombre_obligatorio(nuevo_nombre, 'accion')
    if error:
        return error

    error = validar_relacion_obligatoria(
        nueva_actividad_id,
        'accion',
        'El nombre y la Actividad padre son obligatorios.'
    )
    if error:
        return error

    try:
        nueva_actividad_id_int = int(nueva_actividad_id)
    except (ValueError, TypeError):
        flash('La Actividad seleccionada no es válida.', 'danger')
        return redirect(url_for('catalogos.index', tab='accion'))

    if accion_duplicada(nuevo_nombre, nueva_actividad_id_int, current_id=id):
        flash(f'El nombre "{nuevo_nombre}" ya está en uso para esa Actividad.', 'danger')
        return redirect(url_for('catalogos.index', tab='accion'))

    try:
        nombre_anterior = item.nombre
        padre_anterior = item.actividad_id

        item.nombre = nuevo_nombre
        item.actividad_id = nueva_actividad_id_int

        registrar_log(
            "Edición Catálogo",
            f"Editada Acción ID {id}: '{nombre_anterior}' -> '{nuevo_nombre}' (Padre {padre_anterior} -> {nueva_actividad_id_int})"
        )
        db.session.commit()

        flash('Registro actualizado correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error editando Acción ID {id}: {str(e)}")
        flash('Error al actualizar el registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='accion'))


@catalogos_bp.route('/accion/toggle/<int:id>', methods=['POST'])
def toggle_accion(id):
    item = Accion.query.get_or_404(id)

    if item.activo and esta_en_uso_en_reportes('accion', item.id):
        flash('No puedes desactivar esta acción porque ya está en uso en reportes técnicos.', 'warning')
        return redirect(url_for('catalogos.index', tab='accion'))

    try:
        item.activo = not item.activo
        estado = "activado" if item.activo else "desactivado"

        registrar_log("Estado Catálogo", f"Acción '{item.nombre}' fue {estado}.")
        db.session.commit()

        flash(f'Registro {estado} correctamente.', 'success')

    except Exception as e:
        db.session.rollback()
        registrar_log_y_confirmar("Error Catálogo", f"Error cambiando estado de Acción ID {id}: {str(e)}")
        flash('Error al cambiar el estado del registro.', 'danger')

    return redirect(url_for('catalogos.index', tab='accion'))