"""Realtime bridge tests use fake Yandex sockets; no paid calls or PostgreSQL."""
import asyncio
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
    def __init__(self, kind, questions, segments=None, inter_segment_delay=0,
                 last_transcription_delay=0, fail_last_transcription=False,
                 drop_last_transcription=False, unregistered_transcript=None):
        self.kind = kind
        self.questions = questions
        self.segments = segments or ['Мой голосовой ответ.']
        self.inter_segment_delay = inter_segment_delay
        self.last_transcription_delay = last_transcription_delay
        self.fail_last_transcription = fail_last_transcription
        self.drop_last_transcription = drop_last_transcription
        self.unregistered_transcript = unregistered_transcript
        self.queue = asyncio.Queue()
        self.sent = []
        self.response_number = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.queue.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self.queue.get()
        if value is None:
            raise StopAsyncIteration
        return json.dumps(value)

    async def send(self, payload):
        event = json.loads(payload)
        self.sent.append(event)
        if self.kind == 'tts' and event['type'] == 'response.create':
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
        elif self.kind == 'stt' and event['type'] == 'input_audio_buffer.append':
            if self.unregistered_transcript:
                await self.queue.put({
                    'type': 'conversation.item.input_audio_transcription.completed',
                    'item_id': 'late-from-prior-question',
                    'transcript': self.unregistered_transcript,
                })
            for index, transcript in enumerate(self.segments):
                if index:
                    await asyncio.sleep(self.inter_segment_delay)
                item_id = f'spoken-{index + 1}'
                await self.queue.put({'type': 'input_audio_buffer.speech_started'})
                await self.queue.put({'type': 'input_audio_buffer.speech_stopped', 'item_id': item_id})
                await self.queue.put({'type': 'response.created',
                                      'response': {'id': 'unwanted-reply'}})
                await self.queue.put({'type': 'conversation.item.added',
                                      'item': {'id': f'auto-reply-{index + 1}',
                                               'role': 'assistant', 'status': 'in_progress'}})
                await self.queue.put({'type': 'conversation.item.done',
                                      'item': {'id': f'auto-reply-{index + 1}',
                                               'role': 'assistant', 'status': 'completed'}})
                await self.queue.put({'type': 'response.done', 'response': {'status': 'cancelled'}})
                if index == len(self.segments) - 1 and self.last_transcription_delay:
                    await asyncio.sleep(self.last_transcription_delay)
                if index == len(self.segments) - 1 and self.drop_last_transcription:
                    continue
                if index == len(self.segments) - 1 and self.fail_last_transcription:
                    await self.queue.put({'type': 'conversation.item.input_audio_transcription.failed',
                                          'item_id': item_id})
                else:
                    await self.queue.put({'type': 'conversation.item.input_audio_transcription.completed',
                                          'item_id': item_id, 'transcript': transcript})
                    await self.queue.put({'type': 'conversation.item.input_audio_transcription.completed',
                                          'item_id': item_id, 'transcript': transcript})


def _fake_state(question, pending=None):
    return SimpleNamespace(phase=Phase.WAITING_FOR_ANSWER, questions=[question],
                           pending_answer=pending,
                           limits=SimpleNamespace(time_budget_seconds=1800))


def test_voice_bridge_auth_speech_and_authoritative_answer(monkeypatch):
    first = SimpleNamespace(id='q1', text='Расскажите про FastAPI.')
    second = SimpleNamespace(id='q2', text='Как работает PostgreSQL?')
    current = {'question': first}
    row = SimpleNamespace(state='fake-state', pending=None, started=time.time())
    budget = FakeBudget()
    upstreams = []
    submitted = []

    class FakeState:
        @staticmethod
        def model_validate_json(_):
            return _fake_state(current['question'])

    def fake_connect(url, **kwargs):
        stream = FakeUpstream('stt' if len(upstreams) == 0 else 'tts', [first, second])
        upstreams.append(stream)
        assert 'Api-Key secret' == kwargs['additional_headers']['Authorization']
        assert 'speech-realtime-deepseek-v4-flash' in url
        return stream

    async def submit(iid, answer, token):
        submitted.append(answer)
        assert iid == 'interview'
        assert token == 'candidate-token'
        assert answer.question_id == first.id
        assert answer.text == 'Мой голосовой ответ.'
        current['question'] = second
        return {'phase': Phase.WAITING_FOR_ANSWER,
                'current_question': {'id': second.id, 'text': second.text}}

    def load(iid, token):
        if token != 'candidate-token':
            raise HTTPException(401, 'No access')
        return row

    def view(_):
        return {'phase': Phase.WAITING_FOR_ANSWER,
                'current_question': {'id': current['question'].id, 'text': current['question'].text}}

    monkeypatch.setenv('YANDEX_API_KEY', 'secret')
    monkeypatch.setenv('YANDEX_FOLDER_ID', 'folder')
    monkeypatch.setattr(voice, 'ANSWER_SILENCE_SECONDS', 0.03)
    monkeypatch.setattr(voice, 'InterviewState', FakeState)
    monkeypatch.setattr(voice, 'YandexBudget', lambda _: budget)
    monkeypatch.setattr(voice, 'connect', fake_connect)
    app = FastAPI()
    voice.register_voice_route(app, None, load, view, submit)

    with TestClient(app) as client:
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            ws.send_json({'type': 'auth', 'token': 'invalid'})
            assert ws.receive_json()['type'] == 'error'
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            ws.send_json({'type': 'auth', 'token': 'candidate-token'})
            assert ws.receive_json() == {'type': 'ready', 'sample_rate': 44100}
            assert ws.receive_json()['type'] == 'state'
            assert ws.receive_json() == {
                'type': 'transcript', 'speaker': 'mimas', 'text': first.text}
            received_audio = []
            while True:
                event = ws.receive_json()
                if event['type'] == 'speech_stopped':
                    break
                assert event['type'] == 'audio'
                received_audio.append(base64.b64decode(event['audio']))
            assert len(received_audio) > 1
            assert all(len(chunk) <= voice.TTS_DOWNSTREAM_CHUNK_BYTES
                       and len(chunk) % 2 == 0 for chunk in received_audio)
            assert sum(map(len, received_audio)) == voice.PCM_BYTES_PER_SECOND * 3
            ws.send_json({'type': 'audio', 'audio': base64.b64encode(b'\x00\x00' * 100).decode()})
            time.sleep(0.1)
            assert not any(event['type'] == 'input_audio_buffer.append' for event in upstreams[0].sent)
            ws.send_json({'type': 'playback_done'})
            ws.send_json({'type': 'audio', 'audio': base64.b64encode(b'\x00\x00' * 100).decode()})
            events = [ws.receive_json() for _ in range(5)]
            assert events[0]['type'] == 'speech_started'
            assert events[1]['type'] == 'speech_stopped'
            assert events[2] == {'type': 'transcript', 'speaker': 'candidate',
                                 'text': 'Мой голосовой ответ.'}
            assert events[3]['type'] == 'state'
            assert events[4] == {'type': 'transcript', 'speaker': 'mimas',
                                 'text': second.text}
            assert ws.receive_json()['type'] == 'audio'
            assert ws.receive_json()['type'] == 'speech_stopped'
            ws.send_json({'type': 'stop'})

    assert len(upstreams) == 2
    assert len(submitted) == 1
    assert any(event['type'] == 'response.cancel' for event in upstreams[0].sent)
    assert any(event == {'type': 'conversation.item.delete', 'item_id': 'spoken-1'}
               for event in upstreams[0].sent)
    assert any(event == {'type': 'conversation.item.delete', 'item_id': 'auto-reply-1'}
               for event in upstreams[0].sent)
    assert budget.settled
    assert budget.settled[0][1] > 0
    assert not budget.released


@pytest.mark.parametrize('segments, expected', [
    (['Сначала проверю данные,', 'затем предложу решение.'],
     'Сначала проверю данные, затем предложу решение.'),
    (['Сначала проверю данные,', 'Сначала проверю данные, затем предложу решение.'],
     'Сначала проверю данные, затем предложу решение.'),
    (['Сначала проверю данные, затем', 'данные, затем предложу решение.'],
     'Сначала проверю данные, затем предложу решение.'),
])
def test_voice_bridge_combines_segments_before_one_submission(monkeypatch, segments, expected):
    question = SimpleNamespace(id='q1', text='Объясните порядок действий.')
    row = SimpleNamespace(state='fake-state', pending=None, started=time.time())
    upstreams = []
    submitted = []

    class FakeState:
        @staticmethod
        def model_validate_json(_):
            return _fake_state(question)

    def fake_connect(url, **kwargs):
        stream = FakeUpstream('stt' if not upstreams else 'tts', [question],
                              segments=segments, unregistered_transcript='Prior answer.',
                              inter_segment_delay=0.02, last_transcription_delay=0.12)
        upstreams.append(stream)
        return stream

    async def submit(iid, answer, token):
        submitted.append(answer)
        return {'phase': Phase.COMPLETED}

    monkeypatch.setenv('YANDEX_API_KEY', 'secret')
    monkeypatch.setenv('YANDEX_FOLDER_ID', 'folder')
    monkeypatch.setattr(voice, 'ANSWER_SILENCE_SECONDS', 0.08)
    monkeypatch.setattr(voice, 'InterviewState', FakeState)
    monkeypatch.setattr(voice, 'YandexBudget', lambda _: FakeBudget())
    monkeypatch.setattr(voice, 'connect', fake_connect)
    app = FastAPI()
    voice.register_voice_route(app, None, lambda iid, token: row,
                               lambda _: {'phase': Phase.WAITING_FOR_ANSWER}, submit)

    with TestClient(app) as client:
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            ws.send_json({'type': 'auth', 'token': 'candidate-token'})
            assert ws.receive_json()['type'] == 'ready'
            assert ws.receive_json()['type'] == 'state'
            assert ws.receive_json()['speaker'] == 'mimas'
            while ws.receive_json()['type'] != 'speech_stopped':
                pass
            ws.send_json({'type': 'playback_done'})
            ws.send_json({'type': 'audio', 'audio': base64.b64encode(b'\x00\x00' * 100).decode()})
            events = [ws.receive_json() for _ in range(6)]
            assert [event['type'] for event in events] == [
                'speech_started', 'speech_stopped', 'speech_started', 'speech_stopped',
                'transcript', 'state']
            assert events[4] == {'type': 'transcript', 'speaker': 'candidate',
                                 'text': expected}
            ws.send_json({'type': 'stop'})

    assert len(submitted) == 1
    assert submitted[0].question_id == question.id
    assert submitted[0].text == expected


@pytest.mark.parametrize('stt_fails, ai_fails, stt_times_out', [
    (True, False, False), (False, True, False), (False, False, True)])
def test_voice_bridge_error_keeps_complete_answer_or_requests_retry(
        monkeypatch, stt_fails, ai_fails, stt_times_out):
    question = SimpleNamespace(id='q1', text='Расскажите о работе.')
    row = SimpleNamespace(state='fake-state', pending=None, started=time.time())
    upstreams = []
    submitted = []

    class FakeState:
        @staticmethod
        def model_validate_json(_):
            return _fake_state(question)

    def fake_connect(url, **kwargs):
        stream = FakeUpstream('stt' if not upstreams else 'tts', [question],
                              segments=['Первая часть.', 'Вторая часть.'] if (stt_fails or stt_times_out) else None,
                              inter_segment_delay=0.02,
                              fail_last_transcription=stt_fails,
                              drop_last_transcription=stt_times_out)
        upstreams.append(stream)
        return stream

    async def submit(iid, answer, token):
        # The real answer endpoint checkpoints before calling the provider.
        row.pending = answer
        submitted.append(answer)
        if ai_fails:
            raise ProviderError('Temporary model error', retryable=True)
        return {'phase': Phase.COMPLETED}

    monkeypatch.setenv('YANDEX_API_KEY', 'secret')
    monkeypatch.setenv('YANDEX_FOLDER_ID', 'folder')
    monkeypatch.setattr(voice, 'ANSWER_SILENCE_SECONDS', 0.05)
    monkeypatch.setattr(voice, 'TRANSCRIPTION_TIMEOUT_SECONDS', 0.07)
    monkeypatch.setattr(voice, 'InterviewState', FakeState)
    monkeypatch.setattr(voice, 'YandexBudget', lambda _: FakeBudget())
    monkeypatch.setattr(voice, 'connect', fake_connect)
    app = FastAPI()
    voice.register_voice_route(app, None, lambda iid, token: row,
                               lambda _: {'phase': Phase.WAITING_FOR_ANSWER}, submit)

    with TestClient(app) as client:
        with client.websocket_connect('/api/ai/sessions/interview/voice') as ws:
            ws.send_json({'type': 'auth', 'token': 'candidate-token'})
            assert ws.receive_json()['type'] == 'ready'
            assert ws.receive_json()['type'] == 'state'
            assert ws.receive_json()['speaker'] == 'mimas'
            while ws.receive_json()['type'] != 'speech_stopped':
                pass
            ws.send_json({'type': 'playback_done'})
            ws.send_json({'type': 'audio', 'audio': base64.b64encode(b'\x00\x00' * 100).decode()})
            events = []
            while True:
                event = ws.receive_json()
                events.append(event)
                if event['type'] == 'error':
                    break
            if stt_fails or stt_times_out:
                time.sleep(0.08)
                ws.send_json({'type': 'stop'})

    if stt_fails or stt_times_out:
        assert not submitted
        assert not any(event['type'] == 'transcript' for event in events)
        assert 'Повторите ответ целиком' in events[-1]['message']
    else:
        assert len(submitted) == 1
        assert submitted[0].text == 'Мой голосовой ответ.'
        assert row.pending.text == submitted[0].text
        assert any(event == {'type': 'transcript', 'speaker': 'candidate',
                             'text': submitted[0].text} for event in events)
        assert 'Ответ сохранён' in events[-1]['message']


@pytest.mark.parametrize('segments, expected', [
    ([(0, 'Я беру ведро и швабру'),
      (1, 'Я беру ведро и швабру и начинаю уборку')],
     'Я беру ведро и швабру и начинаю уборку'),
    ([(0, 'Я мою полы в коридоре'),
      (1, 'полы в коридоре, затем в кабинете')],
     'Я мою полы в коридоре затем в кабинете'),
    ([(0, 'Я выберу средство'), (1, 'средство для ламината')],
     'Я выберу средство для ламината'),
    ([(0, 'да'), (1, 'да, я понял')], 'да да, я понял'),
    ([(0, 'вода'), (1, 'вода')], 'вода'),
])
def test_merge_transcribed_segments(segments, expected):
    assert voice._merge_transcribed_segments(segments) == expected


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
    assert voice._spoken_matches_question('Расскажите про FastAPI!', 'Расскажите про FastAPI.')
    assert voice._spoken_matches_question('Что такое Фаст АПИ?', 'Что такое FastAPI?')
    assert not voice._spoken_matches_question('Вот ответ про FastAPI.', 'Расскажите про FastAPI.')
