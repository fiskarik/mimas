from pathlib import Path

from pydantic import Field, model_validator

from ai_core.models import Model, Text


class Competency(Model):
    id: Text
    name: Text
    concepts: list[Text] = Field(min_length=1)
    goals: list[Text] = Field(min_length=1)
    questions: list[Text] = Field(min_length=1)
    evaluation_criteria: list[Text] = Field(default_factory=list)
    target_questions: int = Field(ge=1, le=5)

    @model_validator(mode='after')
    def paired_goals(self):
        if len(self.goals) != len(self.questions):
            raise ValueError('Each goal requires a reviewed fallback question')
        return self


class CompetencyPlan(Model):
    role: Text
    version: Text
    skills: list[Competency] = Field(min_length=1)

    @model_validator(mode='after')
    def unique_skills(self):
        if len({s.id for s in self.skills}) != len(self.skills):
            raise ValueError('Duplicate skill')
        return self


def load_plan() -> CompetencyPlan:
    path = Path(__file__).resolve().parents[1] / 'competencies' / 'python_backend.json'
    return CompetencyPlan.model_validate_json(path.read_text(encoding='utf-8'))
