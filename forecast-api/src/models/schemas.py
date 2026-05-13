from pydantic import BaseModel, Field
from typing import List, Optional


# ========== REQUESTS ==========

class ForecastRequest(BaseModel):
    horizon: int = Field(
        default=10,
        ge=1,
        le=200,
        description="Горизонт прогноза в годах начиная с 2026",
        examples=[10],
    )
    metrics: Optional[List[str]] = Field(
        default=None,
        description=(
            "Фильтр метрик. Если не передать — вернёт все. "
            "Доступные: CO_mg_m3, NO2_mg_m3, SO2_mg_m3, TSP_mg_m3, population_total, transport_total"
        ),
        examples=[["CO_mg_m3", "NO2_mg_m3"]],
    )


# ========== RESPONSES ==========

class ForecastPoint(BaseModel):
    year: int = Field(description="Год прогноза (начиная с 2026)")
    metric: str = Field(description="Название метрики")
    p10: float = Field(description="10-й перцентиль (оптимистичный)")
    p50: float = Field(description="50-й перцентиль (медиана, базовый прогноз)")
    p90: float = Field(description="90-й перцентиль (пессимистичный)")


class ForecastResponse(BaseModel):
    status: str = "success"
    horizon: int
    start_year: int = 2026
    metrics_returned: int
    total_points: int
    data: List[ForecastPoint]


class MetricsResponse(BaseModel):
    available_metrics: List[str]
    descriptions: dict


class HealthResponse(BaseModel):
    status: str
    model: str
    version: str
    data_files_ok: bool
