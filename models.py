# models.py
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import pytz

db = SQLAlchemy()

def obtener_hora_chile():
    """Retorna la fecha y hora actual en la zona horaria de Chile."""
    cl_tz = pytz.timezone('America/Santiago')
    return datetime.now(cl_tz)


# ==============================================================================
# 1. ESTRUCTURA ORGANIZACIONAL Y ROLES
# ==============================================================================

class Rol(db.Model):
    __tablename__ = 'roles'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)
    
    usuarios = db.relationship('Usuario', back_populates='rol')

class Establecimiento(db.Model):
    __tablename__ = 'establecimientos'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)
    activo = db.Column(db.Boolean, default=True)
    
    departamentos = db.relationship('Departamento', back_populates='establecimiento', cascade="all, delete-orphan")
    usuarios = db.relationship('Usuario', back_populates='establecimiento')

class Departamento(db.Model):
    __tablename__ = 'departamentos'
    id = db.Column(db.Integer, primary_key=True)
    establecimiento_id = db.Column(db.Integer, db.ForeignKey('establecimientos.id', ondelete='CASCADE'), nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False)
    activo = db.Column(db.Boolean, default=True)

    __table_args__ = (
        db.UniqueConstraint('establecimiento_id', 'nombre', name='uq_departamento_nombre'),
    )

    establecimiento = db.relationship('Establecimiento', back_populates='departamentos')
    secciones = db.relationship('Seccion', back_populates='departamento', cascade="all, delete-orphan")
    usuarios = db.relationship('Usuario', back_populates='departamento')

class Seccion(db.Model):
    __tablename__ = 'secciones'
    id = db.Column(db.Integer, primary_key=True)
    departamento_id = db.Column(db.Integer, db.ForeignKey('departamentos.id', ondelete='CASCADE'), nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False)
    activo = db.Column(db.Boolean, default=True)

    __table_args__ = (
        db.UniqueConstraint('departamento_id', 'nombre', name='uq_seccion_nombre'),
    )

    departamento = db.relationship('Departamento', back_populates='secciones')
    usuarios = db.relationship('Usuario', back_populates='seccion')


# ==============================================================================
# 2. USUARIOS Y AUDITORÍA GENERAL
# ==============================================================================

class Usuario(db.Model, UserMixin):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    nombre_completo = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    activo = db.Column(db.Boolean, default=True)
    
    # Campo clave para la lógica de negocio (sólo aplica si rol es TECNICO)
    puede_asignar = db.Column(db.Boolean, default=False)
    
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_chile)
    cambio_clave_requerido = db.Column(db.Boolean, default=False)
    reset_token = db.Column(db.String(64), nullable=True)
    reset_token_expiracion = db.Column(db.DateTime, nullable=True)

    # Foráneas
    rol_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False, index=True)
    establecimiento_id = db.Column(db.Integer, db.ForeignKey('establecimientos.id'), nullable=True, index=True)
    departamento_id = db.Column(db.Integer, db.ForeignKey('departamentos.id'), nullable=True, index=True)
    seccion_id = db.Column(db.Integer, db.ForeignKey('secciones.id'), nullable=True, index=True)

    # Relaciones
    rol = db.relationship('Rol', back_populates='usuarios')
    establecimiento = db.relationship('Establecimiento', back_populates='usuarios')
    departamento = db.relationship('Departamento', back_populates='usuarios')
    seccion = db.relationship('Seccion', back_populates='usuarios')
    
    logs = db.relationship('Log', back_populates='usuario')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Log(db.Model):
    __tablename__ = 'logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=obtener_hora_chile, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'), nullable=True, index=True)
    usuario_nombre = db.Column(db.String(255))
    accion = db.Column(db.String(255), nullable=False, index=True)
    detalles = db.Column(db.Text)

    usuario = db.relationship('Usuario', back_populates='logs')


# ==============================================================================
# 3. CATÁLOGOS TÉCNICOS NORMALIZADOS
# ==============================================================================

class TipoMantencion(db.Model):
    __tablename__ = 'tipos_mantencion'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)
    activo = db.Column(db.Boolean, default=True)

class Categoria(db.Model):
    __tablename__ = 'categorias'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)
    activo = db.Column(db.Boolean, default=True)

class TipoActividad(db.Model):
    __tablename__ = 'tipos_actividad'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), unique=True, nullable=False)
    activo = db.Column(db.Boolean, default=True)
    
    actividades = db.relationship('Actividad', back_populates='tipo_actividad', cascade="all, delete-orphan")

class Actividad(db.Model):
    __tablename__ = 'actividades'
    id = db.Column(db.Integer, primary_key=True)
    tipo_actividad_id = db.Column(db.Integer, db.ForeignKey('tipos_actividad.id', ondelete='CASCADE'), nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False)
    activo = db.Column(db.Boolean, default=True)

    __table_args__ = (
        db.UniqueConstraint('tipo_actividad_id', 'nombre', name='uq_actividad_nombre'),
    )

    tipo_actividad = db.relationship('TipoActividad', back_populates='actividades')
    acciones = db.relationship('Accion', back_populates='actividad', cascade="all, delete-orphan")

class Accion(db.Model):
    __tablename__ = 'acciones'
    id = db.Column(db.Integer, primary_key=True)
    actividad_id = db.Column(db.Integer, db.ForeignKey('actividades.id', ondelete='CASCADE'), nullable=False, index=True)
    nombre = db.Column(db.String(100), nullable=False)
    activo = db.Column(db.Boolean, default=True)

    __table_args__ = (
        db.UniqueConstraint('actividad_id', 'nombre', name='uq_accion_nombre'),
    )

    actividad = db.relationship('Actividad', back_populates='acciones')


# ==============================================================================
# 4. GESTIÓN DE TICKETS
# ==============================================================================

class EstadoTicket(db.Model):
    __tablename__ = 'estados_ticket'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), unique=True, nullable=False)
    descripcion = db.Column(db.String(255))
    
    tickets = db.relationship('Ticket', back_populates='estado')


class Ticket(db.Model):
    __tablename__ = 'tickets'
    id = db.Column(db.Integer, primary_key=True)
    
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)
    tecnico_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True, index=True)
    estado_id = db.Column(db.Integer, db.ForeignKey('estados_ticket.id'), nullable=False, index=True)
    
    asunto = db.Column(db.String(255), nullable=False)
    descripcion = db.Column(db.Text, nullable=False)
    
    fecha_creacion = db.Column(db.DateTime, default=obtener_hora_chile, index=True)
    fecha_actualizacion = db.Column(db.DateTime, default=obtener_hora_chile, onupdate=obtener_hora_chile)
    fecha_finalizacion = db.Column(db.DateTime, nullable=True)

    # Relaciones
    solicitante = db.relationship('Usuario', foreign_keys=[usuario_id], backref='tickets_creados')
    tecnico = db.relationship('Usuario', foreign_keys=[tecnico_id], backref='tickets_asignados')
    estado = db.relationship('EstadoTicket', back_populates='tickets')
    
    # ⚠️ Relación 1 a 1 ESTRICTA con el reporte técnico
    reporte_tecnico = db.relationship('ReporteTecnico', back_populates='ticket', uselist=False, cascade="all, delete-orphan")
    
    adjuntos = db.relationship('Adjunto', back_populates='ticket', cascade="all, delete-orphan")
    historial = db.relationship('HistorialTicket', back_populates='ticket', order_by="desc(HistorialTicket.fecha)", cascade="all, delete-orphan")


# ==============================================================================
# 5. REPORTE TÉCNICO (1 a 1 ESTRICTO)
# ==============================================================================

class ReporteTecnico(db.Model):
    __tablename__ = 'reporte_tecnico'
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, unique=True)
    
    fecha = db.Column(db.Date, nullable=False)
    hora = db.Column(db.Time, nullable=False)
    
    tipo_mantencion_id = db.Column(db.Integer, db.ForeignKey('tipos_mantencion.id'), nullable=False, index=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categorias.id'), nullable=False, index=True)
    categoria_otro = db.Column(db.String(255), nullable=True)
    
    tipo_actividad_id = db.Column(db.Integer, db.ForeignKey('tipos_actividad.id'), nullable=True)
    actividad_id = db.Column(db.Integer, db.ForeignKey('actividades.id'), nullable=True)
    accion_id = db.Column(db.Integer, db.ForeignKey('acciones.id'), nullable=True)
    
    observaciones_generales = db.Column(db.Text)

    # Relaciones
    ticket = db.relationship('Ticket', back_populates='reporte_tecnico')
    tipo_mantencion = db.relationship('TipoMantencion')
    categoria = db.relationship('Categoria')
    tipo_actividad = db.relationship('TipoActividad')
    actividad = db.relationship('Actividad')
    accion = db.relationship('Accion')


# ==============================================================================
# 6. ADJUNTOS
# ==============================================================================

class Adjunto(db.Model):
    __tablename__ = 'adjuntos'
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)
    
    nombre_archivo = db.Column(db.String(255), nullable=False)
    ruta_archivo = db.Column(db.String(500), nullable=False)
    tipo_mime = db.Column(db.String(100))
    
    fase = db.Column(db.Enum('SOLICITUD', 'RESOLUCION'), nullable=False, index=True)
    hash_archivo = db.Column(db.String(128), nullable=True)
    fecha_subida = db.Column(db.DateTime, default=obtener_hora_chile)

    ticket = db.relationship('Ticket', back_populates='adjuntos')
    usuario = db.relationship('Usuario')


# ==============================================================================
# 7. HISTORIAL DE TICKETS (AUDITORÍA ESTRUCTURADA)
# ==============================================================================

class HistorialTicket(db.Model):
    __tablename__ = 'historial_tickets'
    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id', ondelete='CASCADE'), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)
    
    accion = db.Column(db.String(100), nullable=False)
    detalle = db.Column(db.JSON, nullable=True)
    fecha = db.Column(db.DateTime, default=obtener_hora_chile, index=True)

    ticket = db.relationship('Ticket', back_populates='historial')
    usuario = db.relationship('Usuario')

    @property
    def estilo_visual(self):
        """
        Retorna configuración visual (colores e iconos de Tailwind) para el frontend,
        manteniendo el patrón de auditoría estandarizado.
        """
        config = {
            'color_bg': 'bg-gray-100',
            'color_text': 'text-gray-600',
            'icono': 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z', # Default (Info)
            'titulo': self.accion.replace('_', ' ').title()
        }

        if self.accion == 'CREACION':
            config.update({
                'color_bg': 'bg-purple-100',
                'color_text': 'text-purple-600',
                'icono': 'M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z', # Document Add
                'titulo': 'Ticket Creado'
            })
        elif self.accion == 'ASIGNACION':
            config.update({
                'color_bg': 'bg-blue-100',
                'color_text': 'text-blue-600',
                'icono': 'M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z', # User Add
                'titulo': 'Técnico Asignado'
            })
        elif self.accion == 'CONFIRMACION':
            config.update({
                'color_bg': 'bg-yellow-100',
                'color_text': 'text-yellow-600',
                'icono': 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4', # Clipboard Check
                'titulo': 'En Proceso'
            })
        elif self.accion == 'FINALIZACION':
            config.update({
                'color_bg': 'bg-green-100',
                'color_text': 'text-green-600',
                'icono': 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z', # Check Circle
                'titulo': 'Ticket Finalizado'
            })
        elif self.accion == 'ADJUNTO_SOLICITUD' or self.accion == 'ADJUNTO_RESOLUCION':
            config.update({
                'color_bg': 'bg-indigo-100',
                'color_text': 'text-indigo-600',
                'icono': 'M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13', # Paperclip
                'titulo': 'Archivo Adjuntado'
            })

        return config