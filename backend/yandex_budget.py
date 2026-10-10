"""PostgreSQL-backed, process-safe estimated Yandex AI spending ledger.

The ledger reserves conservative amounts before paid requests and records
measured or estimated usage afterwards. Yandex billing remains authoritative.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_UP
import json
import os
import time
from uuid import uuid4

from sqlalchemy import ForeignKey, Numeric, String, Text, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


RUB = Decimal('0.0001')


class BudgetExceeded(Exception):
    pass


class YandexBudgetMonth(Base):
    __tablename__ = 'yandex_budget_months'

    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    spent_rub: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0)
    reserved_rub: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False, default=0)


class YandexCostEntry(Base):
    __tablename__ = 'yandex_cost_entries'

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    month: Mapped[str] = mapped_column(String(7), ForeignKey('yandex_budget_months.month'), index=True)
    service: Mapped[str] = mapped_column(String(40))
    operation: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), index=True)
    reserved_rub: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    charged_rub: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[float] = mapped_column(nullable=False)
    expires_at: Mapped[float] = mapped_column(nullable=False)


def _rub(value) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(RUB, rounding=ROUND_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError('Invalid ruble estimate') from exc
    if not result.is_finite() or result < 0:
        raise ValueError('Invalid ruble estimate')
    return result


def current_month() -> str:
    # Group usage by Moscow calendar month.
    return datetime.now(timezone(timedelta(hours=3))).strftime('%Y-%m')


class YandexBudget:
    """Reserve/settle atomically across API workers sharing PostgreSQL.

    Database is the existing backend.database.Database instance. Alembic
    creates the schema; no create_all is performed here.
    """

    def __init__(self, database, *, limit_rub=None,
                 reservation_ttl_seconds=1800):
        self.database = database
        configured = os.getenv('MIMAS_AI_MONTHLY_LIMIT_RUB', '').strip()
        # An unset or zero limit disables MIMAS's spending cap while retaining
        # reservation and usage accounting. A positive value opts back in.
        configured_limit = _rub(configured) if configured else Decimal('0')
        limits = [value for value in (_rub(limit_rub) if limit_rub is not None else None,
                                      configured_limit) if value is not None and value > 0]
        self.limit_rub = min(limits) if limits else None
        self.reservation_ttl_seconds = reservation_ttl_seconds

    def _month_row(self, session, month: str):
        dialect = self.database.engine.dialect.name
        values = {'month': month, 'spent_rub': 0, 'reserved_rub': 0}
        if dialect == 'postgresql':
            stmt = pg_insert(YandexBudgetMonth).values(**values).on_conflict_do_nothing(index_elements=['month'])
        elif dialect == 'sqlite':
            # Only for isolated tests; the application itself is PostgreSQL-only.
            stmt = sqlite_insert(YandexBudgetMonth).values(**values).on_conflict_do_nothing(index_elements=['month'])
        else:
            raise RuntimeError('Yandex budget requires PostgreSQL')
        session.execute(stmt)
        return session.scalar(select(YandexBudgetMonth).where(YandexBudgetMonth.month == month).with_for_update())

    def _expire(self, session, row: YandexBudgetMonth, now: float):
        stale = session.scalars(select(YandexCostEntry).where(
            YandexCostEntry.month == row.month,
            YandexCostEntry.status == 'reserved',
            YandexCostEntry.expires_at < now,
        ).with_for_update()).all()
        for entry in stale:
            # A crashed worker may have sent a paid request before it died.
            # Never restore that amount to the available monthly budget.
            row.reserved_rub -= entry.reserved_rub
            row.spent_rub += entry.reserved_rub
            entry.charged_rub = entry.reserved_rub
            entry.usage_json = json.dumps({'uncertain': True, 'reservation_expired': True})
            entry.status = 'settled'

    def reserve(self, service: str, operation: str, estimate_rub) -> str:
        if not service or not operation or len(service) > 40 or len(operation) > 80:
            raise ValueError('Invalid Yandex cost labels')
        estimate = _rub(estimate_rub)
        month, now, entry_id = current_month(), time.time(), uuid4().hex
        exceeded = False
        with self.database.session(write=True) as session:
            row = self._month_row(session, month)
            self._expire(session, row, now)
            exceeded = (self.limit_rub is not None and
                        row.spent_rub + row.reserved_rub + estimate > self.limit_rub)
            if not exceeded:
                row.reserved_rub += estimate
                session.add(YandexCostEntry(
                    id=entry_id, month=month, service=service, operation=operation,
                    status='reserved', reserved_rub=estimate, charged_rub=None,
                    created_at=now, expires_at=now + self.reservation_ttl_seconds,
                ))
        # Expired uncertain requests must commit as spent even when a new
        # reservation cannot be admitted.
        if exceeded:
            raise BudgetExceeded('Месячный лимит AI MIMAS исчерпан.')
        return entry_id

    def settle(self, reservation_id: str, actual_rub, usage: dict | None = None):
        actual = _rub(actual_rub)
        with self.database.session(write=True) as session:
            reference = session.get(YandexCostEntry, reservation_id)
            if reference is None:
                raise ValueError('Unknown Yandex reservation')
            row = session.scalar(select(YandexBudgetMonth).where(YandexBudgetMonth.month == reference.month).with_for_update())
            entry = session.scalar(select(YandexCostEntry).where(YandexCostEntry.id == reservation_id).with_for_update())
            if entry.status == 'settled':
                return
            if entry.status == 'released':
                raise ValueError('Released Yandex reservation cannot be settled')
            if entry.status == 'reserved':
                row.reserved_rub -= entry.reserved_rub
            row.spent_rub += actual
            entry.charged_rub = actual
            entry.usage_json = json.dumps(usage, ensure_ascii=False) if usage else None
            entry.status = 'settled'

    def release(self, reservation_id: str):
        with self.database.session(write=True) as session:
            reference = session.get(YandexCostEntry, reservation_id)
            if reference is None:
                return
            row = session.scalar(select(YandexBudgetMonth).where(YandexBudgetMonth.month == reference.month).with_for_update())
            entry = session.scalar(select(YandexCostEntry).where(YandexCostEntry.id == reservation_id).with_for_update())
            if entry.status != 'reserved':
                return
            row.reserved_rub -= entry.reserved_rub
            entry.status = 'released'

    def status(self) -> dict:
        month = current_month()
        with self.database.session() as session:
            row = session.get(YandexBudgetMonth, month)
            return {'month': month,
                    'limit_rub': str(self.limit_rub) if self.limit_rub is not None else None,
                    'spent_rub': str(row.spent_rub if row else Decimal('0')),
                    'reserved_rub': str(row.reserved_rub if row else Decimal('0'))}
