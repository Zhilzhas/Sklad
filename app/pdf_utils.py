from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


def _fmt_money_tenge(value: float | str) -> str:
    try:
        return f"{float(value):.2f} ₸"
    except (TypeError, ValueError):
        return "0.00 ₸"


def _fmt_number(value: float | str) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def _safe_text(value: object, max_len: int = 60) -> str:
    return str(value or "")[:max_len]


def _register_unicode_font() -> tuple[str, str]:
    regular_candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/tahomabd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]

    regular_path = next((p for p in regular_candidates if p.exists()), None)
    bold_path = next((p for p in bold_candidates if p.exists()), None)
    if regular_path and bold_path:
        regular_name = "SkladUnicodeRegular"
        bold_name = "SkladUnicodeBold"
        if regular_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(regular_name, str(regular_path)))
        if bold_name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(bold_name, str(bold_path)))
        return regular_name, bold_name
    return "Helvetica", "Helvetica-Bold"


def generate_invoice_pdf(output_file: Path, invoice: dict[str, str], items: list[dict[str, str]]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(output_file), pagesize=A4)
    width, height = A4
    font_regular, font_bold = _register_unicode_font()

    top = height - 36
    c.setFont(font_bold, 14)
    c.drawString(35, top, f"Накладная № {invoice['invoice_number']}")

    c.setFont(font_regular, 10)
    y = top - 24
    c.drawString(35, y, f"Дата создания накладной: {_safe_text(invoice.get('creation_date', ''), 20)}")
    y -= 15
    c.drawString(35, y, f"Дата накладной: {_safe_text(invoice.get('issued_date', ''), 20)}")
    y -= 15
    c.drawString(35, y, f"Примерная дата выдачи груза: {_safe_text(invoice.get('estimated_release_date', ''), 20)}")
    y -= 15
    c.drawString(35, y, f"Грузоотправитель: {_safe_text(invoice.get('shipper_name', ''), 85)}")
    y -= 15
    c.drawString(35, y, f"Телефон отправителя: {_safe_text(invoice.get('shipper_phone', ''), 25)}")
    y -= 15
    c.drawString(35, y, f"Грузополучатель: {_safe_text(invoice.get('consignee_name', ''), 85)}")
    y -= 15
    c.drawString(35, y, f"Телефон получателя: {_safe_text(invoice.get('consignee_phone', ''), 25)}")

    y -= 22
    c.setFont(font_bold, 9)
    headers = ["№", "Наименование", "Ед.", "Кол-во", "Вес, кг", "Объем, м³", "Мера", "Сумма, ₸"]
    x_coords = [35, 60, 235, 280, 335, 392, 453, 512]
    for idx, header in enumerate(headers):
        c.drawString(x_coords[idx], y, header)

    c.line(35, y - 3, width - 35, y - 3)
    y -= 16
    c.setFont(font_regular, 9)
    for item in items:
        if y < 90:
            c.showPage()
            y = height - 60
            c.setFont(font_regular, 9)
        c.drawString(35, y, _safe_text(item["line_no"], 4))
        c.drawString(60, y, _safe_text(item["name"], 30))
        c.drawString(235, y, _safe_text(item["unit"], 10))
        c.drawRightString(322, y, str(int(float(item["quantity"]))))
        c.drawRightString(383, y, _fmt_number(item["weight_kg"]))
        c.drawRightString(445, y, _fmt_number(item["volume_m3"]))
        c.drawString(453, y, "Вес" if item["measure"] == "weight" else "Объем")
        c.drawRightString(width - 38, y, _fmt_number(item.get("line_total", "0")))
        y -= 14

    y -= 8
    c.line(35, y, width - 35, y)
    y -= 15
    c.setFont(font_bold, 10)
    c.drawString(35, y, f"Тариф за 1 кг: {_fmt_money_tenge(invoice.get('tariff_price_per_kg', '0'))}")
    y -= 14
    c.drawString(35, y, f"Тариф за 1 м³: {_fmt_money_tenge(invoice.get('tariff_price_per_m3', '0'))}")
    y -= 16
    c.drawString(35, y, f"Итог по накладной: {_fmt_money_tenge(invoice.get('total_amount', '0'))}")
    c.save()

