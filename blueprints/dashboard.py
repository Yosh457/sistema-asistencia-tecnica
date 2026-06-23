# blueprints/dashboard.py

import calendar
from datetime import timedelta
from flask import Blueprint, render_template, jsonify, abort, request
from flask_login import login_required, current_user
from sqlalchemy import func

# Modelos necesarios para las agregaciones
from models import db, Ticket, EstadoTicket, Usuario, ReporteTecnico, Categoria, Establecimiento
from utils import obtener_hora_chile

# ==========================================================
# CONFIGURACIÓN DEL BLUEPRINT
# ==========================================================

dashboard_bp = Blueprint(
    'dashboard',
    __name__,
    template_folder='../templates',
    url_prefix='/dashboard'
)

# ==========================================================
# PROTECCIÓN GLOBAL Y CONTROL DE ACCESO
# ==========================================================

@dashboard_bp.before_request
@login_required
def before_request():
    """
    Solo permitimos el acceso al Dashboard a:
    - Administradores
    - Técnicos con permiso de asignar (Gestores TICs)
    """
    if current_user.rol.nombre == 'ADMIN':
        return
    
    if current_user.rol.nombre == 'TECNICO' and current_user.puede_asignar:
        return
        
    abort(403)


# ==========================================================
# HELPERS DE FECHAS (OPTIMIZACIÓN DE ÍNDICES)
# ==========================================================

def obtener_rango_fechas(periodo):
    """
    Calcula el inicio y fin de un período para usar en consultas SQL con 
    operadores de rango (>= y <). Esto permite al motor de la BD 
    utilizar eficientemente los índices de las columnas de fecha.
    """
    ahora = obtener_hora_chile().replace(tzinfo=None)
    
    if periodo == 'mes':
        inicio = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        ultimo_dia = calendar.monthrange(ahora.year, ahora.month)[1]
        fin = inicio + timedelta(days=ultimo_dia)
        return inicio, fin
        
    elif periodo == 'anio':
        inicio = ahora.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        fin = ahora.replace(year=ahora.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return inicio, fin
        
    # 'historico' u otro valor devuelve sin límites
    return None, None


# ==========================================================
# 1. RUTA PRINCIPAL: CÁLCULO DE KPIs
# ==========================================================

@dashboard_bp.route('/')
def index():
    """
    Renderiza la vista principal del dashboard y calcula
    los KPIs dinámicos basados en el período seleccionado.
    """
    periodo = request.args.get('periodo', 'mes')
    inicio, fin = obtener_rango_fechas(periodo)

    # Queries base
    q_ingresados = Ticket.query
    q_resueltos = Ticket.query.join(EstadoTicket).filter(EstadoTicket.nombre == 'FINALIZADO')

    # Aplicamos filtro de fechas si aplica (para optimizar uso de índices)
    if inicio and fin:
        q_ingresados = q_ingresados.filter(Ticket.fecha_creacion >= inicio, Ticket.fecha_creacion < fin)
        q_resueltos = q_resueltos.filter(Ticket.fecha_finalizacion >= inicio, Ticket.fecha_finalizacion < fin)

    total_ingresados = q_ingresados.count()
    total_resueltos = q_resueltos.count()

    # Cálculo de Tasa de Resolución del Período
    tasa_resolucion = 0.0
    if total_ingresados > 0:
        # Usamos total ingresados vs resueltos. Puede superar 100% si se resuelve backlog anterior, 
        # lo cual es un excelente indicador de limpieza de mesa de ayuda.
        tasa_resolucion = round((total_resueltos / total_ingresados) * 100, 1)

    # ---------------------------------------------------------
    # KPIs Estáticos (Backlog actual)
    # ---------------------------------------------------------
    # Independiente del filtro de fecha, un ticket "CREADO" hoy es trabajo pendiente HOY.
    pendientes = Ticket.query.join(EstadoTicket).filter(EstadoTicket.nombre == 'CREADO').count()
    
    en_ejecucion = Ticket.query.join(EstadoTicket).filter(
        EstadoTicket.nombre.in_(['ASIGNADO', 'EN_PROCESO'])
    ).count()

    kpis = {
        'ingresados': total_ingresados,
        'resueltos': total_resueltos,
        'pendientes': pendientes,
        'en_ejecucion': en_ejecucion,
        'tasa_resolucion': tasa_resolucion
    }

    return render_template('admin/dashboard.html', kpis=kpis, periodo_actual=periodo)


# ==========================================================
# 2. ENDPOINT API: DATOS PARA CHART.JS
# ==========================================================

@dashboard_bp.route('/api/datos')
def api_datos():
    """
    Devuelve los datos procesados en formato JSON filtrados por período.
    Se cruza con los requerimientos de la UI para Chart.js.
    """
    periodo = request.args.get('periodo', 'mes')
    inicio, fin = obtener_rango_fechas(periodo)
    
    # ---------------------------------------------------------
    # Gráfico 1: Distribución por Estado (Del período)
    # ---------------------------------------------------------
    q_est = db.session.query(EstadoTicket.nombre, func.count(Ticket.id)).join(Ticket)
    
    if inicio and fin:
        q_est = q_est.filter(Ticket.fecha_creacion >= inicio, Ticket.fecha_creacion < fin)
        
    estados_query = q_est.group_by(EstadoTicket.nombre).all()
    
    grafico_estados = {
        'labels': [row[0] for row in estados_query],
        'data': [row[1] for row in estados_query]
    }

    # ---------------------------------------------------------
    # Gráfico 2: Top Categorías de Problemas
    # ---------------------------------------------------------
    q_cat = db.session.query(Categoria.nombre, func.count(ReporteTecnico.id))\
        .join(ReporteTecnico, Categoria.id == ReporteTecnico.categoria_id)\
        .join(Ticket, Ticket.id == ReporteTecnico.ticket_id)
        
    if inicio and fin:
        # Filtramos por cuándo se finalizó/reportó
        q_cat = q_cat.filter(Ticket.fecha_finalizacion >= inicio, Ticket.fecha_finalizacion < fin)
        
    categorias_query = q_cat.group_by(Categoria.nombre)\
        .order_by(func.count(ReporteTecnico.id).desc())\
        .limit(5).all()

    grafico_categorias = {
        'labels': [row[0] for row in categorias_query],
        'data': [row[1] for row in categorias_query]
    }

    # ---------------------------------------------------------
    # Gráfico 3: Tickets por Establecimiento (Nuevo)
    # ---------------------------------------------------------
    q_estab = db.session.query(Establecimiento.nombre, func.count(Ticket.id))\
        .join(Usuario, Ticket.usuario_id == Usuario.id)\
        .join(Establecimiento, Usuario.establecimiento_id == Establecimiento.id)
        
    if inicio and fin:
        q_estab = q_estab.filter(Ticket.fecha_creacion >= inicio, Ticket.fecha_creacion < fin)
        
    estab_query = q_estab.group_by(Establecimiento.nombre)\
        .order_by(func.count(Ticket.id).desc())\
        .limit(5).all()

    grafico_establecimientos = {
        'labels': [row[0][:20] + "..." if len(row[0]) > 20 else row[0] for row in estab_query], # Truncamos nombres largos
        'data': [row[1] for row in estab_query]
    }

    # ---------------------------------------------------------
    # Retorno General
    # ---------------------------------------------------------
    return jsonify({
        'estados': grafico_estados,
        'categorias': grafico_categorias,
        'establecimientos': grafico_establecimientos
    })