# -*- coding: utf-8 -*-
# Парсинг поквартирных/помесячных XLSX из Apple Numbers
# Делает помесячную «плоскую» таблицу и годовую агрегацию.

from __future__ import annotations
import argparse, re
from pathlib import Path
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd

# ---------- словари / нормализация ----------
RU_MONTHS = {
    "январь":1,"февраль":2,"март":3,"апрель":4,"май":5,"май":5,
    "июнь":6,"июль":7,"август":8,"сентябрь":9,"октябрь":10,"ноябрь":11,"декабрь":12
}
POST_IN_TITLE = re.compile(r"(пнз|пост)\s*№?\s*(\d+)", re.I)

METRIC_PATTERNS = [
    (re.compile(r"\bвзвеш.*в-?ва\b", re.I), "TSP_mg_m3", "Взвеш.в-ва"),
    (re.compile(r"\bдиоксид\s*серы\b", re.I), "SO2_mg_m3", "Диоксид серы"),
    (re.compile(r"\bуглерод[а]?\s*оксид\b", re.I), "CO_mg_m3", "Углерода оксид"),
    (re.compile(r"\bазот[а]?\s*диоксид\b", re.I), "NO2_mg_m3", "Азота диоксид"),
]
ORDERED_KEYS = ["TSP_mg_m3","SO2_mg_m3","CO_mg_m3","NO2_mg_m3"]

def nrm(x) -> str:
    s = "" if x is None else str(x)
    return s.strip().replace("\u00A0"," ")

def cf(x) -> str:
    return nrm(x).casefold()

def to_float(x) -> float:
    if x is None or (isinstance(x, float) and np.isnan(x)): return np.nan
    s = nrm(x).replace("\u2212","-").replace(",",".")
    s = re.sub(r"[^\d\.\-eE]", "", s)
    try: return float(s)
    except: return np.nan

def to_date(x) -> Optional[date]:
    if isinstance(x, (pd.Timestamp, datetime)): return x.date()
    if isinstance(x, date): return x
    s = nrm(x)
    if not s: return None
    for fmt in ("%d.%m.%Y","%d.%m.%y","%Y-%m-%d","%m/%d/%y","%m/%d/%Y","%d/%m/%y","%d/%m/%Y"):
        try: return datetime.strptime(s, fmt).date()
        except: pass
    dt = pd.to_datetime(s, errors="coerce", dayfirst=True)
    return None if pd.isna(dt) else dt.date()

# ---------- извлечение метаданных ----------
def guess_meta(df: pd.DataFrame, sheet_name: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    year = month = post = None
    head = df.iloc[:20, :10].fillna("")
    for r in range(head.shape[0]):
        for c in range(head.shape[1]-1):
            key = cf(head.iat[r,c])
            val = nrm(head.iat[r,c+1])
            if key == "год":
                m = re.search(r"(\d{4})", val)
                if m: year = int(m.group(1))
            elif key == "месяц":
                month = RU_MONTHS.get(cf(val), month)
            elif key in ("пост", "пост№", "пост #", "пнз"):
                m = re.search(r"(\d+)", val)
                if m: post = int(m.group(1))
    if post is None:
        m = POST_IN_TITLE.search(sheet_name or "")
        if m: post = int(m.group(2))
    return year, month, post

# ---------- поиск строки заголовка и колонок ----------
def find_header_row(df: pd.DataFrame) -> Optional[int]:
    # ищем строку, где есть «дата» (поле A7~A8 на твоём скрине)
    search = df.iloc[:40, :20].fillna("")
    for r in range(search.shape[0]):
        row = [cf(x) for x in list(search.iloc[r, :])]
        if "дата" in row: return r
    # запасной вариант — строка, где есть «концентрации»
    for r in range(search.shape[0]):
        row = [cf(x) for x in list(search.iloc[r, :])]
        if any("концентраци" in t for t in row): return r+1
    return None

def detect_columns(df: pd.DataFrame, header_row: int):
    # колонка даты — там, где ниже чаще всего парсятся даты
    best_col = None; best_hits = 0
    for c in range(min(40, df.shape[1])):
        hits = 0
        for r in range(header_row+1, min(df.shape[0], header_row+1+80)):
            if to_date(df.iat[r, c]) is not None: hits += 1
        if hits > best_hits:
            best_hits = hits; best_col = c
    date_col = best_col if best_hits >= 6 else None

    # колонка «Срок» (если есть)
    srok_col = None
    for c in range(min(40, df.shape[1])):
        if cf(df.iat[header_row, c]).startswith("срок"):
            srok_col = c; break

    # метрики — сперва по названиям (в строке заголовка ±1)
    metric_cols: Dict[str,int] = {}
    for rr in (header_row-1, header_row, header_row+1):
        if rr < 0 or rr >= df.shape[0]: continue
        for c in range(min(60, df.shape[1])):
            txt = nrm(df.iat[rr,c])
            if not txt: continue
            for pat, key, _ in METRIC_PATTERNS:
                if key not in metric_cols and pat.search(txt):
                    metric_cols[key] = c

    # если названия пустые — взять 4 числовых столбца сразу справа от даты
    if (not metric_cols) and (date_col is not None):
        guess = []
        for c in range(date_col+1, min(df.shape[1], date_col+12)):
            vals = [to_float(df.iat[r,c]) for r in range(header_row+1, min(df.shape[0], header_row+1+40))]
            nums = sum(0 if np.isnan(v) else 1 for v in vals)
            if nums >= 6: guess.append(c)
            if len(guess) == 4: break
        if len(guess) == 4:
            metric_cols = {k: col for k, col in zip(ORDERED_KEYS, guess)}

    return date_col, srok_col, metric_cols

# ---------- парс листа ----------
def parse_sheet(df: pd.DataFrame, src_name: str, sheet_name: str, debug=False) -> List[Dict]:
    year, month, post = guess_meta(df, sheet_name)
    header = find_header_row(df)
    if header is None:
        if debug: print(f"  · {src_name} [{sheet_name}]: нет строки шапки")
        return []

    date_col, srok_col, metric_cols = detect_columns(df, header)
    if debug:
        print(f"  · {src_name} [{sheet_name}]: header={header}, date_col={date_col}, "
              f"srok_col={srok_col}, metrics={metric_cols}, meta=(y={year},m={month},post={post})")

    if date_col is None or not metric_cols:
        if debug: print("    → не смог определить дату или метрики")
        return []

    # строки данных начинаются после header
    rows: List[Dict] = []
    blanks = 0
    for r in range(header+1, df.shape[0]):
        d = to_date(df.iat[r, date_col])
        if d is None:
            blanks += 1
            if blanks > 80: break
            continue
        blanks = 0
        y = year or d.year
        m = month or d.month
        srok = nrm(df.iat[r, srok_col]) if srok_col is not None else ""

        for key, col in metric_cols.items():
            v = to_float(df.iat[r, col])
            if np.isnan(v): continue
            rows.append({
                "source_file": src_name,
                "sheet": sheet_name,
                "post_id": post,
                "date": d.isoformat(),
                "year": int(y),
                "month": int(m),
                "day": int(d.day),
                "srok": srok,
                "metric": key,
                "metric_ru": dict((k,ru) for _,k,ru in METRIC_PATTERNS)[key],
                "value": float(v),
                "unit": "мг/куб.м",
            })
    return rows

# ---------- файл целиком (все листы) ----------
def parse_workbook(path: Path, debug=False) -> List[Dict]:
    try:
        # читаем ВСЕ листы как «сырые» датафреймы
        xl = pd.read_excel(path, sheet_name=None, header=None, engine="openpyxl", dtype=object)
    except Exception as e:
        if debug: print(f"  ! {path.name}: не открылся ({e})")
        return []
    out: List[Dict] = []
    for sname, df in xl.items():
        out += parse_sheet(df, path.name, str(sname), debug=debug)
    return out

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", required=True)
    ap.add_argument("--out-monthly", required=True)
    ap.add_argument("--out-yearly", required=True)
    ap.add_argument("--agg", choices=["mean","median"], default="mean")
    ap.add_argument("--debug-one", help="Путь к конкретному файлу для подробного разбора")
    args = ap.parse_args()

    if args.debug_one:
        print("🔍 DEBUG одиночного файла")
        rows = parse_workbook(Path(args.debug_one), debug=True)
        print(f"  итого строк: {len(rows)}")
        if rows:
            print(pd.DataFrame(rows).head(25))
        return

    files = sorted(Path().glob(args.glob))
    print(f"Найдено файлов: {len(files)}")
    all_rows: List[Dict] = []
    for fp in files:
        part = parse_workbook(fp)
        print(f"  • {fp.name}: +{len(part)}")
        all_rows += part

    if not all_rows:
        print("⚠️ Не удалось извлечь ни одной строки. Попробуй --debug-one на конкретном файле.")
        return

    monthly = (pd.DataFrame(all_rows)
               .drop_duplicates()
               .sort_values(["year","month","date","post_id","metric"])
               .reset_index(drop=True))
    Path(args.out_monthly).parent.mkdir(parents=True, exist_ok=True)
    monthly.to_csv(args.out_monthly, index=False, encoding="utf-8-sig")
    print(f"✅ Месячные сохранены: {args.out_monthly} ({len(monthly)} строк)")

    aggfunc = np.mean if args.agg == "mean" else np.median
    yearly = (monthly.groupby(["metric","year"], as_index=False)["value"]
              .agg(aggfunc)
              .rename(columns={"value":"value_year"}))
    yearly["unit"] = "мг/куб.м"
    yearly.to_csv(args.out_yearly, index=False, encoding="utf-8-sig")
    print(f"✅ Годовые сохранены: {args.out_yearly} ({len(yearly)} строк)")

if __name__ == "__main__":
    main()