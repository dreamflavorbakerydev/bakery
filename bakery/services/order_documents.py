"""Download complete, historical order documents without changing business records."""
from io import BytesIO
from pathlib import Path
import re
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def order_pdf(order):
    # ReportLab ships these fonts; no remote assets or customer data leave the app.
    fonts = Path(reportlab.__file__).parent / 'fonts'
    if 'OrderVera' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('OrderVera', str(fonts / 'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('OrderVeraBold', str(fonts / 'VeraBd.ttf')))
    body = ParagraphStyle('OrderBody', fontName='OrderVera', fontSize=9, leading=13, spaceAfter=4)
    heading = ParagraphStyle('OrderHeading', parent=body, fontName='OrderVeraBold', fontSize=20, leading=26)
    bold = ParagraphStyle('OrderBold', parent=body, fontName='OrderVeraBold')
    right = ParagraphStyle('OrderRight', parent=body, alignment=TA_RIGHT)

    def text(value, style=body):
        return Paragraph(escape(str(value or '—')).replace('\n', '<br/>'), style)

    def day(value):
        return value.strftime('%A, %B %d, %Y') if value else '—'

    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, rightMargin=36, leftMargin=36,
        topMargin=36, bottomMargin=36, title=f'Order {order.order_number}', author='Bakery')
    story = [text('BAKERY · ORDER DETAILS', bold), text(order.customer_location.location_name, heading),
        text(f'{order.customer.customer_name} · {order.order_number}'),
        text(f'Status: {order.get_status_display()}'), Spacer(1, 12)]
    if order.requires_approval:
        story.append(text('This delivery is past its cutoff. Bakery approval is required before it enters the bake totals.'))
    details = [('Delivery date', day(order.requested_delivery_date)),
        ('Production begins', day(order.required_production_date)),
        ('Reference / PO', order.customer_po_number), ('Notes', order.notes)]
    for label, value in details:
        story.extend([text(label, bold), text(value)])
    story.append(Spacer(1, 14))
    rows = [[text(label, bold) for label in ['Product', 'Quantity', 'Unit price', 'Total', 'Bake date']]]
    for line in order.items.all():
        quantity = f'{line.quantity} {line.unit_of_measure}'
        if line.pack_size > 1:
            quantity += f' of {line.pack_size}'
        identifier = f'{line.customer_sku or line.upc} · {line.product.internal_product_code}'
        rows.append([text(f'{line.product_name}\n{identifier}'), text(quantity),
            text(f'${line.unit_price:,.2f}', right), text(f'${line.line_total:,.2f}', right),
            text(line.required_production_date.strftime('%b %d, %Y'))])
    table = Table(rows, colWidths=[204, 87, 72, 72, 105], repeatRows=1, hAlign='LEFT')
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f6f0')),
        ('LINEBELOW', (0, 0), (-1, -1), .4, colors.HexColor('#dfe5da')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 9), ('BOTTOMPADDING', (0, 0), (-1, -1), 9),
    ]))
    story.extend([table, Spacer(1, 18), text(f'Order total: ${order.total:,.2f}', heading)])
    doc.build(story)
    return output.getvalue()


def download_orders(orders):
    def filename(order):
        reference = re.sub(r'[^A-Za-z0-9_-]', '_', order.order_number) or str(order.pk)
        return f'order-{reference}.pdf'

    if len(orders) == 1:
        return order_pdf(orders[0]), 'application/pdf', filename(orders[0])
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        for order in orders:
            archive.writestr(filename(order), order_pdf(order))
    return output.getvalue(), 'application/zip', 'selected-orders.zip'
