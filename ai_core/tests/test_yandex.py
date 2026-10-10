import asyncio
from contextlib import contextmanager
from decimal import Decimal
from io import BytesIO
import json

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai_core.llm.base import ProviderError
from ai_core.llm.yandex import YandexProvider
from backend.yandex_budget import BudgetExceeded, YandexBudget, YandexCostEntry, YandexBudgetMonth
from backend.yandex_services import YandexServices, YandexServiceError


class FakeBudget:
    def __init__(self):
        self.calls = []

    def reserve(self, service, operation, amount):
        self.calls.append(('reserve', service, operation, amount))
        return 'reservation'

    def settle(self, reservation, amount, usage=None):
        self.calls.append(('settle', reservation, amount, usage))

    def release(self, reservation):
        self.calls.append(('release', reservation))


def test_yandex_provider_structured_and_budget_usage():
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        assert request.headers['OpenAI-Project'] == 'folder'
        assert request.headers['Authorization'] == 'Api-Key secret'
        return httpx.Response(200, json={
            'choices': [{'message': {'content': '{"answer":"ok"}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120},
        })
    budget = FakeBudget()
    provider = YandexProvider('secret', 'folder', transport=httpx.MockTransport(handler), budget=budget)
    result = asyncio.run(provider.generate(
        system='Reply in JSON', payload={'question': 'hello'},
        schema={'type': 'object', 'properties': {'answer': {'type': 'string'}},
                'required': ['answer']},
        operation='template'))
    assert json.loads(result)['answer'] == 'ok'
    assert requests[0]['model'] == 'gpt://folder/deepseek-v4.1-flash'
    assert requests[0]['response_format']['type'] == 'json_schema'
    assert budget.calls[0][0] == 'reserve'
    assert budget.calls[1][0] == 'settle'
    assert budget.calls[1][2] == Decimal('0.0400')


def test_yandex_provider_schema_fallback_is_locally_validated():
    formats = []
    def handler(request):
        body = json.loads(request.content)
        formats.append(body['response_format']['type'])
        if len(formats) == 1:
            return httpx.Response(400, json={'message': 'Unsupported json_schema'})
        return httpx.Response(200, json={
            'choices': [{'message': {'content': '{"answer":"ok"}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 10}})
    budget = FakeBudget()
    provider = YandexProvider('secret', 'folder', transport=httpx.MockTransport(handler), budget=budget)
    asyncio.run(provider.generate(system='json', payload={}, schema={
        'type': 'object', 'properties': {'answer': {'type': 'string'}}, 'required': ['answer']}))
    assert formats == ['json_schema', 'json_object']
    assert [call[0] for call in budget.calls] == ['reserve', 'release', 'reserve', 'settle']


def test_yandex_provider_rejects_invalid_json_and_accounts_accepted_request():
    def handler(_):
        return httpx.Response(200, json={
            'choices': [{'message': {'content': '{"answer": 1}'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 10}})
    budget = FakeBudget()
    provider = YandexProvider('secret', 'folder', transport=httpx.MockTransport(handler), budget=budget)
    with pytest.raises(ProviderError) as exc:
        asyncio.run(provider.generate(system='json', payload={}, schema={
            'type': 'object', 'properties': {'answer': {'type': 'string'}},
            'required': ['answer']}))
    assert exc.value.code == 'invalid_provider_response'
    assert budget.calls[-1][0] == 'settle'


def test_yandex_provider_5xx_accounts_uncertain_request():
    provider = YandexProvider('secret', 'folder', budget=FakeBudget(),
                              transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    with pytest.raises(ProviderError):
        asyncio.run(provider.generate(system='json', payload={}, schema={}))
    assert [call[0] for call in provider.budget.calls] == ['reserve', 'settle']


def test_vision_ocr_image_and_multipage_pdf():
    pypdf = pytest.importorskip('pypdf')
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    stream = BytesIO()
    writer.write(stream)
    pages = [
        {'result': {'page': '1', 'text_annotation': {'blocks': [
            {'lines': [{'alternatives': [{'text': 'Second'}]}]}]}}},
        {'result': {'page': '0', 'text_annotation': {'full_text': 'First'}}},
    ]
    def handler(request):
        if request.url.path.endswith('/recognizeTextAsync'):
            return httpx.Response(200, json={'id': 'op1'})
        if request.url.path.endswith('/getRecognition'):
            return httpx.Response(200, text='\n'.join(json.dumps(page) for page in pages))
        if request.url.path.endswith('/recognizeText'):
            return httpx.Response(200, json={'result': {
                'textAnnotation': {'fullText': 'Image text'}}})
        raise AssertionError(request.url.path)
    budget = FakeBudget()
    services = YandexServices('secret', 'folder', budget=budget,
                              transport=httpx.MockTransport(handler), sleep=lambda _: asyncio.sleep(0))
    assert asyncio.run(services.ocr_document(stream.getvalue(), 'application/pdf')) == 'First\n\nSecond'
    assert asyncio.run(services.ocr_document(b'\x89PNG\r\n\x1a\nfake', 'image/png')) == 'Image text'
    assert [c[0] for c in budget.calls] == ['reserve', 'settle', 'reserve', 'settle']
    assert budget.calls[0][3] == Decimal('2.00')


def test_speechkit_async_transcription():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path.endswith('/recognizeFileAsync'):
            body = json.loads(request.content)
            assert body['recognitionModel']['audioFormat']['containerAudio']['containerAudioType'] == 'OGG_OPUS'
            return httpx.Response(200, json={'id': 'stt123'})
        if request.url.path.endswith('/operations/stt123'):
            return httpx.Response(200, json={'done': True})
        if request.url.path.endswith('/getRecognition'):
            return httpx.Response(200, json={'result': {
                'final': {'alternatives': [{'text': 'Тестовый ответ'}]}}})
        raise AssertionError(request.url.path)
    class StubServices(YandexServices):
        async def _ogg_opus(self, _):
            return b'Opus mock', 7.5
    budget = FakeBudget()
    services = StubServices('secret', 'folder', budget=budget, transport=httpx.MockTransport(handler))
    assert asyncio.run(services.transcribe_webm(b'webm')) == 'Тестовый ответ'
    assert len(calls) == 3
    assert budget.calls[0][3] == Decimal('0.1515')


def test_speechkit_failure_keeps_input_for_retry():
    class StubServices(YandexServices):
        async def _ogg_opus(self, _):
            return b'Opus mock', 7.5
    services = StubServices('secret', 'folder', transport=httpx.MockTransport(
        lambda _: httpx.Response(401)))
    with pytest.raises(YandexServiceError) as exc:
        asyncio.run(services.transcribe_webm(b'webm'))
    assert exc.value.code == 'authentication_error'


class MemoryDatabase:
    def __init__(self):
        self.engine = create_engine('sqlite+pysqlite:///:memory:',
                                    connect_args={'check_same_thread': False}, poolclass=StaticPool)
        YandexBudgetMonth.__table__.create(self.engine)
        YandexCostEntry.__table__.create(self.engine)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self, *, write=False):
        with self.sessions() as session:
            with session.begin():
                yield session


def test_budget_reserve_settle_and_limit():
    db = MemoryDatabase()
    budget = YandexBudget(db, limit_rub=Decimal('1.00'))
    first = budget.reserve('llm', 'question', Decimal('0.60'))
    with pytest.raises(BudgetExceeded):
        budget.reserve('llm', 'question', Decimal('0.50'))
    budget.settle(first, Decimal('0.20'), {'prompt_tokens': 42})
    assert budget.status()['spent_rub'] == '0.2000'
    second = budget.reserve('vision_ocr', 'vacancy_import', Decimal('0.80'))
    budget.release(second)
    assert budget.status()['reserved_rub'] == '0.0000'
    with db.session() as session:
        assert session.query(YandexCostEntry).count() == 2
        assert session.query(YandexBudgetMonth).count() == 1



def test_expired_reservation_stays_charged_conservatively():
    db = MemoryDatabase()
    budget = YandexBudget(db, limit_rub=Decimal('1.00'), reservation_ttl_seconds=-1)
    budget.reserve('llm', 'question', Decimal('0.60'))
    with pytest.raises(BudgetExceeded):
        budget.reserve('llm', 'question', Decimal('0.50'))
    status = budget.status()
    assert status['spent_rub'] == '0.6000'
    assert status['reserved_rub'] == '0.0000'


def test_postgres_budget_concurrent_reservations(monkeypatch):
    # Opt-in: point only at a disposable PostgreSQL database.
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import uuid4
    from sqlalchemy import delete
    import backend.yandex_budget as budget_module

    url = os.getenv('MIMAS_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set MIMAS_TEST_DATABASE_URL to a disposable PostgreSQL database')
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name != 'postgresql':
        pytest.skip('Concurrency check needs PostgreSQL')
    YandexBudgetMonth.__table__.create(engine, checkfirst=True)
    YandexCostEntry.__table__.create(engine, checkfirst=True)
    month = 'T' + uuid4().hex[:6]
    monkeypatch.setattr(budget_module, 'current_month', lambda: month)

    class PgDatabase:
        def __init__(self, engine):
            self.engine = engine
            self.sessions = sessionmaker(engine, expire_on_commit=False)

        @contextmanager
        def session(self, *, write=False):
            with self.sessions() as session:
                with session.begin():
                    yield session

    budget = YandexBudget(PgDatabase(engine), limit_rub=Decimal('1.00'))
    barrier = Barrier(10)

    def attempt(_):
        barrier.wait()
        try:
            return budget.reserve('llm', 'question', Decimal('0.20'))
        except BudgetExceeded:
            return None

    try:
        with ThreadPoolExecutor(max_workers=10) as executor:
            ids = list(executor.map(attempt, range(10)))
        assert len([value for value in ids if value]) == 5
        assert budget.status()['reserved_rub'] == '1.0000'
    finally:
        with engine.begin() as connection:
            connection.execute(delete(YandexCostEntry).where(YandexCostEntry.month == month))
            connection.execute(delete(YandexBudgetMonth).where(YandexBudgetMonth.month == month))
        engine.dispose()


def test_monthly_limit_is_optional_and_can_be_reenabled(monkeypatch):
    db = MemoryDatabase()
    monkeypatch.delenv('MIMAS_AI_MONTHLY_LIMIT_RUB', raising=False)
    unlimited = YandexBudget(db)
    assert unlimited.limit_rub is None
    assert unlimited.status()['limit_rub'] is None
    unlimited.reserve('llm', 'question', Decimal('1500'))
    monkeypatch.setenv('MIMAS_AI_MONTHLY_LIMIT_RUB', '0')
    unlimited = YandexBudget(db)
    assert unlimited.limit_rub is None
    unlimited.reserve('llm', 'question', Decimal('10'))
    monkeypatch.setenv('MIMAS_AI_MONTHLY_LIMIT_RUB', '5000')
    assert YandexBudget(db).limit_rub == Decimal('5000.0000')
    monkeypatch.setenv('MIMAS_AI_MONTHLY_LIMIT_RUB', '0.40')
    budget = YandexBudget(MemoryDatabase())
    assert budget.limit_rub == Decimal('0.4000')
    budget.reserve('llm', 'question', Decimal('0.30'))
    with pytest.raises(BudgetExceeded):
        budget.reserve('llm', 'question', Decimal('0.11'))
