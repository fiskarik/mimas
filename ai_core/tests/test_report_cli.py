import asyncio
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ai_core.interview.engine import InterviewEngine
from ai_core.interview.schemas import Limits
from ai_core.interview.state import Phase
from ai_core.llm.provider import FakeLLMProvider
from ai_core.reports.generator import _answer_count_summary, generate_report
from backend.ai_presenter import session_view


@pytest.mark.parametrize(('count', 'summary'), [
    (0, 'Получено 0 ответов'),
    (1, 'Получен 1 ответ'),
    (3, 'Получено 3 ответа'),
    (11, 'Получено 11 ответов'),
    (21, 'Получен 21 ответ'),
])
def test_russian_answer_count_summary(count, summary):
    assert _answer_count_summary(count) == summary


def test_report_and_candidate_view_use_approved_skill_name():
    state = InterviewEngine(FakeLLMProvider([])).state
    state.plan_snapshot.skills[0].name = 'Мытьё полов'
    state.phase = Phase.COMPLETED
    skill_id = state.skills[0].skill
    report = generate_report(state, mode='scripted')
    view = session_view(SimpleNamespace(id='test', model='fake', state=state.model_dump_json(), pending=None))
    assert report['skills'][0]['name'] == 'Мытьё полов'
    assert view['skill_names'][skill_id] == 'Мытьё полов'


def test_report_requires_independent_goals_and_caps_level():
    evaluated = json.dumps({'correctness':'correct','depth':'high',
                            'evidence':[{'type':'positive','claim':'Explained mechanism','quote':'mechanism'}],
                            'follow_up_required':False,'recommended_difficulty':5})
    provider = FakeLLMProvider([json.dumps({'text':'Question one?'}), evaluated,
                                json.dumps({'text':'Question two?'}), evaluated])
    async def scenario():
        engine = InterviewEngine(provider, limits=Limits(max_questions=2))
        q = await engine.start()
        q = await engine.submit(q.id, 'mechanism')
        assert q.difficulty == 4
        await engine.submit(q.id, 'mechanism')
        report = generate_report(engine.state, mode='scripted')
        first = report['skills'][0]
        assert first['name'] == engine.plan.skills[0].name
        assert first['demonstrated_level'] == 'middle'
        assert first['status'] == 'provisional'
        ids = {e['id'] for e in first['evidence']}
        assert all(s['evidence_id'] in ids for s in first['strengths'])
        assert all(s['demonstrated_level'] is None for s in report['skills'][1:])
        assert 'hire' not in report and 'score' not in report
        assert report['overall_technical_summary'].startswith('Получено 2 ответа.')
        for turn in engine.state.turns:
            turn.question.generation = 'approved_template'
        approved_report = generate_report(engine.state, mode='scripted')
        assert approved_report['skills'][0]['demonstrated_level'] == 'middle'
    asyncio.run(scenario())


def test_cli_offline_creates_report_trace_and_state(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'cli.main', '--max-questions', '1',
                             '--output', str(tmp_path)], input='Synthetic test answer\n',
                            text=True, encoding='utf-8', capture_output=True, cwd=Path(__file__).resolve().parents[2], timeout=30)
    assert result.returncode == 0, result.stderr
    report_path, = tmp_path.glob('*/report.json')
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['mode'] == 'offline_preview'
    assert report['stop_reason'] == 'max_questions'
    events = [json.loads(line) for line in report_path.with_name('trace.jsonl').read_text(encoding='utf-8').splitlines()]
    assert any(e['event'] == 'answer_received' and e['answer']['text'] == 'Synthetic test answer' for e in events)
    assert report_path.with_name('state.json').exists()


def test_slow_generation_does_not_issue_question_past_deadline():
    now = [0.0]
    class SlowProvider:
        async def generate(self, **kwargs):
            now[0] = 1801
            return json.dumps({'text':'Too late?'})
    async def scenario():
        engine = InterviewEngine(SlowProvider(), clock=lambda: now[0])
        assert await engine.start() is None
        assert engine.state.stop_reason == 'time_budget'
        assert not engine.state.questions
    asyncio.run(scenario())
