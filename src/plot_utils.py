from __future__ import annotations
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np

# Настройки для более красивого вывода
plt.style.use('ggplot')
plt.rcParams['figure.figsize'] = (10, 6)
plt.rcParams['font.size'] = 12

def _ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def _save_line_with_band(df: pd.DataFrame, metric: str, out_png: Path, title: str, ylabel: str):
    """
    Основная функция для отрисовки линии p50 с полосой p10–p90.
    """
    sub = df[df["metric"] == metric].sort_values("year")
    if sub.empty:
        # Это предотвратит ошибку, если для метрики нет данных
        return None

    fig = plt.figure(figsize=(8, 5), dpi=160)
    ax = plt.gca()

    # Полоса p10–p90
    ax.fill_between(sub["year"], sub["p10"], sub["p90"], alpha=0.25, color="#ff7f0e", label="Доверительный интервал (P10–P90)")
    # Линия p50
    ax.plot(sub["year"], sub["p50"], linewidth=2.5, color="#ff7f0e", label="P50 (Медиана прогноза)")

    ax.set_title(title, fontsize=14)
    ax.set_xlabel("Год", fontsize=12)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.grid(True, alpha=0.6, linestyle='--')
    ax.legend(loc="best", fontsize=10)
    
    # Настройка тиков по оси X для читаемости
    years = sub["year"].unique()
    if len(years) > 10:
        step = len(years) // 5
        ax.set_xticks(years[::step])
        ax.tick_params(axis='x', rotation=45)
    
    fig.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)
    return out_png

def make_forecast_plots(df: pd.DataFrame, out_dir: str = "data/processed/plots") -> Dict[str, str]:
    """
    На входе df из run_full_forecast (столбцы: metric, year, p10, p50, p90).
    Возвращает словарь метрика -> путь к PNG.
    """
    out = {}
    d = Path(out_dir)
    _ensure_dir(d)

    titles_and_labels = {
        "CO_mg_m3": ("Алматы — Угарный газ (CO) прогноз", "Концентрация, мг/м³"),
        "NO2_mg_m3": ("Алматы — Диоксид азота (NO₂) прогноз", "Концентрация, мг/м³"),
        "SO2_mg_m3": ("Алматы — Диоксид серы (SO₂) прогноз", "Концентрация, мг/м³"),
        "TSP_mg_m3": ("Алматы — Взвешенные в-ва (TSP) прогноз", "Концентрация, мг/м³"),
        "population_total": ("Алматы — Население (прогноз)", "Население, чел."),
        "transport_total": ("Алматы — Транспорт (прогноз)", "Количество транспорта, ед."),
    }

    for metric in df["metric"].unique():
        if metric in titles_and_labels:
            title, ylabel = titles_and_labels[metric]
            path = d / f"{metric}.png"
            out_path = _save_line_with_band(df, metric, path, title, ylabel)
            if out_path:
                out[metric] = str(out_path)

    return out