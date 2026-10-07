"""Realtime bridge tests use fake Yandex sockets; no paid calls or PostgreSQL."""
import asyncio
import base64
import json
from types import SimpleNamespace
import time

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ai_core.interview.state import Phase
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
    def __init__(self, kind, questions):
        self.kind = kind
        self.questions = questions
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
            await self.queue.put({'type': 'input_audio_buffer.speech_started'})
            await self.queue.put({'type': 'input_audio_buffer.speech_stopped', 'item_id': 'spoken-1'})
            await self.queue.put({'type': 'response.created',
                                  'response': {'id': 'unwanted-reply'}})
            await self.queue.put({'type': 'conversation.item.input_audio_transcription.completed',
                                  'item_id': 'spoken-1', 'transcript': 'Мой голосовой ответ.'})
            await self.queue.put({'type': 'conversation.item.input_audio_transcription.completed',
                                  'item_id': 'spoken-1', 'transcript': 'Мой голосовой ответ.'})


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
    assert budget.settled
    assert budget.settled[0][1] > 0
    assert not budget.released


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
    assert voice._spoken_matches_question('Расскажите про FastAPI!', 'Расскажите про FastAPI.')
    assert voice._spoken_matches_question('Что такое Фаст АПИ?', 'Что такое FastAPI?')
    assert not voice._spoken_matches_question('Вот ответ про FastAPI.', 'Расскажите про FastAPI.')
