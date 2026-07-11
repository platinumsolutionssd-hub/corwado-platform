"""
Pydantic schemas — API contracts. Kept separate from SQLAlchemy models
so the API shape can stay stable even if the DB schema evolves.
"""
from datetime import date, datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel


class LandStewardCreate(BaseModel):
    role: str  # smallholder_farmer | cooperative_member | investor_partner | land_owner
    full_name: str
    phone_number: Optional[str] = None
    whatsapp_number: Optional[str] = None
    preferred_language: str = "juba_arabic"
    preferred_channel: Optional[str] = None  # sms|ussd|ivr|whatsapp|radio|in_person
    gender: Optional[str] = None
    is_youth: bool = False
    has_disability: bool = False
    disability_notes: Optional[str] = None
    cooperative_id: Optional[UUID] = None
    registered_by: Optional[str] = None
    registered_offline: bool = False


class LandStewardOut(LandStewardCreate):
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class ParcelGeoJSON(BaseModel):
    """Parcel boundary submitted as GeoJSON polygon coordinates."""
    steward_id: UUID
    geojson: dict  # {"type": "Polygon", "coordinates": [[[lon,lat], ...]]}


class ParcelOut(BaseModel):
    id: UUID
    steward_id: UUID
    area_acres: Optional[float]
    elevation_m: Optional[float]
    soil_type: Optional[str]
    # baseline_suitability/baseline_computed_at dropped (see db/schema.sql
    # migration, post-Day 14): baseline is now per parcel+crop, in
    # parcel_crop_baseline, not a single value per parcel.

    class Config:
        from_attributes = True


class AdvisoryOutput(BaseModel):
    """
    The shared Advisory Output Schema — same shape regardless of whether
    it came from the in-house Digital Twin or Satyukt's Sat2Farm/Sat4Risk.
    """
    parcel_id: UUID
    source: str  # digital_twin | satyukt_sat2farm | satyukt_sat4risk | satyukt_sat4agri
    soil_n: Optional[float] = None
    soil_p: Optional[float] = None
    soil_k: Optional[float] = None
    soil_soc: Optional[float] = None
    soil_ph: Optional[float] = None
    ndvi: Optional[float] = None
    evi: Optional[float] = None
    soil_moisture: Optional[float] = None
    weather_forecast_json: Optional[dict] = None
    pest_disease_alerts: Optional[list] = None
    generated_at: datetime


class PriceBoardEntryCreate(BaseModel):
    crop_id: UUID
    market_location: str
    price_ssp: float
    unit: str = "kg"
    recorded_by: Optional[str] = None


class BuyerPostingCreate(BaseModel):
    buyer_id: UUID
    crop_id: UUID
    quantity_kg: float
    offer_price_ssp: float
    needed_by: Optional[date] = None
    location: Optional[str] = None
