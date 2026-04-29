import os
import json
from pathlib import Path
from typing import Dict
import pandas as pd
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[1] / "src"))
from forecast_core import run_full_forecast, START_YEAR

# Заглушка, если plot_utils.py не найден
try:
    from plot_utils import make_forecast_plots
except ImportError:
    def make_forecast_plots(df, out_dir):
        print("plot_utils not available, skipping chart generation")
        return {}


load_dotenv()

POP = "data/processed/almaty_population_all.csv"
TRN = "data/processed/almaty_transport_yearly.csv"
AIR = "data/processed/air_yearly_from_monthlies.csv"
AIRX = "data/processed/almaty_yearly_from_excels.csv"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

HELP_RU = (
    "🤖 *Привет! Я бот-прогнозист Алматы.*\n\n"
    "*Команды:*\n"
    "  /forecast N — прогноз на N лет (5–100)\n"
    "    *N* — количество шагов/лет, начиная с 2026 года.\n"
    "    Например: `/forecast 20` (Прогноз 2026–2046)\n"
    "  /lang ru|en — выбрать язык\n"
    "  /help — эта справка\n\n"
    "*О чём я рассказываю:*\n"
    "  • Население Алматы\n"
    "  • Количество транспорта\n"
    "  • Качество воздуха (CO, NO₂, SO₂, TSP)\n\n"
    "*Как я работаю:*\n"
    "Использую модель Chronos для анализа исторических данных "
    "и строю прогноз с учётом взаимного влияния факторов. "
    "Рост населения → больше транспорта → хуже воздух.\n\n"
    "_Разработано для диплома IITU_"
)

HELP_EN = (
    "🤖 *Hi! I'm the Almaty forecasting bot.*\n\n"
    "*Commands:*\n"
    "  /forecast N — forecast for N years (5–100)\n"
    "    *N* — number of steps/years, starting from 2026.\n"
    "    Example: `/forecast 20` (Forecast 2026–2046)\n"
    "  /lang ru|en — choose language\n"
    "  /help — this help\n\n"
    "*What I forecast:*\n"
    "  • Almaty population\n"
    "  • Vehicle fleet size\n"
    "  • Air quality (CO, NO₂, SO₂, TSP)\n\n"
    "*How I work:*\n"
    "I use the Chronos model to analyze historical data "
    "and build forecasts considering factor interactions. "
    "Population growth → more vehicles → worse air quality.\n\n"
    "_Developed for IITU diploma project_"
)

def get_lang(ctx: ContextTypes.DEFAULT_TYPE) -> str:
    return ctx.user_data.get("lang", "ru")

def _fmt_num(x, metric, lang="ru"):
    if pd.isna(x) or x is None:
        return "Н/Д" if lang == "ru" else "N/A"
        
    if metric in {"CO_mg_m3", "NO2_mg_m3", "SO2_mg_m3", "TSP_mg_m3"}:
        return f"{x:.3f} мг/м³" if lang == "ru" else f"{x:.3f} mg/m³"
    if metric in {"population_total", "transport_total"}:
        return f"{int(round(x)):,}".replace(",", " ")
    return f"{x:.2f}"

def _delta_pct(a, b):
    if pd.isna(a) or pd.isna(b) or abs(a) < 1e-9: 
        return None
    pct = ((b - a) / a) * 100.0
    return pct

def _trend_emoji(pct):
    if pct is None: return "➡️"
    if pct > 1.0: return "📈" 
    elif pct > 0.1: return "↗️" 
    elif pct < -1.0: return "📉"
    elif pct < -0.1: return "↘️"
    else: return "➡️"

def generate_ollama_summary(df: pd.DataFrame, start_year: int,
                           horizon: int, lang: str) -> str:
    end_year_forecast = start_year + horizon - 1
    end_year_display = start_year + horizon
    
    metrics_data = {}
    for metric in ["population_total", "transport_total", "CO_mg_m3", 
                   "NO2_mg_m3", "SO2_mg_m3", "TSP_mg_m3"]:
        sub = df[df["metric"] == metric]
        if sub.empty: continue
        
        # Берем значения для 2025 и 2025+N-1
        start_val = sub[sub["year"] == start_year]["p50"]
        end_val = sub[sub["year"] == end_year_forecast]["p50"]
        
        if not start_val.empty and not end_val.empty:
            v0 = float(start_val.iloc[0])
            v1 = float(end_val.iloc[0])
            pct = _delta_pct(v0, v1)
            metrics_data[metric] = {"start": v0, "end": v1, "change_pct": pct}
    
    if lang == "ru":
        prompt = f"""Ты — высококвалифицированный аналитик, специализирующийся на урбанистике и экологии.
На основе прогноза для города Алматы на период {start_year}–{end_year_display} напиши красивое, грамотное и детализированное резюме (5-6 предложений).
Удели особое внимание показателям загрязнения воздуха (CO, NO2, SO2, TSP) и тому, как их рост связан с ростом населения и транспорта.
Вот ключевые данные (Start - {start_year}, End - {end_year_display}):
{json.dumps(metrics_data, ensure_ascii=False, indent=2)}
Начни сразу с анализа.
"""
    else:
        prompt = f"""You are a highly qualified analyst specializing in urbanism and ecology.
Based on the forecast for Almaty city for the period {start_year}–{end_year_display}, write a beautiful, articulate, and detailed summary (5-6 sentences) in English.
Pay special attention to air pollution indicators (CO, NO2, SO2, TSP) and how their increase is linked to population and transport growth.
Here are the key data points (Start - {start_year}, End - {end_year_display}):
{json.dumps(metrics_data, ensure_ascii=True, indent=2)}
Start immediately with the analysis.
"""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.5, "top_p": 0.9} 
            },
            timeout=35
        )
        
        if response.status_code == 200:
            result = response.json()
            summary = result.get("response", "").strip()
            if summary: return summary
    except Exception as e:
        print(f"Ollama unavailable: {e}")
    
    return _fallback_summary(metrics_data, start_year, end_year_display, lang)

def _fallback_summary(metrics_data: Dict, start_year: int, end_year_display: int, lang: str) -> str:
    pop_end = metrics_data.get('population_total', {}).get('end', 0)
    pop_pct = metrics_data.get('population_total', {}).get('change_pct', None)
    trn_end = metrics_data.get('transport_total', {}).get('end', 0)
    trn_pct = metrics_data.get('transport_total', {}).get('change_pct', None)

    pollutants_map = {
        "CO_mg_m3": ("Угарный газ (CO)", "Carbon Monoxide (CO)"),
        "NO2_mg_m3": ("Диоксид азота (NO₂)", "Nitrogen Dioxide (NO₂)"),
        "SO2_mg_m3": ("Диоксид серы (SO₂)", "Sulfur Dioxide (SO₂)"),
        "TSP_mg_m3": ("Пыль (TSP)", "Particulate Matter (TSP)"),
    }
    
    if lang == "ru":
        lines = [f"📋 Прогноз для Алматы на {start_year}–{end_year_display} год (Базовый анализ):"]
        
        pop_pct_display = f"({pop_pct:+.1f}%)" if pop_pct is not None else "(Н/Д)"
        trn_pct_display = f"({trn_pct:+.1f}%)" if trn_pct is not None else "(Н/Д)"

        lines.append(
            f"Ожидается значительный рост населения до **{_fmt_num(pop_end, 'population_total')}** {pop_pct_display} "
            f"и увеличение автопарка до **{_fmt_num(trn_end, 'transport_total')}** {trn_pct_display}."
        )
        lines.append("\n**Ключевые показатели загрязнения воздуха:**")
        air_changes = []
        for metric, (name_ru, _) in pollutants_map.items():
            data = metrics_data.get(metric, {})
            v0 = data.get('start', 0.0)
            v1 = data.get('end', 0.0)
            pct = data.get('change_pct')
            
            if pct is None or v0 < 1e-9:
                pct_display = "Н/Д"
            elif abs(pct) < 0.1:
                pct_display = f"{pct:+.2f}%"
            else:
                pct_display = f"{pct:+.1f}%"
            
            emoji = _trend_emoji(pct)
                 
            air_changes.append(
                f" - {name_ru}: с **{v0:.3f}** до **{v1:.3f}** мг/м³ {emoji} ({pct_display})"
            )

        lines.extend(air_changes)
        lines.append(
            "\n*Вывод:* Прогноз показывает устойчивую негативную динамику качества воздуха, что требует срочных регулятивных мер для защиты здоровья горожан."
        )
        return "\n".join(lines)
    else:
        # ... (Аналогичный код для EN) ...
        lines = [f"📋 Forecast for Almaty {start_year}–{end_year_display} (Basic Analysis):"]
        
        pop_pct_display = f"({pop_pct:+.1f}%)" if pop_pct is not None else "(N/A)"
        trn_pct_display = f"({trn_pct:+.1f}%)" if trn_pct is not None else "(N/A)"

        lines.append(
            f"Significant population growth is expected up to **{_fmt_num(pop_end, 'population_total', 'en')}** {pop_pct_display}, "
            f"with the vehicle fleet increasing to **{_fmt_num(trn_end, 'transport_total', 'en')}** {trn_pct_display}."
        )
        lines.append("\n**Key Air Pollution Indicators:**")
        air_changes = []
        for metric, (_, name_en) in pollutants_map.items():
            data = metrics_data.get(metric, {})
            v0 = data.get('start', 0.0)
            v1 = data.get('end', 0.0)
            pct = data.get('change_pct')
            
            if pct is None or v0 < 1e-9:
                pct_display = "N/A"
            elif abs(pct) < 0.1:
                pct_display = f"{pct:+.2f}%"
            else:
                pct_display = f"{pct:+.1f}%"
            
            emoji = _trend_emoji(pct)
                 
            air_changes.append(
                f" - {name_en}: from **{v0:.3f}** to **{v1:.3f}** mg/m³ {emoji} ({pct_display})"
            )
        
        lines.extend(air_changes)
        lines.append(
            "\n*Conclusion:* The forecast indicates a steady negative trend in air quality, which requires urgent regulatory measures to protect public health."
        )
        return "\n".join(lines)


def detailed_statistics(df: pd.DataFrame, start_year: int,
                       horizon: int, lang: str) -> str:
    end_year_forecast = start_year + horizon - 1
    end_year_display = start_year + horizon
    
    metric_names = {
        "ru": {
            "population_total": "👥 Население",
            "transport_total": "🚗 Транспорт",
            "CO_mg_m3": "💨 Угарный газ (CO)",
            "NO2_mg_m3": "💨 Диоксид азота (NO₂)",
            "SO2_mg_m3": "💨 Диоксид серы (SO₂)",
            "TSP_mg_m3": "💨 Пыль (TSP)"
        },
        "en": {
            "population_total": "👥 Population",
            "transport_total": "🚗 Transport",
            "CO_mg_m3": "💨 Carbon Monoxide (CO)",
            "NO2_mg_m3": "💨 Nitrogen Dioxide (NO₂)",
            "SO2_mg_m3": "💨 Sulfur Dioxide (SO₂)",
            "TSP_mg_m3": "💨 Total Suspended Particulates (TSP)"
        }
    }
    
    lines = []
    
    for metric in ["population_total", "transport_total", "CO_mg_m3", 
                   "NO2_mg_m3", "SO2_mg_m3", "TSP_mg_m3"]:
        sub = df[df["metric"] == metric]
        if sub.empty: continue
        
        start_val = sub[sub["year"] == start_year]["p50"]
        end_val = sub[sub["year"] == end_year_forecast]["p50"]
        
        if not start_val.empty and not end_val.empty:
            v0 = float(start_val.iloc[0])
            v1 = float(end_val.iloc[0])
            pct = _delta_pct(v0, v1)
            
            name = metric_names[lang].get(metric, metric)
            
            if pct is None:
                pct_display = "Н/Д" if lang == "ru" else "N/A"
                emoji = "➡️"
            elif abs(pct) < 0.1:
                pct_display = f"{pct:+.2f}%" 
                emoji = _trend_emoji(pct)
            else:
                pct_display = f"{pct:+.1f}%"
                emoji = _trend_emoji(pct)
            
            
            line = (f"{name}: "
               f"**{_fmt_num(v0, metric, lang)}** → "
               f"**{_fmt_num(v1, metric, lang)}** "
               f"{emoji} ({pct_display})")
                   
            lines.append(line)
    
    header = f"📊 *Статистика {start_year}–{end_year_display}:*\n" if lang == "ru" else f"📊 *Statistics {start_year}–{end_year_display}:*\n"
    
    return header + "\n".join(lines)



async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data["lang"] = "ru"
    await update.message.reply_text(HELP_RU, parse_mode=ParseMode.MARKDOWN)

async def help_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(ctx)
    text = HELP_RU if lang == "ru" else HELP_EN
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def lang_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or ctx.args[0].lower() not in ("ru", "en"):
        await update.message.reply_text(
            "Используй: /lang ru или /lang en\n"
            "Use: /lang ru or /lang en"
        )
        return
    
    ctx.user_data["lang"] = ctx.args[0].lower()
    await help_cmd(update, ctx)


async def forecast_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    lang = get_lang(ctx)
    
    try:
        if not ctx.args:
            msg = ("Укажи горизонт прогноза: /forecast 20" if lang == "ru" 
                   else "Provide forecast horizon: /forecast 20")
            await update.message.reply_text(msg)
            return
        
        horizon = int(ctx.args[0])
        if horizon < 5 or horizon > 100:
            msg = ("Горизонт должен быть от 5 до 100 лет" if lang == "ru" 
                   else "Horizon must be between 5 and 100 years")
            await update.message.reply_text(msg)
            return
        
        actual_horizon = horizon
        start_point = START_YEAR
        end_year_display = start_point + actual_horizon
        
        wait_msg = (f"⏳ *Строю прогноз на период {start_point}–{end_year_display}* ({actual_horizon} лет)...\n"
                   f"Это займёт 1-2 минуты." if lang == "ru" 
                   else f"⏳ *Building forecast for {start_point}–{end_year_display}* ({actual_horizon} years)....\n"
                   f"This will take 1-2 minutes.")
        status_message = await update.message.reply_text(wait_msg, parse_mode=ParseMode.MARKDOWN)
        
        df = run_full_forecast(POP, TRN, AIR, AIRX, horizon=actual_horizon)
        
        out_dir = Path("data/processed")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_csv = out_dir / "forecasts_yearly.csv"
        df.to_csv(out_csv, index=False)
        
        await status_message.edit_text(
            "✅ Прогноз готов! Генерирую *красивые* графики..." if lang == "ru"
            else "✅ Forecast ready! Generating *nice* charts..."
        , parse_mode=ParseMode.MARKDOWN)
        
        plot_paths = make_forecast_plots(df, out_dir=str(out_dir / "plots"))
        
        for metric, path in plot_paths.items():
            if Path(path).exists():
                caption_map = {
                    "population_total": f"**Население Алматы ({start_point}–{end_year_display})**" if lang == "ru" else f"**Almaty Population ({start_point}–{end_year_display})**",
                    "transport_total": f"**Автопарк Алматы ({start_point}–{end_year_display})**" if lang == "ru" else f"**Almaty Vehicle Fleet ({start_point}–{end_year_display})**",
                    "CO_mg_m3": f"**Угарный газ (CO) ({start_point}–{end_year_display})**" if lang == "ru" else f"**Carbon Monoxide (CO) ({start_point}–{end_year_display})**",
                    "NO2_mg_m3": f"**Диоксид азота (NO₂) ({start_point}–{end_year_display})**" if lang == "ru" else f"**Nitrogen Dioxide (NO₂) ({start_point}–{end_year_display})**",
                    "SO2_mg_m3": f"**Диоксид серы (SO₂) ({start_point}–{end_year_display})**" if lang == "ru" else f"**Sulfur Dioxide (SO₂) ({start_point}–{end_year_display})**",
                    "TSP_mg_m3": f"**Пыль (TSP) ({start_point}–{end_year_display})**" if lang == "ru" else f"**Particulate Matter (TSP) ({start_point}–{end_year_display})**",
                }
                caption = caption_map.get(metric, metric)
                await update.message.reply_photo(photo=open(path, 'rb'), caption=caption, parse_mode=ParseMode.MARKDOWN)

        stats = detailed_statistics(df, start_point, actual_horizon, lang)
        await update.message.reply_text(stats, parse_mode=ParseMode.MARKDOWN)
        
        summary = generate_ollama_summary(df, start_point, actual_horizon, lang)
        
        final_msg = f"🎯 *АНАЛИТИЧЕСКОЕ РЕЗЮМЕ:* 👇\n\n{summary}" if lang == "ru" else f"🎯 *ANALYTICAL SUMMARY:* 👇\n\n{summary}"
        
        await update.message.reply_text(final_msg, parse_mode=ParseMode.MARKDOWN)
        
        await status_message.delete()
        
    except ValueError:
        msg = "Горизонт должен быть числом от 5 до 100" if lang == "ru" else "Horizon must be a number between 5 and 100"
        await update.message.reply_text(msg)
    except Exception as e:
        print(f"Forecast error: {e}")
        if update.message:
            await update.message.reply_text(
                f"{'Критическая ошибка' if lang == 'ru' else 'Critical error'}: {e}"
            )

async def fallback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message is None:
        return
    lang = get_lang(ctx)
    txt = (update.message.text or "").lower()
    
    keywords_ru = ["прогноз", "население", "транспорт", "воздух", "алматы", "экология"]
    
    if any(k in txt for k in keywords_ru):
        msg = ("Используй команду /forecast N для прогноза.\n"
               "Например: /forecast 20" if lang == "ru"
               else "Use /forecast N command for forecasting.\n"
               "Example: /forecast 20")
    else:
        msg = ("Я специализируюсь на прогнозах для Алматы "
               "(население, транспорт, качество воздуха).\n"
               "Напиши /help для списка команд." if lang == "ru"
               else "I specialize in Almaty forecasts "
               "(population, transport, air quality).\n"
               "Type /help for command list.")
    
    await update.message.reply_text(msg)

def main():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("ERROR: TELEGRAM_TOKEN not set")
        return
    
    app = Application.builder().token(token).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("lang", lang_cmd))
    app.add_handler(CommandHandler("forecast", forecast_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback))
    
    print("Bot started, polling.")
    app.run_polling()


if __name__ == '__main__':
    main()