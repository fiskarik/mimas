"""Observed events request explanation; they never subtract skill evidence."""
from ai_core.interview.events import IntegritySignal


def observe(state, event):
    kind = None
    if event.type == 'PASTE_DETECTED' and event.size >= state.integrity_policy.large_paste_chars:
        kind = 'LARGE_PASTE'
    elif event.type == 'FOCUS_LOST':
        kind = 'FOCUS_LOST_BEFORE_ANSWER'
    if not kind or any(s.question_id == event.question_id and s.type == kind for s in state.integrity_signals):
        return None
    signal = IntegritySignal(type=kind, question_id=event.question_id,
                             context={'event_id': event.id, 'size': event.size, 'source': 'client_reported'},
                             severity='verification_required' if kind == 'LARGE_PASTE' else 'info')
    state.integrity_signals.append(signal)
    return signal


def verification_outcome(result):
    if not result or result.response_kind != 'substantive':
        return 'UNCERTAIN'
    if result.verification_outcome == 'resolved' and result.correctness == 'correct':
        return 'VERIFIED'
    if result.verification_outcome == 'confirmed' and result.correctness == 'incorrect':
        return 'CONTRADICTED'
    return 'UNCERTAIN'
