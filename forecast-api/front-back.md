# Интеграция с Forecast API

ML-сервис прогнозирования качества воздуха, населения и транспорта Алматы.  
Модель: **Amazon Chronos**. Прогноз начинается с **2026 года**.

---

## Быстрый старт

**Base URL** (текущий ngrok, меняется при перезапуске):
```
https://shimmy-unequal-rubbing.ngrok-free.app
```

**Обязательный заголовок** для всех запросов через ngrok:
```
ngrok-Skip-Browser-Warning: true
```
> Без этого заголовка ngrok вернёт HTML-страницу предупреждения вместо JSON.

---

## Эндпоинты

| Метод | Путь | Аналог в боте | Описание |
|---|---|---|---|
| `GET` | `/api/v1/forecast/health` | — | Проверка статуса сервиса |
| `GET` | `/api/v1/forecast/metrics` | — | Список доступных метрик |
| `POST` | `/api/v1/forecast/` | — | Сырые данные прогноза (для графиков) |
| `GET` | `/api/v1/bot/help` | `/help` | Текст справки |
| `POST` | `/api/v1/bot/forecast` | `/forecast N` | Прогноз с текстом и статистикой |

---

## Описание эндпоинтов

### GET `/api/v1/forecast/health`

Проверка что сервис живёт и файлы данных найдены.

**Ответ:**
```json
{
  "status": "ok",
  "model": "amazon/chronos-t5-small",
  "version": "1.0.0",
  "data_files_ok": true
}
```

- `status` — `"ok"` если всё в порядке, `"degraded"` если CSV-файлы не найдены
- `data_files_ok` — если `false`, прогноз работать не будет

---

### GET `/api/v1/forecast/metrics`

Список всех доступных метрик.

**Ответ:**
```json
{
  "available_metrics": [
    "CO_mg_m3",
    "NO2_mg_m3",
    "SO2_mg_m3",
    "TSP_mg_m3",
    "population_total",
    "transport_total"
  ],
  "descriptions": {
    "CO_mg_m3": "Оксид углерода CO (мг/м³)",
    "NO2_mg_m3": "Диоксид азота NO₂ (мг/м³)",
    "SO2_mg_m3": "Диоксид серы SO₂ (мг/м³)",
    "TSP_mg_m3": "Взвешенные TSP (мг/м³)",
    "population_total": "Население Алматы (чел.)",
    "transport_total": "Транспортные средства (ед.)"
  }
}
```

---

### POST `/api/v1/bot/forecast`

Основной эндпоинт. Возвращает то же самое, что Telegram-бот после команды `/forecast N`.

**Запрос:**
```json
{
  "horizon": 20,
  "lang": "ru"
}
```

| Параметр | Тип | Обязательный | Допустимые значения | По умолчанию |
|---|---|---|---|---|
| `horizon` | int | нет | 5–100 | 20 |
| `lang` | string | нет | `"ru"`, `"en"` | `"ru"` |

**Ответ:**
```json
{
  "status": "success",
  "horizon": 20,
  "start_year": 2026,
  "end_year": 2045,
  "lang": "ru",
  "overall_accuracy": 86.7,
  "summary": "📋 Прогноз для Алматы 2026–2045:\n\n👥 Население: 2 281 883 чел. → 2 389 200 чел. 📈 (+4.7%)  [точность: 95.1%]\n🚗 Транспорт: 1 325 334 ед. → 1 167 726 ед. 📉 (-11.9%)  [точность: 86.6%]\n...\n\nТочность данного прогноза составляет: 86.7%\nВывод: Прогноз показывает динамику качества воздуха в зависимости от роста населения и транспорта Алматы.",
  "statistics": [
    {
      "metric": "population_total",
      "name": "👥 Население",
      "start_value": 2281883.0,
      "end_value": 2389200.0,
      "change_pct": 4.7,
      "trend": "up",
      "unit": "чел.",
      "accuracy_pct": 95.1
    },
    {
      "metric": "transport_total",
      "name": "🚗 Транспорт",
      "start_value": 1325334.0,
      "end_value": 1167726.0,
      "change_pct": -11.9,
      "trend": "down",
      "unit": "ед.",
      "accuracy_pct": 86.6
    },
    {
      "metric": "CO_mg_m3",
      "name": "💨 Угарный газ (CO)",
      "start_value": 1.342,
      "end_value": 1.365,
      "change_pct": 1.7,
      "trend": "up",
      "unit": "мг/м³",
      "accuracy_pct": 84.1
    },
    {
      "metric": "NO2_mg_m3",
      "name": "💨 Диоксид азота (NO₂)",
      "start_value": 0.100,
      "end_value": 0.108,
      "change_pct": 7.8,
      "trend": "up",
      "unit": "мг/м³",
      "accuracy_pct": 84.2
    },
    {
      "metric": "SO2_mg_m3",
      "name": "💨 Диоксид серы (SO₂)",
      "start_value": 0.009,
      "end_value": 0.009,
      "change_pct": 3.6,
      "trend": "up",
      "unit": "мг/м³",
      "accuracy_pct": 82.7
    },
    {
      "metric": "TSP_mg_m3",
      "name": "💨 Пыль (TSP)",
      "start_value": 0.152,
      "end_value": 0.147,
      "change_pct": -3.0,
      "trend": "down",
      "unit": "мг/м³",
      "accuracy_pct": 87.3
    }
  ]
}
```

**Поля ответа и как их использовать:**

| Поле | Тип | Использование в UI |
|---|---|---|
| `summary` | string | Готовый текстовый блок — показывать как есть в карточке резюме |
| `overall_accuracy` | float | Один бейдж точности на всю карточку прогноза |
| `start_year` / `end_year` | int | Заголовок: "Прогноз 2026–2045" |
| `statistics[].start_value` | float | Начальное значение метрики (2026 год) для графика |
| `statistics[].end_value` | float | Конечное значение метрики для графика |
| `statistics[].change_pct` | float | Процент изменения, напр. `+4.7%` или `-11.9%` |
| `statistics[].trend` | string | `"up"` → ↑, `"down"` → ↓, `"flat"` → → |
| `statistics[].accuracy_pct` | float | Бейдж точности под каждым графиком |
| `statistics[].unit` | string | Единица: `"чел."`, `"ед."`, `"мг/м³"` |

---

### GET `/api/v1/bot/help`

**Параметры запроса:**

| Параметр | Тип | Значения | По умолчанию |
|---|---|---|---|
| `lang` | string | `"ru"`, `"en"` | `"ru"` |

**Запрос:**
```
GET /api/v1/bot/help?lang=ru
```

**Ответ:**
```json
{
  "lang": "ru",
  "text": "🤖 Привет! Я бот-прогнозист Алматы.\n\nКоманды:\n  /help — эта справка\n  /forecast N — прогноз на N лет (5–100), начиная с 2026\n..."
}
```

---

### POST `/api/v1/forecast/` (сырые данные для кастомных графиков)

Если нужны все точки прогноза по годам (p10/p50/p90) для построения своих графиков.

**Запрос:**
```json
{
  "horizon": 10,
  "metrics": ["CO_mg_m3", "population_total"]
}
```

- `metrics` — опционально, если не передать — вернёт все 6 метрик
- `horizon` — 1–200

**Ответ:**
```json
{
  "status": "success",
  "horizon": 10,
  "start_year": 2026,
  "metrics_returned": 2,
  "total_points": 20,
  "data": [
    {
      "year": 2026,
      "metric": "CO_mg_m3",
      "p10": 1.21,
      "p50": 1.34,
      "p90": 1.48
    },
    {
      "year": 2027,
      "metric": "CO_mg_m3",
      "p10": 1.22,
      "p50": 1.35,
      "p90": 1.51
    }
  ]
}
```

- `p10` — оптимистичный сценарий (нижняя граница)
- `p50` — базовый прогноз (медиана)
- `p90` — пессимистичный сценарий (верхняя граница)

---

## Примеры кода

### Frontend — React + TypeScript

#### Типы (`src/types/forecast.ts`)

```ts
export interface MetricStat {
  metric: string;
  name: string;
  start_value: number;
  end_value: number;
  change_pct: number | null;
  trend: "up" | "down" | "flat";
  unit: string;
  accuracy_pct: number;
}

export interface ForecastResponse {
  status: string;
  horizon: number;
  start_year: number;
  end_year: number;
  lang: string;
  overall_accuracy: number;
  summary: string;
  statistics: MetricStat[];
}
```

#### API-клиент (`src/api/forecast.ts`)

```ts
const BASE_URL = "https://shimmy-unequal-rubbing.ngrok-free.app";

const headers = {
  "Content-Type": "application/json",
  "ngrok-Skip-Browser-Warning": "true",
};

export async function fetchForecast(
  horizon: number,
  lang: "ru" | "en"
): Promise<ForecastResponse> {
  const res = await fetch(`${BASE_URL}/api/v1/bot/forecast`, {
    method: "POST",
    headers,
    body: JSON.stringify({ horizon, lang }),
  });

  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail ?? "Forecast request failed");
  }

  return res.json();
}

export async function fetchHelp(lang: "ru" | "en"): Promise<{ lang: string; text: string }> {
  const res = await fetch(`${BASE_URL}/api/v1/bot/help?lang=${lang}`, { headers });
  if (!res.ok) throw new Error("Help request failed");
  return res.json();
}
```

#### Компонент прогноза (`src/components/ForecastCard.tsx`)

```tsx
import { useState } from "react";
import { fetchForecast } from "../api/forecast";
import type { ForecastResponse, MetricStat } from "../types/forecast";

const TREND_ICON: Record<string, string> = {
  up: "↑",
  down: "↓",
  flat: "→",
};

function MetricRow({ stat }: { stat: MetricStat }) {
  const sign = stat.change_pct !== null && stat.change_pct >= 0 ? "+" : "";
  const pct = stat.change_pct !== null ? `${sign}${stat.change_pct.toFixed(1)}%` : "—";

  return (
    <tr>
      <td>{stat.name}</td>
      <td>{stat.start_value.toLocaleString()}</td>
      <td>{stat.end_value.toLocaleString()}</td>
      <td>{pct}</td>
      <td>{TREND_ICON[stat.trend]}</td>
      <td>{stat.accuracy_pct}%</td>
    </tr>
  );
}

export function ForecastCard() {
  const [horizon, setHorizon] = useState(20);
  const [lang, setLang] = useState<"ru" | "en">("ru");
  const [data, setData] = useState<ForecastResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchForecast(horizon, lang);
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Неизвестная ошибка");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div>
        <label>
          Горизонт (лет):
          <input
            type="number"
            min={5}
            max={100}
            value={horizon}
            onChange={(e) => setHorizon(Number(e.target.value))}
          />
        </label>
        <label>
          Язык:
          <select value={lang} onChange={(e) => setLang(e.target.value as "ru" | "en")}>
            <option value="ru">RU</option>
            <option value="en">EN</option>
          </select>
        </label>
        <button onClick={handleSubmit} disabled={loading}>
          {loading ? "Загрузка..." : "Построить прогноз"}
        </button>
      </div>

      {error && <p style={{ color: "red" }}>{error}</p>}

      {data && (
        <div>
          <h2>
            Прогноз {data.start_year}–{data.end_year}
          </h2>
          <p>Общая точность: <strong>{data.overall_accuracy}%</strong></p>

          <table>
            <thead>
              <tr>
                <th>Метрика</th>
                <th>Начало ({data.start_year})</th>
                <th>Конец ({data.end_year})</th>
                <th>Изменение</th>
                <th>Тренд</th>
                <th>Точность</th>
              </tr>
            </thead>
            <tbody>
              {data.statistics.map((stat) => (
                <MetricRow key={stat.metric} stat={stat} />
              ))}
            </tbody>
          </table>

          <pre style={{ whiteSpace: "pre-wrap", marginTop: "1rem" }}>
            {data.summary}
          </pre>
        </div>
      )}
    </div>
  );
}
```

---

### Backend — Go

#### Структуры (`forecast/types.go`)

```go
package forecast

type ForecastRequest struct {
    Horizon int    `json:"horizon"`
    Lang    string `json:"lang"`
}

type MetricStat struct {
    Metric      string   `json:"metric"`
    Name        string   `json:"name"`
    StartValue  float64  `json:"start_value"`
    EndValue    float64  `json:"end_value"`
    ChangePct   *float64 `json:"change_pct"`
    Trend       string   `json:"trend"`
    Unit        string   `json:"unit"`
    AccuracyPct float64  `json:"accuracy_pct"`
}

type ForecastResponse struct {
    Status          string       `json:"status"`
    Horizon         int          `json:"horizon"`
    StartYear       int          `json:"start_year"`
    EndYear         int          `json:"end_year"`
    Lang            string       `json:"lang"`
    OverallAccuracy float64      `json:"overall_accuracy"`
    Summary         string       `json:"summary"`
    Statistics      []MetricStat `json:"statistics"`
}

type HealthResponse struct {
    Status      string `json:"status"`
    Model       string `json:"model"`
    Version     string `json:"version"`
    DataFilesOk bool   `json:"data_files_ok"`
}

type HelpResponse struct {
    Lang string `json:"lang"`
    Text string `json:"text"`
}

type APIError struct {
    Detail string `json:"detail"`
}
```

#### Клиент (`forecast/client.go`)

```go
package forecast

import (
    "bytes"
    "context"
    "encoding/json"
    "fmt"
    "net/http"
    "time"
)

const (
    baseURL = "https://shimmy-unequal-rubbing.ngrok-free.app"
    timeout = 60 * time.Second
)

type Client struct {
    http *http.Client
}

func NewClient() *Client {
    return &Client{
        http: &http.Client{Timeout: timeout},
    }
}

func (c *Client) newRequest(ctx context.Context, method, path string, body any) (*http.Request, error) {
    var buf bytes.Buffer
    if body != nil {
        if err := json.NewEncoder(&buf).Encode(body); err != nil {
            return nil, err
        }
    }

    req, err := http.NewRequestWithContext(ctx, method, baseURL+path, &buf)
    if err != nil {
        return nil, err
    }

    req.Header.Set("Content-Type", "application/json")
    req.Header.Set("ngrok-Skip-Browser-Warning", "true")
    return req, nil
}

func decode[T any](resp *http.Response) (T, error) {
    var result T
    defer resp.Body.Close()

    if resp.StatusCode >= 400 {
        var apiErr APIError
        json.NewDecoder(resp.Body).Decode(&apiErr)
        return result, fmt.Errorf("API error %d: %s", resp.StatusCode, apiErr.Detail)
    }

    if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
        return result, fmt.Errorf("decode error: %w", err)
    }
    return result, nil
}

func (c *Client) GetForecast(ctx context.Context, horizon int, lang string) (ForecastResponse, error) {
    req, err := c.newRequest(ctx, http.MethodPost, "/api/v1/bot/forecast", ForecastRequest{
        Horizon: horizon,
        Lang:    lang,
    })
    if err != nil {
        return ForecastResponse{}, err
    }

    resp, err := c.http.Do(req)
    if err != nil {
        return ForecastResponse{}, err
    }
    return decode[ForecastResponse](resp)
}

func (c *Client) GetHelp(ctx context.Context, lang string) (HelpResponse, error) {
    req, err := c.newRequest(ctx, http.MethodGet, "/api/v1/bot/help?lang="+lang, nil)
    if err != nil {
        return HelpResponse{}, err
    }

    resp, err := c.http.Do(req)
    if err != nil {
        return HelpResponse{}, err
    }
    return decode[HelpResponse](resp)
}

func (c *Client) CheckHealth(ctx context.Context) (HealthResponse, error) {
    req, err := c.newRequest(ctx, http.MethodGet, "/api/v1/forecast/health", nil)
    if err != nil {
        return HealthResponse{}, err
    }

    resp, err := c.http.Do(req)
    if err != nil {
        return HealthResponse{}, err
    }
    return decode[HealthResponse](resp)
}
```

#### Использование (`main.go`)

```go
package main

import (
    "context"
    "fmt"
    "log"

    "yourmodule/forecast"
)

func main() {
    client := forecast.NewClient()
    ctx := context.Background()

    // Проверка здоровья сервиса
    health, err := client.CheckHealth(ctx)
    if err != nil {
        log.Fatalf("health check failed: %v", err)
    }
    fmt.Printf("Service status: %s, files ok: %v\n", health.Status, health.DataFilesOk)

    // Получить прогноз
    data, err := client.GetForecast(ctx, 20, "ru")
    if err != nil {
        log.Fatalf("forecast failed: %v", err)
    }

    fmt.Printf("Прогноз %d–%d\n", data.StartYear, data.EndYear)
    fmt.Printf("Точность: %.1f%%\n", data.OverallAccuracy)
    fmt.Println(data.Summary)

    for _, stat := range data.Statistics {
        pct := 0.0
        if stat.ChangePct != nil {
            pct = *stat.ChangePct
        }
        fmt.Printf("  %s: %.0f → %.0f (%+.1f%%) [точность: %.1f%%]\n",
            stat.Name, stat.StartValue, stat.EndValue, pct, stat.AccuracyPct,
        )
    }
}
```

---

## Обработка ошибок

| HTTP-статус | Когда возникает | Что делать |
|---|---|---|
| `200` | Успех | Обработать ответ |
| `400` | Передана неизвестная метрика | Показать сообщение об ошибке пользователю |
| `422` | Нарушена валидация (например `horizon=999`) | Проверить параметры запроса |
| `500` | Ошибка ML-модели или файлов данных | Показать "Сервис временно недоступен" |

**Структура ошибки:**
```json
{
  "detail": "Описание ошибки"
}
```

---

## Важные замечания

1. **Первый запрос медленнее** — модель Chronos загружается в память (~10–30 сек). Последующие запросы быстрее (2–5 сек).

2. **ngrok URL меняется** при каждом перезапуске `ngrok http 8000`. При переезде на постоянный сервер (VPS, Railway, Render и т.д.) `ngrok-Skip-Browser-Warning` заголовок больше не нужен.

3. **CORS настроен** — фронт может обращаться к API напрямую из браузера без прокси.

4. **Timeout** — ставить минимум 60 секунд, так как ML-инференс занимает время.
