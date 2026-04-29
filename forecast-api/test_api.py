"""
Тест API через ngrok (или localhost).
Запуск: python test_api.py
"""
import sys
import json
import time
import requests

# ─── НАСТРОЙКИ ────────────────────────────────────────────
# URL берётся из аргумента командной строки или используется localhost
BASE_URL = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"
TIMEOUT  = 180  # секунд (модель грузится долго при первом запросе)
# ──────────────────────────────────────────────────────────

HEADERS = {
    "Content-Type": "application/json",
    "ngrok-skip-browser-warning": "true",  # убирает ngrok-предупреждение
}

PASS = "\033[92m PASS\033[0m"
FAIL = "\033[91m FAIL\033[0m"


def check(name: str, ok: bool, detail: str = ""):
    status = PASS if ok else FAIL
    print(f"[{status}] {name}" + (f"  →  {detail}" if detail else ""))
    return ok


def safe_json(r: requests.Response) -> dict:
    try:
        return r.json()
    except Exception:
        print(f"   Ответ не JSON ({r.status_code}): {r.text[:200]}")
        return {}


def test_health():
    print("\n── Health check ──────────────────────────────")
    r = requests.get(f"{BASE_URL}/api/v1/forecast/health", headers=HEADERS, timeout=10)
    check("HTTP 200", r.status_code == 200, f"got {r.status_code}")
    data = safe_json(r)
    check("status == ok", data.get("status") == "ok", str(data.get("status")))
    check("data_files_ok", data.get("data_files_ok") is True, str(data.get("data_files_ok")))


def test_metrics():
    print("\n── Список метрик ─────────────────────────────")
    r = requests.get(f"{BASE_URL}/api/v1/forecast/metrics", headers=HEADERS, timeout=10)
    check("HTTP 200", r.status_code == 200)
    data = safe_json(r)
    metrics = data.get("available_metrics", [])
    expected = {"CO_mg_m3", "NO2_mg_m3", "SO2_mg_m3", "TSP_mg_m3",
                "population_total", "transport_total"}
    check("Все 6 метрик присутствуют", expected.issubset(set(metrics)), str(metrics))


def test_help():
    print("\n── Bot /help ──────────────────────────────────")
    for lang in ("ru", "en"):
        r = requests.get(
            f"{BASE_URL}/api/v1/bot/help",
            params={"lang": lang},
            headers=HEADERS,
            timeout=10,
        )
        check(f"HTTP 200 (lang={lang})", r.status_code == 200)
        data = safe_json(r)
        check(f"Поле text не пустое (lang={lang})", bool(data.get("text")))


def test_raw_forecast():
    print("\n── Raw forecast (данные для графика) ─────────")
    payload = {"horizon": 5, "metrics": ["CO_mg_m3", "population_total"]}
    t0 = time.time()
    r = requests.post(
        f"{BASE_URL}/api/v1/forecast/",
        json=payload,
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    elapsed = round(time.time() - t0, 1)
    check("HTTP 200", r.status_code == 200, f"got {r.status_code}, {elapsed}s")
    if r.status_code != 200:
        print("   Ошибка:", r.text[:300])
        return

    data = safe_json(r)
    check("status == success",  data.get("status") == "success")
    check("start_year == 2026", data.get("start_year") == 2026, str(data.get("start_year")))
    check("total_points == 10", data.get("total_points") == 10, str(data.get("total_points")))

    # Проверяем структуру первого элемента
    first = data["data"][0] if data.get("data") else {}
    for field in ("year", "metric", "p10", "p50", "p90"):
        check(f"Поле '{field}' есть", field in first)

    check("p10 <= p50 <= p90", first.get("p10", 0) <= first.get("p50", 0) <= first.get("p90", 1))
    check("Год >= 2026", first.get("year", 0) >= 2026, str(first.get("year")))


def test_bot_forecast():
    print("\n── Bot forecast (аналог /forecast N в боте) ──")
    for lang in ("ru", "en"):
        payload = {"horizon": 5, "lang": lang}
        t0 = time.time()
        r = requests.post(
            f"{BASE_URL}/api/v1/bot/forecast",
            json=payload,
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        elapsed = round(time.time() - t0, 1)
        check(f"HTTP 200 (lang={lang})", r.status_code == 200, f"{elapsed}s")
        if r.status_code != 200:
            print("   Ошибка:", r.text[:300])
            continue

        data = safe_json(r)
        check(f"status == success",       data.get("status") == "success")
        check(f"start_year == 2026",      data.get("start_year") == 2026)
        check(f"overall_accuracy есть",   isinstance(data.get("overall_accuracy"), (int, float)))
        check(f"overall_accuracy 50–100", 50 <= data.get("overall_accuracy", 0) <= 100,
              str(data.get("overall_accuracy")))
        check(f"summary не пустой",       bool(data.get("summary")))
        check(f"statistics не пустой",    len(data.get("statistics", [])) > 0)

        stats = data.get("statistics", [])
        if stats:
            s = stats[0]
            for field in ("metric", "name", "start_value", "end_value",
                          "change_pct", "trend", "unit", "accuracy_pct"):
                check(f"Поле '{field}' в statistics", field in s)
            check("trend в (up/down/flat)", s.get("trend") in ("up", "down", "flat"))
            check("accuracy_pct 50–100",
                  50 <= s.get("accuracy_pct", 0) <= 100, str(s.get("accuracy_pct")))

        # Выводим summary чтобы видеть что реально пишет ML
        print(f"\n   --- summary (lang={lang}) ---")
        print("  ", data.get("summary", "").replace("\n", "\n   "))
        print()


def test_validation():
    print("\n── Валидация входных данных ───────────────────")

    # horizon вне диапазона
    r = requests.post(
        f"{BASE_URL}/api/v1/bot/forecast",
        json={"horizon": 999},
        headers=HEADERS,
        timeout=10,
    )
    check("horizon=999 → 422", r.status_code == 422, f"got {r.status_code}")

    # неизвестная метрика
    r = requests.post(
        f"{BASE_URL}/api/v1/forecast/",
        json={"horizon": 5, "metrics": ["wrong_metric"]},
        headers=HEADERS,
        timeout=10,
    )
    check("unknown metric → 400", r.status_code == 400, f"got {r.status_code}")


def main():
    print(f"Тестируем: {BASE_URL}")
    print("=" * 50)

    try:
        requests.get(f"{BASE_URL}/", headers=HEADERS, timeout=5)
    except Exception as e:
        print(f"\nНе удалось подключиться к {BASE_URL}: {e}")
        print("Убедись что API и ngrok запущены.")
        sys.exit(1)

    test_health()
    test_metrics()
    test_help()
    test_validation()
    test_raw_forecast()
    test_bot_forecast()

    print("\n" + "=" * 50)
    print("Готово.")


if __name__ == "__main__":
    main()
