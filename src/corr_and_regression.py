# -*- coding: utf-8 -*-
"""
Корреляции и простые регрессии:
pollutant ∈ {CO_mg_m3, NO2_mg_m3, SO2_mg_m3, TSP_mg_m3}
~ population_total + transport_total

Запуск:
  python src/corr_and_regression.py
"""

from __future__ import annotations
import os
from pathlib import Path
import numpy as np
import pandas as pd


# --- входные пути (правь под себя при необходимости) ---
AIR_CSV = Path("data/processed/air_yearly_from_monthlies.csv")
POP_CSV = Path("data/processed/almaty_population_all.csv")
TRN_CSV = Path("data/processed/almaty_transport_yearly.csv")

# --- выходная папка ---
OUT_DIR = Path("data/processed/analysis")


def load_air(path: Path) -> pd.DataFrame:
    """
    Воздух: wide-таблица по годам, колонка со значениями = value_year.
    Итог: колонки ['year','CO_mg_m3','NO2_mg_m3','SO2_mg_m3','TSP_mg_m3']
    """
    if not path.exists():
        raise FileNotFoundError(f"Нет файла воздуха: {path}")
    air = pd.read_csv(path)
    val_col = "value_year"
    if val_col not in air.columns:
        raise KeyError(f"В воздухе нет '{val_col}'. Найдены: {air.columns.tolist()}")
    pivot = (
        air.pivot(index="year", columns="metric", values=val_col)
           .reset_index()
           .sort_values("year")
           .reset_index(drop=True)
    )
    return pivot


def load_population(path: Path) -> pd.DataFrame:
    """
    Население: приводим к ['year','population_total'].
    В исходнике колонка называется 'population' -> переименуем.
    """
    if not path.exists():
        raise FileNotFoundError(f"Нет файла населения: {path}")
    pop = pd.read_csv(path)
    if "population_total" not in pop.columns:
        if "population" in pop.columns:
            pop = pop.rename(columns={"population": "population_total"})
        else:
            raise KeyError(f"Нет 'population_total' или 'population' в {path}. Доступно: {pop.columns.tolist()}")
    pop = pop[["year", "population_total"]].dropna()
    return pop


def load_transport(path: Path) -> pd.DataFrame:
    """
    Транспорт: агрегируем 'value' по году к ['year','transport_total'].
    """
    if not path.exists():
        raise FileNotFoundError(f"Нет файла транспорта: {path}")
    trn = pd.read_csv(path)
    if "year" not in trn.columns or "value" not in trn.columns:
        raise KeyError(f"В транспорте нужны 'year' и 'value'. Доступно: {trn.columns.tolist()}")
    total = (
        trn.groupby("year", as_index=False)["value"]
           .sum()
           .rename(columns={"value": "transport_total"})
    )
    return total


def build_panel(air: pd.DataFrame, pop: pd.DataFrame, trn: pd.DataFrame) -> pd.DataFrame:
    """
    Объединяет воздух + население + транспорт по общим годам.
    Приводит числовые столбцы и выкидывает строки с NaN.
    """
    df = (
        air.merge(pop, on="year", how="inner")
           .merge(trn, on="year", how="inner")
           .sort_values("year")
           .reset_index(drop=True)
    )
    num_cols = ["CO_mg_m3","NO2_mg_m3","SO2_mg_m3","TSP_mg_m3",
                "population_total","transport_total"]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=num_cols)
    return df


def correlations(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    targets = ["CO_mg_m3","NO2_mg_m3","SO2_mg_m3","TSP_mg_m3"]
    drivers = ["population_total","transport_total"]
    pearson  = df[drivers + targets].corr(numeric_only=True).loc[drivers, targets]
    spearman = df[drivers + targets].corr(method="spearman", numeric_only=True).loc[drivers, targets]
    return pearson, spearman


def linreg_two_x(df: pd.DataFrame, y: str, X1: str, X2: str) -> tuple[np.ndarray, float]:
    """
    Оценивает Y ~ 1 + X1 + X2 по МНК (numpy.linalg.lstsq).
    Возвращает коэффициенты [b0,b1,b2] и R^2.
    """
    Y = df[y].to_numpy(float)
    X = np.column_stack([np.ones(len(df)), df[X1].to_numpy(float), df[X2].to_numpy(float)])
    beta, *_ = np.linalg.lstsq(X, Y, rcond=None)
    y_hat = X @ beta
    ss_res = np.sum((Y - y_hat)**2)
    ss_tot = np.sum((Y - Y.mean())**2)
    r2 = 1 - ss_res/ss_tot if ss_tot > 0 else np.nan
    return beta, float(r2)


def regressions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Прогоняет 4 отдельные регрессии по загрязнителям.
    """
    rows = []
    for pol in ["CO_mg_m3","NO2_mg_m3","SO2_mg_m3","TSP_mg_m3"]:
        beta, r2 = linreg_two_x(df, pol, "population_total", "transport_total")
        b0, b_pop, b_trn = beta
        rows.append({
            "target": pol,
            "intercept": b0,
            "beta_population": b_pop,
            "beta_transport": b_trn,
            "r2": r2
        })
    return pd.DataFrame(rows)


def main():
    # загрузка
    air = load_air(AIR_CSV)
    pop = load_population(POP_CSV)
    trn = load_transport(TRN_CSV)

    # объединённая панель
    df = build_panel(air, pop, trn)

    # вывод о данных
    print("✅ Колонки:", df.columns.tolist())
    print("📅 Диапазон лет:", int(df["year"].min()), "-", int(df["year"].max()))
    print("📐 Размерность:", df.shape)

    # корреляции
    pearson, spearman = correlations(df)
    pearson = pearson.round(3)
    spearman = spearman.round(3)

    # регрессии
    regr = regressions(df)
    regr[["intercept","beta_population","beta_transport","r2"]] = \
        regr[["intercept","beta_population","beta_transport","r2"]].round(4)

    # сохранение
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pearson.to_csv(OUT_DIR / "correlations_pearson.csv")
    spearman.to_csv(OUT_DIR / "correlations_spearman.csv")
    regr.to_csv(OUT_DIR / "regressions.csv", index=False)

    print("\n📈 Корреляции Пирсона (drivers ↔ pollutants):\n", pearson)
    print("\n📈 Корреляции Спирмена (drivers ↔ pollutants):\n", spearman)
    print("\n🔎 Линейные модели (Y ~ population_total + transport_total):\n", regr)

    # краткая шпаргалка для комиссии — Markdown
    md = []
    md.append(f"# Summary ({int(df['year'].min())}-{int(df['year'].max())})")
    md.append("## Pearson correlations")
    md.append(pearson.to_markdown())
    md.append("\n## Spearman correlations")
    md.append(spearman.to_markdown())
    md.append("\n## Linear models (OLS)")
    md.append(regr.to_markdown(index=False))
    (OUT_DIR / "summary.md").write_text("\n\n".join(md), encoding="utf-8")
    print(f"\n📝 Сохранено в: {OUT_DIR}/ (csv + summary.md)")


if __name__ == "__main__":
    main()