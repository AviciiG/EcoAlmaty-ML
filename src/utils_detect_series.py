# src/utils_detect_series.py
from __future__ import annotations
import re
import pandas as pd

def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols = {c.lower(): c for c in df.columns}
    for pat in candidates:
        # точное совпадение
        if pat in cols:
            return cols[pat]
        # по подстроке/регэкспу
        for k, orig in cols.items():
            if re.search(pat, k):
                return orig
    return None

def read_yearly_series(path: str,
                       city_filters=("алматы", "г. алматы", "город алматы"),
                       value_candidates=("value", "значение", "count", "qty", "кол-во", "количество"),
                       year_candidates=("year", r"\bгод\b", r"\byear\b", r"\bдат[аы].*?(\d{4})")
                       ) -> list[dict]:
    """
    Читает разные по форме *годовые* CSV и достаёт ряды для Алматы.
    Ожидается, что в файле есть столбец года и столбцы значений (возможно несколько метрик).
    Возвращает список записей: {metric, year, value, unit, source_file}
    """
    df = pd.read_csv(path)
    df.columns = [str(c).strip() for c in df.columns]

    # фильтр по городу, если есть столбец с территорией
    terr_col = _find_column(df, ["террит", "регион", "область", "город", "като", "location", "place"])
    if terr_col:
        mask_city = False
        for w in city_filters:
            mask_city = mask_city | df[terr_col].astype(str).str.lower().str.contains(w)
        df = df.loc[mask_city].copy()

    # год
    year_col = _find_column(df, list(year_candidates))
    if not year_col:
        # попытка вытащить год из строки/даты
        for c in df.columns:
            y = df[c].astype(str).str.extract(r"(\d{4})", expand=False)
            if y.notna().sum() >= len(df) * 0.7:
                df["__year__"] = y.astype(float).astype("Int64")
                year_col = "__year__"
                break
    if not year_col:
        return []

    # единицы измерения, если встречаются как отдельный столбец
    unit_col = _find_column(df, ["unit", "ед", "единиц", "ед.изм", "ед_изм"])
    unit_global = None
    if unit_col and df[unit_col].dropna().nunique() == 1:
        unit_global = str(df[unit_col].dropna().iloc[0]).strip()

    # попытаемся угадать метрики: все числовые столбцы (кроме year/unit)
    ignore = {year_col}
    if unit_col:
        ignore.add(unit_col)

    num_cols = []
    for c in df.columns:
        if c in ignore:
            continue
        s = pd.to_numeric(df[c], errors="coerce")
        if s.notna().sum() >= max(3, int(len(s)*0.5)):  # столбец действительно числовой
            num_cols.append((c, s))

    records = []
    for c, s in num_cols:
        unit = unit_global
        # если в названии столбца встречаются единицы — аккуратно сохраним
        m = re.search(r"\((.*?)\)", c)
        if m:
            unit = unit or m.group(1)

        for _, row in df[[year_col, c]].dropna().iterrows():
            y = int(row[year_col])
            v = float(row[c])
            records.append({
                "metric": c.strip(),
                "year": y,
                "value": v,
                "unit": unit,
                "source_file": path
            })
    return records