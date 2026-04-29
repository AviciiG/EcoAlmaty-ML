from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import random
import numpy as np
import pandas as pd
import torch
from chronos import BaseChronosPipeline

DEVICE = "cpu"
DTYPE = torch.float32
RANDOM_SEED = 42

INITIAL_CONDITIONS_YEAR = 2025
START_YEAR = 2026
BASE_YEAR = 2024

POPULATION_IMPACT = 0.2
TRANSPORT_IMPACT = 0.6

BOUNDS = {
    "CO_mg_m3":         (0.0, 15.0),
    "NO2_mg_m3":        (0.0, 0.8),
    "SO2_mg_m3":        (0.0, 0.5),
    "TSP_mg_m3":        (0.0, 0.8),
    "population_total": (1_000_000, 8_000_000),
    "transport_total":  (10_000, 5_000_000),
}

POLLUTANTS = ["CO_mg_m3", "NO2_mg_m3", "SO2_mg_m3", "TSP_mg_m3"]


@dataclass
class ForecastResult:
    metric: str
    years: List[int]
    p10: List[float]
    p50: List[float]
    p90: List[float]


_PIPELINE_CACHE: dict = {}


def _load_pipeline(model_name: str = "amazon/chronos-t5-small") -> BaseChronosPipeline:
    if model_name not in _PIPELINE_CACHE:
        print(f"Loading model: {model_name}")
        _PIPELINE_CACHE[model_name] = BaseChronosPipeline.from_pretrained(
            model_name,
            device_map=DEVICE,
            dtype=DTYPE,
        )
    return _PIPELINE_CACHE[model_name]


def _clip(values: np.ndarray, metric: str) -> np.ndarray:
    lo, hi = BOUNDS.get(metric, (None, None))
    if lo is not None and hi is not None:
        values = np.clip(values, lo, hi)
    return values


def _apply_driver_impacts(
    forecast: np.ndarray,
    pop_growth: float,
    transport_growth: float,
) -> np.ndarray:
    impact = 1.0 + POPULATION_IMPACT * pop_growth + TRANSPORT_IMPACT * transport_growth
    return forecast * impact


def _read_csv_safe(path: str) -> Optional[pd.DataFrame]:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return pd.read_csv(p)
    except Exception:
        return None


def _get_annual_growth(series: pd.Series) -> float:
    vals = series.dropna().values
    if len(vals) < 2 or vals[0] == 0:
        return 0.0
    total = (vals[-1] - vals[0]) / abs(vals[0])
    annual = total / max(len(vals) - 1, 1)
    return float(np.clip(annual, -0.5, 0.5))


def _build_history(df: pd.DataFrame, metric: str) -> Optional[np.ndarray]:
    sub = df[(df["metric"] == metric) & (df["year"] <= BASE_YEAR)].sort_values("year")
    if len(sub) < 4:
        return None
    return sub["value"].values.astype(np.float32)


def _run_chronos_forecast(
    pipeline: BaseChronosPipeline,
    history: np.ndarray,
    horizon: int,
    quantile_levels: List[float] = [0.1, 0.5, 0.9],
) -> Dict[str, np.ndarray]:
    context_tensor = torch.tensor(history, dtype=DTYPE).unsqueeze(0)  # [1, T]
    quantiles, _ = pipeline.predict_quantiles(
        context_tensor,
        prediction_length=horizon,
        quantile_levels=quantile_levels,
    )
    q = quantiles[0].numpy()
    return {
        "p10": q[:, 0],
        "p50": q[:, 1],
        "p90": q[:, 2],
    }


def _parse_air_yearly(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower().strip() for c in df.columns]

    if "value_year" in df.columns and "value" not in df.columns:
        df = df.rename(columns={"value_year": "value"})

    df["year"]  = pd.to_numeric(df["year"],  errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    return df[["metric", "year", "value"]].dropna()


def _parse_population(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower().strip() for c in df.columns]

    if "population" in df.columns:
        df = df.rename(columns={"population": "value"})

    df["year"]   = pd.to_numeric(df["year"],  errors="coerce")
    df["value"]  = pd.to_numeric(df["value"], errors="coerce")
    df["metric"] = "population_total"

    return df[["metric", "year", "value"]].dropna()


def _parse_transport(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [c.lower().strip() for c in df.columns]

    df["year"]  = pd.to_numeric(df["year"],  errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["year", "value"])

    grouped = df.groupby("year", as_index=False)["value"].sum()
    grouped["value"] = grouped["value"] * 1000  # thousands → units
    grouped["metric"] = "transport_total"

    return grouped[["metric", "year", "value"]]


def _build_long_format(
    air_df: pd.DataFrame,
    pop_df: Optional[pd.DataFrame],
    trn_df: Optional[pd.DataFrame],
) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []

    air_long = _parse_air_yearly(air_df)
    if not air_long.empty:
        frames.append(air_long)

    if pop_df is not None:
        pop_long = _parse_population(pop_df)
        if not pop_long.empty:
            frames.append(pop_long)

    if trn_df is not None:
        trn_long = _parse_transport(trn_df)
        if not trn_long.empty:
            frames.append(trn_long)

    if not frames:
        raise ValueError("Нет данных для прогноза!")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined[combined["year"] <= BASE_YEAR]
    return combined


def run_full_forecast(
    population_csv: str,
    transport_csv: str,
    air_yearly_csv: str,
    air_yearly_extra_csv: str,
    horizon: int = 80,
    model_name: str = "amazon/chronos-t5-small",
) -> pd.DataFrame:
    """
    Запускает полный прогноз через Chronos.
    Возвращает DataFrame: year, metric, p10, p50, p90
    Годы начинаются с 2026.
    """

    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)
    torch.manual_seed(RANDOM_SEED)

    pop_df  = _read_csv_safe(population_csv)
    trn_df  = _read_csv_safe(transport_csv)
    air_df  = _read_csv_safe(air_yearly_csv)

    if air_df is None:
        raise ValueError("Главный файл воздушных данных не найден!")

    all_series = _build_long_format(air_df, pop_df, trn_df)

    pop_growth = 0.0
    trn_growth = 0.0

    pop_sub = all_series[
        (all_series["metric"] == "population_total") &
        (all_series["year"] <= BASE_YEAR)
    ]["value"]
    if not pop_sub.empty:
        pop_growth = _get_annual_growth(pop_sub)

    trn_sub = all_series[
        (all_series["metric"] == "transport_total") &
        (all_series["year"] <= BASE_YEAR)
    ]["value"]
    if not trn_sub.empty:
        trn_growth = _get_annual_growth(trn_sub)

    pipeline = _load_pipeline(model_name)

    results: List[dict] = []
    metrics = all_series["metric"].unique()
    print(f"Forecasting: {metrics.tolist()}")

    for metric in metrics:
        history = _build_history(all_series, metric)

        if history is None:
            continue

        try:
            fc = _run_chronos_forecast(pipeline, history, horizon)

            if metric in POLLUTANTS:
                for key in ["p10", "p50", "p90"]:
                    fc[key] = _apply_driver_impacts(fc[key], pop_growth, trn_growth)

            for key in ["p10", "p50", "p90"]:
                fc[key] = _clip(fc[key], metric)

            years = list(range(START_YEAR, START_YEAR + horizon))
            for i, year in enumerate(years):
                results.append({
                    "year":   year,
                    "metric": metric,
                    "p10":    round(float(fc["p10"][i]), 6),
                    "p50":    round(float(fc["p50"][i]), 6),
                    "p90":    round(float(fc["p90"][i]), 6),
                })

        except Exception as e:
            print(f"Skipping {metric}: {e}")
            continue

    if not results:
        raise ValueError("Не удалось построить ни одного прогноза!")

    return pd.DataFrame(results)