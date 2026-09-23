"""Apply a validated evaluation to evidence, verification and skill state."""
from ai_core.evidence.service import collect
from ai_core.interview.decision_engine import next_difficulty
from ai_core.interview.events import Contradiction
from ai_core.interview.integrity import verification_outcome
from ai_core.interview.state import Turn
from ai_core.models import Level


def apply_evaluation(state, limits, question, answer, attempt, record):
    skill = state.skills[state.skill_index]
    misconception = next((m for m in skill.misconceptions if m.id == question.misconception_id), None)
    verification = next((v for v in state.verification_history if v.id == question.verification_id), None)
    state.turns.append(Turn(question=question, answer=answer, evaluation=attempt))
    record('evaluation_completed', question_id=question.id, evaluation=attempt.model_dump(mode='json'))
    result = attempt.result
    if result:
        evidence, new_misconceptions = collect(question, result)
        skill.evidence.extend(evidence)
        for item in evidence:
            record('evidence_created', evidence=item.model_dump(mode='json'))
        if misconception:
            outcome = verification_outcome(result)
            if outcome != 'UNCERTAIN':
                misconception.status = 'resolved' if outcome == 'VERIFIED' else 'confirmed'
            misconception.verification_question_id = question.id
            record('misconception_checked', misconception=misconception.model_dump(mode='json'))
        for item in new_misconceptions:
            if not any(m.claim == item.claim for m in skill.misconceptions):
                skill.misconceptions.append(item)
                record('misconception_detected', misconception=item.model_dump(mode='json'))
        skill.difficulty = next_difficulty(skill.difficulty, result)
        for c in result.contradictions:
            if not any(x.question_id == question.id and x.claim == c.claim for x in state.contradictions):
                state.contradictions.append(Contradiction(skill=skill.skill, question_id=question.id, **c.model_dump()))
    if verification:
        verification.outcome = verification_outcome(result)
        verification.evidence_ids = [e.id for e in skill.evidence if e.question_id == question.id]
        if verification.kind == 'integrity':
            signal = next(s for s in state.integrity_signals if s.id == verification.target_id)
            signal.resolved = verification.outcome == 'VERIFIED'
        elif verification.kind == 'knowledge':
            contradiction = next(c for c in state.contradictions if c.id == verification.target_id)
            contradiction.status = {'VERIFIED':'resolved', 'CONTRADICTED':'confirmed'}.get(verification.outcome, 'unresolved')
        record('verification_completed', verification=verification.model_dump(mode='json'))
    update_skill(state, skill, limits, record)


def update_skill(state, skill, limits, record):
    sources = {e.question_id for e in skill.evidence if e.type == 'positive'}
    unresolved = any(m.status != 'resolved' for m in skill.misconceptions) or any(c.skill == skill.skill and c.status != 'resolved' for c in state.contradictions)
    skill.confidence = min(1.0, len(sources) / limits.minimum_evidence_per_skill)
    skill.status = 'VERIFIED' if len(sources) >= limits.minimum_evidence_per_skill and not unresolved else 'IN_PROGRESS'
    successful = [t for t in state.turns if t.question.skill == skill.skill
                  and t.evaluation.result and t.evaluation.result.correctness == 'correct'
                  and t.evaluation.result.depth in ('medium', 'high') and not t.evaluation.result.missing_concepts]
    skill.current_level = (list(Level)[min(min(t.question.difficulty for t in successful)-1, list(Level).index(skill.target_level))]
                           if len({t.question.goal for t in successful}) >= limits.minimum_evidence_per_skill and not unresolved else None)
    record('skill_state_updated', skill=skill.skill, status=skill.status)
