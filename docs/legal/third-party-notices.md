# Сторонние компоненты и их лицензии

Проверено 27.10.2026 по `backend/requirements.lock.txt` и `frontend/package.json` (версии из установленных пакетов). Обновлять при изменении зависимостей.

## Вывод

Все зависимости совместимы с закрытым коммерческим SaaS:
- **разрешительные лицензии** (MIT, BSD, Apache-2.0, ISC, PSF) требуют сохранять уведомления об авторских правах при распространении;
- **psycopg2-binary** (LGPL с исключениями) и **certifi** (MPL-2.0) используются без изменений на сервере. Сервис не распространяет их в виде программы, поэтому требований к нашему коду они не создают.

Если MIMAS начнёт поставляться клиентам как устанавливаемая программа (на их серверы), этот вывод нужно пересмотреть.

## Python (сервер)

| Пакет | Лицензия | | Пакет | Лицензия |
|---|---|---|---|---|
| fastapi | MIT | | sqlalchemy | MIT |
| starlette | BSD-3-Clause | | alembic | MIT |
| uvicorn | BSD-3-Clause | | psycopg2-binary | LGPL с исключениями |
| pydantic | MIT | | boto3, botocore, s3transfer | Apache-2.0 |
| httpx, httpcore | BSD-3-Clause | | pypdf | BSD-3-Clause |
| python-multipart | Apache-2.0 | | python-docx | MIT |
| websockets | BSD-3-Clause | | lxml | BSD-3-Clause |
| jsonschema и зависимости | MIT | | cryptography | Apache-2.0 или BSD-3-Clause |
| google-genai, google-auth | Apache-2.0 | | requests | Apache-2.0 |
| certifi | MPL-2.0 | | urllib3 | MIT |
| typing_extensions | PSF-2.0 | | прочие транзитивные | MIT, BSD, Apache-2.0 |
| pytest (только для тестов) | MIT | | | |

## JavaScript (интерфейс)

| Пакет | Версия | Лицензия |
|---|---|---|
| next | 15.5.25 | MIT |
| react, react-dom | 19.3.0 | MIT |
| lucide-react | 0.468.0 | ISC |
| typescript (сборка) | 5.9.3 | Apache-2.0 |

## Шрифты и медиа

| Материал | Источник | Права |
|---|---|---|
| Golos Text | Google Fonts | SIL Open Font License 1.1 — можно использовать коммерчески |
| `mimas-fluid.mp4` | Собственная процедурная анимация (`scripts/render_mimas_fluid.py`) | Наши |
| `mimas-orb.mp4` | Из присланного файла `document_5294113509527827677.mp4` | **Неизвестно** — подтвердить права или заменить |
| Логотипы `brand/mimas-*.gif` | Переданы командой | Подтвердить авторство |

## Сервисы

| Сервис | Для чего | Что проверить |
|---|---|---|
| Yandex Cloud (AI Studio, речь, Object Storage, ВМ) | Хостинг, AI, хранение | Условия использования; договор поручения обработки ПД |
| Tavus (если подключим) | Видео вопросов с аватаром | Доступность для российского юрлица, оплата, письменное согласие человека, чьё лицо используется |
| Render, Neon | Текущий хостинг | Отключить после переезда в Россию |
