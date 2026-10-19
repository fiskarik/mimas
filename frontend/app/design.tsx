'use client';

import {ArrowDown, ArrowRight, ArrowUp, ArrowUpRight, Check, ShieldCheck, Video} from 'lucide-react';
import {InterviewOrb, MotionVideo} from './motion';
import {BrandLogo} from './brand-logo';
import {CursorDots} from './cursor-dots';
import {LandingInterviewPreview, LandingProcess, LandingRoles, LandingSkillReport} from './landing-product';

export type OrbState = 'idle' | 'speaking' | 'listening' | 'thinking' | 'saved';
export const stateNames: Record<OrbState, string> = {
  idle: 'Готов к диалогу',
  speaking: 'Озвучиваю вопрос',
  listening: 'Слушаю ответ',
  thinking: 'Обрабатываю ответ',
  saved: 'Ответ сохранён',
};

export const GlassOrb = InterviewOrb;

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
            <p>Продавец-кассир, работник торгового зала, сборщик заказов или работник склада — каждый может рассказать о своём опыте. MIMAS задаёт вопросы о знакомых задачах и сохраняет ответы для человека, который принимает решение.</p>
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

      <LandingInterviewPreview/>
      <LandingProcess/>
      <LandingSkillReport onCompany={onCompany}/>

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

      <LandingRoles/>

      <section className="landing-cta">
        <div className="cta-orbit" aria-hidden="true"><PixelMark/></div>
        <span className="small-kicker"><BrandLogo tone="dark" width={52}/> ЗНАНИЯ ВАЖНО УСЛЫШАТЬ</span>
        <h2>Всё начинается<br/>с <span>разговора.</span></h2>
        <a className="primary" href="/?view=candidate">Найти вакансию <ArrowUpRight size={19}/></a>
        <button className="hero-secondary" onClick={onCompany}>Разместить вакансию <ArrowRight size={17}/></button>
      </section>
      <CursorDots/>
    </main>
    <footer className="landing-footer">
      <div className="footer-top">
        <a href="/" className="brand-word" aria-label="mimas — главная"><BrandLogo tone="light" width="clamp(130px, 14vw, 175px)"/></a>
        <p>Голосовой разговор о рабочих задачах.<br/>Решение остаётся за человеком.</p>
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
