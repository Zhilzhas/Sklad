from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


TABLE_SCHEMAS: dict[str, list[str]] = {
    "invoices": [
        "invoice_id",
        "invoice_number",
        "shipper_name",
        "shipper_phone",
        "consignee_name",
        "consignee_phone",
        "issued_date",
        "tariff_price_per_kg",
        "tariff_price_per_m3",
        "total_amount",
        "pdf_file",
        "created_at",
        "updated_at",
    ],
    "invoice_items": [
        "item_id",
        "invoice_id",
        "line_no",
        "name",
        "unit",
        "quantity",
        "weight_kg",
        "volume_m3",
        "measure",
        "unit_price",
        "line_total",
        "created_at",
        "updated_at",
    ],
    "wagons": [
        "wagon_id",
        "wagon_code",
        "destination",
        "description",
        "created_at",
        "updated_at",
    ],
    "wagon_allocations": [
        "allocation_id",
        "invoice_id",
        "item_id",
        "wagon_id",
        "allocation_measure",
        "allocation_value",
        "created_at",
        "updated_at",
    ],
}


@dataclass
class CsvStore:
    base_dir: Path

    def __post_init__(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        for table_name, headers in TABLE_SCHEMAS.items():
            self._ensure_table(table_name, headers)

    def _table_path(self, table_name: str) -> Path:
        if table_name not in TABLE_SCHEMAS:
            raise ValueError(f"Unknown table: {table_name}")
        return self.base_dir / f"{table_name}.csv"

    def _ensure_table(self, table_name: str, headers: list[str]) -> None:
        table_path = self._table_path(table_name)
        if not table_path.exists():
            with table_path.open("w", newline="", encoding="utf-8") as file_obj:
                writer = csv.DictWriter(file_obj, fieldnames=headers)
                writer.writeheader()
            return

        with table_path.open("r", newline="", encoding="utf-8") as file_obj:
            reader = csv.DictReader(file_obj)
            existing_headers = reader.fieldnames or []
            rows = list(reader)

        if existing_headers == headers:
            return

        migrated_rows = []
        for row in rows:
            migrated_rows.append({header: row.get(header, "") for header in headers})

        with table_path.open("w", newline="", encoding="utf-8") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=headers)
            writer.writeheader()
            writer.writerows(migrated_rows)

    def list_rows(self, table_name: str) -> list[dict[str, str]]:
        table_path = self._table_path(table_name)
        with table_path.open("r", newline="", encoding="utf-8") as file_obj:
            reader = csv.DictReader(file_obj)
            return list(reader)

    def append_row(self, table_name: str, row: dict[str, str]) -> dict[str, str]:
        headers = TABLE_SCHEMAS[table_name]
        now = now_iso()
        row_with_timestamps = {**row}
        if "created_at" in headers and not row_with_timestamps.get("created_at"):
            row_with_timestamps["created_at"] = now
        if "updated_at" in headers:
            row_with_timestamps["updated_at"] = now

        normalized = {header: str(row_with_timestamps.get(header, "")) for header in headers}

        table_path = self._table_path(table_name)
        with table_path.open("a", newline="", encoding="utf-8") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=headers)
            writer.writerow(normalized)
        return normalized

    def update_rows(
        self,
        table_name: str,
        predicate: Callable[[dict[str, str]], bool],
        updater: Callable[[dict[str, str]], dict[str, str]],
    ) -> int:
        headers = TABLE_SCHEMAS[table_name]
        rows = self.list_rows(table_name)
        changed = 0
        for idx, row in enumerate(rows):
            if predicate(row):
                updated = updater(dict(row))
                updated["updated_at"] = now_iso()
                rows[idx] = {header: str(updated.get(header, row.get(header, ""))) for header in headers}
                changed += 1

        if changed:
            table_path = self._table_path(table_name)
            with table_path.open("w", newline="", encoding="utf-8") as file_obj:
                writer = csv.DictWriter(file_obj, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)
        return changed

    def replace_rows(self, table_name: str, rows: list[dict[str, str]]) -> None:
        headers = TABLE_SCHEMAS[table_name]
        normalized_rows = [{header: str(row.get(header, "")) for header in headers} for row in rows]
        table_path = self._table_path(table_name)
        with table_path.open("w", newline="", encoding="utf-8") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=headers)
            writer.writeheader()
            writer.writerows(normalized_rows)
