# ParseK

Кратко: ParseK — это B2B lead scraping pipeline для вертикалей Gambling / Nutra / Crypto.

Ключевые изменения (последние коммиты):
- Перенес кеш браузеров Playwright в именованный том Docker (`playwright-cache`) и использую официальный образ Playwright.
- Добавлен `RotatingFileHandler` для логов, чтобы ограничить рост файлов журнала.
- Полностью переработан `src/validator.py` по строгому бизнес-спеку: точная GEO-фильтрация, тонкие правила для role-емейлов (info@, support@ и т.п.), нормализация Telegram/Skype/Discord контактов.
- `src/main.py` теперь сохраняет `validation_summary.json` с полями `total_processed`, `valid_count`, `rejected_count`, `by_reason` и `sample_rejections` (до 15 примеров).

Быстрый старт (локально):

1) Создайте виртуальное окружение и установите зависимости (пример для Windows PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2) Запуск пайплайна (локально, Playwright должен быть установлен):

```powershell
python -m src.main --headless --export-json
```

Docker (рекомендуется):

```powershell
docker-compose up --build -d
```

Файлы состояния и логов:
- `logs/pipeline.log` — ротация логов настроена (5MB, 3 бэкапа).
- `logs/validation_summary.json` — итог валидации после прогонки.
- `output/` — экспортированные результаты (`.json`, `.csv`, `.txt`).

Полезно знать:
- Правила фильтрации email настроены так, чтобы минимизировать ложные срабатывания: `sales.john@example.com` будет пропущен, а `info-team@example.com` или `info123@example.com` — отклонены.
- При необходимости я могу интегрировать graceful shutdown для Playwright (закрытие browser/context при SIGTERM). Напишите, если нужно.

Автор и репозиторий: https://github.com/ALLAHPUDORAS/ParseK
# B2B Lead Scraping Pipeline

Automated lead scraping and validation pipeline for iGaming, Nutra, Gambling, and Crypto verticals.

## Project Summary

This repository contains a Python-based scraping pipeline that:
- crawls affiliate network sources,
- extracts company card data,
- validates leads by geo and contact quality,
- exports results to JSON, CSV, and plain text,
- runs inside Docker with persistent host mounts,
- supports both repeated polling and one-shot execution.

## Repository Layout

Root files:
- `Dockerfile` — builds the container image, installs Python and Playwright dependencies, and configures the entrypoint.
- `docker-compose.yml` — defines the service, persistent volumes, environment file, restart policy, and healthcheck.
- `entrypoint.sh` — background loop runner with one-shot support.
- `.gitignore` — ignores local environment files, output artifacts, logs, and Playwright browser cache.
- `.dockerignore` — ignores local build artifacts for the Docker build context.
- `.env.example` — example environment variables for runtime configuration.
- `requirements.txt` — Python dependencies.
- `README.md` — this documentation.

Source code:
- `src/main.py` — pipeline orchestration, logging, argument parsing, and exports.
- `src/scraper.py` — Playwright scraper, pagination handling, page parsing, and contact extraction.
- `src/validator.py` — lead validation, geo filtering, role email filtering, and normalized contact extraction.
- `src/exporter.py` — JSON/CSV/TXT export logic.
- `src/config.py` — site configuration, verticals, GEO rules, output paths, and defaults.

## Key Features

- Headless browser scraping using Playwright.
- Persistent `playwright-browsers/` volume to avoid repeated browser downloads.
- Host-mounted `output/` and `logs/` for result persistence.
- Automatic error resilience in the background entrypoint.
- Full export support: JSON, CSV, and human-readable text file.
- GEO-fence filtering to exclude RU/BY/CIS and other blocked regions.
- Generic contact filtering to remove role emails like `info@`, `support@`, `admin@`.

## Local Development

```powershell
cd D:\ParseK
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

Use Bash / WSL:

```bash
cd /mnt/d/ParseK
test -f .venv/bin/activate && source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m playwright install chromium
```

## Run Locally

```powershell
python -m src.main --headless --export-json --export-csv --export-text
```

Default behavior if no export flags are passed:
- `leads.json`
- `leads.csv`
- `leads_list.txt`

## Docker Usage

1. Clone the repository:

```powershell
git clone https://github.com/ALLAHPUDORAS/ParseK.git
cd ParseK
copy .env.example .env
```

2. Customize `.env` if needed.

3. Build and start the service:

```powershell
docker compose up --build
```

### Docker Compose behavior

The service mounts:
- `./output` -> `/app/src/output`
- `./logs` -> `/app/src/logs`
- `./playwright-browsers` -> `/ms-playwright`

Environment variables from `.env` are loaded and `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` is enforced.

### One-shot mode

Set `ONE_SHOT=1` in `.env` or pass it into the container at runtime to run the pipeline once and exit.

## Output Files

After a successful run, output files are written to `output/` on the host:
- `leads.json`
- `leads.csv`
- `leads_list.txt`

Log output is written to `logs/pipeline.log`.

## Recommended Git Commits

GitHub shows the same commit message on all files that were added or changed in a single commit. That is why the current repository view may display one placeholder message for many files.

For future cleanup or when splitting history, use these more precise folder-based commit messages:

- `src/`: "Implement scraping, validation, and export pipeline logic"
- `Dockerfile`: "Build Python runtime image and install Playwright dependencies"
- `docker-compose.yml` + `entrypoint.sh`: "Add Docker Compose service, persistent output/log mounts, and background Playwright entrypoint"
- `.gitignore` / `.dockerignore`: "Ignore local env, output artifacts, logs, and build/browser caches"
- `.env.example`: "Add example runtime environment variables"
- `README.md`: "Finalize polished English README and usage documentation"
- root metadata files (`build_check.txt`, `build_nocache.txt`, `build_run.txt`, `.env.example`): "Add build diagnostics and environment examples"

Use these messages when splitting future work into clean commits by folder or feature. The current commit history is still valid; this section is a guideline for a cleaned-up history if you rewrite the initial commit later.

## Notes and Best Practices

- Do not commit the `playwright-browsers/` cache directory.
- Keep `output/`, `logs/`, and `.env` out of version control.
- Use `docker compose up --build` only when dependencies or runtime environment change.
- For quick local debugging, run `python -m src.main --headless --export-json --export-csv --export-text`.

## Troubleshooting

- If Git push fails due to large files, ensure `playwright-browsers/` is ignored and not tracked.
- If Playwright fails inside Docker, verify `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` and that the mounted directory contains the browser cache.
- For browser download issues, remove the volume contents and `docker compose up --build` again.

## Health и метрики

- Сервис предоставляет HTTP health endpoint: `GET /health` на порту `8000`. Возвращает `200` и JSON `{ "status": "ok" }`.
- При установленном пакете `prometheus-client` запускается Prometheus metrics endpoint на порту `8001` по URL `/metrics`.
- `docker-compose.yml` настроен на проверку `http://localhost:8000/health` в качестве healthcheck контейнера.

Пример запуска:

```powershell
docker compose up --build -d
curl http://localhost:8000/health
curl http://localhost:8001/metrics
```

Дополнительно:

- `src/main.py` поддерживает флаг CLI `--one-shot` для одиночного запуска без цикла.
- Параметр окружения `POLL_INTERVAL` задаёт интервал между циклическими запусками.
- После выполнения цикла в `logs/validation_summary.json` сохраняются метрики:
  - `total_processed`
  - `valid_count`
  - `rejected_count`
  - `by_reason`
  - `sample_rejections`
  - `scraper_metrics` (`scraped_pages`, `failed_pages`, `skipped_urls`)
  - `time_spent_seconds`
