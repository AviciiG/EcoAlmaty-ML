# src/chronos_forecast_cli.py
import argparse
from pathlib import Path
import pandas as pd
from forecast_core import run_full_forecast

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--population", default="data/processed/almaty_population_all.csv")
    ap.add_argument("--transport",  default="data/processed/almaty_transport_yearly.csv")
    ap.add_argument("--air-yearly", default="data/processed/air_yearly_from_monthlies.csv")
    ap.add_argument("--air-yearly-extra", default="data/processed/almaty_yearly_from_excels.csv")
    ap.add_argument("--horizon", type=int, default=80)
    ap.add_argument("--out", default="data/processed/forecasts_yearly.csv")
    ap.add_argument("--json", default="data/processed/forecasts_yearly.json")
    args = ap.parse_args()

    df = run_full_forecast(
        population_csv=args.population,
        transport_csv=args.transport,
        air_yearly_csv=args.air_yearly,
        air_yearly_extra_csv=args.air_yearly_extra,
        horizon=args.horizon,
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    df.to_json(args.json, orient="records", force_ascii=False, indent=2)
    print(f"✅ CSV:  {args.out}")
    print(f"✅ JSON: {args.json}")

if __name__ == "__main__":
    main()