from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
    InvoiceCreate,
    TariffApply,
    WagonAllocationCreate,
    WagonAssignRequest,
    WagonCreate,
)
from app.pdf_utils import generate_invoice_pdf
from app.storage import CsvStore, now_iso


BASE_DIR = Path(__file__).resolve().parent.parent
if os.getenv("VERCEL"):
    runtime_base = Path("/tmp/sklad")
    DATA_DIR = Path(os.getenv("DATA_DIR", str(runtime_base / "data")))
    PDF_DIR = Path(os.getenv("PDF_DIR", str(runtime_base / "pdf")))
else:
    DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
    PDF_DIR = Path(os.getenv("PDF_DIR", str(BASE_DIR / "pdf")))

STATIC_DIR = BASE_DIR / "static"

store = CsvStore(DATA_DIR)

app = FastAPI(title="Sklad Logistics Mini App", version="0.3.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _to_float(value: str | float | int | None) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: str | float | int | None) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _fmt2(value: float) -> str:
    return f"{value:.2f}"


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _has_tariff(invoice: dict[str, str]) -> bool:
    return invoice.get("tariff_price_per_kg", "") != "" and invoice.get("tariff_price_per_m3", "") != ""


def _invoice_or_404(invoice_id: str) -> dict[str, str]:
    for row in store.list_rows("invoices"):
        if row["invoice_id"] == invoice_id:
            return row
    raise HTTPException(status_code=404, detail="Invoice not found")


def _items_by_invoice(invoice_id: str) -> list[dict[str, str]]:
    items = [row for row in store.list_rows("invoice_items") if row["invoice_id"] == invoice_id]
    items.sort(key=lambda row: int(row["line_no"]))
    return items


def _next_split_invoice_number(base_number: str) -> str:
    existing_numbers = {row["invoice_number"] for row in store.list_rows("invoices")}
    index = 1
    while True:
        candidate = f"{base_number}-R{index}"
        if candidate not in existing_numbers:
            return candidate
        index += 1


def _scale_value(original_value: str, original_qty: int, new_qty: int) -> float:
    if original_qty <= 0:
        return 0.0
    return round(_to_float(original_value) * (new_qty / original_qty), 2)


def _replace_invoice_items(invoice_id: str, rows_for_invoice: list[dict[str, str]]) -> None:
    all_rows = store.list_rows("invoice_items")
    rows_other_invoices = [row for row in all_rows if row["invoice_id"] != invoice_id]
    timestamp = now_iso()

    normalized_rows = []
    for line_no, row in enumerate(rows_for_invoice, start=1):
        base = dict(row)
        base["invoice_id"] = invoice_id
        base["line_no"] = str(line_no)
        if not base.get("created_at"):
            base["created_at"] = timestamp
        base["updated_at"] = timestamp
        normalized_rows.append(base)

    store.replace_rows("invoice_items", rows_other_invoices + normalized_rows)


def _invoice_payload(invoice_id: str) -> dict:
    invoice = _invoice_or_404(invoice_id)
    items = _items_by_invoice(invoice_id)
    allocations = [row for row in store.list_rows("wagon_allocations") if row["invoice_id"] == invoice_id]
    return {
        "invoice": {
            **invoice,
            "has_tariff": _has_tariff(invoice),
            "has_pdf": invoice.get("pdf_file", "") != "",
        },
        "items": items,
        "allocations": allocations,
    }


def _regenerate_pdf(invoice_id: str) -> str:
    invoice = _invoice_or_404(invoice_id)
    if not _has_tariff(invoice):
        store.update_rows(
            "invoices",
            predicate=lambda row: row["invoice_id"] == invoice_id,
            updater=lambda row: {**row, "pdf_file": ""},
        )
        return ""

    items = _items_by_invoice(invoice_id)
    pdf_path = PDF_DIR / f"invoice_{invoice['invoice_number']}_{invoice['invoice_id']}.pdf"
    generate_invoice_pdf(pdf_path, invoice, items)

    try:
        pdf_ref = str(pdf_path.relative_to(BASE_DIR))
    except ValueError:
        pdf_ref = str(pdf_path)

    store.update_rows(
        "invoices",
        predicate=lambda row: row["invoice_id"] == invoice_id,
        updater=lambda row: {**row, "pdf_file": pdf_ref},
    )
    return pdf_ref


def _recalculate_invoice_with_tariff(invoice_id: str) -> None:
    invoice = _invoice_or_404(invoice_id)
    if not _has_tariff(invoice):
        return

    price_per_kg = _to_float(invoice["tariff_price_per_kg"])
    price_per_m3 = _to_float(invoice["tariff_price_per_m3"])
    items = _items_by_invoice(invoice_id)

    updated_items: dict[str, dict[str, str]] = {}
    total_amount = 0.0
    for item in items:
        if item["measure"] == "weight":
            unit_price = price_per_kg
            line_total = _to_float(item["weight_kg"]) * unit_price
        else:
            unit_price = price_per_m3
            line_total = _to_float(item["volume_m3"]) * unit_price
        total_amount += line_total
        updated_items[item["item_id"]] = {
            **item,
            "unit_price": _fmt2(unit_price),
            "line_total": _fmt2(round(line_total, 2)),
        }

    store.update_rows(
        "invoice_items",
        predicate=lambda row: row["invoice_id"] == invoice_id,
        updater=lambda row: updated_items[row["item_id"]],
    )
    store.update_rows(
        "invoices",
        predicate=lambda row: row["invoice_id"] == invoice_id,
        updater=lambda row: {**row, "total_amount": _fmt2(round(total_amount, 2))},
    )
    _regenerate_pdf(invoice_id)


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/invoices")
def create_invoice(payload: InvoiceCreate) -> dict:
    invoice_id = str(uuid.uuid4())
    store.append_row(
        "invoices",
        {
            "invoice_id": invoice_id,
            "invoice_number": payload.invoice_number,
            "shipper_name": payload.shipper_name,
            "shipper_phone": payload.shipper_phone,
            "consignee_name": payload.consignee_name,
            "consignee_phone": payload.consignee_phone,
            "creation_date": payload.creation_date.isoformat(),
            "issued_date": payload.issued_date.isoformat(),
            "estimated_release_date": "",
            "tariff_price_per_kg": "",
            "tariff_price_per_m3": "",
            "total_amount": "0.00",
            "pdf_file": "",
        },
    )

    for index, item in enumerate(payload.items, start=1):
        store.append_row(
            "invoice_items",
            {
                "item_id": str(uuid.uuid4()),
                "invoice_id": invoice_id,
                "line_no": str(index),
                "name": item.name,
                "unit": item.unit,
                "quantity": str(item.quantity),
                "weight_kg": _fmt2(round(item.weight_kg, 2)),
                "volume_m3": _fmt2(round(item.volume_m3, 2)),
                "measure": item.measure,
                "unit_price": "",
                "line_total": "",
            },
        )

    return _invoice_payload(invoice_id)


@app.get("/api/invoices")
def list_invoices() -> dict[str, list[dict]]:
    invoices = store.list_rows("invoices")
    items = store.list_rows("invoice_items")
    items_count_by_invoice: dict[str, int] = {}
    for item in items:
        items_count_by_invoice[item["invoice_id"]] = items_count_by_invoice.get(item["invoice_id"], 0) + 1

    invoices.sort(key=lambda row: row["created_at"], reverse=True)
    payload = []
    for row in invoices:
        payload.append(
            {
                **row,
                "items_count": items_count_by_invoice.get(row["invoice_id"], 0),
                "has_tariff": _has_tariff(row),
                "has_pdf": row.get("pdf_file", "") != "",
            }
        )
    return {"invoices": payload}


@app.get("/api/invoices/{invoice_id}")
def get_invoice(invoice_id: str) -> dict:
    return _invoice_payload(invoice_id)


@app.get("/api/invoices/{invoice_id}/pdf")
def download_invoice_pdf(invoice_id: str) -> FileResponse:
    invoice = _invoice_or_404(invoice_id)
    if not _has_tariff(invoice):
        raise HTTPException(status_code=400, detail="PDF is generated only after tariff assignment")
    if not invoice.get("pdf_file"):
        _regenerate_pdf(invoice_id)
        invoice = _invoice_or_404(invoice_id)
    if not invoice.get("pdf_file"):
        raise HTTPException(status_code=404, detail="PDF not found")

    pdf_ref = Path(invoice["pdf_file"])
    pdf_path = pdf_ref if pdf_ref.is_absolute() else (BASE_DIR / pdf_ref)
    if not pdf_path.exists():
        # On serverless runtimes /tmp is ephemeral, so regenerate when stale path is stored in DB.
        _regenerate_pdf(invoice_id)
        invoice = _invoice_or_404(invoice_id)
        if not invoice.get("pdf_file"):
            raise HTTPException(status_code=404, detail="PDF file not found")
        pdf_ref = Path(invoice["pdf_file"])
        pdf_path = pdf_ref if pdf_ref.is_absolute() else (BASE_DIR / pdf_ref)
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF file not found")
    return FileResponse(pdf_path, filename=pdf_path.name, media_type="application/pdf")


@app.post("/api/invoices/{invoice_id}/tariff")
def apply_tariff_to_selected_invoice(invoice_id: str, payload: TariffApply) -> dict:
    _invoice_or_404(invoice_id)
    store.update_rows(
        "invoices",
        predicate=lambda row: row["invoice_id"] == invoice_id,
        updater=lambda row: {
            **row,
            "tariff_price_per_kg": _fmt2(round(payload.price_per_kg, 2)),
            "tariff_price_per_m3": _fmt2(round(payload.price_per_m3, 2)),
        },
    )
    _recalculate_invoice_with_tariff(invoice_id)
    return _invoice_payload(invoice_id)


@app.get("/api/wagons")
def list_wagons() -> dict[str, list[dict[str, str]]]:
    wagons = store.list_rows("wagons")
    wagons.sort(key=lambda row: row["created_at"], reverse=True)
    return {"wagons": wagons}


@app.post("/api/wagons")
def create_or_update_wagon(payload: WagonCreate) -> dict[str, str]:
    wagons = store.list_rows("wagons")
    for wagon in wagons:
        if wagon["wagon_code"].strip().lower() == payload.wagon_code.strip().lower():
            store.update_rows(
                "wagons",
                predicate=lambda row: row["wagon_id"] == wagon["wagon_id"],
                updater=lambda row: {
                    **row,
                    "destination": payload.destination or "",
                    "description": payload.description or "",
                },
            )
            return [row for row in store.list_rows("wagons") if row["wagon_id"] == wagon["wagon_id"]][0]

    return store.append_row(
        "wagons",
        {
            "wagon_id": str(uuid.uuid4()),
            "wagon_code": payload.wagon_code.strip(),
            "destination": payload.destination or "",
            "description": payload.description or "",
        },
    )


@app.get("/api/allocations")
def list_allocations(invoice_id: str | None = Query(default=None)) -> dict[str, list[dict[str, str]]]:
    allocations = store.list_rows("wagon_allocations")
    if invoice_id:
        allocations = [row for row in allocations if row["invoice_id"] == invoice_id]
    allocations.sort(key=lambda row: row["created_at"], reverse=True)
    return {"allocations": allocations}


@app.post("/api/allocations")
def create_allocation(payload: WagonAllocationCreate) -> dict[str, str]:
    _invoice_or_404(payload.invoice_id)
    wagons = {row["wagon_id"] for row in store.list_rows("wagons")}
    if payload.wagon_id not in wagons:
        raise HTTPException(status_code=404, detail="Wagon not found")

    item_ids = {item["item_id"] for item in _items_by_invoice(payload.invoice_id)}
    if payload.item_id not in item_ids:
        raise HTTPException(status_code=400, detail="Item does not belong to invoice")

    return store.append_row(
        "wagon_allocations",
        {
            "allocation_id": str(uuid.uuid4()),
            "invoice_id": payload.invoice_id,
            "item_id": payload.item_id,
            "wagon_id": payload.wagon_id,
            "allocation_measure": payload.allocation_measure,
            "allocation_value": str(payload.allocation_value),
        },
    )


@app.post("/api/wagon-assignments")
def assign_invoice_to_wagon(payload: WagonAssignRequest) -> dict:
    invoice = _invoice_or_404(payload.invoice_id)
    wagons = {row["wagon_id"] for row in store.list_rows("wagons")}
    if payload.wagon_id not in wagons:
        raise HTTPException(status_code=404, detail="Wagon not found")

    items = _items_by_invoice(payload.invoice_id)
    if not items:
        raise HTTPException(status_code=400, detail="Invoice has no items")

    moved_quantity_by_item: dict[str, int] = {}
    if payload.fully_loaded:
        for item in items:
            moved_quantity_by_item[item["item_id"]] = _to_int(item["quantity"])
    else:
        for partial in payload.items:
            if partial.item_id in moved_quantity_by_item:
                raise HTTPException(status_code=400, detail="Duplicate item in partial list")
            moved_quantity_by_item[partial.item_id] = partial.moved_quantity

    item_map = {item["item_id"]: item for item in items}
    for item_id in moved_quantity_by_item:
        if item_id not in item_map:
            raise HTTPException(status_code=400, detail="One selected item does not belong to invoice")

    moved_rows: list[dict[str, str]] = []
    remaining_rows: list[dict[str, str]] = []
    for item in items:
        original_qty = _to_int(item["quantity"])
        moved_qty = moved_quantity_by_item.get(item["item_id"], 0)
        if moved_qty < 0 or moved_qty > original_qty:
            raise HTTPException(status_code=400, detail=f"Invalid quantity for item line {item['line_no']}")

        if moved_qty > 0:
            moved_rows.append(
                {
                    **item,
                    "quantity": str(moved_qty),
                    "weight_kg": _fmt2(_scale_value(item["weight_kg"], original_qty, moved_qty)),
                    "volume_m3": _fmt2(_scale_value(item["volume_m3"], original_qty, moved_qty)),
                }
            )
            store.append_row(
                "wagon_allocations",
                {
                    "allocation_id": str(uuid.uuid4()),
                    "invoice_id": payload.invoice_id,
                    "item_id": item["item_id"],
                    "wagon_id": payload.wagon_id,
                    "allocation_measure": "quantity",
                    "allocation_value": str(moved_qty),
                },
            )

        remaining_qty = original_qty - moved_qty
        if remaining_qty > 0:
            remaining_rows.append(
                {
                    **item,
                    "quantity": str(remaining_qty),
                    "weight_kg": _fmt2(_scale_value(item["weight_kg"], original_qty, remaining_qty)),
                    "volume_m3": _fmt2(_scale_value(item["volume_m3"], original_qty, remaining_qty)),
                    "unit_price": "",
                    "line_total": "",
                }
            )

    if not moved_rows:
        raise HTTPException(status_code=400, detail="Nothing was assigned to wagon")

    _replace_invoice_items(payload.invoice_id, moved_rows)
    store.update_rows(
        "invoices",
        predicate=lambda row: row["invoice_id"] == payload.invoice_id,
        updater=lambda row: {
            **row,
            "estimated_release_date": payload.estimated_release_date.isoformat(),
        },
    )
    _recalculate_invoice_with_tariff(payload.invoice_id)

    new_invoice_id = ""
    if remaining_rows:
        new_invoice_id = str(uuid.uuid4())
        new_invoice_number = _next_split_invoice_number(invoice["invoice_number"])
        store.append_row(
            "invoices",
            {
                "invoice_id": new_invoice_id,
                "invoice_number": new_invoice_number,
                "shipper_name": invoice["shipper_name"],
                "shipper_phone": invoice["shipper_phone"],
                "consignee_name": invoice["consignee_name"],
                "consignee_phone": invoice["consignee_phone"],
                "creation_date": _today_iso(),
                "issued_date": invoice["issued_date"],
                "estimated_release_date": "",
                "tariff_price_per_kg": "",
                "tariff_price_per_m3": "",
                "total_amount": "0.00",
                "pdf_file": "",
            },
        )
        for line_no, row in enumerate(remaining_rows, start=1):
            store.append_row(
                "invoice_items",
                {
                    "item_id": str(uuid.uuid4()),
                    "invoice_id": new_invoice_id,
                    "line_no": str(line_no),
                    "name": row["name"],
                    "unit": row["unit"],
                    "quantity": row["quantity"],
                    "weight_kg": row["weight_kg"],
                    "volume_m3": row["volume_m3"],
                    "measure": row["measure"],
                    "unit_price": "",
                    "line_total": "",
                },
            )

    response: dict[str, object] = {"assigned_invoice": _invoice_payload(payload.invoice_id)}
    if new_invoice_id:
        response["new_invoice"] = _invoice_payload(new_invoice_id)
    return response
