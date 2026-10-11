'use client';

import {ArrowDown, ArrowRight, ArrowUp, ArrowUpRight, Check, ClipboardCheck, Mic, ShieldCheck, Video} from 'lucide-react';
import {IntelligenceSection, InterviewOrb, MotionVideo} from './motion';
import {BrandLogo} from './brand-logo';

export type OrbState = 'idle' | 'speaking' | 'listening' | 'thinking' | 'saved';
export const stateNames: Record<OrbState, string> = {
  idle: 'Готов к диалогу',
  speaking: 'Озвучиваю вопрос',
  listening: 'Слушаю ответ',
  thinking: 'Обрабатываю ответ',
  saved: 'Ответ сохранён',
};

export const GlassOrb = InterviewOrb;

const interviewSteps = [
  {
    number: '01',
    icon: <Mic/>,
    title: 'Расскажите',
    text: 'Вопросы по профессии и рабочим ситуациям. Отвечайте голосом и объясняйте свой подход.',
    label: 'ГОЛОСОВОЙ ДИАЛОГ',
  },
  {
    number: '02',
    icon: <ClipboardCheck/>,
    title: 'Разберите ситуацию',
    text: 'Например, сварщику предложат объяснить подготовку соединения и действия при дефекте шва.',
    label: 'ПРОФЕССИОНАЛЬНЫЕ ЗНАНИЯ',
  },
  {
    number: '03',
    icon: <ShieldCheck/>,
    title: 'Изучите отчёт',
    text: 'В отчёте сохраняются ответы и основания оценки. Решение о найме принимает компания.',
    label: 'ПРОЗРАЧНЫЙ РЕЗУЛЬТАТ',
  },
];

const sampleSkills = [
  {skill: 'Подготовка соединения', status: 'Подход описан', text: 'Объяснил порядок очистки кромок перед сваркой.', bars: 6},
  {skill: 'Контроль шва', status: 'Нужно уточнить', text: 'Упомянул осмотр, но не раскрыл признаки дефектов.', bars: 3},
  {skill: 'Практический допуск', status: 'Не проверялся', text: 'Устный ответ не подтверждает практический навык или допуск.', bars: 0},
];

export function Landing({onCompany}: {onCompany: () => void}) {
  return <div className="landing" id="top">
    <a className="skip-link" href="#main-content">Перейти к содержимому</a>
    <header className="landing-nav">
      <a href="/" className="brand-word" aria-label="mimas — главная"><BrandLogo tone="light" width="clamp(108px, 12vw, 155px)"/></a>
      <nav aria-label="Навигация">
        <a href="#how"><PixelMark/>Как работает</a>
        <a href="#evidence"><PixelMark variant="cross"/>Отчёт</a>
        <a href="#integrity"><PixelMark variant="steps"/>Правила</a>
      </nav>
      <button className="nav-enter" onClick={onCompany}>Кабинет компании <ArrowUpRight size={16}/></button>
    </header>
    <main id="main-content">
      <section className="landing-hero" aria-labelledby="hero-title">
        <div className="hero-surface" aria-hidden="true"><MotionVideo src="/media/mimas-fluid.mp4" poster="/media/mimas-fluid-poster.webp"/></div>
        <div className="hero-topline"><BrandLogo tone="light" width="clamp(70px, 9vw, 105px)"/><span>голосовое AI-интервью</span></div>
        <div className="hero-copy">
          <h1 id="hero-title">За каждым <span className="hero-lemon"><PixelMark/>навыком</span><br/>стоит <span className="hero-mint"><PixelMark variant="steps"/>человек.</span></h1>
          <div className="hero-bottom">
            <p>Сварщик, электрик, слесарь или токарь — каждый может рассказать о своём опыте. MIMAS задаёт вопросы по вакансии и сохраняет объяснения для человека, который принимает решение.</p>
            <div className="hero-actions">
              <a className="primary" href="/?view=candidate">Найти вакансию <ArrowUpRight size={18}/></a>
              <button className="hero-company-cta" onClick={onCompany}>Открыть кабинет компании <ArrowUpRight size={17}/></button>
            </div>
          </div>
        </div>
        <div className="hero-footer">
          <a className="hero-scroll" href="#how" aria-label="Перейти к описанию процесса"><ArrowDown size={18}/></a>
        </div>
      </section>

      <section className="landing-manifesto" aria-labelledby="manifesto-title">
        <h2 id="manifesto-title">Меньше догадок.<br/><span>Больше понимания.</span></h2>
        <p>Резюме перечислит опыт. Разговор поможет понять, как кандидат рассуждает<br/>о знакомых рабочих задачах. Практические умения проверяются отдельно.</p>
        <a className="manifesto-link" href="/?view=candidate">Смотреть вакансии <ArrowUpRight size={18}/></a>
      </section>

      <IntelligenceSection/>

      <section className="journey-section" id="how">
        <div className="section-intro">
          <span className="small-kicker"><BrandLogo tone="dark" width={52}/> 01 / ПРОЦЕСС</span>
          <h2>Одна вакансия.<br/><span>Предметный разговор.</span></h2>
          <p>Компания готовит вопросы, кандидат отвечает голосом, обе стороны видят результат.</p>
        </div>
        <div className="journey-grid">{interviewSteps.map(item =>
          <article key={item.number}>
            <div className="journey-top"><span>{item.number} /</span>{item.icon}</div>
            <div className={'journey-visual visual-' + item.number} aria-hidden="true">
              {item.number === '01'
                ? <div className="signal-wave">{Array.from({length: 25}, (_, i) => <i key={i} style={{height: (16 + Math.round(Math.abs(Math.sin(i * 1.7)) * (52 - Math.abs(12-i)*3))) + 'px'}}/>)}</div>
                : item.number === '02'
                  ? <div className="scenario-fragment"><span>Ситуация</span><strong>Как подготовить кромки к сварке?</strong><small>Объясните порядок действий.</small></div>
                  : <div className="signal-result"><PixelMark/><span>Ответ сохранён<small>Разбор · запись · уточнения</small></span><Check size={18}/></div>}
            </div>
            <span className="journey-label">{item.label}</span>
            <h3>{item.title}</h3>
            <p>{item.text}</p>
          </article>)}</div>
      </section>

      <section className="evidence-section" id="evidence">
        <div className="evidence-copy">
          <span className="small-kicker"><BrandLogo tone="light" width={52}/> 02 / РЕЗУЛЬТАТ</span>
          <h2>За оценкой<br/>есть <em>ответ.</em></h2>
          <p>Прочитайте слова кандидата и посмотрите запись. Отчёт показывает, что удалось выяснить в разговоре и что осталось проверить на практике.</p>
          <button className="hero-secondary" onClick={onCompany}>Открыть кабинет компании <ArrowUpRight size={18}/></button>
          <span className="concept-caption">Пример оформления отчёта.<br/>Не результат реального кандидата.</span>
        </div>
        <div className="evidence-sheet">
          <div className="sheet-top"><span><PixelMark/> РАЗБОР ОТВЕТОВ</span><span className="sample-badge">Образец</span></div>
          <h3>Сварщик</h3><p>Выводы ограничены устными ответами</p>
          {sampleSkills.map(item => <div className="skill-example" key={item.skill}>
            <div><strong>{item.skill}</strong><span>{item.status}</span></div>
            <div className="skill-bars" aria-hidden="true">{Array.from({length: 12}, (_, i) => <i className={i < item.bars * 1.5 ? 'filled' : ''} key={i}/>)}</div>
            <p>{item.text}</p>
          </div>)}
          <div className="sheet-foot"><ShieldCheck size={16}/> Решение о найме принимает человек <ArrowUpRight size={16}/></div>
        </div>
      </section>

      <section className="integrity-section" id="integrity">
        <div>
          <span className="small-kicker"><BrandLogo tone="dark" width={52}/> 03 / ПРОЗРАЧНОСТЬ</span>
          <h2>Понятные правила.<br/><span>Уважение к человеку.</span></h2>
          <p className="integrity-caption">Предупреждения не означают автоматического отказа.</p>
        </div>
        <div className="integrity-description">
          <p>С согласия кандидата MIMAS сохраняет запись интервью. События ухода со страницы и другие наблюдения рассматриваются в контексте ответа, а решение остаётся за компанией.</p>
          <div className="availability">
            <span><Video size={19}/> Запись камеры и голоса <Check size={16}/></span>
            <span><ShieldCheck size={19}/> События вкладки и вставки <Check size={16}/></span>
            <span className="future">Расширение браузера для известных вкладок — по желанию</span>
          </div>
        </div>
      </section>

      <section className="landing-cta">
        <div className="cta-orbit" aria-hidden="true"><PixelMark/></div>
        <span className="small-kicker"><BrandLogo tone="dark" width={52}/> ЗНАНИЯ ВАЖНО УСЛЫШАТЬ</span>
        <h2>Всё начинается<br/>с <span>разговора.</span></h2>
        <a className="primary" href="/?view=candidate">Найти вакансию <ArrowUpRight size={19}/></a>
        <button className="hero-secondary" onClick={onCompany}>Разместить вакансию <ArrowRight size={17}/></button>
      </section>
    </main>
    <footer className="landing-footer">
      <div className="footer-top">
        <a href="/" className="brand-word" aria-label="mimas — главная"><BrandLogo tone="light" width="clamp(130px, 14vw, 175px)"/></a>
        <p>Голосовой разговор о профессии.<br/>Решение остаётся за человеком.</p>
        <nav aria-label="Навигация в подвале"><a href="#how">Процесс</a><a href="#evidence">Отчёт</a><a href="#integrity">Правила</a></nav>
        <button className="footer-enter" onClick={onCompany}>Кабинет компании <ArrowUpRight size={18}/></button>
      </div>
    </footer>
    <a className="back-to-top" href="#top" aria-label="Наверх"><ArrowUp size={20}/></a>
  </div>;
}

function PixelMark({variant = 'diamond'}: {variant?: 'diamond' | 'cross' | 'steps'}) {
  return <span className={'pixel-mark pixel-' + variant} aria-hidden="true">{Array.from({length: 9}, (_, i) => <i key={i}/>)}</span>;
}
