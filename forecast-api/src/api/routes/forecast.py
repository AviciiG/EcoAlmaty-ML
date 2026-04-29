import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException

_ML_SRC = Path(__file__).resolve().parents[4] / "src"
if str(_ML_SRC) not in sys.path:
    sys.path.insert(0, str(_ML_SRC))

from forecast_core import run_full_forecast

from src.config import settings
from src.models.schemas import (
    ForecastRequest,
    ForecastResponse,
    ForecastPoint,
    MetricsResponse,
    HealthResponse,
)

router = APIRouter(prefix="/forecast", tags=["Forecast"])

AVAILABLE_METRICS = {
    "CO_mg_m3":         "Оксид углерода CO (мг/м³)",
    "NO2_mg_m3":        "Диоксид азота NO₂ (мг/м³)",
    "SO2_mg_m3":        "Диоксид серы SO₂ (мг/м³)",
    "TSP_mg_m3":        "Взвешенные TSP (мг/м³)",
    "population_total": "Население Алматы (чел.)",
    "transport_total":  "Транспортные средства (ед.)",
}


@router.post(
    "/",
    response_model=ForecastResponse,
    summary="Запустить ML прогноз",
    description=(
        "Запускает модель Chronos и возвращает прогноз для Алматы начиная с 2026 года. "
        "Можно передать metrics для фильтрации. "
        "Внимание: первый запрос запусчает загрузку модели (~10-30 сек)."
    ),
)
async def get_forecast(request: ForecastRequest):
    # Валидация метрик
    if request.metrics:
        invalid = [m for m in request.metrics if m not in AVAILABLE_METRICS]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Неизвестные метрики: {invalid}. Доступные: {list(AVAILABLE_METRICS.keys())}",
            )

    try:
        df = run_full_forecast(
            population_csv=str(settings.BASE_DIR / settings.POPULATION_CSV),
            transport_csv=str(settings.BASE_DIR / settings.TRANSPORT_CSV),
            air_yearly_csv=str(settings.BASE_DIR / settings.AIR_YEARLY_CSV),
            air_yearly_extra_csv=str(settings.BASE_DIR / settings.AIR_YEARLY_EXTRA_CSV),
            horizon=request.horizon,
            model_name=settings.CHRONOS_MODEL,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка ML модели: {str(e)}")

    if request.metrics:
        df = df[df["metric"].isin(request.metrics)]

    points = [
        ForecastPoint(
            year=int(row["year"]),
            metric=str(row["metric"]),
            p10=float(row["p10"]),
            p50=float(row["p50"]),
            p90=float(row["p90"]),
        )
        for _, row in df.iterrows()
    ]

    return ForecastResponse(
        status="success",
        horizon=request.horizon,
        start_year=2026,
        metrics_returned=df["metric"].nunique(),
        total_points=len(points),
        data=points,
    )


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Список доступных метрик",
)
async def get_metrics():
    return MetricsResponse(
        available_metrics=list(AVAILABLE_METRICS.keys()),
        descriptions=AVAILABLE_METRICS,
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Статус сервиса",
)
async def health_check():
    files_ok = all([
        (settings.BASE_DIR / settings.POPULATION_CSV).exists(),
        (settings.BASE_DIR / settings.TRANSPORT_CSV).exists(),
        (settings.BASE_DIR / settings.AIR_YEARLY_CSV).exists(),
    ])
    return HealthResponse(
        status="ok" if files_ok else "degraded",
        model=settings.CHRONOS_MODEL,
        version=settings.API_VERSION,
        data_files_ok=files_ok,
    )
