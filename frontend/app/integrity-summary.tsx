import type {IntegrityReport, Question} from './ai-session';

const outcomes:Record<string,string> = {
  VERIFIED:'Понимание подтверждено',
  UNCERTAIN:'Недостаточно оснований',
  CONTRADICTED:'В объяснении подтверждена ошибка',
  PENDING:'Проверка не завершена',
};

export function IntegritySummary({report, questions}:{report:IntegrityReport; questions:Question[]}) {
  return <section className="card ai-start">
    <h2>События и проверки понимания</h2>
    <p className="muted">{report.note}</p>
    {report.events_truncated && <p className="note">Достигнут лимит событий: история наблюдений неполная.</p>}
    {!report.signals.length && <p>Событий для проверки не зафиксировано.</p>}
    {report.signals.map(signal => <article className="ai-evidence" key={signal.id}>
      <strong>{signal.type === 'LARGE_PASTE' ? 'Большая вставка текста' : 'Потеря фокуса окна'}</strong>
      <p>{new Date(signal.timestamp).toLocaleString()} · {signal.resolved
        ? 'Объяснение подтверждено'
        : signal.severity === 'info' ? 'Информационное событие' : 'Понимание по этому событию не подтверждено'}</p>
    </article>)}
    {report.verifications.map(verification => <article className="ai-evidence" key={verification.id}>
      <strong>{verification.kind === 'integrity' ? 'Объяснение ответа'
        : verification.kind === 'knowledge' ? 'Уточнение противоречия' : 'Уточнение ошибочного утверждения'}</strong>
      <p>{questions.find(question => question.id === verification.question_id)?.text}</p>
      <span className="badge">{outcomes[verification.outcome] || verification.outcome}</span>
    </article>)}
  </section>;
}
