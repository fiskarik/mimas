'use client';

import {useEffect, useRef, useState} from 'react';
import {ArrowLeft, ArrowRight, Loader2, RefreshCw} from 'lucide-react';
import {GlassOrb} from './design';

type Question = {id:string; skill:string; text:string; type:string; generation:string};
type Answer = {question_id:string; text:string};
type Evidence = {id:string; question_id:string; claim:string; quote:string; type:string};
type SkillReport = {skill:string; demonstrated_level:string|null; answers_received:number; evaluated_answers:number; evidence:Evidence[]; missing_concepts:string[]};
type Session = {id:string; model:string; phase:string; current_question:Question|null; questions:Question[]; answers:Answer[]; pending_answer:Answer|null; evaluation_notice:string|null; report:{skills:SkillReport[]; overall_technical_summary:string; stop_reason:string}|null; max_questions:number};
type Access = {id:string; token:string};
const names:Record<string,string> = {'python.core':'Python Core','python.oop':'ООП','python.asyncio':'AsyncIO','web.http':'HTTP / REST','db.postgresql':'PostgreSQL','cs.algorithms':'Алгоритмы','engineering.debugging':'Отладка'};
const levels:Record<string,string> = {basic:'Базовый',junior:'Junior',middle:'Middle',strong_middle:'Strong Middle',senior:'Senior'};
const failureNames:Record<string,string> = {provider_error:'сбой API Groq',invalid_output:'неверный формат ответа модели',unsupported_evidence:'оценка не прошла проверку цитат или цели вопроса',rate_limit:'достигнут лимит Groq',authentication_error:'неверный API-ключ',access_denied:'Groq запретил доступ',model_unavailable:'модель недоступна',output_truncated:'ответ модели обрезан',network_error:'сбой соединения с Groq',invalid_provider_response:'неверный ответ API'};

async function request<T>(path:string, token?:string, body?:unknown, key?:string):Promise<T> {
  const response = await fetch(`/api/ai/sessions${path}`, {method:body === undefined ? 'GET':'POST',
    headers:{'Content-Type':'application/json',...(token?{'X-Interview-Token':token}:{}),...(key?{'X-Company-Key':key}:{})},
    body:body === undefined ? undefined:JSON.stringify(body),cache:'no-store'});
  if(!response.ok) {const error=await response.json().catch(()=>({}));throw new Error(typeof error.detail==='string'?error.detail:`Ошибка сервера (${response.status}). Ответ можно повторить.`);}
  return response.json();
}

export default function AIDemo(){
  const [access,setAccess]=useState<Access|null>(null);
  const [data,setData]=useState<Session|null>(null);
  const [key,setKey]=useState('demo-company');
  const [answer,setAnswer]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [ready,setReady]=useState(false);
  const answerRef=useRef<HTMLTextAreaElement>(null);
  useEffect(()=>{setKey(sessionStorage.getItem('company-key')||'demo-company');
    try {const saved=sessionStorage.getItem('ai-access');if(saved){const value=JSON.parse(saved);if(typeof value.id==='string'&&typeof value.token==='string')setAccess(value);}}
    catch{sessionStorage.removeItem('ai-access');}setReady(true);},[]);
  useEffect(()=>{if(!access)return;let cancelled=false;
    request<Session>(`/${access.id}`,access.token).then(d=>{if(!cancelled){setData(d);if(d.pending_answer)setAnswer(d.pending_answer.text);}}).catch(e=>{if(!cancelled)setError(e.message);});
    return ()=>{cancelled=true;};},[access]);
  async function create(){setBusy(true);setError('');try{
    const next=await request<Access>('',undefined,{},key);sessionStorage.setItem('ai-access',JSON.stringify(next));setAccess(next);
    setData(await request<Session>(`/${next.id}/start`,next.token,{}));setAnswer('');
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function act(action:'answers'|'start'|'finish'){
    if(!access)return;setBusy(true);setError('');
    try {const body=action==='answers'?(data?.pending_answer||{question_id:data?.current_question?.id,text:answer}):{};
      const next=await request<Session>(`/${access.id}/${action}`,access.token,body);setData(next);if(action==='answers')setAnswer('');
    }catch(e){setError((e as Error).message);try{const latest=await request<Session>(`/${access.id}`,access.token);setData(latest);if(latest.pending_answer)setAnswer(latest.pending_answer.text);}catch{/* Original error stays visible. */}}
    finally{setBusy(false);answerRef.current?.focus();}
  }
  async function refresh(){if(!access)return;setBusy(true);setError('');try{const next=await request<Session>(`/${access.id}`,access.token);setData(next);if(next.pending_answer)setAnswer(next.pending_answer.text);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  function reset(){sessionStorage.removeItem('ai-access');setAccess(null);setData(null);setAnswer('');setError('');}
  const current=data?.current_question;
  const notice=data?.evaluation_notice?.replace(/provider_error|invalid_output|unsupported_evidence|rate_limit|authentication_error|access_denied|model_unavailable|output_truncated|network_error|invalid_provider_response/g,v=>failureNames[v]);
  return <div className="ai-demo"><header className="candidate-header"><a href="/" className="brand-word">автособес.</a><a href="/?view=company" className="text-link">Кабинет <ArrowRight size={16}/></a></header>
    <main className="ai-demo-main"><a href="/" className="text-link"><ArrowLeft size={15}/> На главную</a>
      <div className="ai-demo-heading"><div><span className="eyebrow">MIMAS · ЖИВОЕ AI-ИНТЕРВЬЮ</span><h1>Обсудим, как это работает.</h1><p className="muted">Python Backend · Middle · до 20 вопросов / 30 минут</p></div><GlassOrb compact state={busy?'thinking':'idle'}/></div>
      <div className="note">Текстовый режим: камера и микрофон не включаются. Ответы сохраняются на этом сервере и отправляются в Groq. Используйте тестовые данные без персональной информации.</div>
      {error&&<div role="alert" className="error-box">{error}</div>}
      {notice&&<div role="status" className="warning">{notice}</div>}
      {!ready?<p>Загрузка…</p>:!access?<section className="card ai-start"><h2>Начать собеседование</h2><p className="muted">Короткие вопросы по семи компетенциям. Если не знаете ответ, так и напишите — это не считается ошибочным утверждением.</p><form onSubmit={e=>{e.preventDefault();void create();}}><label>Ключ команды<input type="password" value={key} onChange={e=>setKey(e.target.value)} required/></label><button className="primary" disabled={busy}>{busy?<Loader2 className="spin" size={17}/>:<ArrowRight size={17}/>} Начать AI-интервью</button></form></section>
      :!data?<section className="card ai-start"><p>Загружаем сессию…</p><button className="secondary" disabled={busy} onClick={()=>void refresh()}>Повторить загрузку</button><button className="text-link" disabled={busy} onClick={reset}>Другая сессия</button></section>
      :<><div className="ai-session-bar"><span>{data.model} · сохранено ответов: {data.answers.length}</span><button className="text-link" disabled={busy} onClick={()=>void refresh()}><RefreshCw size={14}/> Обновить</button></div>
      {data.phase==='CREATED'&&<button className="primary" disabled={busy} onClick={()=>void act('start')}>Получить первый вопрос</button>}
      {current&&<section className="card ai-question"><div className="section-top"><span className="badge purple">{names[current.skill]||current.skill}</span><span className="muted tiny">Вопрос {data.questions.length} · {current.type==='verification'?'Проверка утверждения':current.type==='follow_up'?'Уточнение':'Основной вопрос'}</span></div>
        <h2>{current.text}</h2>{current.generation==='fallback'&&<p className="tiny muted">Использован резервный вопрос из банка.</p>}
        <form onSubmit={e=>{e.preventDefault();void act('answers');}}><label>Ваш ответ или код<textarea ref={answerRef} value={answer} onChange={e=>setAnswer(e.target.value)} readOnly={!!data.pending_answer||busy} maxLength={16000} placeholder="Объясните своими словами. Код можно вставить с переносами строк."/></label>
        {data.pending_answer&&<p className="note">Ответ уже сохранён. Повторная отправка продолжит его обработку без дубликата.</p>}
        <div className="button-row"><button className="primary" disabled={busy||!answer.trim()}>{busy?<Loader2 className="spin" size={17}/>:<ArrowRight size={17}/>} {busy?'AI обрабатывает ответ…':data.pending_answer?'Повторить обработку':'Отправить ответ'}</button><button type="button" className="secondary" disabled={busy||!!data.pending_answer} onClick={()=>void act('finish')}>Завершить и показать отчёт</button></div></form></section>}
      {data.report&&<section className="ai-report"><div className="section-top"><div><h2>Отчёт по интервью</h2><p className="muted">{data.report.overall_technical_summary}</p></div><button className="secondary" onClick={reset}>Новое интервью</button></div><p className="note">Уровни предварительные. Отсутствие ответа или сбой оценки не доказывают отсутствие навыка.</p><div className="report-skills">{data.report.skills.map(skill=><article className="card" key={skill.skill}><h3>{names[skill.skill]||skill.skill}</h3><span className="badge">{skill.demonstrated_level?levels[skill.demonstrated_level]:'Недостаточно данных'}</span><p>Ответов: {skill.answers_received} · обработано: {skill.evaluated_answers}</p>{skill.evidence.map(e=><div className="ai-evidence" key={e.id}><strong>{e.type==='positive'?'Подтверждение':e.type==='negative'?'Ошибка в утверждении':'Неопределённость'}</strong><p>{e.claim}</p><blockquote>{e.quote}</blockquote></div>)}</article>)}</div></section>}
      {data.answers.length>0&&<details className="card ai-history"><summary>История ответов ({data.answers.length})</summary>{data.answers.map(a=><article key={a.question_id}><h3>{data.questions.find(q=>q.id===a.question_id)?.text}</h3><pre>{a.text}</pre></article>)}</details>}
      </>}
    </main></div>;
}
