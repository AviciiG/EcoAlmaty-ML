from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
import torch
from chronos import BaseChronosPipeline

# ===== НАСТРОЙКИ И КОНСТАНТЫ =====
DEVICE = "cpu"
DTYPE = torch.float32

# Константы для корректного прогноза
INITIAL_CONDITIONS_YEAR = 2025 # Год с известными (1 сент.) начальными условиями
START_YEAR = 2026 # Модель Chronos начинает прогнозирование с этого года
BASE_YEAR = 2024  # Последний год с полными историческими данными

# Константы влияния (для _apply_driver_impacts)
POPULATION_IMPACT = 0.2 
TRANSPORT_IMPACT = 0.6  
# ==================================

BOUNDS = {
    "CO_mg_m3": (0.0, 15.0),
    "NO2_mg_m3": (0.0, 0.8),
    "SO2_mg_m3": (0.0, 0.5),
    "TSP_mg_m3": (0.0, 0.8),
    "population_total": (1_000_000, 8_000_000),
    "transport_total": (100_000, 5_000_000),
}

MIN_GROWTH_RATES = {
    "population_total": 0.005,  
    "transport_total": 0.008,   
    "CO_mg_m3": 0.0,          
    "NO2_mg_m3": 0.0,
    "SO2_mg_m3": 0.0,
    "TSP_mg_m3": 0.0,
}
# ==================================

@dataclass
class SeriesSpec:
    name: str
    years: List[int]
    values: List[float]

# --- Вспомогательные функции (Нормализация, Клиппинг, Монотонность) ---

def _normalize(x: np.ndarray):
    mean = float(np.mean(x))
    std = float(np.std(x))
    if std < 1e-6:
        std = 1.0
    return (x - mean) / std, mean, std

def _denorm(y, mean, std):
    return y * std + mean

def _clip(name: str, arr: np.ndarray) -> np.ndarray:
    lo, hi = BOUNDS.get(name, (-np.inf, np.inf))
    return np.clip(arr, lo, hi)

def _enforce_monotonic_growth(metric: str, values: np.ndarray, base_value: float) -> np.ndarray:
    min_rate = MIN_GROWTH_RATES.get(metric, 0.0)
    
    if min_rate <= 0: return values
        
    result = np.zeros_like(values)
    result[0] = max(values[0], base_value * (1 + min_rate))
    
    for i in range(1, len(values)):
        min_value = result[i - 1] * (1 + min_rate)
        result[i] = max(values[i], min_value)
    
    return result

# --- Загрузка данных (без изменений) ---

def _load_population(fp: Path | None) -> SeriesSpec | None:
    """Загрузка данных о населении"""
    if not fp or not fp.exists(): return None
    df = pd.read_csv(fp)
    col = "population" if "population" in df.columns else (
        "population_total" if "population_total" in df.columns else None)
    if not col or "year" not in df.columns: return None
    df = df[["year", col]].dropna().sort_values("year")
    df.rename(columns={col: "population_total"}, inplace=True)
    return SeriesSpec("population_total",
                      df["year"].astype(int).tolist(),
                      df["population_total"].astype(float).tolist())

def _load_transport(fp: Path | None) -> SeriesSpec | None:
    """Загрузка данных о транспорте"""
    if not fp or not fp.exists(): return None
    df = pd.read_csv(fp)
    df_cars = df[df['category'] == 'Легковые автомобили'].copy()
    if not df_cars.empty:
        df_cars = df_cars[["year", "value"]].dropna().sort_values("year")
        df_cars = df_cars.rename(columns={"value": "transport_total"})
        if df_cars["transport_total"].max() < 10000:
            df_cars["transport_total"] *= 1000
        return SeriesSpec("transport_total",
                          df_cars["year"].astype(int).tolist(),
                          df_cars["transport_total"].astype(float).tolist())
    return None

def _load_air(fp: Path | None, metric: str) -> SeriesSpec | None:
    """Загрузка данных о концентрации воздуха."""
    if not fp or not fp.exists(): 
        return None
    try:
        df = pd.read_csv(fp)
    except Exception:
        return None
        
    if 'metric' in df.columns and 'year' in df.columns and ('value' in df.columns or 'value_year' in df.columns):
        value_col = 'value_year' if 'value_year' in df.columns else 'value'
        
        df_metric = df[df['metric'] == metric].copy()
        
        if df_metric.empty: 
            return None
            
        df_metric = df_metric[["year", value_col]].dropna().sort_values("year")
        df_metric.rename(columns={value_col: "value"}, inplace=True)
             
        return SeriesSpec(metric, 
                          df_metric["year"].astype(int).tolist(), 
                          df_metric["value"].astype(float).tolist())

    return None

def load_all_series(files: Dict[str, Path | None]) -> List[SeriesSpec]:
    """Загрузка всех временных рядов"""
    out: List[SeriesSpec] = []
    
    sp = _load_population(files.get("population"))
    if sp: out.append(sp)
    
    st = _load_transport(files.get("transport"))
    if st: out.append(st)
    
    # Загружаем данные по воздуху, но не используем их для Chronos,
    # а только для определения начальных условий.
    air_file = files.get("air_yearly") 
    for m in ["CO_mg_m3", "NO2_mg_m3", "SO2_mg_m3", "TSP_mg_m3"]:
        sa = _load_air(air_file, m)
        if sa: out.append(sa)
    
    # Для Chronos нам нужны только ряды с достаточным количеством точек (население, транспорт)
    return [s for s in out if s.name in ["population_total", "transport_total"] and len(s.values) >= 3]


def _get_initial_conditions(current_data: List[SeriesSpec], all_series: List[SeriesSpec]) -> pd.DataFrame:
    """
    Гарантирует ненулевые стартовые значения для 2025 года, 
    используя как загруженные (current_data), так и все возможные ряды (all_series),
    включая воздух.
    """
    # Стартовые условия (берем из вашего файла almaty_population_all.csv и transport_yearly.csv)
    # Последние актуальные данные (2024 год). Примем их за базу 2025 года.
    POP_INIT_FALLBACK = 2292055.0  
    TRN_INIT_FALLBACK = 797240.0   
    
    FALLBACK_AIR_INIT = {
        "CO_mg_m3": 1.317, 
        "NO2_mg_m3": 0.090,
        "SO2_mg_m3": 0.009,
        "TSP_mg_m3": 0.141,
    }
    
    # Список всех метрик, которые нам нужны
    ALL_METRICS = ["population_total", "transport_total", "CO_mg_m3", "NO2_mg_m3", "SO2_mg_m3", "TSP_mg_m3"]
    initial_data = {
        "metric": ALL_METRICS,
        "year": [INITIAL_CONDITIONS_YEAR] * len(ALL_METRICS),
        "p50": [0.0] * len(ALL_METRICS)
    }
    
    df_init = pd.DataFrame(initial_data)

    # 1. Обновляем p50 на основе последних исторических данных (2024 год)
    for s in all_series:
        last_value = 0.0
        if s.years and s.values:
            try:
                # Берем последнее значение до 2025 года (т.е. 2024)
                valid_history = [(y, v) for y, v in zip(s.years, s.values) if y <= BASE_YEAR]
                if valid_history:
                    last_value = valid_history[-1][1]
            except Exception:
                pass
        
        if last_value >= 1e-9:
            df_init.loc[df_init["metric"] == s.name, "p50"] = last_value
    
    # 2. Применяем FALLBACK для заполнения пропусков и гарантии старта
    df_init.loc[df_init["metric"] == "population_total", "p50"] = max(df_init.loc[df_init["metric"] == "population_total", "p50"].iloc[0], POP_INIT_FALLBACK)
    df_init.loc[df_init["metric"] == "transport_total", "p50"] = max(df_init.loc[df_init["metric"] == "transport_total", "p50"].iloc[0], TRN_INIT_FALLBACK)
    
    for metric, fallback_val in FALLBACK_AIR_INIT.items():
        # Если значение из исторических данных слишком мало или 0, используем Fallback
        if df_init.loc[df_init["metric"] == metric, "p50"].iloc[0] < 0.001:
            df_init.loc[df_init["metric"] == metric, "p50"] = fallback_val
            
    # Задаем небольшой разброс для P10 и P90 на старте
    df_init["p10"] = df_init["p50"] * 0.95 
    df_init["p90"] = df_init["p50"] * 1.05
    df_init["mean"] = df_init["p50"] 
    
    return df_init.sort_values("metric")

# --- Класс ChronosForecaster (без изменений) ---
# ... (Код ChronosForecaster без изменений) ...

class ChronosForecaster:
    """Forecaster на базе Chronos с улучшениями для стабильности"""
    
    def __init__(self, model_name: str = "amazon/chronos-t5-base"):
        self.pipe = BaseChronosPipeline.from_pretrained(
            model_name, 
            device_map="cpu", 
            torch_dtype=DTYPE
        )

    def forecast_univariate(self, s: SeriesSpec, horizon: int, 
                           start_year: int = START_YEAR) -> pd.DataFrame:
        """Универсальный прогноз для одного ряда."""
        vals = np.array(s.values, dtype=float)
        
        # Получаем базовое значение для 2025 года, чтобы начать прогноз
        df_init_single = _get_initial_conditions(current_data=[s], all_series=[s]) 
        base_value_for_growth = float(df_init_single[df_init_single["metric"] == s.name]["p50"].iloc[0])
        
        x_norm, mean, std = _normalize(vals)
        context = torch.tensor(x_norm, dtype=torch.float32)
        
        results = []
        remain = horizon
        step_size = 24  
        current_year = start_year
        
        while remain > 0:
            step = min(remain, step_size)
            
            q, m = self.pipe.predict_quantiles(
                context=context,
                prediction_length=step,
                quantile_levels=[0.1, 0.5, 0.9],
            )
            
            q = _denorm(q[0].cpu().numpy(), mean, std)
            m = _denorm(m[0].cpu().numpy(), mean, std)
            
            for i in range(step):
                year = current_year + i
                p10, p50, p90 = _clip(s.name, np.array([q[i, 0], q[i, 1], q[i, 2]]))
                mean_i = _clip(s.name, np.array([m[i]]))[0]
                
                results.append((year, float(p10), float(p50), float(p90), float(mean_i)))
            
            remain -= step
            current_year += step

            # Для следующего шага Chronos контекст обновляется прогнозируемыми p50
            new_context_vals = np.array([r[2] for r in results])
            # Контекст: Исторические данные + Прогноз до текущего шага
            context_for_next_step = np.concatenate([vals, new_context_vals])
            context = torch.tensor(_normalize(context_for_next_step)[0], dtype=torch.float32)

        df = pd.DataFrame(results, columns=["year", "p10", "p50", "p90", "mean"])
        
        for col in ["p10", "p50", "p90", "mean"]:
            df[col] = _enforce_monotonic_growth(s.name, df[col].values, base_value_for_growth)
        
        df.insert(0, "metric", s.name)
        
        return df

def _apply_driver_impacts(df: pd.DataFrame, initial_data: pd.DataFrame) -> pd.DataFrame:
    """
    Применяет влияние роста населения и транспорта на загрязнение воздуха 
    для всего горизонта прогноза (2026+).
    """
    # Проверка на наличие базовых данных
    if "population_total" not in initial_data["metric"].unique() or "transport_total" not in initial_data["metric"].unique():
        return df
        
    pop_init = float(initial_data[initial_data["metric"] == "population_total"]["p50"].iloc[0])
    trn_init = float(initial_data[initial_data["metric"] == "transport_total"]["p50"].iloc[0])
    
    # 1. Получаем прогнозы драйверов на весь горизонт (включая 2025)
    pop_data = df[df["metric"] == "population_total"][["year", "p10", "p50", "p90"]].rename(columns={"p50": "pop", "p10": "pop10", "p90": "pop90"})
    trn_data = df[df["metric"] == "transport_total"][["year", "p10", "p50", "p90"]].rename(columns={"p50": "trn", "p10": "trn10", "p90": "trn90"})
    
    if pop_data.empty or trn_data.empty or pop_init == 0 or trn_init == 0: 
        return df
    
    growth_df = pop_data.merge(trn_data, on="year", how="outer")
    
    # Добавляем пустые строки для воздуха на весь горизонт (2026+) для заполнения
    pollutants = ["CO_mg_m3", "NO2_mg_m3", "SO2_mg_m3", "TSP_mg_m3"]
    
    air_rows_to_add = []
    
    for pollutant in pollutants:
        pol_init = float(initial_data[initial_data["metric"] == pollutant]["p50"].iloc[0])
        
        # Если нет базового значения, пропускаем
        if pol_init == 0: continue
            
        pol_data = growth_df.copy()
        
        # Расчет факторов роста для P50 (медиана)
        pop_factor_50 = ((pol_data["pop"] / pop_init) - 1) * POPULATION_IMPACT
        trn_factor_50 = ((pol_data["trn"] / trn_init) - 1) * TRANSPORT_IMPACT
        
        # Расчет факторов роста для P10 и P90 (с небольшим допущением)
        # Для P10 (меньше загрязнение) возьмем нижний предел драйверов
        pop_factor_10 = ((pol_data["pop10"] / pop_init) - 1) * POPULATION_IMPACT
        trn_factor_10 = ((pol_data["trn10"] / trn_init) - 1) * TRANSPORT_IMPACT
        # Для P90 (больше загрязнение) возьмем верхний предел драйверов
        pop_factor_90 = ((pol_data["pop90"] / pop_init) - 1) * POPULATION_IMPACT
        trn_factor_90 = ((pol_data["trn90"] / trn_init) - 1) * TRANSPORT_IMPACT
        
        
        # Базовое прогнозируемое значение, скорректированное на драйверы
        # Используем pol_init как точку отсчета
        adjusted_50 = pol_init * (1 + pop_factor_50 + trn_factor_50)
        adjusted_10 = pol_init * (1 + pop_factor_10 + trn_factor_10)
        adjusted_90 = pol_init * (1 + pop_factor_90 + trn_factor_90)
        
        # Клиппинг
        adjusted_50 = _clip(pollutant, adjusted_50)
        adjusted_10 = _clip(pollutant, adjusted_10)
        adjusted_90 = _clip(pollutant, adjusted_90)

        # Собираем DataFrame для текущего загрязнителя
        pol_df = pd.DataFrame({
            "metric": pollutant,
            "year": pol_data["year"],
            "p50": adjusted_50,
            "p10": adjusted_10,
            "p90": adjusted_90,
            "mean": adjusted_50 # mean = p50 для простоты
        })
        air_rows_to_add.append(pol_df)
        
    df_air = pd.concat(air_rows_to_add, ignore_index=True)
    
    # 3. Объединяем прогнозы драйверов и скорректированный прогноз воздуха
    df_drivers = df[df["metric"].isin(["population_total", "transport_total"])]
    df_final = pd.concat([df_drivers, df_air], ignore_index=True)
    
    return df_final


# --- Главная функция ---

def run_full_forecast(population_csv, transport_csv, air_yearly_csv, 
                     air_yearly_extra_csv, horizon: int) -> pd.DataFrame:
    """Запускает полный прогноз для всех метрик."""
    
    files = {
        "population": Path(population_csv) if population_csv else None,
        "transport": Path(transport_csv) if transport_csv else None,
        "air_yearly": Path(air_yearly_csv) if air_yearly_csv else None, 
        "air_yearly_extra": Path(air_yearly_extra_csv) if air_yearly_extra_csv else None, 
    }
    
    # 1. Загружаем все ряды, но Chronos будет использовать только те, у кого 3+ точки.
    all_series = []
    for f in ["population", "transport"]:
        s = globals()[f"_load_{f}"](files.get(f))
        if s: all_series.append(s)
    
    air_file = files.get("air_yearly") 
    for m in ["CO_mg_m3", "NO2_mg_m3", "SO2_mg_m3", "TSP_mg_m3"]:
        sa = _load_air(air_file, m)
        if sa: all_series.append(sa)
    
    # Ряды, которые идут в Chronos (только те, у которых > 3 точек)
    chronos_series = [s for s in all_series if s.name in ["population_total", "transport_total"] and len(s.values) >= 3]
    
    # 2. Получаем инициализацию 2025 года для ВСЕХ 6 метрик
    df_init = _get_initial_conditions(chronos_series, all_series)
    
    model = ChronosForecaster()
    
    chronos_horizon = max(0, horizon) # Включаем 2025 год в расчет, если Chronos нужен
    
    all_parts = []
    
    # 3. Прогноз Chronos только для драйверов (2026-2025+N)
    if chronos_horizon > 0:
        for s in chronos_series:
            print(f"Прогнозирование Chronos: {s.name}...")
            # Прогноз на (N) шагов, начиная с 2026 года
            part = model.forecast_univariate(s, horizon=horizon, start_year=START_YEAR)
            all_parts.append(part)
    
    df_drivers_forecast = pd.DataFrame()
    if all_parts:
        df_drivers_forecast = pd.concat(all_parts, ignore_index=True)
        # Объединяем df_init (2025 год) с прогнозом драйверов (2026+)
        df = pd.concat([df_init, df_drivers_forecast], ignore_index=True)
    else:
        df = df_init
        
    # Удаляем дубликаты 2025 года, оставляя только из df_init
    df = df.drop_duplicates(subset=["metric", "year"], keep="first")
    
    # 4. Применяем корректировки для воздуха
    df = _apply_driver_impacts(df, df_init)
    
    return df.sort_values(["metric", "year"]).reset_index(drop=True)