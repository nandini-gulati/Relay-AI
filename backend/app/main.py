"""Relay FastAPI Main Application Entry Point."""

from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth_routes import auth_router
from app.config import settings
from app.db import init_db
from app.routes import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("relay")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle hook: initialize database schema on startup."""
    logger.info("Initializing database schema and connection pool...")
    init_db()
    logger.info(
        f"Relay backend started successfully. Configured keys: {len(settings.KEY_POOL)}, "
        f"Model: {settings.LLM_MODEL}, Simulation enabled: {settings.ENABLE_FAILURE_SIMULATION}"
    )
    yield


app = FastAPI(
    title="Relay AI Gateway API",
    description="Resilient LLM Gateway with key failover, response caching, and session memory.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS Middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS if "*" not in settings.ALLOWED_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception Handlers ensuring JSON with a "detail" field at all times
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Ensure standard HTTP exceptions return JSON with detail field."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Ensure request validation errors return 422 JSON with detail field."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": jsonable_encoder(exc.errors(), custom_encoder={Exception: str})},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler preventing unhandled stack traces or HTML errors."""
    logger.error(f"Unhandled exception during {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred"},
    )


# Include endpoints
app.include_router(auth_router)
app.include_router(router)
