"""FloraMW Backend Application Entrypoint.

Provides the FastAPI application factory, lifespan management,
CORS configuration, router mounting, and health checks.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_engine, Base, get_db, AsyncSessionLocal
from app.core.readiness import verify_database_readiness
from app.core.seed import seed_all
from app.api.v1.api import api_router

logger = logging.getLogger("floramw.startup")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context manager for startup and shutdown tasks."""
    # 1. Startup: Verify database schema readiness (owned by Alembic)
    async with async_engine.connect() as conn:
        await conn.run_sync(verify_database_readiness)

    # 2. Seed initial reference data (districts and plants) if not already populated
    async with AsyncSessionLocal() as session:
        await seed_all(session)

    yield

    # 3. Shutdown: Dispose of the database engine pool
    await async_engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="FloraMW Botanical Field Observation and Plant Identification Platform API",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API v1 router
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint providing service information."""
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "api_v1": f"{settings.API_V1_STR}",
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"], status_code=status.HTTP_200_OK)
async def health_check(db: AsyncSession = Depends(get_db)):
    """Comprehensive health check verifying application and database readiness."""
    db_status = "connected"
    try:
        await db.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"unhealthy: {exc}"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
    }

