"""Authenticated server-side bridge for Yandex Speech Realtime interviews.

The assessment engine owns questions, answers, and evaluation. Realtime is used
only for speech transcription and speaking the current persisted question.
Two upstream sockets prevent VAD-triggered replies from becoming interview turns.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from contextlib import AsyncExitStack
from decimal import Decimal
import json
import logging
import os
import re
import time
from uuid import uuid4
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from ai_core.interview.schemas import CandidateAnswer
from ai_core.llm.base import ProviderError
from ai_core.interview.state import InterviewState, Phase
from backend.yandex_budget import BudgetExceeded, YandexBudget

LOGGER = logging.getLogger(__name__)
SAMPLE_RATE = 44100
PCM_BYTES_PER_SECOND = SAMPLE_RATE * 2
MAX_AUDIO_CHUNK_BYTES = PCM_BYTES_PER_SECOND * 2
# Push-to-talk commits one complete answer on release. No server VAD timer
# may turn a thinking pause into an incomplete answer.
TRANSCRIPTION_TIMEOUT_SECONDS = 30.0
# Provider output deltas are not microphone frames: one delta can contain
# several seconds of speech. Bound it separately, then forward small frames.
MAX_TTS_DELTA_BYTES = 8 * 1024 * 1024
TTS_DOWNSTREAM_CHUNK_BYTES = PCM_BYTES_PER_SECOND // 2
AUDIO_WINDOW_BYTES = PCM_BYTES_PER_SECOND * 60
# See https://aistudio.yandex.ru/ru/docs/ai-studio/pricing . Both audio
# directions and text tokens are included in the conservative reservation.
INPUT_AUDIO_RUB_PER_SECOND = Decimal('0.0264')
OUTPUT_AUDIO_RUB_PER_SECOND = Decimal('0.0203')
INPUT_TEXT_RUB_PER_TOKEN = Decimal('0.0003')
OUTPUT_TEXT_RUB_PER_TOKEN = Decimal('0.0005')
WINDOW_RESERVATION_RUB = Decimal('10.00')
VOICE_MODEL = 'speech-realtime-deepseek-v4-flash'
VOICE_FALLBACK_MODEL = 'speech-realtime-260528'
VOICE_INSTRUCTIONS = (
    'Ты голос профессионального интервью MIMAS. На каждый текстовый запрос '
    'произноси только сам вопрос дословно. Не отвечай на него, не пересказывай, '
    'не добавляй вступления, подсказки, оценки или завершающие фразы. '
    'Говори на языке вопроса.'
)
STT_INSTRUCTIONS = (
    'Точно распознавай речь кандидата. Не отвечай ему и не подсказывай. '
    'Вопросы и оценку ведёт другое приложение.'
)


class VoiceProtocolError(Exception):
    pass


class VoiceTransientUpstreamError(VoiceProtocolError):
    pass


def _provider_error_code(event: dict) -> str:
    """Keep diagnostics useful without logging transcripts or provider payloads."""
    error = event.get('error')
    if not isinstance(error, dict):
        return 'unknown'
    value = str(error.get('code') or error.get('type') or 'unknown')
    return value if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', value) else 'other'


def _provider_close_reason(exc: ConnectionClosed) -> str:
    value = str(getattr(getattr(exc, 'rcvd', None), 'reason', ''))
    return value if re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', value) else 'other'


async def _open_yandex_channel(stack: AsyncExitStack, url: str, headers: dict,
                               *, transcribe: bool, max_size: int):
    """Do not announce readiness until Yandex accepts the session settings."""
    channel = 'stt' if transcribe else 'tts'
    urls = (url, url.replace('/' + VOICE_MODEL, '/' + VOICE_FALLBACK_MODEL))
    for attempt, candidate_url in enumerate(urls):
        context = connect(candidate_url, additional_headers=headers, ping_interval=20,
                          open_timeout=15, max_size=max_size)
        stream = None
        try:
            stream = await context.__aenter__()
            await stream.send(json.dumps(_session_update(transcribe=transcribe),
                                         ensure_ascii=False))
            for _ in range(5):
                packet = await asyncio.wait_for(stream.recv(), timeout=10)
                event = json.loads(packet)
                if event.get('type') == 'session.updated':
                    stack.push_async_exit(context.__aexit__)
                    return stream
                if event.get('type') == 'error':
                    code = _provider_error_code(event)
                    if code in ('upstream_unavailable', 'server_error'):
                        raise VoiceTransientUpstreamError(code)
                    raise VoiceProtocolError(
                        'Не удалось настроить голосовой сервис (' + code + ').')
            raise VoiceProtocolError('Голосовой сервис не подтвердил подключение.')
        except (ConnectionClosed, TimeoutError, OSError, VoiceTransientUpstreamError) as exc:
            LOGGER.warning('Yandex voice %s model=%s connection failed: %s code=%s reason=%s',
                           channel, VOICE_MODEL if attempt == 0 else VOICE_FALLBACK_MODEL,
                           type(exc).__name__,
                           getattr(getattr(exc, 'rcvd', None), 'code', None),
                           _provider_close_reason(exc) if isinstance(exc, ConnectionClosed)
                           else str(exc) if isinstance(exc, VoiceTransientUpstreamError)
                           else 'none')
            if stream is not None:
                await context.__aexit__(None, None, None)
            if attempt:
                raise VoiceProtocolError(
                    'Голосовой сервис временно недоступен. Подключитесь повторно.') from exc
            await asyncio.sleep(1)
        except Exception:
            if stream is not None:
                await context.__aexit__(None, None, None)
            raise


class VoiceSpend:
    """One 60-second audio allowance at a time, reserved before media flows."""

    def __init__(self, budget: YandexBudget):
        self.budget = budget
        self.reservation: str | None = None
        self.input_bytes = 0
        self.output_bytes = 0
        self.input_text_tokens = 0
        self.output_text_tokens = 0
        self.used_provider = False
        self.lock = asyncio.Lock()

    def _actual(self) -> Decimal:
        return (
            Decimal(self.input_bytes) / PCM_BYTES_PER_SECOND * INPUT_AUDIO_RUB_PER_SECOND
            + Decimal(self.output_bytes) / PCM_BYTES_PER_SECOND * OUTPUT_AUDIO_RUB_PER_SECOND
            + Decimal(self.input_text_tokens) * INPUT_TEXT_RUB_PER_TOKEN
            + Decimal(self.output_text_tokens) * OUTPUT_TEXT_RUB_PER_TOKEN
        )

    def _usage(self, uncertain: bool = False) -> dict:
        return {
            'input_audio_seconds': round(self.input_bytes / PCM_BYTES_PER_SECOND, 2),
            'output_audio_seconds': round(self.output_bytes / PCM_BYTES_PER_SECOND, 2),
            'input_text_tokens': self.input_text_tokens,
            'output_text_tokens': self.output_text_tokens,
            'estimate': True,
            'uncertain': uncertain,
        }

    def _settle(self, uncertain: bool = False):
        if self.reservation is None:
            return
        if not self.used_provider:
            self.budget.release(self.reservation)
        else:
            actual = max(self._actual(), Decimal('0.05'))
            if uncertain:
                # The upstream may have charged for frames whose receipt was lost.
                actual = max(actual, WINDOW_RESERVATION_RUB)
            self.budget.settle(self.reservation, actual, self._usage(uncertain))
        self.reservation = None

    async def start(self):
        async with self.lock:
            self.reservation = self.budget.reserve(
                'speech_realtime', 'voice_interview', WINDOW_RESERVATION_RUB)

    async def audio(self, direction: str, size: int):
        async with self.lock:
            if self.reservation is None:
                raise VoiceProtocolError('Голосовая сессия не запущена.')
            old = self.input_bytes if direction == 'input' else self.output_bytes
            if old + size > AUDIO_WINDOW_BYTES:
                self._settle()
                self.reservation = self.budget.reserve(
                    'speech_realtime', 'voice_interview', WINDOW_RESERVATION_RUB)
                self.input_bytes = self.output_bytes = 0
                self.input_text_tokens = self.output_text_tokens = 0
            if direction == 'input':
                self.input_bytes += size
            else:
                self.output_bytes += size
            self.used_provider = True

    async def usage(self, response: dict):
        usage = response.get('usage') or {}
        input_details = usage.get('input_token_details') or {}
        output_details = usage.get('output_token_details') or {}
        async with self.lock:
            self.input_text_tokens += max(0, int(input_details.get('text_tokens', usage.get('input_tokens')) or 0))
            self.output_text_tokens += max(0, int(output_details.get('text_tokens', usage.get('output_tokens')) or 0))
            if usage:
                self.used_provider = True

    async def finish(self, uncertain: bool = False):
        async with self.lock:
            self._settle(uncertain)


def _session_update(*, transcribe: bool) -> dict:
    return {
        'type': 'session.update',
        'session': {
            'type': 'realtime',
            'instructions': STT_INSTRUCTIONS if transcribe else VOICE_INSTRUCTIONS,
            'output_modalities': ['text'] if transcribe else ['audio'],
            'max_output_tokens': 64 if transcribe else 256,
            'audio': {
                'input': {
                    'format': {'type': 'audio/pcm', 'rate': SAMPLE_RATE},
                    **({'languages': ['ru-RU']} if transcribe else {}),
                    'turn_detection': None,
                },
                'output': {
                    'format': {'type': 'audio/pcm', 'rate': SAMPLE_RATE},
                    'voice': 'dasha',
                },
            },
        },
    }


def _question_prompt(question: str) -> dict:
    # Questions may contain arbitrary words. JSON quoting keeps the source text
    # explicit, while the session instruction asks the model to speak it exactly.
    return {
        'type': 'conversation.item.create',
        'item': {
            'type': 'message',
            'role': 'user',
            'content': [{
                'type': 'input_text',
                'text': 'Произнеси дословно текст вопроса из поля question: '
                        + json.dumps({'question': question}, ensure_ascii=False),
            }],
        },
    }


def _audio_bytes(encoded: str, *, max_bytes: int = MAX_AUDIO_CHUNK_BYTES) -> bytes:
    if not isinstance(encoded, str) or len(encoded) > ((max_bytes + 2) // 3) * 4:
        raise VoiceProtocolError('Слишком большой фрагмент звука.')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise VoiceProtocolError('Неверный формат звука.') from None
    if not raw or len(raw) % 2 or len(raw) > max_bytes:
        raise VoiceProtocolError('Неверный размер фрагмента звука.')
    return raw


def _tts_audio_chunks(encoded: str):
    """Validate a provider delta and yield browser-sized, PCM-aligned frames."""
    raw = _audio_bytes(encoded, max_bytes=MAX_TTS_DELTA_BYTES)
    for offset in range(0, len(raw), TTS_DOWNSTREAM_CHUNK_BYTES):
        chunk = raw[offset:offset + TTS_DOWNSTREAM_CHUNK_BYTES]
        yield chunk, base64.b64encode(chunk).decode('ascii')


def _transcription_timeout_seconds(audio_bytes: int) -> float:
    # A long held answer can take longer to transcribe after commit. This only
    # bounds provider failure; successful transcripts are submitted immediately.
    return min(90.0, TRANSCRIPTION_TIMEOUT_SECONDS
               + 0.3 * audio_bytes / PCM_BYTES_PER_SECOND)


def _spoken_matches_question(spoken: str, question: str) -> bool:
    # Speech transcripts often spell technical terms phonetically. Reject only
    # a clearly different utterance; the persisted engine question stays truth.
    from difflib import SequenceMatcher
    import re
    roman = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
        'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
        'ф': 'f', 'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
        'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
    }
    def normalized(value: str):
        letters = ''.join(re.findall(r'\w+', value.casefold(), flags=re.UNICODE))
        return ''.join(roman.get(char, char) for char in letters)
    return SequenceMatcher(None, normalized(spoken), normalized(question)).ratio() >= 0.65


def register_voice_route(app: FastAPI, database, load, public_view, submit_answer,
                         expire_if_due=None):
    active: dict[str, WebSocket] = {}

    @app.websocket('/api/ai/sessions/{iid}/voice')
    async def voice_interview(websocket: WebSocket, iid: str):
        await websocket.accept()
        send_lock = asyncio.Lock()

        async def send(payload: dict):
            async with send_lock:
                await websocket.send_json(payload)

        try:
            auth = await asyncio.wait_for(websocket.receive_json(), timeout=15)
            if not isinstance(auth, dict) or auth.get('type') != 'auth':
                raise VoiceProtocolError('Подключение к интервью не подтверждено.')
            token = auth.get('token')
            if not isinstance(token, str) or len(token) > 512:
                raise VoiceProtocolError('Ссылка на интервью недействительна.')
            if expire_if_due is not None:
                completed = await expire_if_due(iid, token)
                if completed is not None:
                    await send({'type': 'state', 'session': completed})
                    await websocket.close()
                    return
            row = load(iid, token)
            state = InterviewState.model_validate_json(row.state)
            if row.pending or state.pending_answer:
                pending = CandidateAnswer.model_validate_json(
                    row.pending or state.pending_answer.model_dump_json())
                await submit_answer(iid, pending, token)
                row = load(iid, token)
                state = InterviewState.model_validate_json(row.state)
            if state.phase != Phase.WAITING_FOR_ANSWER:
                raise VoiceProtocolError('Сначала запустите или восстановите интервью.')
            if not state.questions:
                raise VoiceProtocolError('В интервью пока нет вопроса.')
            api_key = os.getenv('YANDEX_API_KEY', '')
            folder_id = os.getenv('YANDEX_FOLDER_ID', '')
            if not api_key or not folder_id:
                raise VoiceProtocolError('Голосовая модель сейчас не настроена.')
            spend = VoiceSpend(YandexBudget(database))
            await spend.start()
            previous = active.get(iid)
            if previous and previous is not websocket:
                await previous.close(code=4000)
            active[iid] = websocket
        except WebSocketDisconnect:
            return
        except (HTTPException, VoiceProtocolError, BudgetExceeded, ProviderError, ValueError, asyncio.TimeoutError) as exc:
            if 'spend' in locals():
                await spend.finish()
            message = ('Месячный лимит AI исчерпан.' if isinstance(exc, BudgetExceeded)
                       else 'AI временно недоступен. Ответ сохранён; повторите подключение.'
                       if isinstance(exc, ProviderError)
                       else str(getattr(exc, 'detail', exc)))
            try:
                await send({'type': 'error', 'message': message})
                await websocket.close(code=4401)
            except (RuntimeError, WebSocketDisconnect):
                pass
            return

        failed = False
        connected = False
        deadline_at = row.started + min(state.limits.time_budget_seconds, 1200)
        model_uri = f'gpt://{quote(folder_id, safe="")}/{VOICE_MODEL}'
        upstream_url = f'wss://ai.api.cloud.yandex.net/v1/realtime/openai?model={model_uri}'
        headers = {'Authorization': f'Api-Key {api_key}'}

        try:
            async with AsyncExitStack() as upstream_stack:
                stt = await _open_yandex_channel(
                    upstream_stack, upstream_url, headers,
                    transcribe=True, max_size=2 * 1024 * 1024)
                tts = await _open_yandex_channel(
                    upstream_stack, upstream_url, headers,
                    transcribe=False, max_size=12 * 1024 * 1024)
                connected = True
                stt_send_lock = asyncio.Lock()
                tts_send_lock = asyncio.Lock()
                current_question = state.questions[-1]
                speaking = False
                listening = False
                awaiting_playback = False
                seen_items: set[str] = set()
                stt_context_items: set[str] = set()
                deleted_stt_items: set[str] = set()
                stt_maintenance_events: set[str] = set()
                utterance_questions: dict[str, str] = {}
                spoken_question: str | None = None
                stt_events: asyncio.Queue[dict] = asyncio.Queue()
                finish_requested_at = 0.0
                answer_held = False
                answer_audio_bytes = 0
                pending_item_id: str | None = None
                flush_generation = 0
                flush_task: asyncio.Task | None = None

                def cancel_answer_flush():
                    nonlocal flush_generation, flush_task
                    flush_generation += 1
                    if flush_task is not None:
                        flush_task.cancel()
                        flush_task = None

                def schedule_answer_flush():
                    nonlocal flush_task
                    cancel_answer_flush()
                    if not listening or not finish_requested_at:
                        return
                    generation = flush_generation
                    delay = max(0, finish_requested_at
                                + _transcription_timeout_seconds(answer_audio_bytes)
                                - time.monotonic())

                    async def enqueue_timeout():
                        await asyncio.sleep(delay)
                        await stt_events.put({'type': '_transcription_timeout',
                                              'generation': generation})

                    flush_task = asyncio.create_task(enqueue_timeout())

                async def stt_send(payload: dict):
                    async with stt_send_lock:
                        await stt.send(json.dumps(payload, ensure_ascii=False))

                async def retire_stt_item(item_id: str):
                    if item_id in deleted_stt_items:
                        return
                    deleted_stt_items.add(item_id)
                    stt_context_items.discard(item_id)
                    event_id = 'mimas-delete-' + uuid4().hex
                    stt_maintenance_events.add(event_id)
                    await stt_send({'type': 'conversation.item.delete',
                                    'event_id': event_id, 'item_id': item_id})

                async def tts_send(payload: dict):
                    async with tts_send_lock:
                        await tts.send(json.dumps(payload, ensure_ascii=False))

                async def speak(question):
                    nonlocal current_question, speaking, listening, spoken_question, awaiting_playback
                    nonlocal finish_requested_at, answer_held, answer_audio_bytes, pending_item_id
                    # A committed answer stays on the provider socket. It must
                    # not bias recognition of the candidate's next answer.
                    for item_id in tuple(stt_context_items):
                        await retire_stt_item(item_id)
                    cancel_answer_flush()
                    finish_requested_at = 0.0
                    answer_held = False
                    answer_audio_bytes = 0
                    pending_item_id = None
                    current_question = question
                    speaking = True
                    listening = False
                    awaiting_playback = False
                    spoken_question = None
                    await send({'type': 'transcript', 'speaker': 'mimas', 'text': question.text})
                    await tts_send(_question_prompt(question.text))
                    await tts_send({'type': 'response.create'})

                await send({'type': 'ready', 'sample_rate': SAMPLE_RATE})
                await send({'type': 'state', 'session': public_view(row)})
                await speak(current_question)

                async def receive_client():
                    nonlocal speaking, listening, awaiting_playback, finish_requested_at
                    nonlocal answer_held, answer_audio_bytes
                    while True:
                        try:
                            event = await asyncio.wait_for(websocket.receive_json(), timeout=30)
                        except asyncio.TimeoutError:
                            continue
                        if not isinstance(event, dict):
                            raise VoiceProtocolError('Неверное сообщение голосового интервью.')
                        kind = event.get('type')
                        if kind == 'stop':
                            return
                        if kind == 'playback_done':
                            if awaiting_playback:
                                awaiting_playback, listening = False, True
                            continue
                        if kind == 'interrupt':
                            if speaking:
                                speaking, listening, awaiting_playback = False, False, True
                                await tts_send({'type': 'response.cancel'})
                                await send({'type': 'speech_stopped'})
                            continue
                        if kind == 'start_answer':
                            if listening and not answer_held and not finish_requested_at:
                                answer_held = True
                                answer_audio_bytes = 0
                            continue
                        if kind == 'finish_answer':
                            if listening and answer_held and not finish_requested_at:
                                answer_held = False
                                if not answer_audio_bytes:
                                    await send({'type': 'answer_retry', 'message':
                                                'Не услышал ответ. Удерживайте кнопку и повторите.'})
                                    continue
                                finish_requested_at = time.monotonic()
                                # One manual commit covers the entire held answer,
                                # including pauses. No VAD timer can cut it short.
                                await stt_send({'type': 'input_audio_buffer.commit'})
                                # Yandex starts transcription only after an explicit response.
                                # This response stays on the STT socket and is never played.
                                await stt_send({'type': 'response.create'})
                                schedule_answer_flush()
                            continue
                        if kind != 'audio':
                            raise VoiceProtocolError('Неизвестное сообщение голосового интервью.')
                        raw = _audio_bytes(event.get('audio'))
                        if not listening or not answer_held or finish_requested_at:
                            continue
                        await spend.audio('input', len(raw))
                        await stt_send({'type': 'input_audio_buffer.append',
                                        'audio': event['audio']})
                        answer_audio_bytes += len(raw)

                async def pump_stt():
                    async for packet in stt:
                        event = json.loads(packet)
                        kind = event.get('type')
                        item = event.get('item') or {}
                        item_id = item.get('id') if isinstance(item, dict) else None
                        if kind == 'input_audio_buffer.committed':
                            item_id = event.get('item_id')
                            if isinstance(item_id, str):
                                if listening:
                                    stt_context_items.add(item_id)
                                else:
                                    await retire_stt_item(item_id)
                        elif kind in ('conversation.item.created', 'conversation.item.added',
                                      'conversation.item.done', 'response.output_item.added'):
                            if isinstance(item_id, str) and item_id not in deleted_stt_items:
                                stt_context_items.add(item_id)
                                if not listening and (kind == 'conversation.item.done'
                                                      or item.get('status') == 'completed'
                                                      or item.get('role') == 'user'):
                                    await retire_stt_item(item_id)
                        elif kind == 'response.done' and not listening:
                            for old_item_id in tuple(stt_context_items):
                                await retire_stt_item(old_item_id)
                        await stt_events.put(event)
                    raise VoiceProtocolError('Соединение с распознаванием речи прервалось.')

                async def receive_stt():
                    nonlocal listening, finish_requested_at, answer_audio_bytes, pending_item_id
                    while True:
                        event = await stt_events.get()
                        kind = event.get('type')
                        if kind == 'input_audio_buffer.committed':
                            item_id = event.get('item_id')
                            if listening and finish_requested_at and pending_item_id is None:
                                # Yandex can acknowledge a commit with item_id=null,
                                # then send the real ID on the transcription event.
                                pending_item_id = item_id if isinstance(item_id, str) else ''
                                if isinstance(item_id, str):
                                    utterance_questions[item_id] = current_question.id
                            elif isinstance(item_id, str):
                                await retire_stt_item(item_id)
                        elif kind == 'response.created':
                            # The transcription socket never supplies questions
                            # or assessments, even if a response is generated.
                            event_id = 'mimas-cancel-' + uuid4().hex
                            stt_maintenance_events.add(event_id)
                            response_id = (event.get('response') or {}).get('id')
                            payload = {'type': 'response.cancel', 'event_id': event_id}
                            if isinstance(response_id, str):
                                payload['response_id'] = response_id
                            await stt_send(payload)
                        elif kind == 'response.done':
                            await spend.usage(event.get('response') or {})
                        elif kind == 'conversation.item.input_audio_transcription.completed':
                            item_id = event.get('item_id')
                            if not isinstance(item_id, str) or item_id in seen_items:
                                continue
                            seen_items.add(item_id)
                            question_id = utterance_questions.pop(
                                item_id, current_question.id if pending_item_id == '' else None)
                            if (question_id != current_question.id
                                    or pending_item_id not in (item_id, '')
                                    or not listening or not finish_requested_at
                                    or item_id in deleted_stt_items):
                                continue
                            pending_item_id = None
                            cancel_answer_flush()
                            transcript = (event.get('transcript') or '').strip()
                            if not transcript:
                                finish_requested_at = 0.0
                                answer_audio_bytes = 0
                                await retire_stt_item(item_id)
                                await send({'type': 'answer_retry', 'message':
                                            'Речь не удалось распознать. Удерживайте кнопку и повторите.'})
                                continue
                            if len(transcript) > 16000:
                                raise VoiceProtocolError('Ответ слишком длинный. Подключитесь заново и повторите его короче.')
                            listening = False
                            # The provider can acknowledge a commit with item_id=null.
                            # Retire the ID from the transcript itself so the previous
                            # answer cannot leak into recognition of the next turn.
                            await retire_stt_item(item_id)
                            await send({'type': 'transcript', 'speaker': 'candidate', 'text': transcript})
                            try:
                                result = await submit_answer(
                                    iid, CandidateAnswer(question_id=current_question.id, text=transcript), token)
                            except (HTTPException, BudgetExceeded, ProviderError) as exc:
                                # The answer endpoint checkpoints the transcript before
                                # provider I/O. Reconnect can resume a pending answer.
                                await send({'type': 'error', 'message': ('AI временно недоступен. Ответ сохранён.'
                                                                       if isinstance(exc, ProviderError) else
                                                                       str(getattr(exc, 'detail', exc)))})
                                raise VoiceProtocolError('Ответ сохранён. Подключитесь заново для продолжения.') from exc
                            await send({'type': 'state', 'session': result})
                            if result.get('phase') == Phase.WAITING_FOR_ANSWER and result.get('current_question'):
                                fresh = load(iid, token)
                                await speak(InterviewState.model_validate_json(fresh.state).questions[-1])
                            else:
                                await send({'type': 'speech_stopped'})
                        elif kind == 'conversation.item.input_audio_transcription.failed':
                            item_id = event.get('item_id')
                            if isinstance(item_id, str) and pending_item_id in (item_id, ''):
                                raise VoiceProtocolError('Распознавание не удалось. Подключитесь заново и повторите ответ.')
                        elif kind == '_transcription_timeout':
                            if (event.get('generation') == flush_generation and listening
                                    and finish_requested_at):
                                raise VoiceProtocolError('Распознавание задержалось. Подключитесь заново и повторите ответ.')
                        elif kind == 'error':
                            error = event.get('error') or {}
                            origin = error.get('event_id') if isinstance(error, dict) else None
                            if isinstance(origin, str) and origin in stt_maintenance_events:
                                stt_maintenance_events.discard(origin)
                                LOGGER.info('Yandex ignored nonessential STT maintenance: code=%s',
                                            _provider_error_code(event))
                                continue
                            LOGGER.warning('Yandex voice stt error: code=%s',
                                           _provider_error_code(event))
                            raise VoiceProtocolError('Распознавание речи временно недоступно.')

                async def receive_tts():
                    nonlocal speaking, listening, spoken_question, awaiting_playback
                    async for packet in tts:
                        event = json.loads(packet)
                        kind = event.get('type')
                        if kind == 'response.output_audio.delta' and speaking:
                            audio = event.get('delta')
                            if isinstance(audio, str):
                                for chunk, encoded in _tts_audio_chunks(audio):
                                    await spend.audio('output', len(chunk))
                                    await send({'type': 'audio', 'audio': encoded})
                        elif kind == 'response.output_audio_transcript.done':
                            spoken_question = event.get('transcript')
                        elif kind == 'response.done':
                            response = event.get('response') or {}
                            await spend.usage(response)
                            if speaking:
                                if spoken_question and not _spoken_matches_question(spoken_question, current_question.text):
                                    raise VoiceProtocolError('Озвученный вопрос отличается от текста. Подключитесь заново.')
                                speaking, listening, awaiting_playback = False, False, True
                                await send({'type': 'speech_stopped'})
                            status = (event.get('response') or {}).get('status')
                            if status in ('failed', 'incomplete'):
                                raise VoiceProtocolError('Не удалось озвучить вопрос. Подключитесь заново.')
                        elif kind == 'error':
                            LOGGER.warning('Yandex voice tts error: code=%s',
                                           _provider_error_code(event))
                            raise VoiceProtocolError('Озвучивание временно недоступно.')
                    raise VoiceProtocolError('Соединение с озвучиванием прервалось.')

                async def expire_at_deadline():
                    # The event loop may wake just before the wall-clock deadline.
                    # Let the persistent expiry check decide after a short grace.
                    await asyncio.sleep(max(0, deadline_at - time.time()) + 0.02)
                    if expire_if_due is not None:
                        for _ in range(10):
                            completed = await expire_if_due(iid, token)
                            if completed is not None:
                                await send({'type': 'state', 'session': completed})
                                return
                            await asyncio.sleep(0.05)
                    raise VoiceProtocolError('Время голосового интервью истекло.')

                tasks = [
                    asyncio.create_task(receive_client()),
                    asyncio.create_task(pump_stt()),
                    asyncio.create_task(receive_stt()),
                    asyncio.create_task(receive_tts()),
                    asyncio.create_task(expire_at_deadline()),
                ]
                try:
                    finished, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in finished:
                        task.result()
                finally:
                    cancel_answer_flush()
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except WebSocketDisconnect:
            pass
        except ConnectionClosed as exc:
            failed = True
            LOGGER.warning('Yandex voice stream closed: code=%s reason=%s',
                           getattr(getattr(exc, 'rcvd', None), 'code', None),
                           _provider_close_reason(exc))
            try:
                await send({'type': 'error', 'message':
                            'Голосовой сервис прервал соединение. Пробуем подключиться снова.'})
            except (RuntimeError, WebSocketDisconnect):
                pass
        except (VoiceProtocolError, BudgetExceeded) as exc:
            failed = True
            message = 'Месячный лимит AI исчерпан.' if isinstance(exc, BudgetExceeded) else str(exc)
            try:
                await send({'type': 'error', 'message': message})
            except (RuntimeError, WebSocketDisconnect):
                pass
        except Exception as exc:
            failed = True
            LOGGER.warning('Voice runtime failed: %s', type(exc).__name__)
            try:
                await send({'type': 'error', 'message': 'Голосовое соединение прервалось. Ответы сохранены; подключитесь заново.'})
            except (RuntimeError, WebSocketDisconnect):
                pass
        finally:
            try:
                await spend.finish(uncertain=failed and connected)
            except Exception as exc:
                LOGGER.error('Voice budget settlement failed: %s', type(exc).__name__)
            if active.get(iid) is websocket:
                active.pop(iid, None)
            try:
                await websocket.close()
            except (RuntimeError, WebSocketDisconnect):
                pass
