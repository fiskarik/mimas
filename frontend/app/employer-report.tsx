'use client';

import {useEffect,useState} from 'react';
import {AnswerReport} from './answer-report';
import {IntegritySummary} from './integrity-summary';
import {EmployerMonitorReport} from './monitor-ui';
import type {Session} from './ai-session';
import {skillNames} from './marketplace-api';

export function EmployerReport({sessionId,companyKey}:{sessionId:string;companyKey:string}){
  const [session,setSession]=useState<Session|null>(null);
  const [error,setError]=useState('');
  const [recordingStatus,setRecordingStatus]=useState<{status:string;incomplete:boolean;expires_at:number|null}|null>(null);
  useEffect(()=>{
    let cancelled=false;
    const load=async()=>{
      const response=await fetch('/api/market/company/assessments/'+encodeURIComponent(sessionId),{headers:{'X-Company-Key':companyKey},cache:'no-store'});
      if(!response.ok){const body=await response.json().catch(()=>({}));throw new Error(typeof body.detail==='string'?body.detail:'Отчёт недоступен.');}
      const value=await response.json() as {session:Session};
      const recording=await fetch('/api/ai/sessions/'+encodeURIComponent(sessionId)+'/recording/status',{headers:{'X-Company-Key':companyKey},cache:'no-store'});
      if(!cancelled){setSession(value.session);if(recording.ok)setRecordingStatus(await recording.json());}
    };
    void load().catch(e=>{if(!cancelled)setError((e as Error).message);});
    return()=>{cancelled=true;};
  },[sessionId,companyKey]);
  if(error)return <p role="alert" className="error-box">{error}</p>;
  if(!session)return <p className="muted">Загружаем полный отчёт…</p>;
  if(!session.report)return <p className="muted">Отчёт ещё не готов.</p>;
  return <div className="market-full-report">
    {recordingStatus?.incomplete&&<p role="status" className="warning">Видеозапись прервана и содержит только сохранённую часть интервью.</p>}
    <h4>Подробный разбор ответов</h4>
    <AnswerReport reviews={session.report.answer_reviews||[]} rubric={session.report.scoring_rubric} names={skillNames}/>
    {session.report.integrity&&<IntegritySummary report={session.report.integrity} questions={session.questions}/>}
    <EmployerMonitorReport sessionId={sessionId} companyKey={companyKey}/>
  </div>;
}
