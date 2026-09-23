import pytest

from ai_core.evaluation.schemas import EvaluationAttempt, EvaluationResult
from ai_core.interview.schemas import CandidateAnswer, Question
from ai_core.interview.state import Turn
from ai_core.reports.answer_review import review_answer


def make_turn(correctness='correct', depth='high', **extra):
    q=Question(skill='python.core',difficulty=3,type='scenario',goal='Default arguments',text='When is a default evaluated?')
    evidence=[{'type':'negative' if correctness=='incorrect' else 'positive','claim':'Technical finding','quote':'once'}]
    result=EvaluationResult(correctness=correctness,depth=depth,evidence=evidence,
                            follow_up_required=False,recommended_difficulty=3,**extra)
    return Turn(question=q,answer=CandidateAnswer(question_id=q.id,text='once'),
                evaluation=EvaluationAttempt(status='evaluated',attempts=1,result=result))


@pytest.mark.parametrize('correctness,depth,points',[
    ('correct','high',5),('correct','medium',4),('correct','low',3),
    ('partial','high',3),('partial','medium',2),('partial','low',1),('incorrect','low',0)])
def test_explicit_points_rubric(correctness,depth,points):
    report=review_answer(make_turn(correctness,depth))
    assert report['points']==points
    assert report['max_points']==5
    assert report['question_id']
    assert report['reason']


def test_gaps_cap_otherwise_correct_answer_and_remain_visible():
    report=review_answer(make_turn(missing_concepts=['How to avoid shared state']))
    assert report['points']==3
    assert report['missing_concepts']==['How to avoid shared state']


def test_no_answer_and_failures_are_not_zero_points():
    turn=make_turn('insufficient_evidence',response_kind='no_answer')
    assert review_answer(turn)['points'] is None
    turn.evaluation=EvaluationAttempt(status='unavailable',attempts=1,failures=['rate_limit'])
    report=review_answer(turn)
    assert report['points'] is None
    assert report['failures']==['rate_limit']
    assert not report['errors']


def test_error_quote_links_back_to_exact_answer():
    report=review_answer(make_turn('incorrect','low'))
    assert report['errors'][0]['quote'] in report['answer']
    assert report['points']==0


def test_legacy_ungrounded_citation_cannot_be_scored():
    turn=make_turn()
    turn.answer.text='A different answer'
    report=review_answer(turn)
    assert report['points'] is None
    assert not report['strengths']
