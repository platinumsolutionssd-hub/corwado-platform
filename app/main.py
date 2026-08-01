"""
CORWADO Agricultural Extension & Market Linkage Platform
FastAPI application entrypoint.

Run locally with:
    uvicorn app.main:app --reload

Requires a PostgreSQL + PostGIS database. See db/schema.sql for the schema
and .env.example for connection settings.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import stewards, parcels, advisory, market, dispatch, seasons, inputs, authorized_operators, telegram

app = FastAPI(
    title="CORWADO Agricultural Extension & Market Linkage Platform",
    description=(
        "Core API serving the CORWADO farmer registration, advisory, "
        "and market-linkage front-end, per ToR-001-06-2026."
    ),
    version="0.1.0",
)

# Permissive for local dev / demo; tighten before any real deployment
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stewards.router, prefix="/api/stewards", tags=["Land Stewards"])
app.include_router(parcels.router, prefix="/api/parcels", tags=["Parcels"])
app.include_router(advisory.router, prefix="/api/advisory", tags=["Advisory"])
app.include_router(market.router, prefix="/api/market", tags=["Market Linkage"])
app.include_router(dispatch.router, prefix="/api/dispatch", tags=["Message Dispatch"])
app.include_router(seasons.router, prefix="/api/seasons", tags=["Season Planting"])
app.include_router(inputs.router, prefix="/api/inputs", tags=["Bill of Quantities"])
app.include_router(authorized_operators.router, prefix="/api/authorized-operators", tags=["Authorized Operators"])
app.include_router(telegram.router, prefix="/api/telegram", tags=["Telegram Webhook"])


@app.get("/api/health")
def health_check():
    return {"status": "ok", "platform": "CORWADO LAST Project — ToR-001-06-2026"}
