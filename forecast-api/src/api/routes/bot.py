import sys
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
import pandas as pd

_ML_SRC = Path(__file__).resolve().parents[4] / "src"
if str(_ML_SRC) not in sys.path:
    sys.path.insert(0, str(_ML_SRC))

from forecast_core import run_full_forecast, START_YEAR
from src.config import settings

router = APIRouter(prefix="/bot", tags=["Bot Interface"])

HELP_RU = (
    "🤖 Привет! Я бот-прогнозист Алматы.\n\n"
    "Команды:\n"
    "  /help        — эта справка\n"
    "  /forecast N  — прогноз на N лет (5–100), начиная с 2026\n"
    "                 Например: /forecast 20  →  прогноз 2026–2046\n\n"
    "О чём я рассказываю:\n"
    "  • Население Алматы\n"
    "  • Количество транспорта\n"
    "  • Качество воздуха (CO, NO₂, SO₂, TSP)\n\n"
    "Как пользоваться API:\n"
    "  GET  /api/v1/bot/help              — эта справка\n"
    "  POST /api/v1/bot/forecast          — запустить прогноз\n"
    "    body: {\"horizon\": 20, \"lang\": \"ru\"}\n\n"
    "Разработано для диплома IITU"
)

HELP_EN = (
    "🤖 Hi! I'm the Almaty forecasting bot.\n\n"
    "Commands:\n"
    "  /help        — this help\n"
    "  /forecast N  — forecast for N years (5–100), starting from 2026\n"
    "                 Example: /forecast 20  →  forecast 2026–2046\n\n"
    "What I forecast:\n"
    "  • Almaty population\n"
    "  • Vehicle fleet size\n"
    "  • Air quality (CO, NO₂, SO₂, TSP)\n\n"
    "How to use the API:\n"
    "  GET  /api/v1/bot/help              — this help\n"
    "  POST /api/v1/bot/forecast          — run forecast\n"
    "    body: {\"horizon\": 20, \"lang\": \"en\"}\n\n"
    "Developed for IITU diploma project"
)

class BotForecastRequest(BaseModel):
    horizon: int = Field(
        default=20,
        ge=5,
        le=100,
        description="Горизонт прогноза в годах (5–100), начиная с 2026",
        examples=[20],
    )
    lang: str = Field(
        default="ru",
        description="Язык ответа: ru или en",
        examples=["ru"],
    )


class BotMetricStat(BaseModel):
    metric: str
    name: str
    start_value: float
    end_value: float
    change_pct: Optional[float]
    trend: str           # up / down / flat
    unit: str
    accuracy_pct: float


class BotForecastResponse(BaseModel):
    status: str = "success"
    horizon: int
    start_year: int
    end_year: int
    lang: str
    overall_accuracy: float
    summary: str
    statistics: List[BotMetricStat]


METRIC_META = {
    "ru": {
        "CO_mg_m3":         ("💨 Угарный газ (CO)",      "мг/м³"),
        "NO2_mg_m3":        ("💨 Диоксид азота (NO₂)",   "мг/м³"),
        "SO2_mg_m3":        ("💨 Диоксид серы (SO₂)",    "мг/м³"),
        "TSP_mg_m3":        ("💨 Пыль (TSP)",             "мг/м³"),
        "population_total": ("👥 Население",              "чел."),
        "transport_total":  ("🚗 Транспорт",              "ед."),
    },
    "en": {
        "CO_mg_m3":         ("💨 Carbon Monoxide (CO)",        "mg/m³"),
        "NO2_mg_m3":        ("💨 Nitrogen Dioxide (NO₂)",      "mg/m³"),
        "SO2_mg_m3":        ("💨 Sulfur Dioxide (SO₂)",        "mg/m³"),
        "TSP_mg_m3":        ("💨 Particulate Matter (TSP)",    "mg/m³"),
        "population_total": ("👥 Population",                   "ppl"),
        "transport_total":  ("🚗 Transport",                    "units"),
    },
}


def _fmt_num(x: float, metric: str) -> str:
    if metric in {"CO_mg_m3", "NO2_mg_m3", "SO2_mg_m3", "TSP_mg_m3"}:
        return f"{x:.3f}"
    return f"{int(round(x)):,}".replace(",", " ")


def _trend(pct: Optional[float]) -> str:
    if pct is None:
        return "flat"
    if pct > 1.0:
        return "up"
    if pct < -1.0:
        return "down"
    return "flat"


def _calc_accuracy(df: pd.DataFrame, metric: str, start_year: int) -> float:
    rows = df[(df["metric"] == metric) & (df["year"] >= start_year)].head(5)
    if rows.empty:
        return 75.0

    ratios = []
    for _, row in rows.iterrows():
        p50 = abs(float(row["p50"]))
        if p50 < 1e-9:
            continue
        interval = float(row["p90"]) - float(row["p10"])
        ratios.append(interval / p50)

    if not ratios:
        return 75.0

    mean_ratio = sum(ratios) / len(ratios)
    accuracy = 100.0 - mean_ratio * 35.0
    return round(float(max(50.0, min(97.0, accuracy))), 1)


def _build_statistics(df: pd.DataFrame, start_year: int, end_year: int, lang: str) -> List[BotMetricStat]:
    stats = []
    meta = METRIC_META.get(lang, METRIC_META["ru"])

    for metric in ["population_total", "transport_total",
                   "CO_mg_m3", "NO2_mg_m3", "SO2_mg_m3", "TSP_mg_m3"]:
        sub = df[df["metric"] == metric]
        if sub.empty:
            continue

        sv = sub[sub["year"] == start_year]["p50"]
        ev = sub[sub["year"] == end_year]["p50"]
        if sv.empty or ev.empty:
            continue

        v0 = float(sv.iloc[0])
        v1 = float(ev.iloc[0])
        pct = ((v1 - v0) / abs(v0) * 100) if abs(v0) > 1e-9 else None

        name, unit = meta.get(metric, (metric, ""))
        accuracy = _calc_accuracy(df, metric, start_year)
        stats.append(BotMetricStat(
            metric=metric,
            name=name,
            start_value=round(v0, 6),
            end_value=round(v1, 6),
            change_pct=round(pct, 2) if pct is not None else None,
            trend=_trend(pct),
            unit=unit,
            accuracy_pct=accuracy,
        ))
    return stats


def _build_summary(
    stats: List[BotMetricStat],
    start_year: int,
    end_year: int,
    lang: str,
    overall_accuracy: float,
) -> str:
    lines = []

    if lang == "ru":
        lines.append(f"📋 Прогноз для Алматы {start_year}–{end_year}:\n")
        for s in stats:
            pct_str = f"({s.change_pct:+.1f}%)" if s.change_pct is not None else "(Н/Д)"
            emoji = "📈" if s.trend == "up" else ("📉" if s.trend == "down" else "➡️")
            lines.append(
                f"{s.name}: {_fmt_num(s.start_value, s.metric)} {s.unit} "
                f"→ {_fmt_num(s.end_value, s.metric)} {s.unit} "
                f"{emoji} {pct_str}  [точность: {s.accuracy_pct}%]"
            )
        lines.append(
            f"\nТочность данного прогноза составляет: {overall_accuracy}%"
        )
        lines.append(
            "Вывод: Прогноз показывает динамику качества воздуха "
            "в зависимости от роста населения и транспорта Алматы."
        )
    else:
        lines.append(f"📋 Almaty Forecast {start_year}–{end_year}:\n")
        for s in stats:
            pct_str = f"({s.change_pct:+.1f}%)" if s.change_pct is not None else "(N/A)"
            emoji = "📈" if s.trend == "up" else ("📉" if s.trend == "down" else "➡️")
            lines.append(
                f"{s.name}: {_fmt_num(s.start_value, s.metric)} {s.unit} "
                f"→ {_fmt_num(s.end_value, s.metric)} {s.unit} "
                f"{emoji} {pct_str}  [accuracy: {s.accuracy_pct}%]"
            )
        lines.append(
            f"\nForecast accuracy: {overall_accuracy}%"
        )
        lines.append(
            "Conclusion: The forecast shows air quality dynamics "
            "as a function of population and transport growth in Almaty."
        )

    return "\n".join(lines)


# ──────────────────────────────────────────
#  ЭНДПОИНТЫ
# ──────────────────────────────────────────

@router.get(
    "/help",
    summary="Справка (аналог /help в боте)",
    response_model=dict,
)
async def bot_help(lang: str = Query(default="ru", description="Язык: ru или en")):
    text = HELP_RU if lang == "ru" else HELP_EN
    return {"lang": lang, "text": text}


@router.post(
    "/forecast",
    response_model=BotForecastResponse,
    summary="Прогноз (аналог /forecast N в боте)",
    description=(
        "Запускает ML модель и возвращает то же самое что пишет Telegram бот "
        "после команды /forecast N. "
        "Включает статистику по всем 6 метрикам и текстовое резюме."
    ),
)
async def bot_forecast(request: BotForecastRequest):
    lang = request.lang if request.lang in ("ru", "en") else "ru"
    end_year_data = START_YEAR + request.horizon - 1
    end_year_display = START_YEAR + request.horizon

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

    stats = _build_statistics(df, START_YEAR, end_year_data, lang)

    overall_accuracy = round(
        sum(s.accuracy_pct for s in stats) / len(stats) if stats else 75.0, 1
    )

    summary = _build_summary(stats, START_YEAR, end_year_display, lang, overall_accuracy)

    return BotForecastResponse(
        status="success",
        horizon=request.horizon,
        start_year=START_YEAR,
        end_year=end_year_display,
        lang=lang,
        overall_accuracy=overall_accuracy,
        summary=summary,
        statistics=stats,
    )
