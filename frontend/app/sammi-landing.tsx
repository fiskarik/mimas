import { ArrowRight, ArrowUpRight, AudioLines, Check, ClipboardList, Mic2 } from 'lucide-react';
import { BrandLogo } from './brand-logo';

const candidateHref = '/?view=candidate';
const employerHref = '/?view=employer';

const steps = [
  { number: '01', title: 'Выберите направление', body: 'Касса, торговый зал, сборка заказов или склад. Начните с той работы, которая вам подходит.' },
  { number: '02', title: 'Ответьте голосом', body: 'MIMAS задаёт вопросы о рабочих ситуациях. Можно объяснить решение своими словами, без длинных анкет.' },
  { number: '03', title: 'Покажите навыки', body: 'После интервью появляется предварительный отчёт по темам, на которые вы действительно ответили.' },
];

const roles = [
  { number: '01', title: 'Продавец-кассир', detail: 'Покупатели · касса · возвраты' },
  { number: '02', title: 'Работник торгового зала', detail: 'Выкладка · ценники · качество' },
  { number: '03', title: 'Сборщик заказов', detail: 'Комплектация · сроки · замены' },
  { number: '04', title: 'Работник склада', detail: 'Приёмка · хранение · безопасность' },
];

function Eyebrow({ number, children }: { number: string; children: React.ReactNode }) {
  return <div className="sammi-eyebrow"><span>{number}</span><i aria-hidden="true" /><span>{children}</span></div>;
}

function ProductPreview({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? 'sammi-product sammi-product--compact' : 'sammi-product'} aria-label="Пример интерфейса MIMAS: голосовое интервью и отчёт по навыкам">
      <div className="sammi-product-top">
        <div className="sammi-product-brand"><span className="sammi-product-mark" aria-hidden="true">m</span><span>MIMAS</span><span className="sammi-product-separator" /><span>Интервью</span></div>
        <span className="sammi-product-badge">Пример сценария</span>
      </div>
      <div className="sammi-product-body">
        <div className="sammi-product-main">
          <div className="sammi-product-meta"><span className="sammi-product-live"><i aria-hidden="true" /> ГОЛОСОВОЕ ИНТЕРВЬЮ</span><span>01 / 04</span></div>
          <h3>Как вы поможете покупателю, если цена на полке и на кассе различается?</h3>
          <div className="sammi-product-divider" />
          <div className="sammi-product-voice"><span className="sammi-product-voice-icon"><AudioLines size={18} strokeWidth={1.7} /></span><span><b>Ваш ответ</b><small>Расскажите, что сделаете сначала и к кому обратитесь.</small></span><span className="sammi-product-waves" aria-hidden="true"><i/><i/><i/><i/><i/><i/><i/></span></div>
          <div className="sammi-product-bottom"><span><Mic2 size={15} /> Ответ голосом</span><span className="sammi-product-round"><ArrowRight size={16} /></span></div>
        </div>
        <aside className="sammi-product-aside">
          <span className="sammi-product-aside-label">ПРОФИЛЬ ПО НАВЫКАМ</span>
          <h4>Что показал кандидат</h4>
          <p>В отчёт попадают только проверенные темы. Выводы можно прочитать вместе с ответами.</p>
          <div className="sammi-product-skill"><span>Работа с покупателем</span><i /></div>
          <div className="sammi-product-skill"><span>Кассовые ситуации</span><i /></div>
          <div className="sammi-product-skill"><span>Порядок действий</span><i /></div>
          <div className="sammi-product-aside-foot"><ClipboardList size={15} /> Предварительный отчёт</div>
        </aside>
      </div>
    </div>
  );
}

export function SammiLanding() {
  return (
    <main className="sammi-landing" id="top">
      <header className="sammi-header">
        <div className="sammi-header-inner">
          <a href="#top" className="sammi-header-logo" aria-label="MIMAS — на главную"><BrandLogo tone="light" width={108}/></a>
          <nav className="sammi-nav" aria-label="Разделы сайта">
            <a href="#how">Как это работает</a><a href="#roles">Направления</a><a href="#for-company">Для компаний</a>
          </nav>
          <a className="sammi-header-cta" href={employerHref}>Кабинет компании <ArrowUpRight size={16}/></a>
          <details className="sammi-mobile-menu"><summary aria-label="Открыть меню"><span/><span/><span/></summary><nav aria-label="Мобильное меню"><a href="#how">Как это работает</a><a href="#roles">Направления</a><a href={candidateHref}>Кандидатам</a><a href={employerHref}>Кабинет компании</a></nav></details>
        </div>
      </header>

      <section className="sammi-hero" aria-labelledby="sammi-title">
        <div className="sammi-silk sammi-silk--hero" aria-hidden="true"><span/><span/><span/></div>
        <div className="sammi-hero-inner">
          <div className="sammi-hero-copy">
            <p className="sammi-kicker"><span className="sammi-kicker-dot"/> НАВЫКИ ВАЖНЕЕ ФОРМАЛЬНОСТЕЙ</p>
            <h1 id="sammi-title">Навыки слышно <em>в ответе.</em></h1>
            <p className="sammi-hero-description">Голосовое AI-интервью для работы в магазине и на складе. Один разговор помогает понять, как человек объясняет решения рабочих ситуаций.</p>
            <div className="sammi-actions">
              <a className="sammi-button sammi-button--cream" href={candidateHref}>Я ищу работу <ArrowUpRight size={18}/></a>
              <a className="sammi-button sammi-button--outline" href={employerHref}>Я ищу сотрудников <ArrowUpRight size={18}/></a>
            </div>
          </div>
          <div className="sammi-hero-visual"><ProductPreview /></div>
        </div>
        <div className="sammi-hero-bottom"><span>MIMAS / 2026</span><span>КАССА · ЗАЛ · ЗАКАЗЫ · СКЛАД</span><a href="#how">Листайте вниз <span aria-hidden="true">↓</span></a></div>
      </section>

      <section className="sammi-thesis" id="how" aria-labelledby="sammi-thesis-title">
        <div className="sammi-content sammi-thesis-inner">
          <Eyebrow number="01 / ПОДХОД">ПРОСТОЙ РАЗГОВОР ВМЕСТО ПОВТОРНЫХ АНКЕТ</Eyebrow>
          <h2 id="sammi-thesis-title">Опыт нельзя уместить <em>в одну строчку</em> резюме.</h2>
          <p>Кандидат отвечает на вопросы о знакомых рабочих ситуациях. Компания видит не только должность, но и то, какие знания человек сумел объяснить.</p>
        </div>
      </section>

      <section className="sammi-flow" aria-labelledby="sammi-flow-title">
        <div className="sammi-content">
          <div className="sammi-flow-heading"><Eyebrow number="02 / ПРОЦЕСС">ТРИ ШАГА</Eyebrow><h2 id="sammi-flow-title">От голоса<br/>к ясной картине.</h2></div>
          <div className="sammi-steps">{steps.map(step => <article className="sammi-step" key={step.number}><span className="sammi-step-number">{step.number}</span><div><h3>{step.title}</h3><p>{step.body}</p></div><span className="sammi-step-arrow" aria-hidden="true">↗</span></article>)}</div>
        </div>
      </section>

      <section className="sammi-product-section" aria-labelledby="sammi-product-title">
        <div className="sammi-content sammi-product-section-inner">
          <div className="sammi-product-intro"><Eyebrow number="03 / ИНТЕРВЬЮ">СИТУАЦИИ ИЗ РАБОЧЕГО ДНЯ</Eyebrow><h2 id="sammi-product-title">Вопросы, в которых узнаётся <em>работа.</em></h2><p>Как помочь покупателю? Что проверить при сборке заказа? Как действовать при расхождении товара? Темы зависят от выбранного направления.</p><a href={candidateHref} className="sammi-text-link">Перейти к вакансиям <ArrowUpRight size={18}/></a></div>
          <div className="sammi-product-showcase"><ProductPreview compact /></div>
        </div>
      </section>

      <section className="sammi-roles" id="roles" aria-labelledby="sammi-roles-title">
        <div className="sammi-content">
          <div className="sammi-roles-heading"><Eyebrow number="04 / НАПРАВЛЕНИЯ">РАБОТА РЯДОМ С ЛЮДЬМИ И ТОВАРОМ</Eyebrow><h2 id="sammi-roles-title">Для тех, кто держит <em>ритм дня.</em></h2></div>
          <div className="sammi-role-list">{roles.map(role => <a className="sammi-role" href={candidateHref} key={role.number}><span className="sammi-role-number">{role.number}</span><strong>{role.title}</strong><span className="sammi-role-detail">{role.detail}</span><span className="sammi-role-icon"><ArrowUpRight size={20}/></span></a>)}</div>
        </div>
      </section>

      <section className="sammi-company" id="for-company" aria-labelledby="sammi-company-title">
        <div className="sammi-company-glow" aria-hidden="true" />
        <div className="sammi-content sammi-company-inner">
          <div><Eyebrow number="05 / КОМПАНИЯМ">НАЙМ НА ОСНОВЕ ОТВЕТОВ</Eyebrow><h2 id="sammi-company-title">Сначала — общие навыки.<br/><em>Потом — ваши задачи.</em></h2></div>
          <div className="sammi-company-copy"><p>Кандидат проходит общее интервью по направлению. Если для вакансии нужны особые знания, компания может добавить свои вопросы. Отчёт показывает ответы и основания предварительной оценки; решение остаётся за работодателем.</p><a className="sammi-button sammi-button--cream" href={employerHref}>Открыть кабинет компании <ArrowUpRight size={18}/></a></div>
        </div>
      </section>

      <section className="sammi-final" aria-labelledby="sammi-final-title"><div className="sammi-content sammi-final-inner"><Eyebrow number="06 / НАЧАТЬ">ОДИН РАЗГОВОР МОЖЕТ РАССКАЗАТЬ БОЛЬШЕ</Eyebrow><h2 id="sammi-final-title">Дайте навыкам <em>прозвучать.</em></h2><div className="sammi-actions"><a className="sammi-button sammi-button--dark" href={candidateHref}>Найти работу <ArrowUpRight size={18}/></a><a className="sammi-button sammi-button--light-outline" href={employerHref}>Найти сотрудников <ArrowUpRight size={18}/></a></div><div className="sammi-final-note"><Check size={15}/> Предварительная оценка помогает разобраться в ответах, но не заменяет решение человека.</div></div></section>

      <footer className="sammi-footer"><div className="sammi-content sammi-footer-top"><a href="#top" aria-label="MIMAS — наверх"><BrandLogo tone="light" width={130}/></a><nav aria-label="Навигация внизу страницы"><a href="#how">Как это работает</a><a href="#roles">Направления</a><a href={candidateHref}>Кандидатам</a><a href={employerHref}>Компаниям</a></nav></div><div className="sammi-content sammi-footer-bottom"><span>MIMAS · голосовое AI-интервью</span><span>Навыки видны в ответах.</span><a href="#top">Наверх ↑</a></div><div className="sammi-footer-wordmark" aria-hidden="true">mimas</div></footer>
    </main>
  );
}
