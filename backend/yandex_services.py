"""SpeechKit v3 and Vision OCR adapters with bounded uploads and polling.

All requests are server-side. API keys and raw provider responses are never
returned to browsers. PDF OCR uses the asynchronous JSONL API, not the
single-page synchronous endpoint.
"""

import asyncio
import base64
from decimal import Decimal
from io import BytesIO
import json
import math
import os
import re

import httpx

STT_BASE = 'https://stt.api.cloud.yandex.net'
OPERATION_BASE = 'https://operation.api.cloud.yandex.net'
OCR_BASE = 'https://ai.api.cloud.yandex.net/ocr/v1'
STT_RUB_PER_15_SECONDS = Decimal('0.1515')
DEFAULT_OCR_RUB_PER_PAGE = Decimal('0.1321')  # Yandex AI Studio page-model list price, 2026-10
MAX_AUDIO_BYTES = 12 * 1024 * 1024
MAX_AUDIO_SECONDS = 180
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 20


class YandexServiceError(Exception):
    def __init__(self, message: str, code: str = 'provider_error', *, operation_id: str | None = None):
        super().__init__(message)
        self.code = code
        self.operation_id = operation_id


def _error_for_status(status: int) -> YandexServiceError:
    code = {400: 'invalid_request', 401: 'authentication_error',
            403: 'access_denied', 404: 'not_found',
            413: 'input_too_large', 429: 'rate_limit'}.get(status, 'provider_error')
    return YandexServiceError(f'Yandex service: HTTP {status}.', code)


def _parse_jsonl(raw: str) -> list[dict]:
    try:
        # SpeechKit can return one regular JSON document; PDF OCR returns JSONL.
        try:
            whole = json.loads(raw)
            values = [whole] if isinstance(whole, dict) else whole
        except json.JSONDecodeError:
            values = [json.loads(line) for line in raw.splitlines() if line.strip()]
    except json.JSONDecodeError:
        raise YandexServiceError('Yandex returned invalid JSON.', 'invalid_provider_response') from None
    if not isinstance(values, list) or not values or any(not isinstance(item, dict) for item in values):
        raise YandexServiceError('Yandex returned empty result.', 'invalid_provider_response')
    return values


def _extract_ocr_text(page: dict) -> str:
    result = page.get('result', page)
    if not isinstance(result, dict):
        raise YandexServiceError('Yandex OCR returned invalid page.', 'invalid_provider_response')
    if result.get('error'):
        raise YandexServiceError('Yandex OCR could not process a page.', 'provider_error')
    annotation = result.get('textAnnotation') or result.get('text_annotation') or {}
    if not isinstance(annotation, dict):
        raise YandexServiceError('Yandex OCR returned invalid text.', 'invalid_provider_response')
    full = annotation.get('fullText') or annotation.get('full_text')
    if isinstance(full, str) and full.strip():
        return full.strip()
    # Async PDF results may omit fullText; derive it from lines.
    lines = []
    for block in annotation.get('blocks') or []:
        for line in block.get('lines') or []:
            alternatives = line.get('alternatives') or []
            value = (alternatives[0].get('text') if alternatives else line.get('text'))
            if isinstance(value, str) and value.strip():
                lines.append(value.strip())
    return '\n'.join(lines)


def _extract_stt_text(raw: str) -> str:
    values = _parse_jsonl(raw)
    phrases = []
    for item in values:
        result = item.get('result', item)
        if not isinstance(result, dict):
            continue
        final = result.get('final') or {}
        alternatives = final.get('alternatives') or []
        if alternatives:
            value = alternatives[0].get('text')
            if isinstance(value, str) and value.strip():
                phrases.append(value.strip())
    text = ' '.join(phrases).strip()
    if not text:
        raise YandexServiceError('Речь не распознана. Введите ответ текстом.', 'empty_transcription')
    return text


def _duration_from_ffmpeg_progress(stderr: bytes) -> float | None:
    matches = re.findall(rb'out_time=(\d+):(\d+):(\d+(?:\.\d+)?)', stderr)
    if not matches:
        return None
    hours, minutes, seconds = matches[-1]
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


class YandexServices:
    def __init__(self, api_key: str, folder_id: str, *, budget=None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 ffmpeg_path: str = 'ffmpeg', sleep=asyncio.sleep,
                 ocr_rub_per_page=None):
        if not api_key or not folder_id:
            raise ValueError('Set YANDEX_API_KEY and YANDEX_FOLDER_ID')
        self.api_key, self.folder_id = api_key, folder_id
        self.budget, self.transport, self.ffmpeg_path, self.sleep = budget, transport, ffmpeg_path, sleep
        configured_rate = ocr_rub_per_page or os.getenv('YANDEX_OCR_RUB_PER_PAGE', '')
        self.ocr_rub_per_page = Decimal(str(configured_rate or DEFAULT_OCR_RUB_PER_PAGE))
        if self.ocr_rub_per_page <= 0:
            raise ValueError('Invalid OCR ruble estimate')

    @property
    def _headers(self):
        return {'Authorization': f'Api-Key {self.api_key}',
                'x-folder-id': self.folder_id,
                'x-data-logging-enabled': 'false'}

    async def _ogg_opus(self, payload: bytes) -> tuple[bytes, float]:
        """Transcode browser WebM to the SpeechKit-supported Ogg Opus format."""
        try:
            process = await asyncio.create_subprocess_exec(
                self.ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-nostdin',
                '-i', 'pipe:0', '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '48000',
                '-c:a', 'libopus', '-b:a', '64k', '-vbr', 'off',
                '-progress', 'pipe:2', '-f', 'ogg', 'pipe:1',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(payload), timeout=45)
        except (OSError, asyncio.TimeoutError):
            raise YandexServiceError('Не удалось подготовить аудио.', 'audio_conversion_failed') from None
        if process.returncode != 0 or not stdout:
            raise YandexServiceError('Не удалось прочитать аудио.', 'invalid_audio')
        duration = _duration_from_ffmpeg_progress(stderr)
        if duration is None or not 0 < duration <= MAX_AUDIO_SECONDS:
            raise YandexServiceError('Запись должна быть короче трёх минут.', 'audio_duration_invalid')
        return stdout, duration

    async def transcribe_webm(self, payload: bytes) -> str:
        if not payload or len(payload) > MAX_AUDIO_BYTES:
            raise YandexServiceError('Аудио должно быть не больше 12 МБ.', 'input_too_large')
        ogg, duration = await self._ogg_opus(payload)
        return await self._recognize(ogg, {'containerAudio': {'containerAudioType': 'OGG_OPUS'}}, duration)

    async def transcribe_pcm(self, pcm: bytes, sample_rate: int) -> str:
        """16-bit mono PCM as the voice interview streams it; SpeechKit takes it without conversion."""
        if not pcm or len(pcm) % 2 or len(pcm) > MAX_AUDIO_BYTES:
            raise YandexServiceError('Аудио должно быть не больше 12 МБ.', 'input_too_large')
        duration = len(pcm) / (sample_rate * 2)
        if not 0 < duration <= MAX_AUDIO_SECONDS:
            raise YandexServiceError('Запись должна быть короче трёх минут.', 'audio_duration_invalid')
        return await self._recognize(pcm, {'rawAudio': {'audioEncoding': 'LINEAR16_PCM',
                                                        'sampleRateHertz': sample_rate,
                                                        'audioChannelCount': 1}}, duration)

    async def _recognize(self, audio: bytes, audio_format: dict, duration: float) -> str:
        charged_seconds = max(15, math.ceil(duration))
        estimate = STT_RUB_PER_15_SECONDS * Decimal(charged_seconds) / Decimal('15')
        reservation = self.budget.reserve('speechkit', 'transcription', estimate) if self.budget else None
        settled = False
        operation_id = None
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=45) as client:
                response = await client.post(
                    STT_BASE + '/stt/v3/recognizeFileAsync',
                    headers=self._headers,
                    json={'content': base64.b64encode(audio).decode('ascii'),
                          'recognitionModel': {
                              'model': 'general',
                              'audioFormat': audio_format,
                              'languageRestriction': {'restrictionType': 'WHITELIST',
                                                      'languageCode': ['ru-RU', 'en-US']}}},
                )
                if response.status_code >= 400:
                    if reservation and response.status_code < 500:
                        self.budget.release(reservation)
                        settled = True
                    raise _error_for_status(response.status_code)
                operation_id = response.json().get('id')
                if not isinstance(operation_id, str) or not operation_id:
                    raise YandexServiceError('Yandex SpeechKit returned no operation ID.', 'invalid_provider_response')
                if reservation:
                    self.budget.settle(reservation, estimate, {'duration_seconds': duration})
                    settled = True
                for _ in range(45):
                    operation = await client.get(
                        OPERATION_BASE + '/operations/' + operation_id, headers=self._headers)
                    if operation.status_code >= 400:
                        raise _error_for_status(operation.status_code)
                    state = operation.json()
                    if state.get('done'):
                        if state.get('error'):
                            raise YandexServiceError('Распознавание речи завершилось с ошибкой.',
                                                     'provider_error', operation_id=operation_id)
                        for _ in range(5):
                            result = await client.get(
                                STT_BASE + '/stt/v3/getRecognition',
                                headers=self._headers, params={'operationId': operation_id})
                            if result.status_code >= 400:
                                raise _error_for_status(result.status_code)
                            if result.text.strip():
                                return _extract_stt_text(result.text)
                            await self.sleep(1)
                        raise YandexServiceError('Результат распознавания пока не готов.',
                                                 'timeout', operation_id=operation_id)
                    await self.sleep(2)
                raise YandexServiceError('Распознавание занимает слишком долго. Повторите позже.',
                                         'timeout', operation_id=operation_id)
        except httpx.HTTPError:
            raise YandexServiceError('SpeechKit временно недоступен.', 'network_error',
                                     operation_id=operation_id) from None
        except (ValueError, TypeError, KeyError):
            raise YandexServiceError('SpeechKit вернул некорректный ответ.',
                                     'invalid_provider_response', operation_id=operation_id) from None
        finally:
            if reservation and not settled:
                # A network failure after submission may still incur a charge.
                self.budget.settle(reservation, estimate, {'uncertain': True})

    async def ocr_document(self, payload: bytes, mime_type: str) -> str:
        if not payload or len(payload) > MAX_DOCUMENT_BYTES:
            raise YandexServiceError('Документ должен быть не больше 10 МБ.', 'input_too_large')
        mime = mime_type.lower().split(';', 1)[0].strip()
        if mime in ('image/jpeg', 'image/jpg', 'jpeg'):
            if not payload.startswith(b'\xff\xd8\xff'):
                raise YandexServiceError('Файл не является JPEG.', 'invalid_document')
            yandex_mime, pages = 'JPEG', 1
        elif mime in ('image/png', 'png'):
            if not payload.startswith(b'\x89PNG\r\n\x1a\n'):
                raise YandexServiceError('Файл не является PNG.', 'invalid_document')
            yandex_mime, pages = 'PNG', 1
        elif mime in ('application/pdf', 'pdf'):
            if not payload.startswith(b'%PDF-'):
                raise YandexServiceError('Файл не является PDF.', 'invalid_document')
            try:
                from pypdf import PdfReader
                reader = PdfReader(BytesIO(payload), strict=False)
                pages = len(reader.pages)
            except Exception:
                raise YandexServiceError('Не удалось прочитать PDF.', 'invalid_document') from None
            if not 1 <= pages <= MAX_PDF_PAGES:
                raise YandexServiceError('PDF должен содержать от 1 до 20 страниц.', 'input_too_large')
            yandex_mime = 'application/pdf'
        else:
            raise YandexServiceError('Поддерживаются PDF, JPEG и PNG.', 'unsupported_document')
        actual_cost = self.ocr_rub_per_page * pages
        estimate = max(actual_cost, Decimal('1.00') * pages)  # conservative reservation
        reservation = self.budget.reserve('vision_ocr', 'vacancy_import', estimate) if self.budget else None
        settled = False
        operation_id = None
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=45) as client:
                endpoint = '/recognizeTextAsync' if yandex_mime == 'application/pdf' else '/recognizeText'
                response = await client.post(
                    OCR_BASE + endpoint, headers=self._headers,
                    json={'mimeType': yandex_mime, 'languageCodes': ['*'],
                          'model': 'page', 'content': base64.b64encode(payload).decode('ascii')},
                )
                if response.status_code >= 400:
                    if reservation and response.status_code < 500:
                        self.budget.release(reservation)
                        settled = True
                    raise _error_for_status(response.status_code)
                if reservation:
                    self.budget.settle(reservation, actual_cost, {'pages': pages, 'price_estimate': True})
                    settled = True
                if yandex_mime == 'application/pdf':
                    operation_id = response.json().get('id')
                    if not isinstance(operation_id, str) or not operation_id:
                        raise YandexServiceError('Yandex OCR returned no operation ID.',
                                                 'invalid_provider_response')
                    for _ in range(60):
                        result = await client.get(
                            OCR_BASE + '/getRecognition', headers=self._headers,
                            params={'operationId': operation_id})
                        if result.status_code >= 400:
                            raise _error_for_status(result.status_code)
                        if result.text.strip():
                            values = _parse_jsonl(result.text)
                            break
                        await self.sleep(2)
                    else:
                        raise YandexServiceError('OCR занимает слишком долго. Повторите позже.',
                                                 'timeout', operation_id=operation_id)
                else:
                    values = [response.json()]
                ordered = sorted(values, key=lambda item: int((item.get('result') or {}).get('page', 0)))
                text = '\n\n'.join(part for part in (_extract_ocr_text(page) for page in ordered) if part).strip()
                if not text:
                    raise YandexServiceError('Текст на документе не найден.', 'empty_document')
                return text
        except httpx.HTTPError:
            raise YandexServiceError('Yandex OCR временно недоступен.',
                                     'network_error', operation_id=operation_id) from None
        except (ValueError, TypeError, KeyError):
            raise YandexServiceError('Yandex OCR вернул некорректный ответ.',
                                     'invalid_provider_response', operation_id=operation_id) from None
        finally:
            if reservation and not settled:
                self.budget.settle(reservation, estimate, {'pages': pages, 'uncertain': True})


def configured_yandex_services(database=None) -> YandexServices:
    from ai_core.llm.factory import setting
    api_key = setting('YANDEX_API_KEY')
    folder_id = setting('YANDEX_FOLDER_ID')
    budget = None
    if database is not None:
        from backend.yandex_budget import YandexBudget
        budget = YandexBudget(database)
    return YandexServices(api_key, folder_id, budget=budget,
                          ffmpeg_path=setting('MIMAS_FFMPEG_PATH', 'ffmpeg'))
