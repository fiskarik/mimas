'use client';

import {useCallback,useEffect,useState} from 'react';
import {ArrowLeft,ArrowRight,BriefcaseBusiness,CheckCircle2,Loader2,ShieldCheck,Video} from 'lucide-react';
import AIDemo from './ai-demo';
import type {Access} from './ai-session';
import {assessmentFor,levelLabels,market,MarketError,salaryRange,type Level,type MyProfile,type Opportunity} from './marketplace-api';

export function CandidateHub(){
  const [token,setToken]=useState('');
  const [loaded,setLoaded]=useState(false);
  const [me,setMe]=useState<MyProfile|null>(null);
  const [jobs,setJobs]=useState<Opportunity[]>([]);
  const [access,setAccess]=useState<Access|null>(null);
  const [activeJob,setActiveJob]=useState<Pick<Opportunity,'id'|'title'|'company_name'>|null>(null);
  const [stream,setStream]=useState<MediaStream|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [consentJob,setConsentJob]=useState<Pick<Opportunity,'id'|'title'|'company_name'>|null>(null);
  const [consent,setConsent]=useState(false);
  const [name,setName]=useState('');
  const [level,setLevel]=useState<Level>('middle');
  const [stack,setStack]=useState('Python, FastAPI, PostgreSQL');
  const [years,setYears]=useState('2');
  const [github,setGithub]=useState('');
  const [salaryWish,setSalaryWish]=useState('');
  useEffect(()=>{setToken(localStorage.getItem('mimas-candidate-token')||'');setLoaded(true);},[]);
  const refresh=useCallback(async(auth:string)=>{
    const [profile,items]=await Promise.all([market<MyProfile>('/me',{token:auth}),market<Opportunity[]>('/opportunities',{token:auth})]);
    setMe(profile);setJobs(items);
  },[]);
  useEffect(()=>{if(token)void refresh(token).catch(e=>{
    if(e instanceof MarketError&&e.status===401){localStorage.removeItem('mimas-candidate-token');setToken('');setMe(null);setJobs([]);setError('Профиль недоступен. Создайте новый.');}
    else setError((e as Error).message);
  });},[token,refresh]);
  async function register(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError('');
    try{
      const result=await market<{token:string}>('/candidates',{method:'POST',body:{name,level,stack:stack.split(',').map(x=>x.trim()).filter(Boolean),years_experience:Number(years),github_url:github||null,desired_salary_rub:salaryWish?Number(salaryWish):null}});
      localStorage.setItem('mimas-candidate-token',result.token);setToken(result.token);
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function select(job:Opportunity){
    setBusy(true);setError('');
    try{await market('/opportunities/'+job.id+'/interest',{method:'POST',token,body:{}});await refresh(token);}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function openInterview(job:Pick<Opportunity,'id'|'title'|'company_name'>,finished=false){
    setBusy(true);setError('');
    let camera:MediaStream|null=null;
    try{
      if(!finished){
        if(!navigator.mediaDevices?.getUserMedia)throw new Error('Для интервью нужен браузер с доступом к камере и микрофону.');
        camera=await navigator.mediaDevices.getUserMedia({video:{facingMode:'user'},audio:true});
        if(!camera.getVideoTracks().length)throw new Error('Камера не подключена. Без неё начать интервью нельзя.');
      }
      const response=await fetch('/api/ai/sessions',{method:'POST',headers:{'X-Candidate-Token':token,'Content-Type':'application/json'},body:JSON.stringify({opportunity_id:job.id,consent:true}),cache:'no-store'});
      const body=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'Не удалось открыть интервью.');
      setStream(camera);setActiveJob(job);setAccess(body as Access);setConsentJob(null);setConsent(false);
    }catch(e){camera?.getTracks().forEach(track=>track.stop());setError((e as Error).message);}finally{setBusy(false);}
  }
  function leaveInterview(){
    stream?.getTracks().forEach(track=>track.stop());setStream(null);setAccess(null);setActiveJob(null);
    void refresh(token).catch(e=>setError((e as Error).message));
  }
  function logout(){
    stream?.getTracks().forEach(track=>track.stop());localStorage.removeItem('mimas-candidate-token');
    setToken('');setMe(null);setJobs([]);setAccess(null);setActiveJob(null);
  }
  const historical=me?.assessments&&!Array.isArray(me.assessments)?Object.entries(me.assessments).filter(([id])=>!jobs.some(job=>job.id===id)):[];
  if(access)return <AIDemo linkedAccess={access} linkedOpportunity={activeJob?{title:activeJob.title,company_name:activeJob.company_name}:undefined} mediaStream={stream||undefined} onExit={leaveInterview}/>;
  return <div className="market">
    <header className="market-header"><a href="/" className="brand-word">mimas.</a><nav><a href="/" className="text-link"><ArrowLeft size={16}/> На главную</a><a href="/?view=employer" className="text-link">Для компаний <ArrowRight size={16}/></a></nav></header>
    <main className="market-main"><span className="eyebrow">MIMAS · КАНДИДАТ</span><h1>Покажите навыки раньше резюме.</h1><p className="muted">Выберите вакансию и пройдите интервью по её требованиям. Для каждой вакансии будет своё техническое интервью и отдельный отчёт.</p>
      {error&&<div role="alert" className="error-box">{error}</div>}
      {!loaded?<p>Загрузка…</p>:!token?<section className="card market-form"><h2>Профиль разработчика</h2><p className="note">Доступ к профилю хранится в этом браузере. Пока поддерживается специализация Python Backend.</p>
        <form onSubmit={register}><label>Имя или псевдоним<input required minLength={2} maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label>
          <div className="market-fields"><label>Уровень<select value={level} onChange={e=>setLevel(e.target.value as Level)}><option value="junior">Junior</option><option value="middle">Middle</option><option value="senior">Senior</option></select></label><label>Опыт, лет<input type="number" min="0" max="60" step="0.5" value={years} onChange={e=>setYears(e.target.value)}/></label></div>
          <label>Стек через запятую<input required value={stack} onChange={e=>setStack(e.target.value)}/></label>
          <div className="market-fields"><label>GitHub или GitLab, необязательно<input type="url" placeholder="https://github.com/..." value={github} onChange={e=>setGithub(e.target.value)}/></label><label>Желаемая зарплата, ₽, необязательно<input type="number" min="0" value={salaryWish} onChange={e=>setSalaryWish(e.target.value)}/></label></div>
          <button className="primary" disabled={busy}>{busy?<Loader2 className="spin" size={17}/>:<ArrowRight size={17}/>} Найти вакансии</button></form>
      </section>:!me?<p>Загружаем профиль…</p>:<>
        <section className="card market-profile"><div><span className="eyebrow">ВАШ ПРОФИЛЬ</span><h2>{me.profile.name}</h2><p className="muted">Python Backend · {levelLabels[me.profile.level]} · опыт: {me.profile.years_experience} лет</p><div className="tags">{me.profile.stack.map(item=><span key={item}>{item}</span>)}</div></div><button className="secondary" onClick={logout}>Выйти из профиля</button></section>
        <section className="market-section"><div className="market-heading"><div><span className="eyebrow">01 / ВАКАНСИИ</span><h2>Что вам подходит</h2></div><span className="badge">{jobs.filter(item=>item.match?.compatible).length} подходят из {jobs.length}</span></div>
          {jobs.length===0?<div className="card market-empty"><BriefcaseBusiness size={26}/><h3>Пока нет вакансий с утверждённым интервью</h3><p className="muted">Новые вакансии появятся здесь после проверки вопросов работодателем.</p></div>:<div className="market-list">{jobs.map(job=>{
            const assessment=assessmentFor(me,job.id);
            const done=Boolean(assessment?.report);
            const interested=Boolean(job.interested||me.interested_opportunity_ids.includes(job.id));
            return <article className="card market-opportunity" key={job.id}><div className="market-item-top"><span className="eyebrow">{job.company_name}</span><div className="market-statuses"><span className="badge">{job.employment_type==='contract'?'Проектная работа':'Полная занятость'}</span><span className={job.match?.compatible?'badge green':'badge'}>{job.match?.compatible?'Подходит':'Проверьте условия'}</span></div></div>
              <h3>{job.title}</h3><p className="muted">{job.description}</p><p><strong>{salaryRange(job.salary_min_rub,job.salary_max_rub)}</strong> · {levelLabels[job.level]}</p><div className="tags">{job.stack.map(value=><span key={value}>{value}</span>)}</div><p className="market-reasons">{job.match?.reasons.join(' · ')}</p>
              {!interested?<button className="primary" disabled={busy} onClick={()=>void select(job)}>Выбрать вакансию <ArrowRight size={16}/></button>:done?<button className="secondary" disabled={busy} onClick={()=>void openInterview(job,true)}>Открыть мой отчёт <ArrowRight size={16}/></button>:<button className="primary" disabled={busy} onClick={()=>{setConsentJob(job);setConsent(false);}}>{assessment?'Продолжить интервью':'Начать интервью'} <ArrowRight size={16}/></button>}
            </article>;
          })}</div>}
        </section>
        {historical.length>0&&<section className="market-section"><div className="market-heading"><div><span className="eyebrow">02 / ИСТОРИЯ</span><h2>Мои прежние интервью</h2></div></div><div className="market-list">{historical.map(([id,assessment])=>{const past=me.assessment_opportunities?.[id]||{id,title:'Вакансия больше не опубликована',company_name:'Компания',status:'closed'};const done=Boolean(assessment.report||assessment.phase==='COMPLETED'||assessment.status==='completed');return <article className="card market-opportunity" key={id}><span className="eyebrow">{past.company_name}</span><h3>{past.title}</h3><span className="badge">{past.status==='closed'?'Вакансия закрыта':'Вакансия недоступна'}</span><p className="muted">Ваше интервью и отчёт сохраняются даже после закрытия вакансии.</p>{done?<button className="secondary" disabled={busy} onClick={()=>void openInterview(past,true)}>Открыть отчёт <ArrowRight size={16}/></button>:<button className="secondary" disabled={busy} onClick={()=>{setConsentJob(past);setConsent(false);}}>Продолжить интервью <ArrowRight size={16}/></button>}</article>;})}</div></section>}
        {consentJob&&<section className="card market-assessment" aria-labelledby="market-consent-title"><span className="eyebrow">02 / ПЕРЕД ИНТЕРВЬЮ</span><h2 id="market-consent-title">{consentJob.title} · {consentJob.company_name}</h2><p className="muted">MIMAS включит камеру и микрофон, запишет видео и ответы, передаст их для AI-оценки. Отчёт и запись смогут просматривать вы и компания «{consentJob.company_name}». Запись удаляется через 30 дней, текстовый отчёт сохраняется. Окончательное решение о найме принимает человек.</p>
          <label className="market-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> Я согласен(на) на запись интервью и передачу результата этой компании.</label>
          <div className="button-row"><button className="primary" disabled={busy||!consent} onClick={()=>void openInterview(consentJob)}>{busy?<Loader2 size={17} className="spin"/>:<Video size={17}/>} Разрешить камеру и начать</button><button className="secondary" disabled={busy} onClick={()=>setConsentJob(null)}>Отмена</button></div>
          <p className="tiny muted">Если доступ к камере или микрофону запрещён, интервью не начнётся. Распознанный текст ответа можно исправить перед отправкой.</p>
        </section>}
      </>}
      <p className="market-footer"><ShieldCheck size={15}/> AI-оценка носит предварительный характер.</p>
    </main></div>;
}
