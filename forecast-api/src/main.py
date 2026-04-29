from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.api.routes.forecast import router as forecast_router
from src.api.routes.bot import router as bot_router

app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
    description="""
## Almaty Air Quality Forecast API

Модель **Chronos (Amazon)** для прогнозирования качества воздуха, населения и транспорта в Алматы.
Прогноз начинается с **2026 года**.

### Эндпоинты:
- `POST /api/v1/forecast/` — запустить ML прогноз
- `GET  /api/v1/forecast/metrics` — список доступных метрик
- `GET  /api/v1/forecast/health` — статус сервиса
    """,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(forecast_router, prefix="/api/v1")
app.include_router(bot_router, prefix="/api/v1")


@app.get("/", tags=["Root"])
async def root():
    return {
        "message": "Almaty Air Quality Forecast API",
        "docs": "/docs",
        "version": settings.API_VERSION,
        "forecast_starts": 2026,
    }
