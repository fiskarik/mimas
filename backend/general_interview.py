"""Shared profession interviews and consented, evidence-limited candidate rankings."""
import json
import time

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


# Shared questions are reviewed starter content for the pilot. An oral answer
# assesses decisions and knowledge, not practical qualification or work permit.
_CATALOG = (
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


def profession_id_for_name(name: str) -> str | None:
    normalized = name.strip().casefold()
    return next((identifier for identifier, title, _, _ in _CATALOG
                 if title.casefold() == normalized), None)


def profession_view(row: Profession) -> dict:
    return {'id': row.id, 'name': row.name, 'description': row.description,
            'version': row.version}


def ensure_professions(database: Database) -> None:
    """Install reviewed pilot plans after migrations; never replace edited rows."""
    from ai_core.interview.planner import CompetencyPlan
    from backend.marketplace import InterviewSettings

    with database.session(write=True) as db:
        for identifier, name, description, groups in _CATALOG:
            if db.get(Profession, identifier):
                continue
            skills = []
            for skill_id, title, concepts, goals, questions, criteria in groups:
                skills.append({'id': f'{identifier}.{skill_id}', 'name': title,
                               'concepts': list(concepts), 'goals': list(goals),
                               'questions': list(questions), 'evaluation_criteria': list(criteria),
                               'target_questions': 2})
            plan = CompetencyPlan.model_validate({'role': name,
                                                  'version': f'profession-{identifier}-v1',
                                                  'skills': skills})
            settings = InterviewSettings(max_questions=4, max_follow_ups=0,
                                         duration_minutes=10)
            db.add(Profession(id=identifier, name=name, description=description,
                              version=1, plan_json=plan.model_dump_json(),
                              settings_json=settings.model_dump_json(), approved_at=time.time()))


def provisional_rating(report: dict) -> dict:
    """Average only answers with verified citations; never treat unscored as zero."""
    reviewed = report.get('answer_reviews') or []
    points = [item['points'] for item in reviewed
              if item.get('status') == 'assessed' and isinstance(item.get('points'), int)]
    return {'score': round(sum(points) / len(points), 1) if points else None,
            'assessed_answers': len(points), 'total_answers': len(reviewed),
            'max_score': 5, 'provisional': True}
