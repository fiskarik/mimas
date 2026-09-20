from ai_core.evaluation.schemas import EvaluationResult
from ai_core.evidence.models import Misconception, SkillEvidence
from ai_core.interview.schemas import Question


def collect(question: Question, result: EvaluationResult) -> tuple[list[SkillEvidence], list[Misconception]]:
    source = {'follow_up': 'follow_up', 'verification': 'verification',
              'debugging': 'debugging', 'code_reasoning': 'code_explanation'}.get(question.type, 'answer')
    unique = {(e.type, e.claim, e.quote): e for e in result.evidence}
    evidence = [SkillEvidence(skill=question.skill, source=source, type=e.type,
                              claim=e.claim, quote=e.quote, question_id=question.id)
                for e in unique.values()]
    misconceptions = [Misconception(skill=question.skill, claim=m.claim, quote=m.quote,
                                    question_id=question.id) for m in result.misconceptions]
    return evidence, misconceptions
