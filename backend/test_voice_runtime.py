"""Realtime bridge tests use fake Yandex sockets; no paid calls or PostgreSQL."""
import asyncio
from contextlib import AsyncExitStack
import base64
import json
from types import SimpleNamespace
import time

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ai_core.interview.state import Phase
from ai_core.llm.base import ProviderError
from backend import voice_runtime as voice


class FakeBudget:
    def __init__(self):
        self.reserved = []
        self.settled = []
        self.released = []

    def reserve(self, service, operation, amount):
        marker = f'reservation-{len(self.reserved) + 1}'
        self.reserved.append((marker, service, operation, amount))
        return marker

    def settle(self, marker, amount, usage):
        self.settled.append((marker, amount, usage))

    def release(self, marker):
        self.released.append(marker)


class FakeUpstream:
    def __init__(self, kind, questions, transcript='Мой голосовой ответ.',
                 transcription_delay=0, fail_transcription=False,
                 drop_transcription=False, unregistered_transcript=None,
                 null_committed_item_id=False, cancel_error=False):
        self.kind = kind
        self.questions = questions
        self.transcript = transcript
        self.transcription_delay = transcription_delay
        self.fail_transcription = fail_transcription
        self.drop_transcription = drop_transcription
        self.unregistered_transcript = unregistered_transcript
        self.null_committed_item_id = null_committed_item_id
        self.cancel_error = cancel_error
        self.pending_transcription_item_id = None
        self.queue = asyncio.Queue()
        self.sent = []
        self.response_number = 0
        self.commit_number = 0
        self.audio_chunks = 0
        self.deliveries = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        for task in self.deliveries:
            task.cancel()
        await asyncio.gather(*self.deliveries, return_exceptions=True)
        await self.queue.put(None)

    def __aiter__(self):
        return self

    async def recv(self):
        return await self.__anext__()

    async def __anext__(self):
        value = await self.queue.get()
        if value is None:
            raise StopAsyncIteration
        return json.dumps(value)

    async def send(self, payload):
        event = json.loads(payload)
        self.sent.append(event)
        if event['type'] == 'session.update':
            await self.queue.put({'type': 'session.updated',
                                  'session': event['session']})
        elif self.kind == 'tts' and event['type'] == 'response.create':
            question = self.questions[self.response_number]
            self.response_number += 1
            samples = voice.SAMPLE_RATE * 3 if self.response_number == 1 else 100
            audio = base64.b64encode(b'\x00\x00' * samples).decode()
            await self.queue.put({'type': 'response.output_audio.delta', 'delta': audio})
            await self.queue.put({'type': 'response.output_audio_transcript.done',
                                  'transcript': question.text})
            await self.queue.put({'type': 'response.done',
                                  'response': {'status': 'completed', 'usage': {
                                      'input_token_details': {'text_tokens': 30},
                                      'output_token_details': {'text_tokens': 20}}}})
        elif self.kind == 'stt' and event['type'] == 'response.cancel' and self.cancel_error:
            await self.queue.put({'type': 'error', 'error': {
                'code': 'response_cancel_not_active',
                'event_id': event['event_id'],
                'message': 'Response already finished'}})
        elif self.kind == 'stt' and event['type'] == 'input_audio_buffer.append':
            self.audio_chunks += 1
            if self.unregistered_transcript:
                await self.queue.put({
                    'type': 'conversation.item.input_audio_transcription.completed',
                    'item_id': 'late-from-prior-question',
                    'transcript': self.unregistered_transcript,
                })
        elif self.kind == 'stt' and event['type'] == 'input_audio_buffer.commit':
            self.commit_number += 1
            item_id = f'spoken-{self.commit_number}'
            await self.queue.put({'type': 'input_audio_buffer.committed',
                                  'item_id': None if self.null_committed_item_id else item_id})
            self.pending_transcription_item_id = item_id
            self.audio_chunks = 0
        elif self.kind == 'stt' and event['type'] == 'response.create':
            item_id = self.pending_transcription_item_id
            assert item_id is not None, 'Commit must precede transcription response'
            self.pending_transcription_item_id = None

            async def deliver():
                await asyncio.sleep(self.transcription_delay)
                await self.queue.put({'type': 'response.created',
                                      'response': {'id': 'unwanted-reply'}})
                await self.queue.put({'type': 'conversation.item.added',
                                      'item': {'id': f'auto-reply-{self.commit_number}',
                                               'role': 'assistant', 'status': 'in_progress'}})
                await self.queue.put({'type': 'conversation.item.done',
                                      'item': {'id': f'auto-reply-{self.commit_number}',
                                               'role': 'assistant', 'status': 'completed'}})
                await self.queue.put({'type': 'response.done', 'response': {'status': 'cancelled'}})
                if self.drop_transcription:
                    return
                if self.fail_transcription:
                    await self.queue.put({'type': 'conversation.item.input_audio_transcription.failed',
                                          'item_id': item_id})
                else:
                    for _ in range(2):
                        await self.queue.put({'type': 'conversation.item.input_audio_transcription.completed',
                                              'item_id': item_id, 'transcript': self.transcript})

            self.deliveries.append(asyncio.create_task(deliver()))


def _fake_state(question, pending=None, time_budget_seconds=1800):
    return SimpleNamespace(phase=Phase.WAITING_FOR_ANSWER, questions=[question],
                           pending_answer=pending,
                           limits=SimpleNamespace(time_budget_seconds=time_budget_seconds))


def _harness(monkeypatch, questions, *, transcript='Мой голосовой ответ.',
             transcription_delay=0, fail_transcription=False, drop_transcription=False,
             unregistered_transcript=None, provider_error=False,
             null_committed_item_id=False, cancel_error=False,
             time_budget_seconds=1800, expire_if_due=None):
    current = {'index': 0}
    row = SimpleNamespace(state='fake-state', pending=None, started=time.time())
    upstreams = []
    submitted = []
    budget = FakeBudget()

    class FakeState:
        @staticmethod
        def model_validate_json(_):
            return _fake_state(questions[current['index']],
                               time_budget_seconds=time_budget_seconds)

    def fake_connect(url, **kwargs):
        stream = FakeUpstream('stt' if not upstreams else 'tts', questions,
                              transcript=transcript,
                              transcription_delay=transcription_delay,
                              fail_transcription=fail_transcription,
                              drop_transcription=drop_transcription,
                              unregistered_transcript=unregistered_transcript,
                              null_committed_item_id=null_committed_item_id,
                              cancel_error=cancel_error)
        upstreams.append(stream)
        assert kwargs['additional_headers']['Authorization'] == 'Api-Key secret'
        assert 'speech-realtime-deepseek-v4-flash' in url
        return stream

    async def submit(iid, answer, token):
        assert iid == 'interview'
        assert token == 'candidate-token'
        submitted.append(answer)
        row.pending = answer
        if provider_error:
            raise ProviderError('Temporary model error', retryable=True)
        if current['index'] + 1 < len(questions):
            current['index'] += 1
            next_question = questions[current['index']]
            return {'phase': Phase.WAITING_FOR_ANSWER,
                    'current_question': {'id': next_question.id, 'text': next_question.text}}
        return {'phase': Phase.COMPLETED}

    def load(iid, token):
        if token != 'candidate-token':
            raise HTTPException(401, 'No access')
        return row

    def view(_):
        q = questions[current['index']]
        return {'phase': Phase.WAITING_FOR_ANSWER,
                'current_question': {'id': q.id, 'text': q.text}}

    monkeypatch.setenv('YANDEX_API_KEY', 'secret')
    monkeypatch.setenv('YANDEX_FOLDER_ID', 'folder')
    monkeypatch.setattr(voice, 'InterviewState', FakeState)
    monkeypatch.setattr(voice, 'YandexBudget', lambda _: budget)
    monkeypatch.setattr(voice, 'connect', fake_connect)
    app = FastAPI()
    voice.register_voice_route(app, None, load, view, submit, expire_if_due)
    return app, row, upstreams, submitted, budget


def _start_voice(ws, question):
    ws.send_json({'type': 'auth', 'token': 'candidate-token'})
    assert ws.receive_json() == {'type': 'ready', 'sample_rate': voice.SAMPLE_RATE}
    assert ws.receive_json()['type'] == 'state'
    assert ws.receive_json() == {'type': 'transcript', 'speaker': 'mimas',
                                 'text': question.text}
    audio_chunks = []
    while True:
        event = ws.receive_json()
        if event['type'] == 'speech_stopped':
            break
        assert event['type'] == 'audio'
        audio_chunks.append(base64.b64decode(event['audio']))
    ws.send_json({'type': 'playback_done'})
    return audio_chunks


def test_voice_bridge_auth_speech_and_authoritative_answer(monkeypatch):
    first = SimpleNamespace(id='q1', text='Расскажите про FastAPI.')
    second = SimpleNamespace(id='q2', text='Как работает PostgreSQL?')
    app, row, upstreams, submitted, budget = _harness(
        monkeypatch, [first, second], unregistered_transcript='Старый ответ.')

    with TestClient(app) as client:
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            ws.send_json({'type': 'auth', 'token': 'invalid'})
            assert ws.receive_json()['type'] == 'error'
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            chunks = _start_voice(ws, first)
            assert len(chunks) > 1
            assert all(len(chunk) <= voice.TTS_DOWNSTREAM_CHUNK_BYTES
                           and len(chunk) % 2 == 0 for chunk in chunks)
            assert sum(map(len, chunks)) == voice.PCM_BYTES_PER_SECOND * 3
            frame = base64.b64encode(b'\x01\x00' * 100).decode()
            ws.send_json({'type': 'audio', 'audio': frame})
            time.sleep(0.05)
            assert not any(e['type'] == 'input_audio_buffer.append' for e in upstreams[0].sent)
            ws.send_json({'type': 'start_answer'})
            ws.send_json({'type': 'audio', 'audio': frame})
            ws.send_json({'type': 'finish_answer'})
            assert ws.receive_json() == {'type': 'transcript', 'speaker': 'candidate',
                                         'text': 'Мой голосовой ответ.'}
            assert ws.receive_json()['type'] == 'state'
            assert ws.receive_json() == {'type': 'transcript', 'speaker': 'mimas',
                                         'text': second.text}
            assert ws.receive_json()['type'] == 'audio'
            assert ws.receive_json()['type'] == 'speech_stopped'
            ws.send_json({'type': 'stop'})

    assert len(upstreams) == 2
    assert len(submitted) == 1
    assert submitted[0].question_id == first.id
    assert submitted[0].text == 'Мой голосовой ответ.'
    assert sum(e['type'] == 'input_audio_buffer.commit' for e in upstreams[0].sent) == 1
    assert any(e['type'] == 'conversation.item.delete' and e['item_id'] == 'spoken-1'
               for e in upstreams[0].sent)
    assert any(e['type'] == 'response.cancel' for e in upstreams[0].sent)
    assert budget.settled and budget.settled[0][1] > 0


def test_yandex_null_commit_id_still_saves_transcript(monkeypatch):
    # Real Realtime sends item_id=null on the commit acknowledgement, then
    # supplies a real ID only with the transcription event.
    question = SimpleNamespace(id='q1', text='Как проверить сварной шов?')
    app, _, upstreams, submitted, _ = _harness(
        monkeypatch, [question], transcript='Осматриваю шов и проверяю дефекты.',
        null_committed_item_id=True)
    with TestClient(app) as client:
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            _start_voice(ws, question)
            ws.send_json({'type': 'start_answer'})
            ws.send_json({'type': 'audio',
                          'audio': base64.b64encode(b'\x01\x00' * 100).decode()})
            ws.send_json({'type': 'finish_answer'})
            transcript = ws.receive_json()
            assert transcript == {'type': 'transcript', 'speaker': 'candidate',
                                  'text': 'Осматриваю шов и проверяю дефекты.'}
            assert ws.receive_json()['type'] == 'state'
            ws.send_json({'type': 'stop'})
    assert len(submitted) == 1
    sent_types = [event['type'] for event in upstreams[0].sent]
    assert sent_types.index('input_audio_buffer.commit') < sent_types.index('response.create')
    assert sent_types.count('response.create') == 1


@pytest.mark.parametrize('delay', [0, 0.12])
def test_push_to_talk_keeps_pauses_and_submits_once_on_release(monkeypatch, delay):
    question = SimpleNamespace(id='q1', text='Объясните порядок действий.')
    complete_answer = 'Сначала проверю условия. Затем выполню задачу. Это мой полный ответ.'
    app, row, upstreams, submitted, _ = _harness(
        monkeypatch, [question], transcript=complete_answer, transcription_delay=delay)
    monkeypatch.setattr(voice, 'TRANSCRIPTION_TIMEOUT_SECONDS', 0.5)

    with TestClient(app) as client:
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            _start_voice(ws, question)
            frame = base64.b64encode(b'\x01\x00' * 100).decode()
            ws.send_json({'type': 'start_answer'})
            ws.send_json({'type': 'audio', 'audio': frame})
            time.sleep(0.15)  # Longer than the former automatic VAD flush.
            ws.send_json({'type': 'audio', 'audio': frame})
            time.sleep(0.15)
            assert not submitted
            ws.send_json({'type': 'finish_answer'})
            assert ws.receive_json() == {'type': 'transcript', 'speaker': 'candidate',
                                         'text': complete_answer}
            assert ws.receive_json()['type'] == 'state'
            ws.send_json({'type': 'stop'})

    assert len(submitted) == 1
    assert submitted[0].text == complete_answer
    assert sum(e['type'] == 'input_audio_buffer.append' for e in upstreams[0].sent) == 2
    assert sum(e['type'] == 'input_audio_buffer.commit' for e in upstreams[0].sent) == 1


def test_push_to_talk_long_answer_is_one_commit(monkeypatch):
    question = SimpleNamespace(id='q1', text='Расскажите о проекте подробно.')
    app, row, upstreams, submitted, budget = _harness(
        monkeypatch, [question], transcript='Полный ответ о проекте.')
    with TestClient(app) as client:
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            _start_voice(ws, question)
            ws.send_json({'type': 'start_answer'})
            frame = base64.b64encode(b'\x01\x00' * voice.SAMPLE_RATE * 2).decode()
            for _ in range(32):  # 64 seconds, across the budget reservation boundary.
                ws.send_json({'type': 'audio', 'audio': frame})
            ws.send_json({'type': 'finish_answer'})
            assert ws.receive_json()['speaker'] == 'candidate'
            assert ws.receive_json()['type'] == 'state'
            ws.send_json({'type': 'stop'})
    assert len(submitted) == 1
    assert sum(e['type'] == 'input_audio_buffer.commit' for e in upstreams[0].sent) == 1
    assert len(budget.reserved) >= 2


def test_push_to_talk_empty_release_allows_retry(monkeypatch):
    question = SimpleNamespace(id='q1', text='Расскажите про задачу.')
    app, row, upstreams, submitted, _ = _harness(monkeypatch, [question])
    with TestClient(app) as client:
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            _start_voice(ws, question)
            ws.send_json({'type': 'start_answer'})
            ws.send_json({'type': 'finish_answer'})
            assert ws.receive_json() == {
                'type': 'answer_retry',
                'message': 'Не услышал ответ. Удерживайте кнопку и повторите.'}
            assert not submitted
            ws.send_json({'type': 'start_answer'})
            ws.send_json({'type': 'audio',
                          'audio': base64.b64encode(b'\x01\x00' * 100).decode()})
            ws.send_json({'type': 'finish_answer'})
            assert ws.receive_json()['type'] == 'transcript'
            assert ws.receive_json()['type'] == 'state'
            ws.send_json({'type': 'stop'})
    assert len(submitted) == 1
    assert sum(e['type'] == 'input_audio_buffer.commit' for e in upstreams[0].sent) == 1


@pytest.mark.parametrize('stt_fails, ai_fails, stt_times_out', [
    (True, False, False), (False, True, False), (False, False, True)])
def test_voice_bridge_error_keeps_complete_answer_or_requests_retry(
        monkeypatch, stt_fails, ai_fails, stt_times_out):
    question = SimpleNamespace(id='q1', text='Расскажите о работе.')
    app, row, upstreams, submitted, _ = _harness(
        monkeypatch, [question], provider_error=ai_fails,
        fail_transcription=stt_fails, drop_transcription=stt_times_out)
    monkeypatch.setattr(voice, 'TRANSCRIPTION_TIMEOUT_SECONDS', 0.07)
    with TestClient(app) as client:
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            _start_voice(ws, question)
            ws.send_json({'type': 'start_answer'})
            ws.send_json({'type': 'audio',
                          'audio': base64.b64encode(b'\x01\x00' * 100).decode()})
            ws.send_json({'type': 'finish_answer'})
            events = []
            while True:
                event = ws.receive_json()
                events.append(event)
                if event['type'] == 'error':
                    break
            ws.send_json({'type': 'stop'})
    if stt_fails or stt_times_out:
        assert not submitted
        assert not any(e['type'] == 'transcript' for e in events)
        assert 'повторите ответ' in events[-1]['message'].lower()
    else:
        assert len(submitted) == 1
        assert row.pending.text == 'Мой голосовой ответ.'
        assert any(e == {'type': 'transcript', 'speaker': 'candidate',
                         'text': row.pending.text} for e in events)
        assert 'Ответ сохранён' in events[-1]['message']


def test_voice_expired_on_connect_returns_report_without_provider(monkeypatch):
    app = FastAPI()
    seen = []

    async def expire(iid, token):
        seen.append((iid, token))
        return {'phase': Phase.COMPLETED, 'report': {'stop_reason': 'time_budget'}}

    def never_load(iid, token):
        raise AssertionError('expired session must not start provider')

    voice.register_voice_route(app, None, never_load, lambda _: {},
                               lambda *_: None, expire)
    with TestClient(app) as client:
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            ws.send_json({'type': 'auth', 'token': 'candidate-token'})
            assert ws.receive_json() == {'type': 'state', 'session': {
                'phase': Phase.COMPLETED, 'report': {'stop_reason': 'time_budget'}}}
    assert seen == [('interview', 'candidate-token')]



def test_voice_deadline_completes_during_held_answer(monkeypatch):
    question = SimpleNamespace(id='q1', text='Расскажите о своём опыте.')
    deadline = {'at': 0.0}

    async def expire(iid, token):
        if time.time() < deadline['at']:
            return None
        return {'phase': Phase.COMPLETED, 'report': {'stop_reason': 'time_budget'}}

    app, row, upstreams, submitted, _ = _harness(
        monkeypatch, [question], time_budget_seconds=0.25, expire_if_due=expire)
    deadline['at'] = row.started + 0.25
    with TestClient(app) as client:
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            _start_voice(ws, question)
            ws.send_json({'type': 'start_answer'})
            ws.send_json({'type': 'audio',
                          'audio': base64.b64encode(b'\x01\x00' * 100).decode()})
            assert ws.receive_json() == {'type': 'state', 'session': {
                'phase': Phase.COMPLETED, 'report': {'stop_reason': 'time_budget'}}}
    assert not submitted
    assert not any(e['type'] == 'input_audio_buffer.commit' for e in upstreams[0].sent)


def test_long_answer_gets_bounded_extra_transcription_time():
    assert voice._transcription_timeout_seconds(0) == voice.TRANSCRIPTION_TIMEOUT_SECONDS
    assert voice._transcription_timeout_seconds(voice.PCM_BYTES_PER_SECOND * 60) > 45
    assert voice._transcription_timeout_seconds(voice.PCM_BYTES_PER_SECOND * 3600) == 90


def test_voice_spend_reserves_windows_before_audio_and_releases_idle():
    budget = FakeBudget()

    async def exercise():
        idle = voice.VoiceSpend(budget)
        await idle.start()
        await idle.finish()
        assert budget.released == ['reservation-1']
        active = voice.VoiceSpend(budget)
        await active.start()
        await active.audio('input', voice.AUDIO_WINDOW_BYTES)
        await active.audio('input', 2)
        await active.finish()
        assert len(budget.reserved) == 3
        assert len(budget.settled) == 2
        assert all(entry[1] >= 0 for entry in budget.settled)

    asyncio.run(exercise())


def test_speech_mismatch_is_rejected():
    assert voice._session_update(transcribe=False)['session']['audio']['output']['voice'] == 'dasha'
    assert voice._session_update(transcribe=True)['session']['audio']['input']['languages'] == ['ru-RU']
    assert voice._session_update(transcribe=True)['session']['audio']['input']['turn_detection'] is None
    assert voice._spoken_matches_question('Расскажите про FastAPI!', 'Расскажите про FastAPI.')
    assert voice._spoken_matches_question('Что такое Фаст АПИ?', 'Что такое FastAPI?')
    assert not voice._spoken_matches_question('Вот ответ про FastAPI.', 'Расскажите про FastAPI.')


def test_yandex_channel_retries_unavailable_upstream_before_ready(monkeypatch):
    class Unavailable:
        async def __aenter__(self):
            raise OSError('upstream_unavailable')

    attempts = []
    streams = []

    def fake_connect(*args, **kwargs):
        attempts.append((args, kwargs))
        if len(attempts) == 1:
            return Unavailable()
        stream = FakeUpstream('stt', [])
        streams.append(stream)
        return stream

    monkeypatch.setattr(voice, 'connect', fake_connect)

    async def exercise():
        async with AsyncExitStack() as stack:
            stream = await voice._open_yandex_channel(
                stack, 'wss://example.invalid/' + voice.VOICE_MODEL,
                {'Authorization': 'secret'},
                transcribe=True, max_size=2048)
            assert stream is streams[0]
            assert stream.sent[0]['type'] == 'session.update'
        assert len(attempts) == 2
        assert voice.VOICE_MODEL in attempts[0][0][0]
        assert voice.VOICE_FALLBACK_MODEL in attempts[1][0][0]

    asyncio.run(exercise())


def test_provider_error_code_does_not_include_raw_payload():
    event = {'type': 'error', 'error': {'code': 'upstream_unavailable',
                                      'message': 'Candidate transcript and private key'}}
    assert voice._provider_error_code(event) == 'upstream_unavailable'


def test_cancel_race_does_not_drop_recognized_answer(monkeypatch):
    question = SimpleNamespace(id='q1', text='Как проверить инструмент?')
    app, _, upstreams, submitted, _ = _harness(
        monkeypatch, [question], cancel_error=True)
    with TestClient(app) as client:
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            _start_voice(ws, question)
            ws.send_json({'type': 'start_answer'})
            ws.send_json({'type': 'audio',
                          'audio': base64.b64encode(b'\x01\x00' * 100).decode()})
            ws.send_json({'type': 'finish_answer'})
            assert ws.receive_json()['speaker'] == 'candidate'
            assert ws.receive_json()['type'] == 'state'
            ws.send_json({'type': 'stop'})
    assert len(submitted) == 1
    assert any(e['type'] == 'response.cancel' and e.get('event_id')
               for e in upstreams[0].sent)


def test_yandex_channel_falls_back_on_provider_unavailable_event(monkeypatch):
    class ProviderUnavailable(FakeUpstream):
        async def send(self, payload):
            await self.queue.put({'type': 'error', 'error': {
                'type': 'server_error', 'code': 'upstream_unavailable',
                'message': 'temporary'}})

    attempts = []

    def fake_connect(url, **kwargs):
        attempts.append(url)
        return ProviderUnavailable('stt', []) if len(attempts) == 1 else FakeUpstream('stt', [])

    monkeypatch.setattr(voice, 'connect', fake_connect)

    async def exercise():
        async with AsyncExitStack() as stack:
            stream = await voice._open_yandex_channel(
                stack, 'wss://example.invalid/' + voice.VOICE_MODEL,
                {'Authorization': 'secret'}, transcribe=True, max_size=2048)
            assert stream.sent[0]['type'] == 'session.update'
        assert voice.VOICE_FALLBACK_MODEL in attempts[1]

    asyncio.run(exercise())
