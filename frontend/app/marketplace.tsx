'use client';

import {useCallback, useEffect, useState} from 'react';
import {ArrowLeft, ArrowRight, BriefcaseBusiness, CheckCircle2, Loader2, ShieldCheck} from 'lucide-react';
import AIDemo from './ai-demo';
import type {Access, Session} from './ai-session';

type Level = 'junior'|'middle'|'senior';
type Profile = {id:string;name:string;role:string;level:Level;stack:string[];years_experience:number;github_url:string|null;desired_salary_rub:number|null;discoverable:boolean};
type Match = {score:number;reasons:string[];stack_overlap:number;level_match:boolean;salary_match:boolean;compatible:boolean};
type Opportunity = {id:string;company_name:string;title:string;description:string;role:string;level:Level;stack:string[];salary_min_rub:number|null;salary_max_rub:number|null;employment_type:'full_time'|'contract';status:string;match?:Match;interested?:boolean};
type MyProfile = {profile:Profile;interested_opportunity_ids:string[];assessment:Session|null};
type CandidateResult = {profile:Profile;assessment_id:string;summary:string;skills:{skill:string;demonstrated_level:string|null;status:string;answers_received:number;evaluated_answers:number;evidence:{id:string;type:string;claim:string;quote:string;question_text:string}[]}[];quality_status:string;match?:Match;interested?:boolean};

class MarketError extends Error {constructor(public status:number,message:string){super(message);this.name='MarketError';}}

async function market<T>(path:string, options:{method?:string;token?:string;key?:string;body?:unknown} = {}):Promise<T> {
  const response = await fetch('/api/market'+path,{method:options.method||'GET',headers:{'Content-Type':'application/json',...(options.token?{'X-Candidate-Token':options.token}:{}),...(options.key?{'X-Company-Key':options.key}:{})},body:options.body===undefined?undefined:JSON.stringify(options.body),cache:'no-store'});
  if(!response.ok){const body=await response.json().catch(()=>({}));throw new MarketError(response.status,typeof body.detail==='string'?body.detail:'Ошибка сервера ('+response.status+')');}
  return response.json();
}
const salary=(value:number|null)=>value===null?'не указана':new Intl.NumberFormat('ru-RU').format(value)+' ₽';
const salaryRange=(min:number|null,max:number|null)=>min!==null&&max!==null?salary(min)+' — '+salary(max):min!==null?'от '+salary(min):max!==null?'до '+salary(max):'Зарплата не указана';
const labels:Record<Level,string>={junior:'Junior',middle:'Middle',senior:'Senior'};
const skillNames:Record<string,string>={'python.core':'Python Core','python.oop':'ООП','python.asyncio':'AsyncIO','web.http':'HTTP / REST','db.postgresql':'PostgreSQL','cs.algorithms':'Алгоритмы','engineering.debugging':'Отладка'};

export function CandidateHub(){
  const [token,setToken]=useState('');
  const [loaded,setLoaded]=useState(false);
  const [me,setMe]=useState<MyProfile|null>(null);
  const [opportunities,setOpportunities]=useState<Opportunity[]>([]);
  const [access,setAccess]=useState<Access|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [name,setName]=useState('');
  const [level,setLevel]=useState<Level>('middle');
  const [stack,setStack]=useState('Python, FastAPI, PostgreSQL');
  const [years,setYears]=useState('2');
  const [github,setGithub]=useState('');
  const [salaryWish,setSalaryWish]=useState('');

  useEffect(()=>{setToken(localStorage.getItem('mimas-candidate-token')||'');setLoaded(true);},[]);
  const refresh=useCallback(async (auth:string)=>{
    const [profile,rows]=await Promise.all([market<MyProfile>('/me',{token:auth}),market<Opportunity[]>('/opportunities',{token:auth})]);
    setMe(profile);setOpportunities(rows);
  },[]);
  useEffect(()=>{if(token)void refresh(token).catch(e=>{if(e instanceof MarketError&&e.status===401){localStorage.removeItem('mimas-candidate-token');setToken('');setMe(null);setOpportunities([]);setError('Профиль недоступен. Создайте новый.');}else setError((e as Error).message);});},[token,refresh]);

  async function register(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError('');
    try {
      const result=await market<{token:string}>('/candidates',{method:'POST',body:{name,level,stack:stack.split(',').map(x=>x.trim()).filter(Boolean),years_experience:Number(years),github_url:github||null,desired_salary_rub:salaryWish?Number(salaryWish):null}});
      localStorage.setItem('mimas-candidate-token',result.token);setToken(result.token);
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function select(id:string){
    setBusy(true);setError('');
    try{await market('/opportunities/'+id+'/interest',{method:'POST',token,body:{}});await refresh(token);}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function startAssessment(){
    setBusy(true);setError('');
    try {
      const result=await fetch('/api/ai/sessions',{method:'POST',headers:{'X-Candidate-Token':token,'Content-Type':'application/json'},body:'{}'});
      const body=await result.json().catch(()=>({}));
      if(!result.ok)throw new Error(typeof body.detail==='string'?body.detail:'Не удалось создать интервью');
      setAccess(body as Access);
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function setVisibility(value:boolean){
    setBusy(true);setError('');
    try{await market('/me',{method:'PATCH',token,body:{discoverable:value}});await refresh(token);}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  function leave(){localStorage.removeItem('mimas-candidate-token');setToken('');setMe(null);setOpportunities([]);setAccess(null);}
  if(access)return <AIDemo linkedAccess={access} onExit={()=>{setAccess(null);void refresh(token).catch(e=>setError((e as Error).message));}}/>;
  return <div className="market"><header className="market-header"><a href="/" className="brand-word">mimas.</a><nav><a href="/" className="text-link"><ArrowLeft size={16}/> На главную</a><a href="/?view=employer" className="text-link">Для компаний <ArrowRight size={16}/></a></nav></header>
    <main className="market-main"><span className="eyebrow">MIMAS · КАНДИДАТ</span><h1>Покажите навыки раньше резюме.</h1><p className="muted">Создайте профиль, выберите интересные возможности и пройдите одно техническое интервью для будущих проектов.</p>
      {error&&<div role="alert" className="error-box">{error}</div>}
      {!loaded?<p>Загрузка…</p>:!token?<section className="card market-form"><h2>Профиль разработчика</h2><p className="note">Пока поддерживается специализация Python Backend. Для прототипа используйте тестовые данные. Доступ к профилю будет храниться только в этом браузере.</p>
        <form onSubmit={register}><label>Имя или псевдоним<input required minLength={2} maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label>
          <div className="market-fields"><label>Уровень<select value={level} onChange={e=>setLevel(e.target.value as Level)}><option value="junior">Junior</option><option value="middle">Middle</option><option value="senior">Senior</option></select></label><label>Опыт, лет<input type="number" min="0" max="60" step="0.5" value={years} onChange={e=>setYears(e.target.value)}/></label></div>
          <label>Стек через запятую<input required value={stack} onChange={e=>setStack(e.target.value)}/></label>
          <div className="market-fields"><label>GitHub или GitLab, необязательно<input type="url" placeholder="https://github.com/..." value={github} onChange={e=>setGithub(e.target.value)}/></label><label>Желаемая зарплата, ₽, необязательно<input type="number" min="0" value={salaryWish} onChange={e=>setSalaryWish(e.target.value)}/></label></div>
          <button className="primary" disabled={busy}>{busy?<Loader2 className="spin" size={17}/>:<ArrowRight size={17}/>} Найти возможности</button></form>
      </section>:!me?<p>Загружаем профиль…</p>:<>
        <section className="card market-profile"><div><span className="eyebrow">ВАШ ПРОФИЛЬ</span><h2>{me.profile.name}</h2><p className="muted">Python Backend · {labels[me.profile.level]} · {me.profile.years_experience} года опыта</p><div className="tags">{me.profile.stack.map(item=><span key={item}>{item}</span>)}</div></div><button className="secondary" onClick={leave}>Выйти из профиля</button></section>
        <section className="market-section"><div className="market-heading"><div><span className="eyebrow">01 / ВОЗМОЖНОСТИ</span><h2>Что вам подходит</h2></div><span className="badge">{opportunities.filter(item=>item.match?.compatible).length} подходит из {opportunities.length}</span></div>
          {opportunities.length===0?<div className="card market-empty"><BriefcaseBusiness size={26}/><h3>Пока нет опубликованных вакансий</h3><p className="muted">Мы покажем только предложения, которые добавили работодатели. Число совпадений не создаётся искусственно.</p></div>:<div className="market-list">{opportunities.map(item=><article className="card market-opportunity" key={item.id}><div className="market-item-top"><span className="eyebrow">{item.company_name}</span><div className="market-statuses"><span className="badge">{item.employment_type==='contract'?'Проектная работа':'Полная занятость'}</span><span className={item.match?.compatible?'badge green':'badge'}>{item.match?.compatible?'Подходит':'Проверьте условия'}</span></div></div><h3>{item.title}</h3><p className="muted">{item.description}</p><p><strong>{salaryRange(item.salary_min_rub,item.salary_max_rub)}</strong> · {labels[item.level]}</p><div className="tags">{item.stack.map(value=><span key={value}>{value}</span>)}</div><p className="market-reasons">{item.match?.reasons.join(' · ')}</p><button className={item.interested?'secondary':'primary'} disabled={busy||item.interested} onClick={()=>void select(item.id)}>{item.interested?<><CheckCircle2 size={16}/> Интересует вас</>:<>Выбрать возможность <ArrowRight size={16}/></>}</button></article>)}</div>}
        </section>
        <section className="card market-assessment"><span className="eyebrow">02 / ОДНО ИНТЕРВЬЮ</span><h2>{me.assessment?.report?'Ваш профиль навыков готов':me.assessment?'Продолжить оценку навыков':'Подтвердите навыки один раз'}</h2><p className="muted">Технический диалог по Python Backend. Отчёт содержит конкретные ответы и доказательства; выводы предварительные.</p><button className="primary" disabled={busy||me.interested_opportunity_ids.length===0} onClick={()=>void startAssessment()}>{busy?<Loader2 className="spin" size={17}/>:<ArrowRight size={17}/>} {me.assessment?.report?'Открыть отчёт':me.assessment?'Продолжить интервью':'Начать MIMAS Assessment'}</button>{me.interested_opportunity_ids.length===0&&<p className="tiny muted">Сначала выберите хотя бы одну возможность.</p>}</section>
        {me.assessment?.report&&<section className="card market-discovery"><span className="eyebrow">03 / ПОИСК КОМПАНИЯМИ</span><h2>Открыть профиль работодателям?</h2><p className="muted">После согласия работодатели с доступом к MIMAS увидят ваше имя, стек, опыт, ожидания, портфолио и предварительный профиль навыков с выдержками из ответов. Вы можете закрыть доступ здесь в любой момент.</p><button className="secondary" disabled={busy} onClick={()=>void setVisibility(!me.profile.discoverable)}>{me.profile.discoverable?'Скрыть профиль от компаний':'Показывать мой профиль компаниям'}</button><span className="badge">{me.profile.discoverable?'Профиль открыт':'Профиль закрыт'}</span></section>}
      </>}
      <p className="market-footer"><ShieldCheck size={15}/> Оценка не заменяет решение человека о найме.</p>
    </main></div>;
}

export function EmployerHub(){
  const [key,setKey]=useState('');
  const [keyInput,setKeyInput]=useState('');
  const [opportunities,setOpportunities]=useState<Opportunity[]>([]);
  const [candidates,setCandidates]=useState<CandidateResult[]>([]);
  const [selected,setSelected]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [companyName,setCompanyName]=useState('');
  const [title,setTitle]=useState('');
  const [description,setDescription]=useState('');
  const [level,setLevel]=useState<Level>('middle');
  const [stack,setStack]=useState('Python, FastAPI, PostgreSQL');
  const [salaryMin,setSalaryMin]=useState('');
  const [salaryMax,setSalaryMax]=useState('');
  const [employment,setEmployment]=useState<'full_time'|'contract'>('full_time');
  const load=useCallback(async(auth:string, opportunityId='')=>{
    const [jobs,people]=await Promise.all([market<Opportunity[]>('/company/opportunities',{key:auth}),market<CandidateResult[]>('/company/candidates'+(opportunityId?'?opportunity_id='+encodeURIComponent(opportunityId):''),{key:auth})]);
    setOpportunities(jobs);setCandidates(people);
  },[]);
  useEffect(()=>{const saved=sessionStorage.getItem('company-key');if(saved){setKeyInput(saved);void load(saved).then(()=>setKey(saved)).catch(e=>{if(e instanceof MarketError&&e.status===401){sessionStorage.removeItem('company-key');setKeyInput('');}setError((e as Error).message);});}},[load]);
  async function login(event:React.FormEvent){event.preventDefault();setBusy(true);setError('');try{await load(keyInput);sessionStorage.setItem('company-key',keyInput);setKey(keyInput);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function publish(event:React.FormEvent){event.preventDefault();setBusy(true);setError('');try{
    await market('/company/opportunities',{method:'POST',key,body:{company_name:companyName,title,description,level,stack:stack.split(',').map(x=>x.trim()).filter(Boolean),salary_min_rub:salaryMin?Number(salaryMin):null,salary_max_rub:salaryMax?Number(salaryMax):null,employment_type:employment}});
    setTitle('');setDescription('');await load(key,selected);
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  async function changeStatus(item:Opportunity){setBusy(true);setError('');try{await market('/company/opportunities/'+item.id,{method:'PATCH',key,body:{status:item.status==='open'?'closed':'open'}});await load(key,selected);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  function logout(){sessionStorage.removeItem('company-key');setKey('');setKeyInput('');setOpportunities([]);setCandidates([]);setSelected('');setError('');}
  async function choose(id:string){setSelected(id);try{await load(key,id);}catch(e){setError((e as Error).message);}}
  return <div className="market"><header className="market-header"><a href="/" className="brand-word">mimas.</a><nav><a href="/" className="text-link"><ArrowLeft size={16}/> На главную</a><a href="/?view=candidate" className="text-link">Для кандидатов <ArrowRight size={16}/></a></nav></header><main className="market-main"><span className="eyebrow">MIMAS · КОМПАНИЯ</span><h1>Находите навыки с основаниями.</h1><p className="muted">Опубликуйте реальную возможность и смотрите профили кандидатов, разрешивших поиск после технического интервью.</p>{error&&<div role="alert" className="error-box">{error}</div>}
    {!key?<section className="card market-form"><h2>Вход команды</h2><form onSubmit={login}><label>Ключ команды<input type="password" required value={keyInput} onChange={e=>setKeyInput(e.target.value)}/></label><button className="primary" disabled={busy}>Открыть кабинет <ArrowRight size={16}/></button></form></section>:<>
      <div className="market-heading"><div><span className="eyebrow">01 / ВАКАНСИИ</span><h2>Опубликованные возможности</h2></div><div className="market-statuses"><button className="secondary" onClick={()=>void load(key,selected)}>Обновить</button><button className="secondary" onClick={logout}>Выйти</button></div></div>
      <div className="market-list">{opportunities.length===0?<div className="card market-empty">Пока нет опубликованных вакансий.</div>:opportunities.map(item=><article key={item.id} className="card market-opportunity"><span className="eyebrow">{item.company_name}</span><h3>{item.title}</h3><p className="muted">{item.description}</p><div className="tags">{item.stack.map(value=><span key={value}>{value}</span>)}</div><p className="tiny muted">{item.status==='open'?'Приём открыт':'Вакансия закрыта'}</p><button className="secondary" disabled={busy} onClick={()=>void changeStatus(item)}>{item.status==='open'?'Закрыть вакансию':'Открыть снова'}</button></article>)}</div>
      <section className="card market-form"><span className="eyebrow">НОВАЯ ВОЗМОЖНОСТЬ</span><h2>Опубликовать вакансию</h2><form onSubmit={publish}><div className="market-fields"><label>Компания<input required value={companyName} onChange={e=>setCompanyName(e.target.value)}/></label><label>Название вакансии<input required value={title} onChange={e=>setTitle(e.target.value)}/></label></div><label>Описание<textarea required minLength={10} maxLength={4000} value={description} onChange={e=>setDescription(e.target.value)}/></label><div className="market-fields"><label>Уровень<select value={level} onChange={e=>setLevel(e.target.value as Level)}><option value="junior">Junior</option><option value="middle">Middle</option><option value="senior">Senior</option></select></label><label>Формат<select value={employment} onChange={e=>setEmployment(e.target.value as 'full_time'|'contract')}><option value="full_time">Полная занятость</option><option value="contract">Проектная работа</option></select></label></div><label>Стек через запятую<input required value={stack} onChange={e=>setStack(e.target.value)}/></label><div className="market-fields"><label>Зарплата от, ₽<input type="number" min="0" value={salaryMin} onChange={e=>setSalaryMin(e.target.value)}/></label><label>Зарплата до, ₽<input type="number" min="0" value={salaryMax} onChange={e=>setSalaryMax(e.target.value)}/></label></div><button className="primary" disabled={busy}>Опубликовать <ArrowRight size={16}/></button></form></section>
      <section className="market-section"><div className="market-heading"><div><span className="eyebrow">02 / КАНДИДАТЫ</span><h2>Профили после интервью</h2></div><select aria-label="Фильтр по вакансии" value={selected} onChange={e=>void choose(e.target.value)}><option value="">Все кандидаты</option>{opportunities.map(item=><option value={item.id} key={item.id}>{item.title} · {item.company_name}</option>)}</select></div><p className="note">Виден только кандидат, который завершил AI-интервью и согласился открыть профиль. Выводы об уровне предварительные; решение принимает человек.</p><div className="market-list">{candidates.length===0?<div className="card market-empty">Пока нет открытых профилей с завершённым интервью.</div>:candidates.map(person=><article className="card market-person" key={person.profile.id}><div className="market-item-top"><div><h3>{person.profile.name}</h3><p className="muted">Python Backend · {labels[person.profile.level]} · {person.profile.years_experience} года опыта</p></div>{person.interested&&<span className="badge green">Выбрал вакансию</span>}</div><p>{person.summary}</p><div className="tags">{person.profile.stack.map(item=><span key={item}>{item}</span>)}</div>{person.profile.github_url&&<a className="text-link" href={person.profile.github_url} target="_blank" rel="noreferrer">Портфолио <ArrowRight size={15}/></a>}<p className="tiny muted">Зарплатное ожидание: {salary(person.profile.desired_salary_rub)}</p>{person.skills.map(skill=><details className="market-skill" key={skill.skill}><summary>{skillNames[skill.skill]||skill.skill} · {skill.demonstrated_level||'Недостаточно данных'} · ответов: {skill.evaluated_answers}/{skill.answers_received}</summary>{skill.evidence.length===0?<p>Проверенных оснований пока нет.</p>:skill.evidence.map(e=><blockquote key={e.id}>{e.question_text&&<><span className="market-skill-question">Вопрос: {e.question_text}</span><br/></>}<strong>{e.claim}</strong><br/>{e.quote}</blockquote>)}</details>)}</article>)}</div></section>
    </>}</main></div>;
}
