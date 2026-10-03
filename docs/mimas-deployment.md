# Выпуск MIMAS с PostgreSQL и Yandex AI

Обновление нельзя публиковать, пока не проверены миграция на копии базы, реальный структурированный ответ DeepSeek, SpeechKit/OCR, приватный бакет и месячный лимит. `render.yaml` держит ключи как deployment secrets; не вставляйте их в Git и не показывайте в браузере.

## 1. Копия данных и миграция

1. В Neon сделайте ветку/резервную копию рабочей PostgreSQL базы и убедитесь, что она восстанавливается. Запишите число строк старых `interviews`, `ai_sessions`, `candidate_profiles`, `opportunities`, `candidate_assessments` и контрольные суммы важных полей. Не запускайте миграцию впервые на production.
2. Укажите URL **копии** как `DATABASE_URL`. Команда `.venv\Scripts\python.exe scripts/migrate.py` проверяет точный набор старых таблиц, штампует старую схему `0001_legacy`, затем применяет `0002_tenants_ai`. Для пустой базы создаёт обе версии с нуля. На неизвестной схеме останавливается.
3. После миграции сравните старые строки и отчёты: все старые вакансии и приглашения принадлежат `legacy`, открытые вакансии становятся черновиками, незавершённые AI-сессии архивируются, завершённые отчёты остаются. Старый `COMPANY_KEY` должен совпадать с существующим секретом Render.
4. Только после успешной проверки копии сделайте актуальную резервную копию production и задайте `MIMAS_MIGRATION_BACKUP_CONFIRMED=1` в Render. Не меняйте `COMPANY_KEY`.

Для локальных демонстрационных данных задайте `MIMAS_DEV_DATABASE_URL` отдельной dev PostgreSQL БД, отличной от production `DATABASE_URL`. Запустите `scripts/import_legacy_demo.py --help`; сначала dry-run, затем импорт с явным `--confirm-db`, после чего сравните записи и медиа. Разделяйте dev и production бакеты.

## 2. Yandex AI Studio, SpeechKit, Vision

В Yandex Cloud создайте сервисный аккаунт и API-ключ с доступом к [AI Studio](https://aistudio.yandex.ru/ru/docs/ai-studio/concepts/generation/models), [SpeechKit STT](https://aistudio.yandex.ru/ru/docs/speechkit/stt-v3/api-ref/AsyncRecognizer/recognizeFile) и [Vision OCR](https://aistudio.yandex.ru/ru/docs/vision/operations/ocr/text-detection-pdf). В Render задайте `YANDEX_API_KEY`, `YANDEX_FOLDER_ID`, `MIMAS_LLM_PROVIDER=yandex`, `YANDEX_MODEL=deepseek-v4.1-flash`. Ключ остаётся на сервере. Для распознавания WebM контейнер преобразуется в Ogg Opus через ffmpeg, уже установленный в Dockerfile.

До переключения выполните один реальный, ограниченный по токенам вызов нового провайдера со схемой `CompetencyPlan` на тестовой вакансии. Проверьте сохранение структуры JSON, затем короткую диктовку и отсканированную страницу. Эти вызовы оплачиваются Yandex Cloud; mock-тесты не доказывают доступности выбранной модели, прав API-ключа или точность распознавания.

MIMAS резервирует оценочную стоимость до платного обращения и учитывает результат в PostgreSQL. `MIMAS_AI_MONTHLY_LIMIT_RUB` можно уменьшить, но код не позволяет поднять его выше 1000 ₽/мес. Неизвестный результат сетевого вызова учитывается консервативно. Сверяйте [тарифы AI Studio](https://aistudio.yandex.ru/ru/docs/ai-studio/pricing) и отдельно настройте оповещение о расходах в интерфейсе Yandex Cloud: внутренний лимит не управляет счётом провайдера.

## 3. Приватное видео

Создайте **приватный бакет без версионирования** Object Storage. Скрипт откажется применять правила, если анонимный GET тестового объекта не возвращает 403 либо включено версионирование. Укажите в Render `MIMAS_S3_BUCKET`, `MIMAS_S3_ENDPOINT=https://storage.yandexcloud.net`, `MIMAS_S3_REGION=ru-central1`, `MIMAS_S3_ACCESS_KEY`, `MIMAS_S3_SECRET_KEY`. Используйте отдельный бакет/ключи для разработки. Настройте CORS и удаление записей:

```powershell
.venv\Scripts\python.exe scripts/configure_video_bucket.py --origin https://mimas.onrender.com
.venv\Scripts\python.exe scripts/configure_video_bucket.py --origin https://mimas.onrender.com --apply
```

CORS разрешает браузеру PUT частей и GET по короткой подписанной ссылке, а также открывает заголовок ETag для завершения multipart. Правило жизненного цикла удаляет `recordings/` через 30 дней и отменяет незавершённые загрузки через один день. Если загрузка затянулась, сервер создаст новый multipart, а браузер повторно отправит части из IndexedDB. API прекращает выдавать ссылку на видео по истечении 30 дней независимо от задержки фонового удаления объекта в хранилище. Текстовые ответы и отчёты остаются в PostgreSQL. Проверьте [тарифы Object Storage](https://yandex.cloud/ru/docs/storage/pricing).

## 4. Render и сквозная проверка

В сервисе Render задайте `DATABASE_URL`, прежний `COMPANY_KEY`, новый `MIMAS_ADMIN_KEY`, перечисленные ключи Yandex и S3, затем отправьте код и дождитесь успешного health check `/api/health`. Он вернёт 503 в production, если AI, камера/хранилище или admin key не настроены. `scripts/start-cloud.sh` запускает Alembic до FastAPI.

Пройдите путь двух кандидатов на одной вакансии: заявка и ручное одобрение компании → одноразовый ключ → импорт и правка вакансии → генерация, ручная правка и утверждение шаблона → два отдельных интервью → отчёты кандидатов и компании. Ключом второй компании попробуйте открыть чужую вакансию, отчёт и видео: все три запроса должны вернуть 404. Прервите загрузку видео, перезагрузите вкладку и повторите её из сохранённых частей. При сбое SpeechKit текстовый ответ должен оставаться редактируемым. Проверьте, что после достижения месячного лимита новые вызовы не отправляются.
