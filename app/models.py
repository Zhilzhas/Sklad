from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator


MeasureType = Literal["weight", "volume"]
AllocationMeasureType = Literal["quantity", "weight", "volume"]
UserRole = Literal["admin", "user"]
KZ_PHONE_PATTERN = r"^\+7\d{10}$"


class InvoiceItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    unit: str = Field(min_length=1, max_length=50, description="e.g. box, bag")
    quantity: int = Field(gt=0)
    weight_kg: float = Field(ge=0)
    volume_m3: float = Field(ge=0)
    measure: MeasureType

    @model_validator(mode="after")
    def ensure_selected_measure_has_value(self) -> "InvoiceItemCreate":
        if self.measure == "weight" and self.weight_kg <= 0:
            raise ValueError("For measure=weight, weight_kg must be > 0")
        if self.measure == "volume" and self.volume_m3 <= 0:
            raise ValueError("For measure=volume, volume_m3 must be > 0")
        return self


class InvoiceCreate(BaseModel):
    invoice_number: str | None = Field(default=None, min_length=1, max_length=100)
    shipper_name: str = Field(min_length=1, max_length=200)
    shipper_phone: str = Field(pattern=KZ_PHONE_PATTERN)
    consignee_name: str = Field(min_length=1, max_length=200)
    consignee_phone: str = Field(pattern=KZ_PHONE_PATTERN)
    creation_date: date
    issued_date: date
    items: list[InvoiceItemCreate] = Field(min_length=1)


class InvoiceUpdate(BaseModel):
    shipper_name: str = Field(min_length=1, max_length=200)
    shipper_phone: str = Field(pattern=KZ_PHONE_PATTERN)
    consignee_name: str = Field(min_length=1, max_length=200)
    consignee_phone: str = Field(pattern=KZ_PHONE_PATTERN)
    creation_date: date
    issued_date: date
    items: list[InvoiceItemCreate] = Field(min_length=1)


class TariffApply(BaseModel):
    price_per_kg: float = Field(ge=0)
    price_per_m3: float = Field(ge=0)


class WagonCreate(BaseModel):
    wagon_code: str | None = Field(default=None, min_length=1, max_length=100)
    destination: str | None = Field(default=None, max_length=150)
    description: str | None = Field(default=None, max_length=250)


class WagonAllocationCreate(BaseModel):
    invoice_id: str
    item_id: str
    wagon_id: str
    allocation_measure: AllocationMeasureType
    allocation_value: float = Field(gt=0)


class WagonAssignItem(BaseModel):
    item_id: str
    moved_quantity: int = Field(gt=0)


class WagonAssignRequest(BaseModel):
    invoice_id: str
    wagon_id: str
    estimated_release_date: date
    fully_loaded: bool
    items: list[WagonAssignItem] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_items_for_partial_load(self) -> "WagonAssignRequest":
        if not self.fully_loaded and not self.items:
            raise ValueError("When fully_loaded is false, items must be provided")
        return self


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=100)


class UserCreate(BaseModel):
    login: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=3, max_length=100)
    role: UserRole


class UserRoleUpdate(BaseModel):
    role: UserRole
