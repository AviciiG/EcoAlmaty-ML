# Almaty Forecast API

ML сервис для прогноза качества воздуха, населения и транспорта в Алматы. Прогноз с 2026 года.

**Запуск:**
```bash
cd forecast-api && source ../.venv/bin/activate
uvicorn src.main:app --port 8000
```

**Swagger (интерактивная документация):** `http://localhost:8000/docs`

---

## Эндпоинты

| Метод | URL | Описание |
|-------|-----|----------|
| GET  | `/api/v1/bot/help?lang=ru` | Справка (аналог /help в боте) |
| POST | `/api/v1/bot/forecast` | Прогноз с резюме и точностью (аналог /forecast N) |
| POST | `/api/v1/forecast/` | Сырые данные по годам — для графиков |
| GET  | `/api/v1/forecast/metrics` | Список метрик |
| GET  | `/api/v1/forecast/health` | Статус сервиса |

---

## POST /api/v1/bot/forecast — главный эндпоинт

**Запрос:**
```json
{ "horizon": 20, "lang": "ru" }
```

| Поле    | По умолчанию | Описание |
|---------|--------------|----------|
| horizon | 20           | Лет прогноза (5–100) |
| lang    | ru           | Язык: ru или en |

**Ответ:**
```json
{
  "status": "success",
  "start_year": 2026,
  "end_year": 2045,
  "overall_accuracy": 87.4,
  "summary": "Прогноз для Алматы 2026–2045:\nНаселение: 2 195 100 → 3 140 000 чел. 📈 (+43.0%)  [точность: 94.2%]\n...\nТочность данного прогноза составляет: 87.4%",
  "statistics": [
    {
      "metric": "population_total",
      "name": "👥 Население",
      "start_value": 2195100,
      "end_value": 3140000,
      "change_pct": 43.0,
      "trend": "up",
      "unit": "чел.",
      "accuracy_pct": 94.2
    }
  ]
}
```

Первый запрос занимает 30–60 сек (загрузка модели), последующие быстрее.

---

## POST /api/v1/forecast/ — данные для графика

**Запрос:**
```json
{ "horizon": 10, "metrics": ["CO_mg_m3", "population_total"] }
```

**Ответ (массив data):**
```json
{ "year": 2026, "metric": "CO_mg_m3", "p10": 1.18, "p50": 1.46, "p90": 1.60 }
```

`p50` — базовый прогноз, `p10`–`p90` — диапазон неопределённости.

---

## Доступные метрики

| Код | Описание |
|-----|----------|
| `CO_mg_m3` | Угарный газ (мг/м³) |
| `NO2_mg_m3` | Диоксид азота (мг/м³) |
| `SO2_mg_m3` | Диоксид серы (мг/м³) |
| `TSP_mg_m3` | Взвешенные вещества (мг/м³) |
| `population_total` | Население Алматы (чел.) |
| `transport_total` | Транспорт (ед.) |

---

## Примеры

**JavaScript (фронт):**
```javascript
const res = await fetch('https://ваш-url/api/v1/bot/forecast', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ horizon: 20, lang: 'ru' })
});
const data = await res.json();
console.log(data.summary);           // готовый текст с точностью
console.log(data.overall_accuracy);  // 87.4
console.log(data.statistics);        // массив по метрикам
```

**Python (бек):**
```python
import requests
data = requests.post(
    'https://ваш-url/api/v1/bot/forecast',
    json={"horizon": 20, "lang": "ru"},
    timeout=120
).json()
print(data['overall_accuracy'])  # 87.4
print(data['summary'])
```

---

## Ошибки

| Код | Причина |
|-----|---------|
| 400 | Неизвестная метрика |
| 500 | Ошибка ML модели (подробности в поле `detail`) |
