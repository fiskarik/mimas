from enum import StrEnum

from ai_core.evaluation.schemas import EvaluationResult
from ai_core.interview.schemas import Limits
from ai_core.interview.state import SkillState
from ai_core.models import Model


class Action(StrEnum):
    VERIFY_KNOWLEDGE = 'VERIFY_KNOWLEDGE'
    VERIFICATION = 'VERIFY_KNOWLEDGE'
    VERIFY_INTEGRITY = 'VERIFY_INTEGRITY'
    FOLLOW_UP = 'FOLLOW_UP'
    ASK_QUESTION = 'ASK_QUESTION'
    NEXT_QUESTION = 'ASK_QUESTION'
    NEXT_SKILL = 'NEXT_SKILL'
    COMPLETE_INTERVIEW = 'COMPLETE_INTERVIEW'
    FINISH = 'COMPLETE_INTERVIEW'


class Decision(Model):
    action: Action
    reason: str
    goal: str = ''
    misconception_id: str | None = None
    target_id: str | None = None


def decide(skill: SkillState, result: EvaluationResult | None, limits: Limits,
           total: int, elapsed: float, follow_ups: int, target_questions: int, state=None) -> Decision:
    if total >= limits.max_questions:
        return Decision(action=Action.FINISH, reason='max_questions')
    if elapsed >= limits.time_budget_seconds:
        return Decision(action=Action.FINISH, reason='time_budget')
    if skill.questions_asked >= limits.max_questions_per_skill:
        return Decision(action=Action.NEXT_SKILL, reason='skill_question_limit')
    if state and follow_ups < limits.max_follow_ups_per_question:
        signal = next((s for s in state.integrity_signals if not s.resolved
                       and s.severity == 'verification_required'
                       and s.verification_count < state.integrity_policy.max_verifications_per_signal
                       and any(t.question.id == s.question_id and t.question.skill == skill.skill for t in state.turns)), None)
        if signal:
            return Decision(action=Action.VERIFY_INTEGRITY, reason='unresolved_large_paste_signal',
                            goal='Объясните ключевую мысль вашего предыдущего ответа своими словами', target_id=signal.id)
        contradiction = next((c for c in state.contradictions if c.skill == skill.skill and c.status == 'unresolved' and not c.checked), None)
        if contradiction:
            return Decision(action=Action.VERIFY_KNOWLEDGE, reason='cross_answer_contradiction',
                            goal='Уточнить противоречие: ' + contradiction.claim, target_id=contradiction.id)
    if result and result.response_kind != 'substantive':
        return Decision(action=Action.NEXT_SKILL if skill.primary_questions >= limits.no_answer_primary_limit else Action.NEXT_QUESTION,
                        reason='no_evidence_try_another_goal')
    if follow_ups < limits.max_follow_ups_per_question:
        pending = next((m for m in skill.misconceptions if m.status == 'unresolved'), None)
        if pending:
            return Decision(action=Action.FOLLOW_UP, reason='unresolved_misconception',
                            goal='Проверить утверждение: ' + pending.claim,
                            misconception_id=pending.id)
        if result and result.follow_up_required:
            return Decision(action=Action.FOLLOW_UP, reason='specific_uncertainty', goal=result.follow_up_goal)
    # Distinct source questions, not number of LLM bullet points.
    sources = {e.question_id for e in skill.evidence if e.type == 'positive'}
    unresolved = any(m.status != 'resolved' for m in skill.misconceptions)
    if len(sources) >= limits.minimum_evidence_per_skill and not unresolved:
        return Decision(action=Action.NEXT_SKILL, reason='minimum_evidence_collected')
    if skill.primary_questions >= target_questions:
        return Decision(action=Action.NEXT_SKILL, reason='planned_coverage_reached')
    return Decision(action=Action.NEXT_QUESTION, reason='insufficient_coverage')


def next_difficulty(current: int, result: EvaluationResult | None) -> int:
    if result is None:
        return current
    if result.correctness == 'correct' and result.depth == 'high' and not result.misconceptions:
        return min(5, current + 1)
    if result.correctness in ('incorrect', 'insufficient_evidence'):
        return max(1, current - 1)
    return current
