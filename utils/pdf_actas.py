# utils/pdf_actas.py
import os
from reportlab.lib.pagesizes import LETTER
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.enums import TA_CENTER, TA_LEFT

def generar_informe_tecnico_pdf(ticket, output_filename):
    """Genera el PDF oficial del Reporte Técnico."""
    output_dir = os.path.dirname(output_filename)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    doc = SimpleDocTemplate(
        output_filename, pagesize=LETTER, rightMargin=50, leftMargin=50, topMargin=30, bottomMargin=30
    )
    elements = []
    styles = getSampleStyleSheet()

    # --- LOGOS ---
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    logo1_path = os.path.join(base_dir, 'static', 'img', 'Logo_Red_APS_2.png')
    logo2_path = os.path.join(base_dir, 'static', 'img', 'logoMaho.png')

    if os.path.exists(logo1_path) and os.path.exists(logo2_path):
        img1 = Image(logo1_path, width=120, height=50)
        img2 = Image(logo2_path, width=120, height=50)
        img1.hAlign, img2.hAlign = 'LEFT', 'RIGHT'
        t_logos = Table([[img1, '', img2]], colWidths=[200, 140, 200])
        t_logos.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'LEFT'), ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('TOPPADDING', (0, 0), (-1, -1), 0),
        ]))
        elements.append(t_logos)
        elements.append(Spacer(1, 10))

    # --- ESTILOS ---
    estilo_titulo = ParagraphStyle('TituloActa', parent=styles['Heading1'], alignment=TA_CENTER, fontSize=16, spaceAfter=20, textColor=colors.HexColor('#275c80'))
    estilo_subtitulo = ParagraphStyle('Subtitulo', parent=styles['Heading2'], fontSize=12, spaceBefore=15, spaceAfter=10, textColor=colors.HexColor('#444444'))
    estilo_normal = styles['Normal']

    # --- CABECERA ---
    elements.append(Paragraph(f"INFORME DE ASISTENCIA TÉCNICA TKT-{ticket.id}", estilo_titulo))

    data_general = [
        ['Ticket ID:', f"TKT-{ticket.id}"],
        ['Fecha Solicitud:', ticket.fecha_creacion.strftime('%d/%m/%Y %H:%M')],
        ['Solicitante:', ticket.solicitante.nombre_completo],
        ['Unidad:', ticket.solicitante.departamento.nombre if ticket.solicitante.departamento else 'No registrada'],
        ['Estado Actual:', ticket.estado.nombre],
    ]
    t_general = Table(data_general, colWidths=[120, 300])
    t_general.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#f0f0f0')),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(t_general)

    # --- SOLICITUD ---
    elements.append(Paragraph("1. Detalle de la Solicitud", estilo_subtitulo))
    elements.append(Paragraph(f"<b>Asunto:</b> {ticket.asunto}", estilo_normal))
    elements.append(Spacer(1, 5))
    elements.append(Paragraph("<b>Descripción del Problema:</b>", estilo_normal))
    desc_str = ticket.descripcion.replace('\n', '<br/>')
    elements.append(Paragraph(desc_str, estilo_normal))

    # --- REPORTE TÉCNICO ---
    elements.append(Paragraph("2. Resolución Técnica", estilo_subtitulo))
    if ticket.reporte_tecnico:
        rt = ticket.reporte_tecnico
        cat_txt = rt.categoria.nombre if rt.categoria else '-'
        if rt.categoria_otro: cat_txt += f" ({rt.categoria_otro})"
        
        data_rt = [
            ['Técnico Asignado:', ticket.tecnico.nombre_completo if ticket.tecnico else '-'],
            ['Fecha Resolución:', rt.fecha.strftime('%d/%m/%Y')],
            ['Tipo Mantención:', rt.tipo_mantencion.nombre if rt.tipo_mantencion else '-'],
            ['Categoría:', cat_txt],
            ['Actividad:', rt.actividad.nombre if rt.actividad else '-'],
            ['Acción Realizada:', rt.accion.nombre if rt.accion else '-'],
        ]
        t_rt = Table(data_rt, colWidths=[120, 300])
        t_rt.setStyle(TableStyle([('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey), ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold')]))
        elements.append(t_rt)
        
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("<b>Observaciones Técnicas:</b>", estilo_normal))
        obs_str = (rt.observaciones_generales or 'Sin observaciones').replace('\n', '<br/>')
        elements.append(Paragraph(obs_str, estilo_normal))
    else:
        elements.append(Paragraph("Aún no se ha generado el reporte técnico.", estilo_normal))

    # --- TRAZABILIDAD ---
    elements.append(Paragraph("3. Historial de Movimientos", estilo_subtitulo))
    if ticket.historial:
        data_hist = [[Paragraph("<b>Fecha/Hora</b>", estilo_normal), Paragraph("<b>Usuario</b>", estilo_normal), Paragraph("<b>Acción</b>", estilo_normal)]]
        
        # Invertimos para que el PDF muestre lo más antiguo primero
        historial_asc = sorted(ticket.historial, key=lambda x: x.fecha) 
        
        for h in historial_asc:
            data_hist.append([
                Paragraph(h.fecha.strftime("%d/%m/%Y %H:%M"), estilo_normal),
                Paragraph(h.usuario.nombre_completo if h.usuario else 'Sistema', estilo_normal),
                Paragraph(h.accion.replace('_', ' ').title(), estilo_normal)
            ])
            
        t_hist = Table(data_hist, colWidths=[100, 150, 170], repeatRows=1)
        t_hist.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EFF6FF')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
        ]))
        elements.append(t_hist)

    doc.build(elements)
    return True