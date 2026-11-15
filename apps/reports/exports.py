import csv
import io
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone

BURGUNDY = "650D35"


def filename(report, ext):
    return f"malkia_{report['type']}_{report['start']:%Y%m%d}_{report['end']:%Y%m%d}.{ext}"


def to_csv(report):
    resp = HttpResponse(content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename(report, "csv")}"'
    resp.write("﻿")  # BOM so Excel opens UTF-8 correctly
    w = csv.writer(resp)
    w.writerow([f"Malkia Konnect - {report['title']}", report["subtitle"]])
    w.writerow(report["columns"])
    w.writerows(report["rows"])
    return resp


def to_xlsx(report, generated_by=""):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = report["title"][:31]
    ncols = max(len(report["columns"]), 4)
    ws["A1"] = "MALKIA KONNECT - Smart Attendance Management System"
    ws["A1"].font = Font(bold=True, size=14, color=BURGUNDY)
    ws["A2"] = f"{report['title']} | {report['subtitle']}"
    ws["A2"].font = Font(bold=True)
    ws["A3"] = f"Generated {timezone.localtime():%d %b %Y %H:%M}" + (f" by {generated_by}" if generated_by else "")
    ws["A3"].font = Font(italic=True, color="746573")
    head_row = 5
    for i, col in enumerate(report["columns"], start=1):
        c = ws.cell(row=head_row, column=i, value=col)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=BURGUNDY)
        c.alignment = Alignment(horizontal="center")
    for r, row in enumerate(report["rows"], start=head_row + 1):
        for i, val in enumerate(row, start=1):
            ws.cell(row=r, column=i, value=float(val) if hasattr(val, "quantize") else val)
    for i in range(1, ncols + 1):
        width = max([len(str(report["columns"][i - 1])) if i <= len(report["columns"]) else 8] +
                    [len(str(row[i - 1])) for row in report["rows"][:200] if i <= len(row)])
        ws.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 45)
    ws.freeze_panes = ws.cell(row=head_row + 1, column=1)
    buf = io.BytesIO()
    wb.save(buf)
    resp = HttpResponse(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{filename(report, "xlsx")}"'
    return resp


def to_pdf(report, generated_by=""):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    burgundy = colors.HexColor("#" + BURGUNDY)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=14 * mm, title=report["title"], author="Malkia Konnect")
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=burgundy, fontSize=16, alignment=0, spaceAfter=2)
    meta = ParagraphStyle("meta", parent=styles["Normal"], textColor=colors.HexColor("#746573"), fontSize=9)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=7.5, leading=9)
    head = ParagraphStyle("head", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    story = []
    logo = Path(settings.BASE_DIR) / "static" / "images" / "emblem-color.png"
    title_block = [Paragraph("MALKIA KONNECT - Smart Attendance Management System", h1),
                   Paragraph(f"<b>{report['title']}</b> &nbsp;|&nbsp; {report['subtitle']}", meta),
                   Paragraph(f"Generated {timezone.localtime():%d %b %Y %H:%M}" + (f" by {generated_by}" if generated_by else ""), meta)]
    if logo.exists():
        header = Table([[Image(str(logo), width=14 * mm, height=14.6 * mm), title_block]], colWidths=[18 * mm, None])
        header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story.append(header)
    else:
        story.extend(title_block)
    story.append(Spacer(1, 6 * mm))
    if report["rows"]:
        data = [[Paragraph(str(c), head) for c in report["columns"]]]
        for row in report["rows"]:
            data.append([Paragraph(str(v), cell) for v in row])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), burgundy),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFF5F8")]),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E9C9D8")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("No records found for the selected filters.", styles["Normal"]))

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#746573"))
        canvas.drawString(12 * mm, 8 * mm, "Malkia Konnect Shop - Sinza, Dar es Salaam")
        canvas.drawRightString(landscape(A4)[0] - 12 * mm, 8 * mm, f"Page {d.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="{filename(report, "pdf")}"'
    return resp
