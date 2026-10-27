"""Shared profession interviews and consented, evidence-limited candidate rankings."""
import hashlib
import json
import time
from functools import cache
from pathlib import Path

from sqlalchemy import Float, ForeignKey, Integer, Text, select
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base, Database


class Profession(Base):
    __tablename__ = 'professions'
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    description: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    plan_json: Mapped[str] = mapped_column(Text)
    settings_json: Mapped[str] = mapped_column(Text)
    approved_at: Mapped[float] = mapped_column(Float)


class GeneralAssessment(Base):
    __tablename__ = 'general_assessments'
    candidate_id: Mapped[str] = mapped_column(Text, ForeignKey('candidate_profiles.id'), primary_key=True)
    profession_id: Mapped[str] = mapped_column(Text, ForeignKey('professions.id'), primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, ForeignKey('ai_sessions.id'), unique=True)
    share_with_companies: Mapped[int] = mapped_column(Integer, default=0, server_default='0')
    consent_at: Mapped[float] = mapped_column(Float)
    created: Mapped[float] = mapped_column(Float)


# Reviewed retail templates in format v2 (question cards), one file per profession.
# Oral answers show knowledge of situations, not proven on-the-job performance.
_TEMPLATE_DIR = Path(__file__).resolve().parent / 'professions'
_RETAIL_IDS = ('cashier', 'sales_associate', 'order_picker', 'stock_worker')


@cache
def _retail_templates() -> tuple[dict, ...]:
    return tuple(json.loads((_TEMPLATE_DIR / f'{identifier}.json').read_text(encoding='utf-8'))
                 for identifier in _RETAIL_IDS)


# Keep historical plans addressable so completed interviews and existing
# vacancies remain readable; they are not offered as new pilot choices.
_LEGACY_CATALOG = (
    ('welder', 'Сварщик', 'Подготовка, безопасность и контроль сварочных работ', (
        ('safety', 'Безопасность сварочных работ',
         ('Подготовка рабочего места', 'Средства защиты'),
         ('Проверить подготовку безопасного места сварки', 'Проверить выбор средств защиты'),
         ('Что вы проверите на рабочем месте перед началом сварки?',
          'Какие средства защиты и почему нужны при ручной дуговой сварке?'),
         ('Упоминает пожароопасные материалы и ограждение зоны',
          'Объясняет защиту глаз, кожи и дыхания')),
        ('quality', 'Подготовка соединения и контроль шва',
         ('Чтение чертежа', 'Подготовка кромок и контроль дефектов'),
         ('Проверить чтение требований к соединению', 'Проверить объяснение контроля качества'),
         ('Как по чертежу и заданию вы определите, какое соединение нужно выполнить?',
          'Как подготовите детали и по каким признакам проверите готовый шов?'),
         ('Сверяет размеры и тип соединения с заданием',
          'Называет подготовку поверхностей и проверяемые дефекты')),
    )),
    ('electrician', 'Электрик', 'Безопасность и диагностика электрооборудования', (
        ('safety', 'Электробезопасность',
         ('Отключение питания', 'Проверка отсутствия напряжения'),
         ('Проверить порядок безопасной подготовки', 'Проверить подтверждение отсутствия напряжения'),
         ('Как подготовите рабочее место перед ремонтом электроцепи?',
          'Как убедитесь, что на участке нет напряжения перед работой?'),
         ('Называет отключение и предотвращение повторного включения',
          'Упоминает проверенный прибор и безопасный порядок проверки')),
        ('diagnostics', 'Диагностика неисправностей',
         ('Схемы', 'Измерения'),
         ('Проверить последовательность диагностики', 'Проверить выбор измерений'),
         ('Как по схеме локализуете неисправность в цепи?',
          'Какие измерения проведёте и как убедитесь в их безопасности?'),
         ('Сопоставляет схему и фактическое состояние',
          'Обосновывает выбор измерений и безопасную процедуру')),
    )),
    ('fitter', 'Слесарь', 'Подготовка, сборка и контроль механических узлов', (
        ('safety', 'Безопасность слесарных работ',
         ('Исправность инструмента', 'Защита рук и глаз'),
         ('Проверить рабочее место', 'Проверить выбор инструмента'),
         ('Что проверите перед началом слесарных работ?',
          'Как подберёте безопасный инструмент для обработки детали?'),
         ('Упоминает крепление заготовки и исправность инструмента',
          'Обосновывает выбор инструмента и средств защиты')),
        ('assembly', 'Сборка и контроль узла',
         ('Чтение чертежа', 'Допуски и проверка'),
         ('Проверить работу по чертежу', 'Проверить контроль качества сборки'),
         ('Как прочитаете чертёж и подготовите детали к сборке?',
          'Как проверите размеры и работу собранного узла?'),
         ('Сверяет детали и размеры с чертежом',
          'Называет измерение и проверку работоспособности')),
    )),
    ('turner', 'Токарь', 'Безопасность, обработка и контроль размеров', (
        ('safety', 'Безопасность токарной обработки',
         ('Закрепление заготовки', 'Работа со стружкой'),
         ('Проверить подготовку станка', 'Проверить безопасную работу со стружкой'),
         ('Что проверите перед пуском токарного станка?',
          'Как будете удалять стружку и почему именно так?'),
         ('Упоминает закрепление заготовки и инструментов',
          'Исключает удаление стружки руками при работе станка')),
        ('machining', 'Обработка и контроль детали',
         ('Чтение чертежа', 'Измерение размеров'),
         ('Проверить планирование обработки', 'Проверить контроль размеров'),
         ('Как по чертежу выберете порядок обработки детали?',
          'Как и когда измерите размеры готовой детали?'),
         ('Учитывает размеры и допуски из чертежа',
          'Называет подходящий измерительный инструмент')),
    )),
)


# Catalog texts installed by earlier versions. A row that still holds one of them
# was never edited by a reviewer, so a newer catalog version may replace it.
_PRISTINE_FINGERPRINTS = {
    ('cashier', 1): 'a9de1c70d0fe53ba16d6d154ea3f336879f647b02cf0a583a8df3ffe854e5109',
    ('sales_associate', 1): '20989dd805d1a324ad508064da40e2bc6261529c073339716db8496df53d90ed',
    ('order_picker', 1): '28f9a4b84c507f9ae13d4633cc2a938266ea904d2c1ce5e4d469243371a7f735',
    ('stock_worker', 1): '0d55df1b1d3e19284991fa163319a5303ff8c99fdcb93f20f36248303fbd2058',
}


def _fingerprint(row: 'Profession') -> str:
    canonical = json.dumps({'name': row.name, 'description': row.description,
                            'plan': json.loads(row.plan_json), 'settings': json.loads(row.settings_json)},
                           ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


@cache
def _names() -> dict[str, str]:
    return {**{template['id']: template['name'] for template in _retail_templates()},
            **{identifier: name for identifier, name, _, _ in _LEGACY_CATALOG}}


def active_profession_ids() -> tuple[str, ...]:
    return _RETAIL_IDS


_PROFESSION_ALIASES = {
    'кассир': 'cashier',
    'продавец': 'cashier',
    'сотрудник торгового зала': 'sales_associate',
    'продавец-консультант': 'sales_associate',
    'комплектовщик': 'order_picker',
    'комплектовщик заказов': 'order_picker',
    'кладовщик': 'stock_worker',
}


def profession_id_for_name(name: str) -> str | None:
    normalized = name.strip().casefold()
    return _PROFESSION_ALIASES.get(normalized) or next(
        (identifier for identifier, title in _names().items()
         if title.casefold() == normalized), None)


def profession_name_for_id(identifier: str) -> str | None:
    return _names().get(identifier)


def profession_view(row: Profession) -> dict:
    return {'id': row.id, 'name': row.name, 'description': row.description,
            'version': row.version}


def _catalog():
    """Every installable profession: id, name, description, version, plan, settings."""
    from ai_core.interview.planner import CompetencyPlan
    from backend.marketplace import InterviewSettings

    for template in _retail_templates():
        plan = CompetencyPlan.model_validate({
            'role': template['name'], 'version': f"profession-{template['id']}-v{template['version']}",
            'not_assessed': template['not_assessed'], 'skills': template['skills']})
        yield (template['id'], template['name'], template['description'], template['version'],
               plan, InterviewSettings.model_validate(template['settings']))
    for identifier, name, description, groups in _LEGACY_CATALOG:
        skills = []
        for skill_id, title, concepts, goals, questions, criteria in groups:
            skills.append({'id': f'{identifier}.{skill_id}', 'name': title,
                           'concepts': list(concepts), 'goals': list(goals),
                           'questions': list(questions), 'evaluation_criteria': list(criteria),
                           'target_questions': 2})
        plan = CompetencyPlan.model_validate({'role': name,
                                              'version': f'profession-{identifier}-v1',
                                              'skills': skills})
        yield (identifier, name, description, 1, plan,
               InterviewSettings(max_questions=4, max_follow_ups=0, duration_minutes=10))


def ensure_professions(database: Database) -> None:
    """Install reviewed pilot plans after migrations; never replace edited rows.

    A newer catalog version replaces a row only while it still holds the exact
    text of an earlier catalog version. Started interviews keep their snapshot.
    """
    with database.session(write=True) as db:
        for identifier, name, description, version, plan, settings in _catalog():
            content = {'name': name, 'description': description, 'version': version,
                       'plan_json': plan.model_dump_json(), 'settings_json': settings.model_dump_json(),
                       'approved_at': time.time()}
            row = db.get(Profession, identifier)
            if row is None:
                db.add(Profession(id=identifier, **content))
            elif (row.version < version
                  and _PRISTINE_FINGERPRINTS.get((identifier, row.version)) == _fingerprint(row)):
                for key, value in content.items():
                    setattr(row, key, value)


def provisional_rating(report: dict) -> dict:
    """Average only answers with verified citations; never treat unscored as zero.

    Template v2 reports score each question once (its best answer, red flags applied).
    """
    cards = report.get('card_scores')
    if cards is not None:
        points = [item['points'] for item in cards
                  if item.get('status') == 'assessed' and isinstance(item.get('points'), int)]
        total = len(cards)
    else:
        reviewed = report.get('answer_reviews') or []
        points = [item['points'] for item in reviewed
                  if item.get('status') == 'assessed' and isinstance(item.get('points'), int)]
        total = len(reviewed)
    return {'score': round(sum(points) / len(points), 1) if points else None,
            'assessed_answers': len(points), 'total_answers': total,
            'max_score': 5, 'provisional': True}
