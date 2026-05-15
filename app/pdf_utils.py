from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


BASE_DIR = Path(__file__).resolve().parent.parent

PDF_STATUS_LABELS = {
    "formed": "Сформирована накладная",
    "loading": "Загружается на отправку",
    "in_transit": "В пути",
    "delivered": "Доставлено",
    "unloaded": "Выдано получателю",
}


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
        BASE_DIR / "app" / "fonts" / "NotoSans-Regular.ttf",
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/tahoma.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    ]
    bold_candidates = [
        BASE_DIR / "app" / "fonts" / "NotoSans-Bold.ttf",
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
    y -= 15
    status_key = (invoice.get("status") or "formed").strip()
    c.drawString(35, y, f"Статус: {PDF_STATUS_LABELS.get(status_key, PDF_STATUS_LABELS['formed'])}")
    y -= 15
    c.drawString(35, y, f"Дата изменения статуса: {_safe_text(invoice.get('status_changed_at', ''), 30)}")

    y -= 22
    headers = [
        "Строка",
        "Наименование",
        "Ед.",
        "Кол-во",
        "Вес, кг",
        "Объем, м³",
        "Мера",
        "Тариф, ₸",
        "Сумма вес, ₸",
        "Сумма объем, ₸",
        "Сумма, ₸",
    ]
    col_edges = [20, 44, 170, 198, 230, 272, 314, 358, 402, 458, 514, width - 20]
    header_height = 16
    row_height = 15

    def draw_table_header(top_y: float) -> float:
        c.setFont(font_bold, 9)
        for idx, header in enumerate(headers):
            x0 = col_edges[idx]
            x1 = col_edges[idx + 1]
            c.rect(x0, top_y - header_height, x1 - x0, header_height, stroke=1, fill=0)
            c.drawString(x0 + 2, top_y - header_height + 5, _safe_text(header, 24))
        return top_y - header_height

    y = draw_table_header(y)
    c.setFont(font_regular, 9)

    for item in items:
        if y - row_height < 90:
            c.showPage()
            y = height - 60
            y = draw_table_header(y)
            c.setFont(font_regular, 9)

        qty = int(float(item.get("quantity", "0") or 0))
        line_weight = float(item.get("weight_kg", "0") or 0) * qty
        line_volume = float(item.get("volume_m3", "0") or 0) * qty
        row_values = [
            _safe_text(item.get("line_no", ""), 4),
            _safe_text(item.get("name", ""), 30),
            _safe_text(item.get("unit", ""), 10),
            str(qty),
            _fmt_number(line_weight),
            _fmt_number(line_volume),
            "Вес" if item.get("measure") == "weight" else "Объем",
            _fmt_number(item.get("unit_price", "0")),
            _fmt_number(item.get("line_total_weight", "0")),
            _fmt_number(item.get("line_total_volume", "0")),
            _fmt_number(item.get("line_total", "0")),
        ]
        numeric_cols = {3, 4, 5, 7, 8, 9, 10}

        for idx, value in enumerate(row_values):
            x0 = col_edges[idx]
            x1 = col_edges[idx + 1]
            c.rect(x0, y - row_height, x1 - x0, row_height, stroke=1, fill=0)
            if idx in numeric_cols:
                c.drawRightString(x1 - 2, y - row_height + 5, value)
            else:
                c.drawString(x0 + 2, y - row_height + 5, value)

        y -= row_height

    total_qty = sum(int(float(item.get("quantity", "0") or 0)) for item in items)
    total_weight = sum(float(item.get("weight_kg", "0") or 0) * int(float(item.get("quantity", "0") or 0)) for item in items)
    total_volume = sum(float(item.get("volume_m3", "0") or 0) * int(float(item.get("quantity", "0") or 0)) for item in items)
    total_weight_sum = sum(float(item.get("line_total_weight", "0") or 0) for item in items)
    total_volume_sum = sum(float(item.get("line_total_volume", "0") or 0) for item in items)
    total_money = sum(float(item.get("line_total", "0") or 0) for item in items)

    if y - row_height < 90:
        c.showPage()
        y = height - 60
        y = draw_table_header(y)
        c.setFont(font_regular, 9)

    c.setFont(font_bold, 9)
    totals_row = [
        "ИТОГО",
        "",
        "",
        str(total_qty),
        _fmt_number(total_weight),
        _fmt_number(total_volume),
        "-",
        "-",
        _fmt_number(total_weight_sum),
        _fmt_number(total_volume_sum),
        _fmt_number(total_money),
    ]
    numeric_cols = {3, 4, 5, 8, 9, 10}
    for idx, value in enumerate(totals_row):
        x0 = col_edges[idx]
        x1 = col_edges[idx + 1]
        c.rect(x0, y - row_height, x1 - x0, row_height, stroke=1, fill=0)
        if idx in numeric_cols:
            c.drawRightString(x1 - 2, y - row_height + 5, value)
        else:
            c.drawString(x0 + 2, y - row_height + 5, value)
    y -= row_height

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
