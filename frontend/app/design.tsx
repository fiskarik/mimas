'use client';

import {useEffect, useRef, useState} from 'react';
import {ArrowDown, ArrowRight, ArrowUpRight, Check, Code2, Mic, ShieldCheck, Video, X} from 'lucide-react';
import {IntelligenceSection, InterviewOrb, MotionToggle, MotionVideo} from './motion';

export type OrbState = 'idle' | 'speaking' | 'listening' | 'thinking' | 'saved';
export const stateNames: Record<OrbState, string> = {idle: 'Готов к диалогу', speaking: 'Озвучиваю вопрос', listening: 'Слушаю ответ', thinking: 'Обрабатываю ответ', saved: 'Ответ сохранён'};

// Shared video sphere supplied for mimas.
export const GlassOrb = InterviewOrb;

export function Landing({onCompany}: {onCompany: () => void}) {
  const returnFocus = useRef<HTMLElement | null>(null);
  const [audience, setAudience] = useState<'company' | 'candidate'>('company');
  const [preview, setPreview] = useState(false);
  useEffect(() => {
    if (!preview) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {document.body.style.overflow = previousOverflow; returnFocus.current?.focus();};
  }, [preview]);
  const [state, setState] = useState<OrbState>('idle');
  const [answer, setAnswer] = useState('');
  const [step, setStep] = useState(0);
  const [previewError, setPreviewError] = useState('');
  const questions = ['Почему изменяемый аргумент по умолчанию может привести к ошибкам?', 'Что произойдёт с event loop при выполнении долгой CPU-bound функции?', 'В каких случаях индекс ускоряет SQL-запрос?'];
  return <div className="landing">
    <a className="skip-link" href="#main-content">Перейти к содержимому</a>
    <header className="landing-nav">
      <a href="/" className="brand-word" aria-label="mimas — главная"><PixelMark/>mimas</a>
      <nav aria-label="Навигация"><a href="#how"><PixelMark/>Процесс</a><a href="#evidence"><PixelMark variant="cross"/>Результат</a><a href="#integrity"><PixelMark variant="steps"/>Прокторинг</a></nav>
      <button className="nav-enter" onClick={onCompany}>В кабинет <ArrowUpRight size={16}/></button>
    </header>
    <main id="main-content">
      <section className="landing-hero" aria-labelledby="hero-title">
        <div className="hero-surface" aria-hidden="true"><MotionVideo src="/media/mimas-fluid.mp4" poster="/media/mimas-fluid-poster.webp"/></div>
        <div className="hero-topline"><span>ИНТЕЛЛЕКТ В ОСНОВЕ ДИАЛОГА</span><MotionToggle/></div>
        <div className="hero-copy">
          <div className="small-kicker"><span/> AI · ТЕХНИЧЕСКИЕ ИНТЕРВЬЮ</div>
          <h1 id="hero-title">За каждым <span className="hero-lemon"><PixelMark/>навыком</span><br/>стоит <span className="hero-mint"><PixelMark variant="steps"/>человек.</span></h1>
          <div className="hero-bottom">
            <p aria-live="polite">{audience === 'company' ? <>Узнайте, как думает ваш следующий разработчик.<br/>AI-интервью, код и доказательства навыков — вместе.</> : <>Покажите, как вы думаете и решаете задачи.<br/>Ваши знания, ваш подход, ваш следующий шаг.</>}</p>
            <div className="hero-actions"><button className="primary" onClick={e => {returnFocus.current = e.currentTarget; setPreview(true);}}>Посмотреть демо <ArrowUpRight size={18}/></button>{audience === 'company' ? <button className="hero-secondary" onClick={onCompany}>Пригласить кандидата <ArrowRight size={17}/></button> : <a className="hero-secondary" href="/?view=ai">Попробовать AI <ArrowRight size={17}/></a>}</div>
          </div>
        </div>
        <div className="hero-footer"><span className="hero-footnote">НАВЫКИ. КОНТЕКСТ. ДОВЕРИЕ.</span><div className="audience-switch" role="group" aria-label="Для кого mimas"><button aria-pressed={audience === 'company'} onClick={() => setAudience('company')}><PixelMark/>Для компании</button><button aria-pressed={audience === 'candidate'} onClick={() => setAudience('candidate')}><PixelMark variant="steps"/>Для кандидата</button></div><a className="hero-scroll" href="#how" aria-label="Перейти к сценарию"><ArrowDown size={18}/></a></div>
      </section>

      <section className="landing-manifesto" aria-labelledby="manifesto-title"><span className="small-kicker"><PixelMark/> ЧЕЛОВЕК + ТЕХНОЛОГИЯ</span><h2 id="manifesto-title">Меньше догадок.<br/><span>Больше понимания.</span></h2><p>Резюме расскажет об опыте. Диалог покажет мышление.<br/>Соединяем вопросы, практику и контекст, чтобы вы увидели главное.</p><a className="manifesto-link" href="/?view=ai">Познакомиться с AI-интервью <ArrowUpRight size={18}/></a></section>

      <IntelligenceSection/>

      <section className="journey-section" id="how"><div className="section-intro"><span className="small-kicker"><PixelMark/> 01 / ПРОЦЕСС</span><h2>Один диалог.<br/><span>Больше контекста.</span></h2><p>От первого вопроса до взвешенного решения. Каждый этап добавляет ясности.</p></div><div className="journey-grid">{[{n:'01',icon:<Mic/>,title:'Расскажите',text:'Вопросы по специализации. Диалог, в котором есть место вашему ходу мысли.',label:'ДИАЛОГ С AI'},{n:'02',icon:<Code2/>,title:'Покажите',text:'Практическая задача, ваш код и объяснение выбранного решения.',label:'ОТ МЫСЛИ К КОДУ'},{n:'03',icon:<ShieldCheck/>,title:'Подтвердите',text:'Ответы, запись и события интервью. Основания для каждой оценки.',label:'ПОЛНАЯ КАРТИНА'}].map(item => <article key={item.n}><div className="journey-top"><span>{item.n} /</span>{item.icon}</div><div className={`journey-visual visual-${item.n}`} aria-hidden="true">{item.n === '01' ? <div className="signal-wave">{Array.from({length:25},(_,i)=><i key={i} style={{height:`${16 + Math.round(Math.abs(Math.sin(i * 1.7)) * (52 - Math.abs(12-i)*3))}px`}}/>)}</div> : item.n === '02' ? <div className="code-fragment"><span>def</span> find_potential():<br/><b>    return</b> skills + context</div> : <div className="signal-result"><PixelMark/><span>Навык подтверждён<small>Ответ · Код · Объяснение</small></span><Check size={18}/></div>}</div><span className="journey-label">{item.label}</span><h3>{item.title}</h3><p>{item.text}</p></article>)}</div></section>

      <section className="evidence-section" id="evidence"><div className="evidence-copy"><span className="small-kicker"><PixelMark variant="cross"/> 02 / РЕЗУЛЬТАТ</span><h2>За оценкой<br/>есть <em>история.</em></h2><p>Откройте ответ, прочитайте код, посмотрите запись. Весь контекст — перед вами. Решение — за вами.</p><button className="hero-secondary" onClick={onCompany}>Перейти к кандидатам <ArrowUpRight size={18}/></button><span className="concept-caption">Пример оформления отчёта.<br/>Не результат реального кандидата.</span></div><div className="evidence-sheet"><div className="sheet-top"><span><PixelMark/> КАРТА НАВЫКОВ</span><span className="sample-badge">Образец</span></div><h3>Python Backend</h3><p>За каждым выводом — конкретный ответ</p>{[{skill:'Python',status:'Понимание подтверждено',text:'Объяснил изменяемые аргументы и предложил исправление.',bars:6},{skill:'AsyncIO',status:'Есть вопросы',text:'Нужно уточнить выбор подхода для CPU-bound задач.',bars:3},{skill:'SQL',status:'Недостаточно данных',text:'Не хватает оснований для оценки индексов.',bars:1}].map(item=><div className="skill-example" key={item.skill}><div><strong>{item.skill}</strong><span>{item.status}</span></div><div className="skill-bars" aria-hidden="true">{Array.from({length:12},(_,i)=><i className={i<item.bars*1.5?'filled':''} key={i}/>)}</div><p>{item.text}</p></div>)}<div className="sheet-foot"><ShieldCheck size={16}/> Решение о найме принимает человек <ArrowUpRight size={16}/></div></div></section>

      <section className="integrity-section" id="integrity"><div><span className="small-kicker"><PixelMark variant="steps"/> 03 / ПРОЗРАЧНОСТЬ</span><h2>Внимание к деталям.<br/><span>Уважение к человеку.</span></h2><p className="integrity-caption">Доверие начинается с понятных правил.</p></div><div className="integrity-description"><p>Предупреждения помогают соблюдать правила. События остаются на временной шкале и рассматриваются вместе с контекстом.</p><div className="availability"><span><Video size={19}/> Запись камеры и микрофона <Check size={16}/></span><span><ShieldCheck size={19}/> События вкладки и вставки <Check size={16}/></span><span className="future">В разработке · распознавание лиц и телефона</span></div></div></section>

      <section className="landing-cta"><div className="cta-orbit" aria-hidden="true"><PixelMark/></div><span className="small-kicker">СЛЕДУЮЩИЙ СИЛЬНЫЙ КАНДИДАТ</span><h2>Всё начинается<br/>с <span>разговора.</span></h2><button className="primary" onClick={onCompany}>Создать приглашение <ArrowUpRight size={19}/></button><a className="hero-secondary" href="/?view=ai">Попробовать AI-интервью <ArrowRight size={17}/></a></section>
    </main>
    <footer className="landing-footer"><div className="footer-top"><a href="/" className="brand-word"><PixelMark/>mimas.</a><p>Технологии, которые помогают<br/>увидеть человека.</p><nav aria-label="Навигация в подвале"><a href="#how">Процесс</a><a href="#evidence">Результат</a><a href="#integrity">Прокторинг</a></nav><button className="footer-enter" onClick={onCompany}>В кабинет <ArrowUpRight size={18}/></button></div><div className="footer-bottom"><span>© 2026 mimas</span><span>НАВЫКИ. КОНТЕКСТ. ДОВЕРИЕ.</span><span>ПРОТОТИП</span></div></footer>
    {preview && <div className="preview-overlay" role="dialog" aria-modal="true" aria-labelledby="preview-title" onKeyDown={e => {if(e.key === 'Escape') setPreview(false); if(e.key === 'Tab'){const focusable=Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),textarea,a[href]'));const first=focusable[0],last=focusable[focusable.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}}}><div className="preview-window"><header><span className="small-kicker" id="preview-title">ПРОСМОТР ИНТЕРВЬЮ</span><button autoFocus className="icon-button" aria-label="Закрыть просмотр" onClick={() => setPreview(false)}><X/></button></header><div className="preview-banner">Интерактивный образец · камера и микрофон выключены · ответы не сохраняются</div><div className="preview-body"><div className="preview-question"><span className="badge purple">Python Backend · вопрос {step+1} из 3</span><h2>{questions[step]}</h2><label>Попробуйте ввести ответ<textarea value={answer} onChange={e=>{setAnswer(e.target.value);setPreviewError('');}} placeholder="Я бы начал с того, что…"/></label>{previewError&&<p role="alert" className="preview-validation">{previewError}</p>}<button className="primary" onClick={()=>{if(!answer.trim()){setPreviewError('Введите ответ, чтобы попробовать следующий этап.');return;}setState('saved');setAnswer('');setStep(v=>(v+1)%questions.length);}}>Следующий вопрос <ArrowRight size={17}/></button></div><aside className="preview-agent"><GlassOrb state={state}/><strong aria-live="polite">{stateNames[state]}</strong><p>Попробуйте состояния AI-объекта</p><div className="orb-controls">{(['idle','speaking','listening','thinking'] as OrbState[]).map(s=><button key={s} aria-pressed={state===s} onClick={()=>setState(s)}>{s==='idle'?'Ожидание':s==='speaking'?'Говорит':s==='listening'?'Слушает':'Думает'}</button>)}</div><div className="preview-camera"><Video size={22}/><span>Камера не используется в просмотре</span></div></aside></div></div></div>}
  </div>;
}

function PixelMark({variant = 'diamond'}: {variant?: 'diamond' | 'cross' | 'steps'}) {
  return <span className={`pixel-mark pixel-${variant}`} aria-hidden="true">{Array.from({length:9}, (_,i) => <i key={i}/>)}</span>;
}
