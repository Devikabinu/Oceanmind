import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.alerts import router as alerts_router
from app.api.v1.alignment import router as alignment_router
from app.api.v1.anomaly import router as anomaly_router
from app.api.v1.auth import router as auth_router
from app.api.v1.biodiversity_observations import router as biodiversity_observations_router
from app.api.v1.data_quality import router as data_quality_router
from app.api.v1.data_sources import router as data_sources_router
from app.api.v1.datasets import router as datasets_router
from app.api.v1.forecast import router as forecast_router
from app.api.v1.ingestion import router as ingestion_router
from app.api.v1.ocean_observations import router as ocean_observations_router
from app.api.v1.risk import router as risk_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.seed import seed_data_sources
from app.db.session import SessionLocal

configure_logging()
logger = logging.getLogger("ocean_platform")

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    db = SessionLocal()
    try:
        seed_data_sources(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Ocean Environmental Intelligence Platform - Module 1",
    description="User & Ocean Data Management: auth, data-source registry, "
    "multi-source ingestion, data quality, and spatiotemporal fusion.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router, prefix="/api")
app.include_router(data_sources_router, prefix="/api")
app.include_router(datasets_router, prefix="/api")
app.include_router(ingestion_router, prefix="/api")
app.include_router(ocean_observations_router, prefix="/api")
app.include_router(biodiversity_observations_router, prefix="/api")
app.include_router(data_quality_router, prefix="/api")
app.include_router(alignment_router, prefix="/api")
app.include_router(forecast_router, prefix="/api")
app.include_router(anomaly_router, prefix="/api")
app.include_router(risk_router, prefix="/api")
app.include_router(alerts_router, prefix="/api")
