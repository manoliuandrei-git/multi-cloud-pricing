"""
Export Utilities
Handles exporting pricing comparisons to PDF and CSV
"""
import csv
import json
from io import StringIO, BytesIO
from typing import List, Dict
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_CENTER, TA_LEFT

from utils.logger import get_logger

logger = get_logger(__name__)


def export_to_csv(services: List[Dict], selected_ids: List[int] = None) -> str:
    """
    Export services to CSV format

    Args:
        services: List of service dictionaries
        selected_ids: Optional list of IDs to export (None = export all)

    Returns:
        CSV string
    """
    # Filter selected services if IDs provided
    if selected_ids:
        services = [s for s in services if s.get('id') in selected_ids]

    if not services:
        return "No services to export"

    # Create CSV in memory
    output = StringIO()
    writer = csv.writer(output)

    # Write header
    headers = [
        'Cloud Provider',
        'Service Name',
        'Instance Type',
        'Region',
        'Price per Hour (USD)',
        'Price per Month (USD)',
        'vCPU',
        'Memory',
        'Storage',
        'Features'
    ]
    writer.writerow(headers)

    # Write data rows
    for service in services:
        specs = service.get('specifications', {})
        if isinstance(specs, str):
            try:
                specs = json.loads(specs)
            except:
                specs = {}

        row = [
            service.get('cloud_provider', ''),
            service.get('service_name', ''),
            service.get('instance_type', ''),
            service.get('region', ''),
            service.get('price_per_hour', ''),
            service.get('price_per_month', ''),
            specs.get('vcpu', ''),
            specs.get('memory', specs.get('memory_gb', '')),
            specs.get('storage', specs.get('storage_gb', '')),
            service.get('features', '')
        ]
        writer.writerow(row)

    csv_content = output.getvalue()
    output.close()

    logger.info(f"Exported {len(services)} services to CSV")
    return csv_content


def export_to_pdf(
    services: List[Dict],
    selected_ids: List[int] = None,
    user_requirements: Dict = None,
    recommendations: List[Dict] = None
) -> bytes:
    """
    Export services to PDF format

    Args:
        services: List of service dictionaries
        selected_ids: Optional list of IDs to export (None = export all)
        user_requirements: Optional user requirements to include
        recommendations: Optional AI recommendations to include

    Returns:
        PDF bytes
    """
    # Filter selected services if IDs provided
    if selected_ids:
        services = [s for s in services if s.get('id') in selected_ids]

    if not services:
        return b"No services to export"

    # Create PDF in memory
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)

    # Container for PDF elements
    elements = []

    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1f77b4'),
        spaceAfter=30,
        alignment=TA_CENTER
    )

    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#2ca02c'),
        spaceAfter=12,
        spaceBefore=12
    )

    # Title
    title = Paragraph("Multi-Cloud Pricing Comparison Report", title_style)
    elements.append(title)

    # Timestamp
    timestamp = Paragraph(
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        styles['Normal']
    )
    elements.append(timestamp)
    elements.append(Spacer(1, 0.3*inch))

    # User Requirements (if provided)
    if user_requirements:
        elements.append(Paragraph("User Requirements", heading_style))

        req_text = "<br/>".join([
            f"<b>{key}:</b> {value}"
            for key, value in user_requirements.items()
            if value and key != 'specifications'
        ])

        if user_requirements.get('specifications'):
            specs = user_requirements['specifications']
            req_text += "<br/><b>Specifications:</b><br/>" + "<br/>".join([
                f"  • {k}: {v}" for k, v in specs.items()
            ])

        elements.append(Paragraph(req_text, styles['Normal']))
        elements.append(Spacer(1, 0.2*inch))

    # AI Recommendations (if provided)
    if recommendations:
        elements.append(Paragraph("AI Recommendations", heading_style))

        for i, rec in enumerate(recommendations[:3], 1):
            service_info = rec.get('service_info', {})
            reason = rec.get('reason', '')

            rec_text = f"""
            <b>{i}. {service_info.get('cloud_provider')} - {service_info.get('service_name')}</b><br/>
            Price: ${service_info.get('price_per_month', 0):.2f}/month<br/>
            Reason: {reason}
            """

            elements.append(Paragraph(rec_text, styles['Normal']))
            elements.append(Spacer(1, 0.1*inch))

        elements.append(Spacer(1, 0.2*inch))

    # Services Table
    elements.append(Paragraph("Pricing Comparison", heading_style))

    # Prepare table data
    table_data = [[
        'Provider',
        'Service',
        'Type',
        'Region',
        'Price/Month'
    ]]

    for service in services[:50]:  # Limit to 50 services for PDF
        row = [
            service.get('cloud_provider', ''),
            service.get('service_name', '')[:30],  # Truncate long names
            service.get('instance_type', '')[:20],
            service.get('region', ''),
            f"${service.get('price_per_month', 0):.2f}"
        ]
        table_data.append(row)

    # Create table
    table = Table(table_data, colWidths=[1*inch, 2*inch, 1.5*inch, 1.5*inch, 1*inch])

    # Style table
    table.setStyle(TableStyle([
        # Header style
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4CAF50')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),

        # Data style
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),  # Align price column right
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),

        # Alternating row colors
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
    ]))

    elements.append(table)
    elements.append(Spacer(1, 0.3*inch))

    # Summary statistics
    if services:
        elements.append(Paragraph("Summary Statistics", heading_style))

        prices = [s.get('price_per_month', 0) for s in services if s.get('price_per_month')]
        total_price = sum(s.get('price_per_month', 0) for s in services if s.get('id') in (selected_ids or []))

        summary_text = f"""
        <b>Total Services Found:</b> {len(services)}<br/>
        <b>Lowest Price:</b> ${min(prices):.2f}/month<br/>
        <b>Highest Price:</b> ${max(prices):.2f}/month<br/>
        <b>Average Price:</b> ${sum(prices)/len(prices):.2f}/month<br/>
        """

        if selected_ids:
            summary_text += f"<b>Total Cost (Selected):</b> ${total_price:.2f}/month<br/>"

        elements.append(Paragraph(summary_text, styles['Normal']))

    # Footer
    elements.append(Spacer(1, 0.3*inch))
    footer_text = """
    <i>Generated by Multi-Cloud Pricing Calculator</i><br/>
    <i>Powered by Claude AI (Anthropic)</i>
    """
    elements.append(Paragraph(footer_text, styles['Normal']))

    # Build PDF
    doc.build(elements)

    # Get PDF bytes
    pdf_bytes = buffer.getvalue()
    buffer.close()

    logger.info(f"Exported {len(services)} services to PDF")
    return pdf_bytes


def create_export_filename(export_type: str) -> str:
    """
    Create a timestamped filename for export

    Args:
        export_type: 'csv' or 'pdf'

    Returns:
        Filename string
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return f"cloud_pricing_comparison_{timestamp}.{export_type}"
