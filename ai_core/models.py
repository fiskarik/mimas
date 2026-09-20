"""Shared domain values; the model cannot choose engine transitions."""
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', validate_assignment=True)


class Level(StrEnum):
    BASIC = 'basic'
    JUNIOR = 'junior'
    MIDDLE = 'middle'
    STRONG_MIDDLE = 'strong_middle'
    SENIOR = 'senior'


class QuestionType(StrEnum):
    CONCEPTUAL = 'conceptual'
    SCENARIO = 'scenario'
    PRACTICAL = 'practical'
    DEBUGGING = 'debugging'
    FOLLOW_UP = 'follow_up'
    VERIFICATION = 'verification'
    CODE_REASONING = 'code_reasoning'


class EvidenceType(StrEnum):
    POSITIVE = 'positive'
    NEGATIVE = 'negative'
    UNCERTAIN = 'uncertain'
