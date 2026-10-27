from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ai_core.models import Model, Text

CardType = Literal['situational', 'behavioral', 'knowledge']


class Anchors(Model):
    """Observable answers for points 5, 3 and 1; 4 and 2 lie between them."""
    strong: Text
    acceptable: Text
    weak: Text


class QuestionCard(Model):
    """Template v2: one reviewed question with its scoring rules."""
    goal: Text
    type: CardType
    question: Text
    # Equivalent wordings of the same situation; one is chosen per interview.
    variants: list[Text] = Field(default_factory=list, max_length=4)
    # The only follow-up questions the engine may ask for this card.
    probes: list[Text] = Field(default_factory=list, max_length=3)
    anchors: Anchors
    # Unacceptable actions: they cap the points and are shown to the employer.
    red_flags: list[Text] = Field(default_factory=list, max_length=4)
    not_assessed: list[Text] = Field(default_factory=list, max_length=6)
    source: Text | None = None

    @model_validator(mode='after')
    def spoken_wordings(self):
        wordings = [self.question, *self.variants]
        if len(set(wordings)) != len(wordings):
            raise ValueError('Question variants must differ')
        if any(len(text) > 600 for text in [*wordings, *self.probes]):
            raise ValueError('Spoken questions must not exceed 600 characters')
        return self

    def evaluator_view(self, plan_not_assessed: list[str]) -> dict:
        """Card as the evaluator sees it; list positions are the indices it returns."""
        return {'type': self.type, 'goal': self.goal,
                'anchors': {'strong': self.anchors.strong, 'acceptable': self.anchors.acceptable,
                            'weak': self.anchors.weak},
                'red_flags': list(self.red_flags), 'probes': list(self.probes),
                'not_assessed': [*plan_not_assessed, *self.not_assessed]}


def _card_value(card, *path):
    for name in path:
        card = card.get(name) if isinstance(card, dict) else getattr(card, name, None)
    return card


class Competency(Model):
    id: Text
    name: Text
    concepts: list[Text] = Field(min_length=1)
    goals: list[Text] = Field(min_length=1)
    questions: list[Text] = Field(min_length=1)
    evaluation_criteria: list[Text] = Field(default_factory=list)
    target_questions: int = Field(ge=1, le=5)
    cards: list[QuestionCard] = Field(default_factory=list, max_length=5)

    @model_validator(mode='before')
    @classmethod
    def derive_from_cards(cls, data):
        # A v2 competency is written as cards only; v1 fields stay derived so
        # existing readers (vacancy prompts, editors, reports) keep working.
        if not isinstance(data, dict) or not data.get('cards'):
            return data
        cards = data['cards']
        data = dict(data)
        data.setdefault('goals', [_card_value(card, 'goal') for card in cards])
        data.setdefault('questions', [_card_value(card, 'question') for card in cards])
        if not data.get('evaluation_criteria'):
            data['evaluation_criteria'] = [_card_value(card, 'anchors', 'strong') for card in cards]
        data.setdefault('target_questions', len(cards))
        return data

    @model_validator(mode='after')
    def paired_goals(self):
        if len(self.goals) != len(self.questions):
            raise ValueError('Each goal requires a reviewed fallback question')
        if self.cards:
            if ([card.goal for card in self.cards] != self.goals
                    or [card.question for card in self.cards] != self.questions):
                raise ValueError('Card goals and questions must match the competency')
            if self.target_questions > len(self.cards):
                raise ValueError('Each planned question requires a card')
        return self


class CompetencyPlan(Model):
    role: Text
    version: Text
    skills: list[Competency] = Field(min_length=1)
    # Template v2: never part of a score, for every question of the plan.
    not_assessed: list[Text] = Field(default_factory=list, max_length=8)

    @model_validator(mode='after')
    def unique_skills(self):
        if len({s.id for s in self.skills}) != len(self.skills):
            raise ValueError('Duplicate skill')
        if len({bool(s.cards) for s in self.skills}) > 1:
            raise ValueError('Either every competency or none uses question cards')
        return self

    @property
    def uses_cards(self) -> bool:
        return bool(self.skills[0].cards)

    def card_for(self, skill: str, card_index: int | None) -> QuestionCard | None:
        if card_index is None:
            return None
        competency = next((s for s in self.skills if s.id == skill), None)
        if competency is None or card_index >= len(competency.cards):
            return None
        return competency.cards[card_index]


def plan_json_schema(*, cards: bool = False) -> dict:
    """Schema for AI drafts; vacancy drafts stay in the v1 format for now."""
    schema = CompetencyPlan.model_json_schema()
    if not cards:
        schema['properties'].pop('not_assessed', None)
        schema['$defs']['Competency']['properties'].pop('cards', None)
        for name in ('QuestionCard', 'Anchors'):
            schema['$defs'].pop(name, None)
    return schema


def load_plan() -> CompetencyPlan:
    path = Path(__file__).resolve().parents[1] / 'competencies' / 'python_backend.json'
    return CompetencyPlan.model_validate_json(path.read_text(encoding='utf-8'))
