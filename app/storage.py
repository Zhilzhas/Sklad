from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sqlalchemy import Column, MetaData, String, Table, create_engine, delete, insert, inspect, select, text


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
        "creation_date",
        "issued_date",
        "estimated_release_date",
        "tariff_price_per_kg",
        "tariff_price_per_m3",
        "status",
        "status_changed_at",
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
        "line_total_weight",
        "line_total_volume",
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
        "allocation_weight_kg",
        "allocation_volume_m3",
        "created_at",
        "updated_at",
    ],
    "users": [
        "user_id",
        "login",
        "password_hash",
        "role",
        "created_at",
        "updated_at",
    ],
    "idempotency_keys": [
        "idempotency_key",
        "route",
        "entity_id",
        "created_at",
        "updated_at",
    ],
}


class _CsvBackend:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
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

        migrated_rows = [{header: row.get(header, "") for header in headers} for row in rows]
        with table_path.open("w", newline="", encoding="utf-8") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=headers)
            writer.writeheader()
            writer.writerows(migrated_rows)

    def list_rows(self, table_name: str) -> list[dict[str, str]]:
        with self._table_path(table_name).open("r", newline="", encoding="utf-8") as file_obj:
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
        with self._table_path(table_name).open("a", newline="", encoding="utf-8") as file_obj:
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
            with self._table_path(table_name).open("w", newline="", encoding="utf-8") as file_obj:
                writer = csv.DictWriter(file_obj, fieldnames=headers)
                writer.writeheader()
                writer.writerows(rows)
        return changed

    def replace_rows(self, table_name: str, rows: list[dict[str, str]]) -> None:
        headers = TABLE_SCHEMAS[table_name]
        normalized_rows = [{header: str(row.get(header, "")) for header in headers} for row in rows]
        with self._table_path(table_name).open("w", newline="", encoding="utf-8") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=headers)
            writer.writeheader()
            writer.writerows(normalized_rows)

    def delete_rows(self, table_name: str, predicate: Callable[[dict[str, str]], bool]) -> int:
        rows = self.list_rows(table_name)
        kept_rows = [row for row in rows if not predicate(row)]
        deleted = len(rows) - len(kept_rows)
        if deleted:
            self.replace_rows(table_name, kept_rows)
        return deleted


class _SqlBackend:
    def __init__(self, database_url: str) -> None:
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+psycopg://", 1)
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        self.engine = create_engine(database_url, future=True, pool_pre_ping=True)
        self.metadata = MetaData()
        self.tables: dict[str, Table] = {}
        for table_name, headers in TABLE_SCHEMAS.items():
            columns = [Column(header, String, nullable=False, default="") for header in headers]
            self.tables[table_name] = Table(table_name, self.metadata, *columns)
        self.metadata.create_all(self.engine)
        self._ensure_missing_columns()

    def _ensure_missing_columns(self) -> None:
        inspector = inspect(self.engine)
        with self.engine.begin() as conn:
            for table_name, headers in TABLE_SCHEMAS.items():
                if table_name not in inspector.get_table_names():
                    continue
                existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
                missing_cols = [col for col in headers if col not in existing_cols]
                for col in missing_cols:
                    conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{col}" VARCHAR NOT NULL DEFAULT \'\''))

    def list_rows(self, table_name: str) -> list[dict[str, str]]:
        table = self.tables[table_name]
        with self.engine.begin() as conn:
            result = conn.execute(select(table))
            rows = []
            for row in result:
                mapping = row._mapping
                rows.append({key: str(mapping.get(key) or "") for key in TABLE_SCHEMAS[table_name]})
            return rows

    def append_row(self, table_name: str, row: dict[str, str]) -> dict[str, str]:
        headers = TABLE_SCHEMAS[table_name]
        now = now_iso()
        row_with_timestamps = {**row}
        if "created_at" in headers and not row_with_timestamps.get("created_at"):
            row_with_timestamps["created_at"] = now
        if "updated_at" in headers:
            row_with_timestamps["updated_at"] = now
        normalized = {header: str(row_with_timestamps.get(header, "")) for header in headers}
        with self.engine.begin() as conn:
            conn.execute(insert(self.tables[table_name]).values(**normalized))
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
            self.replace_rows(table_name, rows)
        return changed

    def replace_rows(self, table_name: str, rows: list[dict[str, str]]) -> None:
        headers = TABLE_SCHEMAS[table_name]
        normalized_rows = [{header: str(row.get(header, "")) for header in headers} for row in rows]
        with self.engine.begin() as conn:
            conn.execute(delete(self.tables[table_name]))
            if normalized_rows:
                conn.execute(insert(self.tables[table_name]), normalized_rows)

    def delete_rows(self, table_name: str, predicate: Callable[[dict[str, str]], bool]) -> int:
        rows = self.list_rows(table_name)
        kept_rows = [row for row in rows if not predicate(row)]
        deleted = len(rows) - len(kept_rows)
        if deleted:
            self.replace_rows(table_name, kept_rows)
        return deleted


@dataclass
class CsvStore:
    base_dir: Path

    def __post_init__(self) -> None:
        database_url = os.getenv("DATABASE_URL", "").strip()
        if database_url:
            self._backend = _SqlBackend(database_url)
            self.backend_type = "sql"
        else:
            self._backend = _CsvBackend(self.base_dir)
            self.backend_type = "csv"

    def list_rows(self, table_name: str) -> list[dict[str, str]]:
        return self._backend.list_rows(table_name)

    def append_row(self, table_name: str, row: dict[str, str]) -> dict[str, str]:
        return self._backend.append_row(table_name, row)

    def update_rows(
        self,
        table_name: str,
        predicate: Callable[[dict[str, str]], bool],
        updater: Callable[[dict[str, str]], dict[str, str]],
    ) -> int:
        return self._backend.update_rows(table_name, predicate, updater)

    def replace_rows(self, table_name: str, rows: list[dict[str, str]]) -> None:
        self._backend.replace_rows(table_name, rows)

    def delete_rows(self, table_name: str, predicate: Callable[[dict[str, str]], bool]) -> int:
        return self._backend.delete_rows(table_name, predicate)
