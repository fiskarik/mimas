'use client';

import {createContext, useContext, useEffect, useRef, useState, type ReactNode} from 'react';
import {ArrowUpRight, Check, PackageCheck} from 'lucide-react';
import type {OrbState} from './design';

const MotionContext = createContext({allowed: false});

export function MotionProvider({children}: {children: ReactNode}) {
  const [ready, setReady] = useState(false);
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(preference.matches);
    update(); setReady(true);
    preference.addEventListener('change', update);
    return () => preference.removeEventListener('change', update);
  }, []);
  const allowed = ready && !reduced;
  return <MotionContext.Provider value={{allowed}}>
    <div className="motion-root" data-motion={allowed ? 'playing' : 'paused'}>{children}</div>
  </MotionContext.Provider>;
}

/** Silent, local video; pauses off screen, in background tabs and for reduced motion. */
export function MotionVideo({src, poster, className = '', speed = 1}: {
  src: string; poster: string; className?: string; speed?: number;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const {allowed} = useContext(MotionContext);
  const [visible, setVisible] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [foreground, setForeground] = useState(true);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    const observer = new IntersectionObserver(([entry]) => setVisible(entry.isIntersecting));
    observer.observe(video);
    const onVisibility = () => setForeground(!document.hidden);
    onVisibility();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {observer.disconnect(); document.removeEventListener('visibilitychange', onVisibility); video.pause();};
  }, []);
  const playing = allowed && visible && foreground && !failed;
  useEffect(() => {if (playing) setLoaded(true);}, [playing]);
  useEffect(() => {
    const video = ref.current;
    if (!video) return;
    video.playbackRate = speed;
    if (loaded && playing) void video.play().catch(() => { /* Poster remains visible if autoplay is unavailable. */ });
    else video.pause();
    return () => video.pause();
  }, [loaded, playing, speed]);
  return <video ref={ref} className={className} src={loaded && !failed ? src : undefined}
    poster={poster} muted loop playsInline preload="none" aria-hidden="true" tabIndex={-1}
    disablePictureInPicture onError={() => setFailed(true)}/>;
}

export function InterviewOrb({state = 'idle', compact = false}: {state?: OrbState; compact?: boolean}) {
  const speed = {idle: .7, speaking: 1.25, listening: .85, thinking: 1.6, saved: .55}[state];
  return <div className={`glass-orb neural-orb ${compact ? 'orb-compact' : ''} orb-${state}`} aria-hidden="true">
    <MotionVideo src="/media/mimas-fluid.mp4" poster="/media/mimas-fluid-poster.webp" speed={speed}/>
  </div>;
}

function Pointer({kind}: {kind: 'human' | 'agent'}) {
  return <div className={`scene-pointer pointer-${kind}`} aria-hidden="true">
    <svg viewBox="0 0 34 42"><path d="M3 2L30 24L17 26L11 39Z" fill="currentColor" stroke="#ffffff90" strokeWidth="1.5"/></svg>
    <span><i/>{kind === 'human' ? 'Кандидат' : 'ИИ'}</span>
  </div>;
}

function NeuralMark() {
  return <svg className="neural-mark" viewBox="0 0 300 260" fill="none" aria-hidden="true">
    <path className="neural-link" d="M68 190V70L150 148L232 70V190M68 130H111M190 130H232" stroke="currentColor" strokeWidth="28" strokeLinejoin="round" strokeLinecap="round"/>
    {[[68,70],[68,130],[68,190],[109,109],[150,148],[191,109],[232,70],[232,130],[232,190]].map(([x,y],i)=><rect key={i} className={`neural-node node-${i}`} x={x-20} y={y-20} width="40" height="40" rx="13" fill="currentColor"/>)}
    <circle className="neural-spark" cx="150" cy="62" r="10" fill="#c3f6d6"/>
  </svg>;
}

export function IntelligenceSection() {
  const [step, setStep] = useState(0);
  const panels = [
    {label: 'Вопрос', title: 'С чего начинается диалог', text: '«Что вы сделаете, если при приёмке товара обнаружили недостачу?»', code: 'Приёмка товара', detail: 'Тема · склад / учёт товара'},
    {label: 'Контекст', title: 'Важно, как вы рассуждаете', text: 'ИИ уточняет, как кандидат проверит документы и сообщит о расхождении.', code: 'Сверка → фиксация → сообщение', detail: 'Ответ → уточнение → объяснение'},
    {label: 'Вывод', title: 'У оценки есть основания', text: 'В отчёте видны ответы и навыки, которые ещё стоит проверить на рабочем месте.', code: 'Устный ответ ≠ работа на практике', detail: 'Решение о найме — за человеком'},
  ];
  return <section className="intelligence-section" id="intelligence" aria-labelledby="intelligence-title">
    <div className="intelligence-heading"><span className="small-kicker"><span/> MIMAS / КАНДИДАТ И ИИ</span><h2 id="intelligence-title">Два участника.<br/><span>Одна понятная картина.</span></h2><p>Кандидат объясняет рабочую задачу.<br/>ИИ помогает увидеть ход решения.</p></div>
    <div className="intelligence-grid">
      <article className="intelligence-card">
        <div className="collaboration-scene motion-scene" role="img" aria-label="Кандидат и ИИ обсуждают рабочую задачу">
          <div className="scene-grid" aria-hidden="true"/>
          <div className="scene-meta"><span>01 / ГОЛОСОВОЙ ДИАЛОГ</span><span className="scene-live"><i/> КАНДИДАТ + ИИ</span></div>
          <NeuralMark/><Pointer kind="human"/><Pointer kind="agent"/>
          <span className="scene-code" aria-hidden="true"><PackageCheck size={13}/> вопрос → решение → объяснение</span>
        </div>
        <div className="intelligence-caption"><span className="scene-number">01</span><div><h3>Диалог, а не допрос.</h3><p>Кандидат объясняет действия. ИИ задаёт уточнения. В центре всегда остаётся человек.</p></div><ArrowUpRight aria-hidden="true" size={20}/></div>
      </article>
      <article className="intelligence-card">
        <div className="reasoning-scene motion-scene" data-step={step}>
          <div className="iso-grid" aria-hidden="true"/>
          <div className="scene-meta"><span>02 / ОТ ВОПРОСА К ВЫВОДУ</span><span>СХЕМА РАБОТЫ</span></div>
          <div className="reasoning-orbit" aria-hidden="true"><i/><i/><i/></div>
          <div className="reasoning-core"><InterviewOrb state={step === 0 ? 'speaking' : step === 1 ? 'thinking' : 'saved'}/></div>
          <div className="context-fragment" aria-live="polite"><span>{panels[step].detail}</span><code>{panels[step].code}</code><i><Check size={12}/> {step === 2 ? 'Основания собраны' : step === 1 ? 'Контекст связан' : 'Тема определена'}</i></div>
          <div className="reasoning-tabs" role="tablist" aria-label="Этапы интервью с ИИ">{panels.map((panel,i)=><button key={panel.label} id={`reasoning-tab-${i}`} role="tab" aria-selected={step === i} aria-controls="reasoning-panel" tabIndex={step === i ? 0 : -1}
            onClick={() => setStep(i)} onKeyDown={event => {
              const next = event.key === 'ArrowRight' ? (i+1)%3 : event.key === 'ArrowLeft' ? (i+2)%3 : event.key === 'Home' ? 0 : event.key === 'End' ? 2 : null;
              if (next !== null) {event.preventDefault(); setStep(next); document.getElementById(`reasoning-tab-${next}`)?.focus();}
            }}><span>0{i+1}</span>{panel.label}</button>)}</div>
        </div>
        <div className="intelligence-caption" id="reasoning-panel" role="tabpanel" aria-labelledby={`reasoning-tab-${step}`}><span className="scene-number">02</span><div><h3>{panels[step].title}</h3><p>{panels[step].text}</p></div><ArrowUpRight aria-hidden="true" size={20}/></div>
      </article>
    </div>
  </section>;
}
