import os
import qrcode
import io
import base64
from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image, HRFlowable
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.pdfgen import canvas
from utils.gst_calculator import number_to_words

BRAND_TEAL = colors.HexColor('#00897B')
BRAND_DARK = colors.HexColor('#1a1a2e')
BRAND_LIGHT = colors.HexColor('#f0faf9')
BRAND_ACCENT = colors.HexColor('#00BFA5')


def generate_upi_qr(upi_id: str, amount: float, name: str, invoice_no: str) -> str:
    """Generate UPI QR code and return as base64 PNG"""
    upi_string = f"upi://pay?pa={upi_id}&pn={name}&am={amount}&tn=Invoice-{invoice_no}&cu=INR"
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(upi_string)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#00897B", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode()


def generate_invoice_qr(invoice_url: str) -> str:
    """Generate verification QR for invoice URL"""
    qr = qrcode.QRCode(version=1, box_size=5, border=2)
    qr.add_data(invoice_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1a1a2e", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode()


def generate_invoice_pdf(invoice_data: dict, output_path: str) -> str:
    """
    Generate a professional GST-compliant invoice PDF.
    invoice_data keys: seller, client, invoice, items, gst, upi_id, base_url
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=15*mm,
        leftMargin=15*mm,
        topMargin=10*mm,
        bottomMargin=15*mm
    )

    styles = getSampleStyleSheet()
    story = []

    # ── HEADER ────────────────────────────────────────────────────
    header_data = [
        [
            Paragraph(f"""
                <font name="Helvetica-Bold" size="22" color="#00897B">GST</font><font name="Helvetica-Bold" size="22" color="#1a1a2e">Link</font><br/>
                <font size="8" color="#666666">GST Invoice Generator</font>
            """, styles['Normal']),
            Paragraph(f"""
                <para align="right">
                <font name="Helvetica-Bold" size="16" color="#1a1a2e">TAX INVOICE</font><br/>
                <font size="9" color="#00897B">#{invoice_data['invoice']['number']}</font><br/>
                <font size="8" color="#888888">Date: {invoice_data['invoice']['date']}</font><br/>
                <font size="8" color="#888888">Due: {invoice_data['invoice']['due_date']}</font>
                </para>
            """, ParagraphStyle('right', parent=styles['Normal'], alignment=TA_RIGHT))
        ]
    ]
    header_table = Table(header_data, colWidths=[90*mm, 90*mm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width="100%", thickness=2, color=BRAND_TEAL))
    story.append(Spacer(1, 5*mm))

    # ── FROM / TO ──────────────────────────────────────────────────
    s = invoice_data['seller']
    c = invoice_data['client']

    def party_block(title, name, gstin, address, state, email='', phone=''):
        lines = [f"<font name='Helvetica-Bold' color='#00897B' size='8'>{title}</font>",
                 f"<font name='Helvetica-Bold' size='11'>{name}</font>"]
        if gstin:
            lines.append(f"<font size='8' color='#555'>GSTIN: {gstin}</font>")
        if address:
            lines.append(f"<font size='8' color='#555'>{address}</font>")
        if state:
            lines.append(f"<font size='8' color='#555'>State: {state}</font>")
        if email:
            lines.append(f"<font size='8' color='#555'>{email}</font>")
        if phone:
            lines.append(f"<font size='8' color='#555'>{phone}</font>")
        return Paragraph('<br/>'.join(lines), styles['Normal'])

    party_data = [[
        party_block("FROM (Supplier)", s.get('name',''), s.get('gstin',''), s.get('address',''), s.get('state',''), s.get('email',''), s.get('phone','')),
        party_block("TO (Recipient)", c.get('name',''), c.get('gstin',''), c.get('address',''), c.get('state',''), c.get('email',''), c.get('phone',''))
    ]]
    party_table = Table(party_data, colWidths=[90*mm, 90*mm])
    party_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), colors.HexColor('#f0faf9')),
        ('BACKGROUND', (1,0), (1,0), colors.HexColor('#fff8f0')),
        ('BOX', (0,0), (0,0), 0.5, colors.HexColor('#00897B')),
        ('BOX', (1,0), (1,0), 0.5, colors.HexColor('#FF8F00')),
        ('LEFTPADDING', (0,0), (-1,-1), 8),
        ('RIGHTPADDING', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(party_table)
    story.append(Spacer(1, 5*mm))

    # ── LINE ITEMS ─────────────────────────────────────────────────
    inv = invoice_data['invoice']
    gst = invoice_data['gst']

    item_header = ['#', 'Description', 'SAC/HSN', 'Rate (₹)', 'GST%', 'Amount (₹)']
    item_rows = [item_header]

    desc = inv.get('description', 'Professional Services')
    hsn = inv.get('hsn_sac', '998312')
    base = gst['base_amount']
    rate_pct = gst['gst_rate']

    item_rows.append(['1', Paragraph(desc, styles['Normal']), hsn, f"{base:,.2f}", f"{rate_pct}%", f"{base:,.2f}"])

    items_table = Table(item_rows, colWidths=[10*mm, 70*mm, 22*mm, 28*mm, 16*mm, 28*mm])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), BRAND_DARK),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 8),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('ALIGN', (1,1), (1,-1), 'LEFT'),
        ('FONTSIZE', (0,1), (-1,-1), 9),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor('#f9f9f9')]),
        ('GRID', (0,0), (-1,-1), 0.3, colors.HexColor('#dddddd')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 4*mm))

    # ── GST SUMMARY ────────────────────────────────────────────────
    summary_rows = [['Taxable Amount', f"₹{base:,.2f}"]]

    if gst['gst_type'] == 'CGST_SGST':
        summary_rows.append([f"CGST @ {rate_pct/2}%", f"₹{gst['cgst']:,.2f}"])
        summary_rows.append([f"SGST @ {rate_pct/2}%", f"₹{gst['sgst']:,.2f}"])
    else:
        summary_rows.append([f"IGST @ {rate_pct}%", f"₹{gst['igst']:,.2f}"])

    summary_rows.append(['', ''])
    summary_rows.append([Paragraph('<font name="Helvetica-Bold" size="11">TOTAL</font>', styles['Normal']),
                          Paragraph(f'<font name="Helvetica-Bold" size="11" color="#00897B">₹{gst["total"]:,.2f}</font>', styles['Normal'])])

    summary_table = Table(summary_rows, colWidths=[130*mm, 50*mm])
    summary_table.setStyle(TableStyle([
        ('ALIGN', (1,0), (1,-1), 'RIGHT'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('LINEBELOW', (0,-2), (-1,-2), 1, BRAND_TEAL),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#f0faf9')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('RIGHTPADDING', (1,0), (1,-1), 8),
    ]))
    story.append(summary_table)

    # Amount in words
    words = number_to_words(gst['total'])
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(f"<font size='8' color='#555'>Amount in words: <i>{words}</i></font>", styles['Normal']))
    story.append(Spacer(1, 5*mm))

    # ── QR CODES ──────────────────────────────────────────────────
    upi_id = invoice_data.get('upi_id', '')
    base_url = invoice_data.get('base_url', '')
    public_token = invoice_data.get('public_token', '')
    invoice_no = inv['number']

    qr_left = []
    qr_right = []

    if upi_id:
        upi_qr_b64 = generate_upi_qr(upi_id, gst['total'], s.get('name', 'GSTLink'), invoice_no)
        upi_img_data = base64.b64decode(upi_qr_b64)
        upi_buf = io.BytesIO(upi_img_data)
        upi_img = Image(upi_buf, width=30*mm, height=30*mm)
        qr_left = [
            upi_img,
            Paragraph(f"<para align='center'><font name='Helvetica-Bold' size='8'>Pay via UPI</font><br/><font size='7' color='#888'>{upi_id}</font></para>", styles['Normal'])
        ]

    if base_url and public_token:
        inv_url = f"{base_url}/invoice/view/{public_token}"
        inv_qr_b64 = generate_invoice_qr(inv_url)
        inv_img_data = base64.b64decode(inv_qr_b64)
        inv_buf = io.BytesIO(inv_img_data)
        inv_img = Image(inv_buf, width=30*mm, height=30*mm)
        qr_right = [
            inv_img,
            Paragraph("<para align='center'><font name='Helvetica-Bold' size='8'>Verify Invoice</font><br/><font size='7' color='#888'>Scan to verify</font></para>", styles['Normal'])
        ]

    if qr_left or qr_right:
        left_cell = qr_left if qr_left else ['']
        right_cell = qr_right if qr_right else ['']
        qr_data = [[left_cell[0] if qr_left else '', right_cell[0] if qr_right else '']]
        qr_table = Table(qr_data, colWidths=[90*mm, 90*mm])
        qr_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(qr_table)
        # Labels row
        label_data = [[left_cell[1] if len(qr_left) > 1 else '', right_cell[1] if len(qr_right) > 1 else '']]
        label_table = Table(label_data, colWidths=[90*mm, 90*mm])
        label_table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER')]))
        story.append(label_table)
        story.append(Spacer(1, 4*mm))

    # ── NOTES & FOOTER ────────────────────────────────────────────
    if invoice_data.get('notes'):
        story.append(Paragraph(f"<font name='Helvetica-Bold' size='8'>Notes:</font> <font size='8' color='#555'>{invoice_data['notes']}</font>", styles['Normal']))
        story.append(Spacer(1, 3*mm))

    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#cccccc')))
    story.append(Spacer(1, 3*mm))
    story.append(Paragraph(
        "<para align='center'><font size='7' color='#aaaaaa'>This is a computer-generated invoice. Generated via GSTLink.in | Subject to jurisdiction of courts in India.</font></para>",
        styles['Normal']
    ))

    doc.build(story)
    return output_path
