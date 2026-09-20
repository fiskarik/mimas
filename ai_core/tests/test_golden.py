"""Scripted policy regression, NOT a measurement of live model accuracy."""
import asyncio
import json
from pathlib import Path

import pytest

from ai_core.evaluation.evaluator import AnswerEvaluator
from ai_core.evidence.service import collect
from ai_core.interview.decision_engine import decide
from ai_core.interview.schemas import Limits, Question
from ai_core.interview.state import SkillState
from ai_core.llm.provider import FakeLLMProvider
from ai_core.models import Level

SCENARIOS = sorted((Path(__file__).parent / 'golden_interviews').glob('*.json'))


@pytest.mark.parametrize('path', SCENARIOS, ids=lambda p: p.stem)
def test_scripted_evaluation_drives_expected_policy(path):
    scenario = json.loads(path.read_text(encoding='utf-8'))
    provider = FakeLLMProvider([json.dumps(scenario['scripted_evaluation'])])
    question = Question(skill='python.asyncio', difficulty=3, type='scenario',
                        goal='CPU-bound work inside event loop', text=scenario['question'])
    evaluation = asyncio.run(AnswerEvaluator(provider).evaluate(
        question, scenario['candidate_answer'], Level.MIDDLE, []))
    assert evaluation.status == 'evaluated'
    evidence, misconceptions = collect(question, evaluation.result)
    skill = SkillState(skill=question.skill, target_level=Level.MIDDLE,
                       evidence=evidence, misconceptions=misconceptions,
                       questions_asked=1, primary_questions=1)
    decision = decide(skill, evaluation.result, Limits(), 1, 0, 0, 3)
    assert decision.action == scenario['expected_action']
    assert any(e.type == scenario['expected_evidence_type'] for e in evidence)
    assert all(e.question_id == question.id for e in evidence)
