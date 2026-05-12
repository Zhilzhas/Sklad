from __future__ import annotations

import os
import re
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
    InvoiceCreate,
    InvoiceStatusUpdate,
    InvoiceUpdate,
    LoginRequest,
    TariffApply,
    UserCreate,
    UserPasswordReset,
    UserRoleUpdate,
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

AUTH_SECRET = os.getenv("AUTH_SECRET", "sklad-auth-secret-2026").encode("utf-8")
TOKEN_TTL_SECONDS = 60 * 60 * 12
WAGON_MAX_WEIGHT_KG = 64000.0
WAGON_MAX_VOLUME_M3 = 130.0


def _password_hash(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _ensure_default_admin() -> None:
    users = store.list_rows("users")
    has_admin = any((row.get("login") or "").strip().lower() == "admin" for row in users)
    if has_admin:
        return
    store.append_row(
        "users",
        {
            "user_id": str(uuid.uuid4()),
            "login": "admin",
            "password_hash": _password_hash("123"),
            "role": "admin",
        },
    )


def _token_sign(data: bytes) -> str:
    signature = hmac.new(AUTH_SECRET, data, hashlib.sha256).digest()
    return urlsafe_b64encode(signature).decode("utf-8").rstrip("=")


def _token_encode(payload: dict) -> str:
    payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload_part = urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")
    sign_part = _token_sign(payload_bytes)
    return f"{payload_part}.{sign_part}"


def _token_decode(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Invalid token")
    payload_part, sign_part = parts
    payload_part += "=" * ((4 - len(payload_part) % 4) % 4)
    payload_bytes = urlsafe_b64decode(payload_part.encode("utf-8"))
    expected_sign = _token_sign(payload_bytes)
    if not hmac.compare_digest(expected_sign, sign_part):
        raise HTTPException(status_code=401, detail="Invalid token signature")
    payload = json.loads(payload_bytes.decode("utf-8"))
    if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise HTTPException(status_code=401, detail="Token expired")
    return payload


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization required")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    return authorization[len(prefix) :].strip()


def _current_user(authorization: str | None) -> dict[str, str]:
    token = _extract_bearer(authorization)
    payload = _token_decode(token)
    user_id = payload.get("user_id", "")
    users = store.list_rows("users")
    for row in users:
        if row["user_id"] == user_id:
            return row
    raise HTTPException(status_code=401, detail="User not found")


def _require_admin(authorization: str | None) -> dict[str, str]:
    user = _current_user(authorization)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _current_user_with_fallback_token(authorization: str | None, token: str | None) -> dict[str, str]:
    if authorization:
        return _current_user(authorization)
    if token:
        payload = _token_decode(token)
        user_id = payload.get("user_id", "")
        for row in store.list_rows("users"):
            if row["user_id"] == user_id:
                return row
    raise HTTPException(status_code=401, detail="Authorization required")




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
    items.sort(key=lambda row: _to_int(row.get("line_no")))
    return items


def _next_split_invoice_number(base_number: str) -> str:
    existing_numbers = {row["invoice_number"] for row in store.list_rows("invoices")}
    index = 1
    while True:
        candidate = f"{base_number}-R{index}"
        if candidate not in existing_numbers:
            return candidate
        index += 1


def _next_code(rows: list[dict[str, str]], key: str, prefix: str, width: int) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    max_num = 0
    for row in rows:
        value = (row.get(key) or "").strip()
        match = pattern.match(value)
        if not match:
            continue
        max_num = max(max_num, int(match.group(1)))
    return f"{prefix}{str(max_num + 1).zfill(width)}"


def _next_invoice_number() -> str:
    return _next_code(store.list_rows("invoices"), "invoice_number", "INV-", 6)


def _next_wagon_code() -> str:
    return _next_code(store.list_rows("wagons"), "wagon_code", "WG-", 5)


def _dedupe_table_by_id(table_name: str, id_key: str) -> int:
    rows = store.list_rows(table_name)
    latest_by_id: dict[str, dict[str, str]] = {}
    for row in rows:
        row_id = (row.get(id_key) or "").strip()
        if not row_id:
            continue
        existing = latest_by_id.get(row_id)
        if not existing or (row.get("updated_at", ""), row.get("created_at", "")) > (
            existing.get("updated_at", ""),
            existing.get("created_at", ""),
        ):
            latest_by_id[row_id] = row
    if len(latest_by_id) == len(rows):
        return 0
    deduped_rows = sorted(latest_by_id.values(), key=lambda x: (x.get("created_at", ""), x.get(id_key, "")))
    store.replace_rows(table_name, deduped_rows)
    return len(rows) - len(deduped_rows)


def _dedupe_all() -> None:
    _dedupe_table_by_id("invoices", "invoice_id")
    _dedupe_table_by_id("invoice_items", "item_id")
    _dedupe_table_by_id("wagons", "wagon_id")
    _dedupe_table_by_id("wagon_allocations", "allocation_id")
    _dedupe_table_by_id("users", "user_id")
    _dedupe_table_by_id("idempotency_keys", "idempotency_key")


def _invoice_metrics(items: list[dict[str, str]]) -> dict[str, str]:
    total_qty = 0
    total_weight = 0.0
    total_volume = 0.0
    total_weight_sum = 0.0
    total_volume_sum = 0.0
    total_sum = 0.0
    for x in items:
        qty = _to_int(x.get("quantity"))
        total_qty += qty
        total_weight += _to_float(x.get("weight_kg")) * qty
        total_volume += _to_float(x.get("volume_m3")) * qty
        total_weight_sum += _to_float(x.get("line_total_weight"))
        total_volume_sum += _to_float(x.get("line_total_volume"))
        total_sum += _to_float(x.get("line_total"))
    return {
        "total_quantity": str(total_qty),
        "total_weight_kg": _fmt2(round(total_weight, 2)),
        "total_volume_m3": _fmt2(round(total_volume, 2)),
        "total_weight_sum": _fmt2(round(total_weight_sum, 2)),
        "total_volume_sum": _fmt2(round(total_volume_sum, 2)),
        "total_sum": _fmt2(round(total_sum, 2)),
    }


def _wagon_usage(wagon_id: str) -> dict[str, float]:
    used_weight = 0.0
    used_volume = 0.0
    for row in store.list_rows("wagon_allocations"):
        if row.get("wagon_id") != wagon_id:
            continue
        used_weight += _to_float(row.get("allocation_weight_kg"))
        used_volume += _to_float(row.get("allocation_volume_m3"))

    remaining_weight = max(0.0, WAGON_MAX_WEIGHT_KG - used_weight)
    remaining_volume = max(0.0, WAGON_MAX_VOLUME_M3 - used_volume)
    return {
        "max_weight_kg": WAGON_MAX_WEIGHT_KG,
        "max_volume_m3": WAGON_MAX_VOLUME_M3,
        "used_weight_kg": round(used_weight, 2),
        "used_volume_m3": round(used_volume, 2),
        "remaining_weight_kg": round(remaining_weight, 2),
        "remaining_volume_m3": round(remaining_volume, 2),
    }


def _idempotency_get(route: str, key: str) -> str | None:
    for row in store.list_rows("idempotency_keys"):
        if row.get("route") == route and row.get("idempotency_key") == key:
            return row.get("entity_id") or None
    return None


def _idempotency_save(route: str, key: str, entity_id: str) -> None:
    store.append_row(
        "idempotency_keys",
        {
            "idempotency_key": key,
            "route": route,
            "entity_id": entity_id,
        },
    )


_ensure_default_admin()
_dedupe_all()


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
    items = _items_with_live_totals(invoice, _items_by_invoice(invoice_id))
    allocations = [row for row in store.list_rows("wagon_allocations") if row["invoice_id"] == invoice_id]
    metrics = _invoice_metrics(items)
    return {
        "invoice": {
            **invoice,
            **metrics,
            "total_amount": metrics["total_sum"],
            "status": invoice.get("status") or "formed",
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

    items = _items_with_live_totals(invoice, _items_by_invoice(invoice_id))
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

    items = _items_by_invoice(invoice_id)

    updated_items: dict[str, dict[str, str]] = {}
    total_amount = 0.0
    for item in items:
        unit_price, line_total_weight, line_total_volume, line_total = _line_totals_for_item(item, invoice)
        total_amount += line_total
        updated_items[item["item_id"]] = {
            **item,
            "unit_price": unit_price,
            "line_total_weight": _fmt2(round(line_total_weight, 2)),
            "line_total_volume": _fmt2(round(line_total_volume, 2)),
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


def _line_totals_for_item(item: dict[str, str], invoice: dict[str, str]) -> tuple[str, float, float, float]:
    if not _has_tariff(invoice):
        return "", 0.0, 0.0, 0.0

    qty = max(0, _to_int(item.get("quantity")))
    price_per_kg = _to_float(invoice.get("tariff_price_per_kg"))
    price_per_m3 = _to_float(invoice.get("tariff_price_per_m3"))
    weight_sum = _to_float(item.get("weight_kg")) * price_per_kg * qty
    volume_sum = _to_float(item.get("volume_m3")) * price_per_m3 * qty
    measure = (item.get("measure") or "weight").strip()

    if measure == "volume":
        unit_price = price_per_m3
        line_total_weight = 0.0
        line_total_volume = volume_sum
        line_total = volume_sum
    else:
        unit_price = price_per_kg
        line_total_weight = weight_sum
        line_total_volume = 0.0
        line_total = weight_sum

    return _fmt2(round(unit_price, 2)), round(line_total_weight, 2), round(line_total_volume, 2), round(line_total, 2)


def _items_with_live_totals(invoice: dict[str, str], items: list[dict[str, str]]) -> list[dict[str, str]]:
    computed: list[dict[str, str]] = []
    for item in items:
        unit_price, line_total_weight, line_total_volume, line_total = _line_totals_for_item(item, invoice)
        if _has_tariff(invoice):
            computed.append(
                {
                    **item,
                    "unit_price": unit_price,
                    "line_total_weight": _fmt2(line_total_weight),
                    "line_total_volume": _fmt2(line_total_volume),
                    "line_total": _fmt2(line_total),
                }
            )
        else:
            computed.append(
                {
                    **item,
                    "unit_price": item.get("unit_price", ""),
                    "line_total_weight": item.get("line_total_weight", ""),
                    "line_total_volume": item.get("line_total_volume", ""),
                    "line_total": item.get("line_total", ""),
                }
            )
    return computed


@app.get("/")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _auth_payload(user: dict[str, str]) -> dict[str, str]:
    return {"user_id": user["user_id"], "login": user["login"], "role": user.get("role", "user")}


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> dict:
    login = payload.login.strip().lower()
    password_hash = _password_hash(payload.password)
    for user in store.list_rows("users"):
        if user.get("login", "").strip().lower() == login and user.get("password_hash") == password_hash:
            now_ts = int(datetime.now(timezone.utc).timestamp())
            token = _token_encode(
                {
                    "user_id": user["user_id"],
                    "login": user["login"],
                    "role": user.get("role", "user"),
                    "iat": now_ts,
                    "exp": now_ts + TOKEN_TTL_SECONDS,
                }
            )
            return {"token": token, "user": _auth_payload(user)}
    raise HTTPException(status_code=401, detail="Invalid login or password")


@app.get("/api/auth/me")
def me(authorization: str | None = Header(default=None)) -> dict:
    user = _current_user(authorization)
    return {"user": _auth_payload(user)}


@app.get("/api/admin/users")
def list_users(authorization: str | None = Header(default=None)) -> dict[str, list[dict[str, str]]]:
    _require_admin(authorization)
    users = store.list_rows("users")
    users.sort(key=lambda row: row.get("created_at", ""), reverse=True)
    return {"users": [_auth_payload(row) for row in users]}


@app.post("/api/admin/users")
def create_user(payload: UserCreate, authorization: str | None = Header(default=None)) -> dict[str, str]:
    _require_admin(authorization)
    login = payload.login.strip()
    if any(row.get("login", "").strip().lower() == login.lower() for row in store.list_rows("users")):
        raise HTTPException(status_code=400, detail="Login already exists")
    user = store.append_row(
        "users",
        {
            "user_id": str(uuid.uuid4()),
            "login": login,
            "password_hash": _password_hash(payload.password),
            "role": payload.role,
        },
    )
    return _auth_payload(user)


@app.patch("/api/admin/users/{user_id}/role")
def update_user_role(user_id: str, payload: UserRoleUpdate, authorization: str | None = Header(default=None)) -> dict[str, str]:
    admin = _require_admin(authorization)
    users = store.list_rows("users")
    target = next((x for x in users if x["user_id"] == user_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["login"].strip().lower() == "admin" and payload.role != "admin":
        raise HTTPException(status_code=400, detail="Default admin role cannot be changed")
    if target["user_id"] == admin["user_id"] and payload.role != "admin":
        raise HTTPException(status_code=400, detail="You cannot remove admin role from yourself")
    store.update_rows(
        "users",
        predicate=lambda row: row["user_id"] == user_id,
        updater=lambda row: {**row, "role": payload.role},
    )
    refreshed = next(x for x in store.list_rows("users") if x["user_id"] == user_id)
    return _auth_payload(refreshed)


@app.patch("/api/admin/users/{user_id}/password")
def reset_user_password(
    user_id: str, payload: UserPasswordReset, authorization: str | None = Header(default=None)
) -> dict[str, str]:
    _require_admin(authorization)
    users = store.list_rows("users")
    target = next((x for x in users if x["user_id"] == user_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    store.update_rows(
        "users",
        predicate=lambda row: row["user_id"] == user_id,
        updater=lambda row: {**row, "password_hash": _password_hash(payload.password)},
    )
    return {"status": "password_reset"}


@app.get("/api/next-numbers")
def next_numbers(authorization: str | None = Header(default=None)) -> dict[str, str]:
    _current_user(authorization)
    return {
        "next_invoice_number": _next_invoice_number(),
        "next_wagon_code": _next_wagon_code(),
    }


@app.get("/api/item-templates")
def item_templates(authorization: str | None = Header(default=None)) -> dict[str, list[dict[str, str]]]:
    _current_user(authorization)
    templates: dict[str, dict[str, str]] = {}
    for row in store.list_rows("invoice_items"):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        existing = templates.get(name)
        if not existing or row.get("updated_at", "") > existing.get("updated_at", ""):
            templates[name] = row
    result = []
    for name, row in templates.items():
        result.append(
            {
                "name": name,
                "unit": row.get("unit", ""),
                "weight_kg": row.get("weight_kg", ""),
                "volume_m3": row.get("volume_m3", ""),
                "measure": row.get("measure", ""),
            }
        )
    result.sort(key=lambda x: x["name"].lower())
    return {"templates": result}


@app.post("/api/invoices")
def create_invoice(
    payload: InvoiceCreate,
    authorization: str | None = Header(default=None),
    x_idempotency_key: str | None = Header(default=None),
) -> dict:
    _current_user(authorization)
    if x_idempotency_key:
        existing_invoice_id = _idempotency_get("create_invoice", x_idempotency_key)
        if existing_invoice_id:
            return _invoice_payload(existing_invoice_id)

    invoice_id = str(uuid.uuid4())
    invoice_number = _next_invoice_number()
    store.append_row(
        "invoices",
        {
            "invoice_id": invoice_id,
            "invoice_number": invoice_number,
            "shipper_name": payload.shipper_name,
            "shipper_phone": payload.shipper_phone,
            "consignee_name": payload.consignee_name,
            "consignee_phone": payload.consignee_phone,
            "creation_date": payload.creation_date.isoformat(),
            "issued_date": payload.issued_date.isoformat(),
            "estimated_release_date": "",
            "tariff_price_per_kg": "",
            "tariff_price_per_m3": "",
            "status": "formed",
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
                "line_total_weight": "",
                "line_total_volume": "",
                "line_total": "",
            },
        )

    if x_idempotency_key:
        _idempotency_save("create_invoice", x_idempotency_key, invoice_id)

    return _invoice_payload(invoice_id)


@app.get("/api/invoices")
def list_invoices(authorization: str | None = Header(default=None)) -> dict[str, list[dict]]:
    _current_user(authorization)
    _dedupe_all()
    invoices = store.list_rows("invoices")
    items = store.list_rows("invoice_items")
    items_by_invoice: dict[str, list[dict[str, str]]] = {}
    for item in items:
        items_by_invoice.setdefault(item["invoice_id"], []).append(item)

    invoices.sort(key=lambda row: row["created_at"], reverse=True)
    payload = []
    for row in invoices:
        invoice_items = items_by_invoice.get(row["invoice_id"], [])
        invoice_items.sort(key=lambda x: _to_int(x.get("line_no")))
        computed_items = _items_with_live_totals(row, invoice_items)
        metrics = _invoice_metrics(computed_items)
        payload.append(
            {
                **row,
                "items_count": len(computed_items),
                "total_quantity": int(metrics["total_quantity"]),
                "total_weight_kg": metrics["total_weight_kg"],
                "total_volume_m3": metrics["total_volume_m3"],
                "total_weight_sum": metrics["total_weight_sum"],
                "total_volume_sum": metrics["total_volume_sum"],
                "total_amount": metrics["total_sum"],
                "status": row.get("status") or "formed",
                "has_tariff": _has_tariff(row),
                "has_pdf": row.get("pdf_file", "") != "",
            }
        )
    return {"invoices": payload}


@app.get("/api/invoices/{invoice_id}")
def get_invoice(invoice_id: str, authorization: str | None = Header(default=None)) -> dict:
    _current_user(authorization)
    return _invoice_payload(invoice_id)


@app.get("/api/invoices/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: str, authorization: str | None = Header(default=None), token: str | None = Query(default=None)
) -> FileResponse:
    _current_user_with_fallback_token(authorization, token)
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
def apply_tariff_to_selected_invoice(
    invoice_id: str, payload: TariffApply, authorization: str | None = Header(default=None)
) -> dict:
    _current_user(authorization)
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


@app.patch("/api/invoices/{invoice_id}/status")
def update_invoice_status(
    invoice_id: str, payload: InvoiceStatusUpdate, authorization: str | None = Header(default=None)
) -> dict:
    _current_user(authorization)
    _invoice_or_404(invoice_id)
    if payload.status in {"formed", "loading"}:
        raise HTTPException(status_code=400, detail="This status is set automatically")
    store.update_rows(
        "invoices",
        predicate=lambda row: row["invoice_id"] == invoice_id,
        updater=lambda row: {**row, "status": payload.status},
    )
    return _invoice_payload(invoice_id)


@app.put("/api/invoices/{invoice_id}")
def update_invoice(
    invoice_id: str,
    payload: InvoiceUpdate,
    authorization: str | None = Header(default=None),
) -> dict:
    _require_admin(authorization)
    invoice = _invoice_or_404(invoice_id)
    store.update_rows(
        "invoices",
        predicate=lambda row: row["invoice_id"] == invoice_id,
        updater=lambda row: {
            **row,
            "shipper_name": payload.shipper_name,
            "shipper_phone": payload.shipper_phone,
            "consignee_name": payload.consignee_name,
            "consignee_phone": payload.consignee_phone,
            "creation_date": payload.creation_date.isoformat(),
            "issued_date": payload.issued_date.isoformat(),
            "pdf_file": "",
            "tariff_price_per_kg": invoice.get("tariff_price_per_kg", ""),
            "tariff_price_per_m3": invoice.get("tariff_price_per_m3", ""),
            "status": invoice.get("status", "formed"),
        },
    )

    new_items: list[dict[str, str]] = []
    for item in payload.items:
        new_items.append(
            {
                "item_id": str(uuid.uuid4()),
                "invoice_id": invoice_id,
                "name": item.name,
                "unit": item.unit,
                "quantity": str(item.quantity),
                "weight_kg": _fmt2(round(item.weight_kg, 2)),
                "volume_m3": _fmt2(round(item.volume_m3, 2)),
                "measure": item.measure,
                "unit_price": "",
                "line_total_weight": "",
                "line_total_volume": "",
                "line_total": "",
            }
        )
    _replace_invoice_items(invoice_id, new_items)
    _recalculate_invoice_with_tariff(invoice_id)
    return _invoice_payload(invoice_id)


@app.delete("/api/invoices/{invoice_id}")
def delete_invoice(invoice_id: str, authorization: str | None = Header(default=None)) -> dict[str, str]:
    _require_admin(authorization)
    invoice = _invoice_or_404(invoice_id)
    store.delete_rows("wagon_allocations", lambda row: row["invoice_id"] == invoice_id)
    store.delete_rows("invoice_items", lambda row: row["invoice_id"] == invoice_id)
    deleted = store.delete_rows("invoices", lambda row: row["invoice_id"] == invoice_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Invoice not found")

    pdf_ref = invoice.get("pdf_file", "")
    if pdf_ref:
        pdf_path = Path(pdf_ref)
        if not pdf_path.is_absolute():
            pdf_path = BASE_DIR / pdf_ref
        if pdf_path.exists():
            try:
                pdf_path.unlink()
            except OSError:
                pass
    return {"status": "deleted"}


@app.get("/api/wagons")
def list_wagons(authorization: str | None = Header(default=None)) -> dict[str, list[dict[str, str]]]:
    _current_user(authorization)
    wagons = store.list_rows("wagons")
    wagons.sort(key=lambda row: row["created_at"], reverse=True)
    payload: list[dict[str, str]] = []
    for wagon in wagons:
        usage = _wagon_usage(wagon["wagon_id"])
        payload.append(
            {
                **wagon,
                "max_weight_kg": _fmt2(usage["max_weight_kg"]),
                "max_volume_m3": _fmt2(usage["max_volume_m3"]),
                "used_weight_kg": _fmt2(usage["used_weight_kg"]),
                "used_volume_m3": _fmt2(usage["used_volume_m3"]),
                "remaining_weight_kg": _fmt2(usage["remaining_weight_kg"]),
                "remaining_volume_m3": _fmt2(usage["remaining_volume_m3"]),
            }
        )
    return {"wagons": payload}


@app.get("/api/wagons/{wagon_id}/capacity")
def wagon_capacity(
    wagon_id: str, invoice_id: str | None = Query(default=None), authorization: str | None = Header(default=None)
) -> dict[str, str | bool]:
    _current_user(authorization)
    if not any(x["wagon_id"] == wagon_id for x in store.list_rows("wagons")):
        raise HTTPException(status_code=404, detail="Wagon not found")
    usage = _wagon_usage(wagon_id)
    invoice_weight = 0.0
    invoice_volume = 0.0
    fits_full = False
    if invoice_id:
        items = _items_by_invoice(invoice_id)
        invoice_weight = sum(_to_float(x.get("weight_kg")) * _to_int(x.get("quantity")) for x in items)
        invoice_volume = sum(_to_float(x.get("volume_m3")) * _to_int(x.get("quantity")) for x in items)
        fits_full = invoice_weight <= usage["remaining_weight_kg"] and invoice_volume <= usage["remaining_volume_m3"]

    return {
        "max_weight_kg": _fmt2(usage["max_weight_kg"]),
        "max_volume_m3": _fmt2(usage["max_volume_m3"]),
        "used_weight_kg": _fmt2(usage["used_weight_kg"]),
        "used_volume_m3": _fmt2(usage["used_volume_m3"]),
        "remaining_weight_kg": _fmt2(usage["remaining_weight_kg"]),
        "remaining_volume_m3": _fmt2(usage["remaining_volume_m3"]),
        "invoice_weight_kg": _fmt2(invoice_weight),
        "invoice_volume_m3": _fmt2(invoice_volume),
        "fits_full_invoice": fits_full,
    }


@app.post("/api/wagons")
def create_or_update_wagon(payload: WagonCreate, authorization: str | None = Header(default=None)) -> dict[str, str]:
    _current_user(authorization)
    wagons = store.list_rows("wagons")
    incoming_code = (payload.wagon_code or "").strip()
    for wagon in wagons:
        if incoming_code and wagon["wagon_code"].strip().lower() == incoming_code.lower():
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
            "wagon_code": incoming_code or _next_wagon_code(),
            "destination": payload.destination or "",
            "description": payload.description or "",
        },
    )


@app.get("/api/allocations")
def list_allocations(
    invoice_id: str | None = Query(default=None), authorization: str | None = Header(default=None)
) -> dict[str, list[dict[str, str]]]:
    _current_user(authorization)
    allocations = store.list_rows("wagon_allocations")
    if invoice_id:
        allocations = [row for row in allocations if row["invoice_id"] == invoice_id]
    allocations.sort(key=lambda row: row["created_at"], reverse=True)
    return {"allocations": allocations}


@app.post("/api/allocations")
def create_allocation(payload: WagonAllocationCreate, authorization: str | None = Header(default=None)) -> dict[str, str]:
    _current_user(authorization)
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
            "allocation_weight_kg": "0.00",
            "allocation_volume_m3": "0.00",
        },
    )


@app.post("/api/wagon-assignments")
def assign_invoice_to_wagon(payload: WagonAssignRequest, authorization: str | None = Header(default=None)) -> dict:
    _current_user(authorization)
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
    moved_total_weight = 0.0
    moved_total_volume = 0.0
    for item in items:
        original_qty = _to_int(item["quantity"])
        moved_qty = moved_quantity_by_item.get(item["item_id"], 0)
        if moved_qty < 0 or moved_qty > original_qty:
            raise HTTPException(status_code=400, detail=f"Invalid quantity for item line {item['line_no']}")

        if moved_qty > 0:
            item_weight = _to_float(item["weight_kg"])
            item_volume = _to_float(item["volume_m3"])
            moved_weight = item_weight * moved_qty
            moved_volume = item_volume * moved_qty
            moved_total_weight += moved_weight
            moved_total_volume += moved_volume
            moved_rows.append(
                {
                    **item,
                    "quantity": str(moved_qty),
                    "weight_kg": _fmt2(item_weight),
                    "volume_m3": _fmt2(item_volume),
                }
            )

        remaining_qty = original_qty - moved_qty
        if remaining_qty > 0:
            remaining_rows.append(
                {
                    **item,
                    "quantity": str(remaining_qty),
                    "weight_kg": _fmt2(_to_float(item["weight_kg"])),
                    "volume_m3": _fmt2(_to_float(item["volume_m3"])),
                    "unit_price": "",
                    "line_total_weight": "",
                    "line_total_volume": "",
                    "line_total": "",
                }
            )

    if not moved_rows:
        raise HTTPException(status_code=400, detail="Nothing was assigned to wagon")

    usage = _wagon_usage(payload.wagon_id)
    if moved_total_weight > usage["remaining_weight_kg"] or moved_total_volume > usage["remaining_volume_m3"]:
        raise HTTPException(
            status_code=400,
            detail=(
                "Not enough wagon capacity. "
                f"Remaining: {usage['remaining_weight_kg']:.2f} kg / {usage['remaining_volume_m3']:.2f} m3"
            ),
        )

    for item in moved_rows:
        moved_qty = _to_int(item["quantity"])
        alloc_weight = _to_float(item["weight_kg"]) * moved_qty
        alloc_volume = _to_float(item["volume_m3"]) * moved_qty
        store.append_row(
            "wagon_allocations",
            {
                "allocation_id": str(uuid.uuid4()),
                "invoice_id": payload.invoice_id,
                "item_id": item["item_id"],
                "wagon_id": payload.wagon_id,
                "allocation_measure": "quantity",
                "allocation_value": str(moved_qty),
                "allocation_weight_kg": _fmt2(round(alloc_weight, 2)),
                "allocation_volume_m3": _fmt2(round(alloc_volume, 2)),
            },
        )

    _replace_invoice_items(payload.invoice_id, moved_rows)
    store.update_rows(
        "invoices",
        predicate=lambda row: row["invoice_id"] == payload.invoice_id,
        updater=lambda row: {
            **row,
            "estimated_release_date": payload.estimated_release_date.isoformat(),
            "status": "loading",
        },
    )
    _recalculate_invoice_with_tariff(payload.invoice_id)

    new_invoice_id = ""
    if remaining_rows:
        new_invoice_id = str(uuid.uuid4())
        new_invoice_number = _next_invoice_number()
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
                "status": "formed",
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
                    "line_total_weight": "",
                    "line_total_volume": "",
                    "line_total": "",
                },
            )

    response: dict[str, object] = {"assigned_invoice": _invoice_payload(payload.invoice_id)}
    if new_invoice_id:
        response["new_invoice"] = _invoice_payload(new_invoice_id)
    return response
