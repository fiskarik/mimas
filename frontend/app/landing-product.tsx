'use client';

import {useEffect, useRef, useState} from 'react';
import {ArrowRight, ArrowUpRight, Boxes, Check, CheckCheck, ChevronRight, ClipboardCheck, Clock3, FileText, Headphones, Loader2, MessageCircle, Mic, PackageCheck, ScanLine, ShieldCheck, ShoppingBasket, Store, Video} from 'lucide-react';
import {BrandLogo} from './brand-logo';

const question = 'На кассе цена оказалась выше, чем на ценнике. Покупатель возмущён. Как вы поступите?';
const answer = 'Спокойно выслушаю покупателя, проверю товар и ценник. Позову ответственного сотрудника, чтобы уточнить расхождение и решить вопрос по правилам магазина. Объясню покупателю, что делаю.';
const words = answer.split(' ');
const phaseStarts = [0, 4200, 11000, 14000];
const phases = [
  {label: 'Вопрос', title: 'MIMAS задаёт рабочую ситуацию', detail: 'Продавец-кассир · обслуживание покупателей', icon: MessageCircle},
  {label: 'Ответ', title: 'Кандидат объясняет свои действия', detail: 'Голос превращается в текст ответа', icon: Mic},
  {label: 'Разбор', title: 'MIMAS разбирает ответ', detail: 'Выделяем основания и вопросы для уточнения', icon: Loader2},
  {label: 'Результат', title: 'За каждым выводом — слова кандидата', detail: 'Ответ и разбор доступны в отчёте', icon: CheckCheck},
];

function useShowcaseSequence() {
  const ref = useRef<HTMLElement>(null);
  const [visible, setVisible] = useState(false);
  const [foreground, setForeground] = useState(false);
  const [motion, setMotion] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [selected, setSelected] = useState<number|null>(null);
  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const updateMotion = () => setMotion(!preference.matches);
    const updateVisibility = () => setForeground(!document.hidden);
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting), {threshold: .15});
    if (ref.current) observer.observe(ref.current);
    updateMotion(); updateVisibility();
    preference.addEventListener('change', updateMotion);
    document.addEventListener('visibilitychange', updateVisibility);
    return () => {observer.disconnect(); preference.removeEventListener('change', updateMotion); document.removeEventListener('visibilitychange', updateVisibility);};
  }, []);
  useEffect(() => {
    if (!visible || !foreground || !motion || hovered || focused) return;
    const timer = window.setInterval(() => {setSelected(null); setElapsed(value => (value + 400) % 22000);}, 400);
    return () => window.clearInterval(timer);
  }, [visible, foreground, motion, hovered, focused]);
  const phase = motion ? phaseStarts.reduce((result, start, index) => elapsed >= start ? index : result, 0) : selected ?? 3;
  const select = (index: number) => {setSelected(index); setElapsed(phaseStarts[index]);};
  return {ref, phase, elapsed, motion, manual: selected !== null, playing: visible && foreground && motion && !hovered && !focused, select, setHovered, setFocused};
}

function RetailPortrait() {
  return <svg className="lp-portrait-art" viewBox="0 0 500 420" preserveAspectRatio="xMidYMid slice" fill="none" aria-hidden="true">
    <defs><linearGradient id="lp-room" x1="0" y1="0" x2="500" y2="420" gradientUnits="userSpaceOnUse"><stop stopColor="#40594c"/><stop offset="1" stopColor="#13281f"/></linearGradient><linearGradient id="lp-shirt" x1="230" y1="225" x2="350" y2="420" gradientUnits="userSpaceOnUse"><stop stopColor="#b7c8a4"/><stop offset="1" stopColor="#71896c"/></linearGradient></defs>
    <path fill="url(#lp-room)" d="M0 0h500v420H0z"/>
    <g opacity=".2" stroke="#d3e7ca" strokeWidth="3"><path d="M28 99h444M28 174h444M28 249h444"/><path d="M49 54h37v43H49zM99 67h55v30H99zM362 43h42v54h-42zM416 64h33v33h-33zM34 128h62v44H34zM110 137h33v35h-33zM366 122h63v50h-63zM442 140h30v32h-30z"/></g>
    <ellipse cx="254" cy="426" rx="165" ry="60" fill="#0b1712" opacity=".3"/>
    <path d="M133 420v-81c0-65 44-104 117-104s117 39 117 104v81" fill="url(#lp-shirt)"/>
    <path d="M215 220v34c0 25 70 25 70 0v-34" fill="#bd9d7d"/>
    <ellipse cx="250" cy="161" rx="65" ry="83" fill="#d4b593"/>
    <path d="M183 163c-11-59 8-106 67-106 63 0 84 43 65 111l-11-42c-35 1-65-13-81-31-8 23-21 35-35 39l-5 29Z" fill="#24352b"/>
    <path d="M198 155c-6 45 2 73 30 93-39-7-62-41-47-91l17-2Z" fill="#24352b"/>
    <path d="M230 176h1m38 0h1" stroke="#4e4d3e" strokeWidth="5" strokeLinecap="round"/>
    <path d="M238 208c8 5 16 5 24 0" stroke="#936c55" strokeWidth="3" strokeLinecap="round"/>
    <path d="m210 265 40 27 40-27 22 155H189l21-155Z" fill="#2b4937"/>
    <path d="M250 292v128" stroke="#c7d8ae" strokeWidth="2" opacity=".4"/>
    <rect x="278" y="307" width="49" height="23" rx="4" fill="#d4e6be"/><path d="M286 319h26" stroke="#3c5d43" strokeWidth="3"/>
    <rect x="340" y="303" width="115" height="71" rx="10" fill="#13251d" stroke="#718d72"/><path d="m392 374-9 36h31l-9-36" fill="#182e23"/>
    <path d="M364 325h49m-49 14h30" stroke="#b8d7ac" strokeWidth="4" strokeLinecap="round" opacity=".6"/>
  </svg>;
}

export function LandingInterviewPreview() {
  const sequence = useShowcaseSequence();
  const stage = phases[sequence.phase];
  const StatusIcon = stage.icon;
  const count = sequence.phase === 1 && sequence.motion && !sequence.manual ? Math.max(1, Math.ceil((sequence.elapsed - phaseStarts[1]) / 6800 * words.length)) : words.length;
  const complete = sequence.phase === 3;
  return <section ref={sequence.ref} className="lp-showcase" id="intelligence" aria-labelledby="lp-showcase-title">
    <div className="lp-section-head"><span className="lp-eyebrow"><BrandLogo tone="light" width={68}/> ВНУТРИ MIMAS</span><h2 id="lp-showcase-title">Рабочая ситуация.<br/><em>Живой ответ.</em></h2><p>Посмотрите, как разговор о работе превращается в понятный отчёт по навыкам.</p></div>
    <div className="lp-console" data-phase={sequence.phase} data-playing={sequence.playing}
      onMouseEnter={() => sequence.setHovered(true)} onMouseLeave={() => sequence.setHovered(false)}
      onFocusCapture={() => sequence.setFocused(true)} onBlurCapture={event => {if (!event.currentTarget.contains(event.relatedTarget as Node|null)) sequence.setFocused(false);}}>
      <div className="lp-console-toolbar"><span className="lp-console-brand"><BrandLogo tone="light" width={77}/><span>ИНТЕРВЬЮ</span></span><span className="lp-example-badge">Вымышленный пример</span></div>
      <div className="lp-console-status"><span className={'lp-status-icon'+(sequence.phase===2?' lp-spin':'')}><StatusIcon size={20}/></span><div><strong>{stage.title}</strong><span>{stage.detail}</span></div><span className="lp-status-step">0{sequence.phase+1} / 04</span></div>
      <div className="lp-dialog-grid">
        <div className="lp-portrait"><RetailPortrait/><div className="lp-portrait-top"><span>ПРОДАВЕЦ-КАССИР</span><strong>Анна</strong></div><span className="lp-camera-badge"><Video size={13}/> Образец интерфейса</span><div className="lp-portrait-bottom"><div className={'lp-wave'+(sequence.phase===1?' is-speaking':'')} aria-hidden="true">{Array.from({length:25},(_,i)=><i key={i} style={{height:10+Math.abs(Math.sin(i*1.7))*23+'px',animationDelay:i*.07+'s'}}/>)}</div><span>{sequence.phase===1?'Кандидат отвечает':complete?'Ответ сохранён':'Голосовое интервью'}</span><Headphones size={17}/></div></div>
        <div className="lp-transcript"><div className="lp-panel-label"><MessageCircle size={15}/> СТЕНОГРАММА <span>RU</span></div><article className="lp-transcript-question"><span>MIMAS</span><p>{question}</p></article><article className={'lp-transcript-answer'+(sequence.phase===0?' is-waiting':'')}><span>АННА</span><p aria-live="off">{sequence.phase===0?'Сейчас прозвучит ответ кандидата…':words.slice(0,count).join(' ')}{sequence.phase===1&&<i className="lp-text-caret" aria-hidden="true"/>}</p></article><div className="lp-transcript-foot"><ShieldCheck size={14}/> Слова кандидата сохраняются в отчёте</div></div>
      </div>
      <div className="lp-result-strip"><span className="lp-result-heading"><ClipboardCheck size={17}/>{complete?'Основания оценки':'Разбор ответа'}</span><div className={complete?'lp-result-copy is-ready':'lp-result-copy'}><strong>{complete?'Работа с покупателем · подход описан':'От ответа — к разбору навыков'}</strong><p>{complete?'Проверяет ценник, привлекает ответственного и объясняет покупателю свои действия.':'MIMAS сопоставляет объяснение с критериями и отмечает, что стоит уточнить.'}</p></div><span className={'lp-result-check'+(complete?' is-ready':'')}><Check size={20}/></span></div>
      <div className="lp-phase-controls" aria-label="Этапы примера интервью">{phases.map((phase,index)=><button key={phase.label} type="button" aria-pressed={index===sequence.phase} onClick={()=>sequence.select(index)}><span>0{index+1}</span>{phase.label}<i aria-hidden="true"/></button>)}</div>
    </div>
    <div className="lp-facts"><span><strong>Одно</strong> общее интервью</span><span><Clock3 size={17}/><strong>До 20 минут</strong> на разговор</span><span><FileText size={17}/>Ответы и основания <strong>в отчёте</strong></span></div>
  </section>;
}

const processSteps = [
  {title:'Общее интервью',icon:Mic,summary:'Расскажите о знакомых рабочих задачах.',heading:'Один разговор о вашем опыте',text:'Выберите направление работы и ответьте голосом на вопросы по блокам. Объясните, как действуете в обычных и сложных рабочих ситуациях.',tags:['Рабочие ситуации','Ответы голосом','До 20 минут']},
  {title:'Отчёт по навыкам',icon:ClipboardCheck,summary:'Получите разбор с основаниями оценки.',heading:'Опыт становится понятнее',text:'В профиле появляются разобранные навыки, ваши ответы и темы, которые требуют уточнения. Вы видите, на чём основан каждый вывод.',tags:['Стенограмма','Основания оценки','Вопросы для уточнения']},
  {title:'Подходящие вакансии',icon:Store,summary:'Выбирайте работу с готовым профилем.',heading:'Ваши ответы работают дальше',text:'Откликайтесь на интересующие вакансии. С вашего согласия компании смогут увидеть общий отчёт и сравнить ответы кандидатов по одним критериям.',tags:['Выбор вакансий','Общий отчёт','Доступ с согласия']},
  {title:'Дополнительные вопросы',icon:MessageCircle,summary:'Только когда компании нужно уточнить детали.',heading:'Уточнения под конкретную работу',text:'Если нужны особые навыки или опыт, компания добавит короткое интервью по своим задачам. Уже разобранные базовые темы проходят один раз.',tags:['Задачи компании','Узкие навыки','Без повторения базы']},
];

export function LandingProcess() {
  const [active,setActive] = useState(0);
  const step = processSteps[active];
  const Icon = step.icon;
  return <section className="lp-process" id="how" aria-labelledby="lp-process-title">
    <div className="lp-section-head lp-head-light"><span className="lp-eyebrow">01 / ПУТЬ КАНДИДАТА</span><h2 id="lp-process-title">Один раз расскажите.<br/><em>Двигайтесь дальше.</em></h2><p>Общий отчёт остаётся в вашем профиле и помогает находить следующие возможности.</p></div>
    <ol className="lp-process-steps">{processSteps.map((item,index)=>{const StepIcon=item.icon;return <li key={item.title} data-active={active===index}><button type="button" aria-pressed={active===index} aria-controls="lp-process-detail" onClick={()=>setActive(index)}><span className="lp-step-node"><StepIcon size={23}/><small>0{index+1}</small></span><strong>{item.title}</strong><span className="lp-step-summary">{item.summary}</span><ChevronRight className="lp-step-arrow" size={16}/></button></li>;})}</ol>
    <div className="lp-process-detail" id="lp-process-detail" role="region" aria-label={step.title}><span className="lp-detail-icon"><Icon size={27}/></span><div key={step.title}><span className="lp-detail-label">ШАГ 0{active+1}</span><h3>{step.heading}</h3><p>{step.text}</p><div className="lp-detail-tags">{step.tags.map(tag=><span key={tag}><Check size={12}/>{tag}</span>)}</div></div><a href="/?view=candidate" aria-label="Перейти в кабинет кандидата"><ArrowUpRight size={24}/></a></div>
  </section>;
}

export function LandingSkillReport({onCompany}:{onCompany:()=>void}) {
  return <section className="lp-report" id="evidence" aria-labelledby="lp-report-title">
    <div className="lp-report-heading"><div><span className="lp-eyebrow">02 / РЕЗУЛЬТАТ РАЗГОВОРА</span><h2 id="lp-report-title">Видно, что умеет<br/><em>объяснить человек.</em></h2></div><div><p>Навыки, слова кандидата и вопросы для уточнения — в одном отчёте. Компания видит основания и принимает решение.</p><button className="lp-text-button" type="button" onClick={onCompany}>Открыть кабинет компании <ArrowUpRight size={17}/></button></div></div>
    <div className="lp-report-dashboard"><header><span className="lp-report-person"><span className="lp-avatar">АК</span><span><strong>Анна · продавец-кассир</strong><small>Общее интервью · отчёт по навыкам</small></span></span><span className="lp-example-badge">Образец отчёта</span></header>
      <div className="lp-report-grid"><article className="lp-skill-spotlight"><span className="lp-skill-kicker"><MessageCircle size={17}/> РАБОТА С ПОКУПАТЕЛЕМ</span><span className="lp-skill-status"><CheckCheck size={14}/> Подход описан</span><h3>Спокойно разобраться<br/>в сложной ситуации.</h3><p>Кандидат описал проверку ценника, обращение к ответственному и объяснение действий покупателю.</p><blockquote>«Проверю товар и ценник. Позову ответственного сотрудника… Объясню покупателю, что делаю».</blockquote><span className="lp-quote-source">Основание · фрагмент ответа</span></article>
        <article className="lp-skill-small"><PackageCheck size={23}/><span className="lp-skill-status lp-status-clarify">Нужно уточнить</span><h3>Приёмка товара</h3><p>Названа сверка количества. Стоит уточнить, как кандидат зафиксирует недостачу.</p><span className="lp-skill-bottom">Следующий вопрос <ArrowUpRight size={16}/></span></article>
        <article className="lp-skill-small lp-skill-practical"><ScanLine size={23}/><span className="lp-skill-status lp-status-practical">Не проверялось</span><h3>Работа с кассой</h3><p>Практическое владение кассой нужно проверить на рабочем месте.</p><span className="lp-skill-bottom">Проверка на практике <ArrowUpRight size={16}/></span></article></div>
      <footer><span><ShieldCheck size={16}/> Решение о найме принимает человек</span><span>Вымышленный пример оформления отчёта</span></footer>
    </div>
  </section>;
}

const roles = [
  {name:'Продавец-кассир',label:'01 / КАССА',icon:ScanLine,topic:'Покупатель и цена',question:'Цена на кассе не совпала с ценником. Как вы объясните покупателю свои действия?',skills:['Обслуживание покупателей','Работа с конфликтами']},
  {name:'Торговый зал',label:'02 / ПОЛКИ',icon:Store,topic:'Порядок на полке',question:'На полке обнаружен товар с истекающим сроком годности. Что вы сделаете?',skills:['Выкладка товара','Внимание к срокам']},
  {name:'Сборщик заказов',label:'03 / ЗАКАЗЫ',icon:ShoppingBasket,topic:'Точность заказа',question:'Нужного товара нет в наличии. Как вы согласуете замену и проверите заказ?',skills:['Комплектация','Работа с заменами']},
  {name:'Работник склада',label:'04 / СКЛАД',icon:Boxes,topic:'Приёмка и учёт',question:'Количество товара не совпало с документами. Как вы проверите и зафиксируете расхождение?',skills:['Приёмка товара','Учёт расхождений']},
];

export function LandingRoles() {
  const [active,setActive] = useState(0);
  const role = roles[active];
  return <section className="lp-roles" aria-labelledby="lp-roles-title"><div className="lp-section-head lp-head-light"><span className="lp-eyebrow">НАПРАВЛЕНИЯ РАБОТЫ</span><h2 id="lp-roles-title">Знакомые задачи.<br/><em>Ваш опыт.</em></h2><p>Вопросы о ситуациях, с которыми встречаются сотрудники магазинов и складов.</p></div>
    <div className="lp-role-cards" aria-label="Направления интервью">{roles.map((item,index)=>{const Icon=item.icon;return <button key={item.name} type="button" data-active={active===index} aria-pressed={active===index} aria-controls="lp-role-example" onClick={()=>setActive(index)}><span className="lp-role-index">{item.label}</span><span className="lp-role-art" aria-hidden="true"><i/><i/><Icon strokeWidth={.85}/></span><span className="lp-role-title">{item.name}<ArrowUpRight size={19}/></span></button>;})}</div>
    <div className="lp-role-example" id="lp-role-example" role="region" aria-label={'Пример вопроса: '+role.name}><div><span className="lp-detail-label">ПРИМЕР СИТУАЦИИ · {role.topic}</span><p key={role.name}>{role.question}</p></div><div className="lp-role-skills">{role.skills.map(skill=><span key={skill}>{skill}</span>)}</div><a href="/?view=candidate" aria-label={'Открыть кабинет кандидата: '+role.name}><ArrowRight size={21}/></a></div>
  </section>;
}
