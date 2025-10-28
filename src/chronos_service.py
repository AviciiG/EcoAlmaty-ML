# src/chronos_service.py
from __future__ import annotations
import argparse
import json
from pathlib import Path
from collections import defaultdict

import torch
import pandas as pd
from chronos import BaseChronosPipeline
from utils_detect_series import read_yearly_series

# ====== настройки по умолчанию ======
DEFAULT_FILES = [
    "data/processed/almaty_population_all.csv",
    "data/processed/almaty_transport_yearly.csv",
    "data/processed/almaty_yearly_from_excels.csv",  # воздух агрегированный по годам
]

def load_all_series(paths: list[str]) -> pd.DataFrame:
    all_rows = []
    for p in paths:
        pth = Path(p)
        if not pth.exists():
            print(f"⚠️ файл не найден: {pth}")
            continue
        try:
            rows = read_yearly_series(str(pth))
            if not rows:
                print(f"⚠️ не нашёл годовые ряды для Алматы в: {pth.name}")
            else:
                all_rows += rows
        except Exception as e:
            print(f"⚠️ ошибка чтения {pth.name}: {e}")
    if not all_rows:
        return pd.DataFrame(columns=["metric","year","value","unit","source_file"])
    df = (pd.DataFrame(all_rows)
            .drop_duplicates()
            .sort_values(["metric","year"])
            .reset_index(drop=True))
    return df

def chronos_pipeline(model_name: str = "amazon/chronos-t5-base"):
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.float16 if device == "mps" else torch.float32
    pipe = BaseChronosPipeline.from_pretrained(
        model_name,
        device_map=device,
        torch_dtype=dtype,
    )
    return pipe, device

def forecast_series(pipe: BaseChronosPipeline,
                    df: pd.DataFrame,
                    horizon: int,
                    min_points: int = 6) -> pd.DataFrame:
    """
    По каждому metric строим прогноз на horizon лет вперёд.
    Требуем минимум min_points наблюдений.
    Возвращает tidy-таблицу с q10/median/q90 и mean.
    """
    out_rows = []
    for metric, g in df.groupby("metric", sort=False):
        g2 = g.sort_values("year")
        if len(g2) < min_points:
            print(f"• пропускаю «{metric}»: мало точек ({len(g2)})")
            continue
        series = g2["value"].astype(float).tolist()
        last_year = int(g2["year"].max())

        # предсказание квантилей
        context = torch.tensor(series, dtype=torch.float32)
        quantiles, mean = pipe.predict_quantiles(
            context=context,
            prediction_length=horizon,
            quantile_levels=[0.1, 0.5, 0.9],
        )  # формы: [batch=1, horizon, 3], [batch=1, horizon]

        q = quantiles[0].tolist()
        m = mean[0].tolist()

        for i in range(horizon):
            year = last_year + i + 1
            out_rows.append({
                "metric": metric,
                "year": year,
                "pred_mean": m[i],
                "pred_p10": q[i][0],
                "pred_p50": q[i][1],
                "pred_p90": q[i][2],
            })
    return pd.DataFrame(out_rows)

def main():
    ap = argparse.ArgumentParser(description="Chronos yearly forecaster for Almaty CSVs")
    ap.add_argument("--files", nargs="*", default=DEFAULT_FILES,
                    help="Список CSV с годовыми рядами (Алматы). По умолчанию — три наших файла.")
    ap.add_argument("--horizon", type=int, default=10,
                    help="Горизонт прогноза в годах (по умолчанию 10)")
    ap.add_argument("--model", default="amazon/chronos-t5-base",
                    help="Chronos модель (small/base/large и т.п.)")
    ap.add_argument("--out", default="data/processed/forecasts_yearly.csv",
                    help="куда сохранить CSV с прогнозом")
    ap.add_argument("--dump-json", default="data/processed/forecasts_yearly.json",
                    help="дополнительно сохранить JSON")
    args = ap.parse_args()

    print("📂 Читаю годовые ряды…")
    df_hist = load_all_series(args.files)
    if df_hist.empty:
        print("❌ Не удалось собрать исторические ряды — проверь файлы/столбцы.")
        return

    print(f"✓ Исторических точек: {len(df_hist)} по {df_hist['metric'].nunique()} метрикам.")
    pipe, device = chronos_pipeline(args.model)
    print(f"🧠 Chronos на устройстве: {device}")

    print("🔮 Строю прогнозы…")
    df_pred = forecast_series(pipe, df_hist, horizon=args.horizon, min_points=6)
    if df_pred.empty:
        print("❌ Прогнозов не получилось (слишком мало точек?).")
        return

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df_pred.to_csv(args.out, index=False, encoding="utf-8-sig")
    print(f"✅ CSV сохранён: {args.out}")

    # компактный JSON для фронта/бота
    payload = defaultdict(list)
    for (metric), g in df_pred.groupby("metric"):
        payload[metric] = [
            {"year": int(r.year),
             "mean": float(r.pred_mean),
             "p10": float(r.pred_p10),
             "p50": float(r.pred_p50),
             "p90": float(r.pred_p90)}
            for r in g.itertuples(index=False)
        ]
    Path(args.dump_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"✅ JSON сохранён: {args.dump_json}")

if __name__ == "__main__":
    main()