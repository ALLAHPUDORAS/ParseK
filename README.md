# B2B Lead Scraping Pipeline

Автоматизированный пайплайн для сбора и валидации B2B-лидов в iGaming / Nutra / Gambling / Crypto.

## Структура репозитория

- `src/main.py` — основной запуск пайплайна
- `src/scraper.py` — парсер сайтов и сбор карточек компаний
- `src/validator.py` — фильтрация GEO и контактов
- `src/exporter.py` — выгрузка в CSV/JSON/TXT
- `src/config.py` — конфигурация сайтов, GEO-фильтров, исключений
- `requirements.txt` — зависимости Python
- `.gitignore` — исключения для коммитов

## Установка

```powershell
cd d:\ParseK
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

> Если вы используете Bash или WSL, активируйте окружение через `source .venv/bin/activate`.

## Запуск

```powershell
python -m src.main --headless --export-json --export-csv --export-text
```

Если опции экспорта не заданы, скрипт сохранит результаты по умолчанию во все три формата.

## Запуск в Docker

```powershell
git clone <your-repository-url>
cd <repository>
copy .env.example .env
# настройте переменные в .env по необходимости

docker-compose up --build
```

Контейнер автоматически монтирует каталог `./output` на хосте в `/app/output` внутри контейнера.

## Файлы вывода

По умолчанию создаются файлы в каталоге `output/`:

- `leads.json`
- `leads.csv`
- `leads_list.txt`

## Примечания

- В `.gitignore` уже добавлены шаблоны для `.venv/`, `__pycache__/`, `.env`, `*.log`, `*.csv`, `*.json`.
- Рекомендуется коммитить только код и конфигурацию, не выгрузки данных.
