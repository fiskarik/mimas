'use client';

import {useCallback,useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,CheckCircle2,Copy,FileText,Loader2,ShieldCheck,UploadCloud,Video} from 'lucide-react';
import {levelLabels,market,MarketError,salary,skillNames,type CandidateResult,type Level,type Opportunity} from './marketplace-api';
import {EmployerReport} from './employer-report';
import {BrandLogo} from './brand-logo';

type Skill = {id:string;name:string;concepts:string[];goals:string[];questions:string[];target_questions:number;evaluation_criteria?:string[]};
type Plan = {role:string;version:string;skills:Skill[]};
type InterviewSettings = {max_questions:number;max_follow_ups:number;duration_minutes:number};
type Template = {id:string;opportunity_id:string;version:number|string;status:string;plan:Plan;settings:InterviewSettings;created:number;approved?:number|null};
type CompanyApplication = {id:string;name:string;contact_email:string;status:string;created:number};
type ClaimStatus = {application_id:string;name:string;status:string};
type Profession = {id:string;name:string;description:string};
type GeneralCandidate = {candidate_name:string;profession_id:string;interested_in_your_vacancy:boolean;level:Level;years_experience:number;rating:{score:number|null;assessed_answers:number;total_answers:number;max_score:number;provisional:boolean};skills:{name:string;status:string;answers_received:number}[];summary:string};
const defaultStack='Сварщик, ручная дуговая сварка, чтение чертежей, охрана труда';
const clone=<T,>(value:T):T=>JSON.parse(JSON.stringify(value));
const getError=(e:unknown)=>e instanceof Error?e.message:'Неизвестная ошибка';
function claimLink(token:string){return window.location.origin+'/?view=employer#claim='+encodeURIComponent(token);}
async function recordingUrl(sessionId:string,key:string){
  const response=await fetch('/api/ai/sessions/'+encodeURIComponent(sessionId)+'/recording/url',{headers:{'X-Company-Key':key},cache:'no-store'});
  if(!response.ok){const value=await response.json().catch(()=>({}));throw new Error(typeof value.detail==='string'?value.detail:'Запись пока недоступна');}
  const body=await response.json() as {url:string};return body.url;
}

function TemplateEditor({template,plan,onChange,readOnly}:{template:Template;plan:Plan;onChange:(plan:Plan)=>void;readOnly:boolean}){
  const editSkill=(index:number,patch:Partial<Skill>)=>{const next=clone(plan);next.skills[index]={...next.skills[index],...patch};onChange(next);};
  const editPair=(index:number,pair:number,field:'goals'|'questions',value:string)=>{const next=clone(plan);next.skills[index][field][pair]=value;onChange(next);};
  const addPair=(index:number)=>{const next=clone(plan);next.skills[index].goals.push('Новая цель проверки');next.skills[index].questions.push('Новый основной вопрос');onChange(next);};
  const removePair=(index:number,pair:number)=>{const next=clone(plan);if(next.skills[index].goals.length<=1)return;next.skills[index].goals.splice(pair,1);next.skills[index].questions.splice(pair,1);onChange(next);};
  const addSkill=()=>{const next=clone(plan);next.skills.push({id:'skill.custom'+(Date.now()%100000),name:'Новая компетенция',concepts:['Концепция'],goals:['Цель проверки'],questions:['Основной вопрос'],target_questions:1,evaluation_criteria:['Критерий оценки']});onChange(next);};
  return <div className="market-template"><div className="market-item-top"><div><span className="eyebrow">ШАБЛОН · ВЕРСИЯ {template.version}</span><h3>{readOnly?'Утверждённый план интервью':'Проверьте план интервью перед публикацией'}</h3></div><span className={readOnly?'badge green':'badge amber'}>{readOnly?'Утверждён':'Черновик'}</span></div>
    <p className="muted tiny">Это дополнительные вопросы только по узким требованиям вакансии. Не повторяйте базовые темы общего интервью по профессии. Проверьте рабочие ситуации и критерии оценки. Голосовой ответ не подтверждает практический навык или допуск к работе.</p>
    {plan.skills.map((skill,index)=><section className="market-skill-editor card" key={index}><div className="market-item-top"><span className="eyebrow">КОМПЕТЕНЦИЯ {index+1}</span>{!readOnly&&plan.skills.length>1&&<button type="button" className="text-link" onClick={()=>{const next=clone(plan);next.skills.splice(index,1);onChange(next);}}>Удалить</button>}</div>
      <div className="market-fields"><label>Название<input disabled={readOnly} value={skill.name} onChange={e=>editSkill(index,{name:e.target.value})}/></label><label>Идентификатор<input disabled={readOnly} value={skill.id} onChange={e=>editSkill(index,{id:e.target.value})}/></label></div>
      <label>Темы и рабочие ситуации через запятую<input disabled={readOnly} value={skill.concepts.join(', ')} onChange={e=>editSkill(index,{concepts:e.target.value.split(',').map(x=>x.trim()).filter(Boolean)})}/></label>
      <label>Критерии оценки, по одному в строке<textarea disabled={readOnly} value={(skill.evaluation_criteria||[]).join('\n')} onChange={e=>editSkill(index,{evaluation_criteria:e.target.value.split('\n').map(x=>x.trim()).filter(Boolean)})}/></label>
      <label>Целевое число вопросов<input type="number" min="1" max="5" disabled={readOnly} value={skill.target_questions} onChange={e=>editSkill(index,{target_questions:Number(e.target.value)})}/></label>
      <div className="market-pairs">{skill.goals.map((goal,pair)=><div className="market-pair" key={pair}><strong>Проверка {pair+1}</strong><label>Цель<textarea disabled={readOnly} value={goal} onChange={e=>editPair(index,pair,'goals',e.target.value)}/></label><label>Основной вопрос интервью<textarea disabled={readOnly} value={skill.questions[pair]||''} onChange={e=>editPair(index,pair,'questions',e.target.value)}/></label>{!readOnly&&skill.goals.length>1&&<button type="button" className="text-link" onClick={()=>removePair(index,pair)}>Удалить пару</button>}</div>)}</div>
      {!readOnly&&<button type="button" className="secondary" onClick={()=>addPair(index)}>Добавить цель и вопрос</button>}
    </section>)}
    {!readOnly&&<button type="button" className="secondary" onClick={addSkill}>Добавить компетенцию</button>}
  </div>;
}

function SettingsEditor({settings,onChange,readOnly}:{settings:InterviewSettings;onChange:(value:InterviewSettings)=>void;readOnly:boolean}){
  const change=(field:keyof InterviewSettings,value:number)=>onChange({...settings,[field]:value});
  return <section className="card market-skill-editor" aria-label="Настройки интервью">
    <span className="eyebrow">НАСТРОЙКИ ИНТЕРВЬЮ</span>
    <h3>Продолжительность и вопросы</h3>
    <p className="muted tiny">Параметры сохраняются в утверждённой версии. Начатые интервью не меняются после новой редакции.</p>
    <div className="market-fields">
      <label>Максимум вопросов<input type="number" min="1" max="20" required disabled={readOnly} value={settings.max_questions} onChange={e=>change('max_questions',Number(e.target.value))}/></label>
      <label>Уточнений на один вопрос<input type="number" min="0" max="2" required disabled={readOnly} value={settings.max_follow_ups} onChange={e=>change('max_follow_ups',Number(e.target.value))}/></label>
      <label>Время, минут<input type="number" min="5" max="20" required disabled={readOnly} value={settings.duration_minutes} onChange={e=>change('duration_minutes',Number(e.target.value))}/></label>
    </div>
    <p className="tiny muted">Интервью закончится после лимита времени или вопросов. Компания получает отчёт по ответам, которые кандидат успел дать.</p>
  </section>;
}

export function EmployerHub(){
  const [key,setKey]=useState('');
  const [keyInput,setKeyInput]=useState('');
  const [jobs,setJobs]=useState<Opportunity[]>([]);
  const [people,setPeople]=useState<CandidateResult[]>([]);
  const [professions,setProfessions]=useState<Profession[]>([]);
  const [ratingProfession,setRatingProfession]=useState('welder');
  const [generalCandidates,setGeneralCandidates]=useState<GeneralCandidate[]|null>(null);
  const [jobGeneralCandidates,setJobGeneralCandidates]=useState<GeneralCandidate[]>([]);
  const [selected,setSelected]=useState('');
  const [activePanel,setActivePanel]=useState<'template'|'candidates'>('template');
  const [template,setTemplate]=useState<Template|null>(null);
  const [plan,setPlan]=useState<Plan|null>(null);
  const [settings,setSettings]=useState<InterviewSettings|null>(null);
  const [dirty,setDirty]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [sourceMode,setSourceMode]=useState<'manual'|'paste'|'upload'>('manual');
  const [rawVacancy,setRawVacancy]=useState('');
  const [importedFile,setImportedFile]=useState('');
  const [title,setTitle]=useState('');
  const [description,setDescription]=useState('');
  const [level,setLevel]=useState<Level>('middle');
  const [stack,setStack]=useState(defaultStack);
  const [salaryMin,setSalaryMin]=useState('');
  const [salaryMax,setSalaryMax]=useState('');
  const [employment,setEmployment]=useState<'full_time'|'contract'>('full_time');
  const [companyName,setCompanyName]=useState('');
  const [contact,setContact]=useState('');
  const [claimToken,setClaimToken]=useState('');
  const [claimStatus,setClaimStatus]=useState<ClaimStatus|null>(null);
  const [claimKey,setClaimKey]=useState('');
  const [applicationLink,setApplicationLink]=useState('');
  const [adminKey,setAdminKey]=useState('');
  const [applications,setApplications]=useState<CompanyApplication[]>([]);
  const [videoUrls,setVideoUrls]=useState<Record<string,string>>({});
  const [openReport,setOpenReport]=useState('');
  const workbenchRef=useRef<HTMLElement>(null);

  const load=useCallback(async(auth:string,opportunityId='')=>{
    const [opportunities,candidates]=await Promise.all([
      market<Opportunity[]>('/company/opportunities',{key:auth}),
      market<CandidateResult[]>('/company/candidates'+(opportunityId?'?opportunity_id='+encodeURIComponent(opportunityId):''),{key:auth})
    ]);
    const vacancy=opportunities.find(item=>item.id===opportunityId);
    const general=vacancy?.profession_id?await market<GeneralCandidate[]>('/company/general-candidates?profession_id='+encodeURIComponent(vacancy.profession_id)+'&opportunity_id='+encodeURIComponent(vacancy.id),{key:auth}):[];
    setJobs(opportunities);setPeople(candidates);setJobGeneralCandidates(general);
  },[]);
  useEffect(()=>{
    const saved=sessionStorage.getItem('company-key');
    if(saved){setKeyInput(saved);void load(saved).then(()=>setKey(saved)).catch(e=>{if(e instanceof MarketError&&e.status===401){sessionStorage.removeItem('company-key');setKeyInput('');}setError(getError(e));});}
    const hash=new URLSearchParams(window.location.hash.slice(1));
    const fromLink=hash.get('claim');
    if(fromLink)setClaimToken(fromLink);
  },[load]);
  useEffect(()=>{if(claimToken)void market<ClaimStatus>('/companies/claim',{claimToken}).then(setClaimStatus).catch(e=>setError(getError(e)));},[claimToken]);
  useEffect(()=>{void market<Profession[]>('/professions').then(setProfessions).catch(()=>{});},[]);

  async function login(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError('');
    try{await load(keyInput);sessionStorage.setItem('company-key',keyInput);setKey(keyInput);}
    catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  async function apply(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError('');setNotice('');
    try{
      const result=await market<{application_id:string;claim_token:string}>('/companies/apply',{method:'POST',body:{name:companyName,contact_email:contact}});
      const link=claimLink(result.claim_token);setApplicationLink(link);setClaimToken(result.claim_token);
      window.location.hash='claim='+encodeURIComponent(result.claim_token);
      setNotice('Заявка отправлена. Сохраните приватную ссылку: по ней можно получить ключ после одобрения.');
    }catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  async function claim(){
    setBusy(true);setError('');try{
      const result=await market<{company_key:string}>('/companies/claim',{method:'POST',claimToken});
      setClaimKey(result.company_key);setKeyInput(result.company_key);setClaimStatus(s=>s?{...s,status:'claimed'}:s);
      window.location.hash='';
    }catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  async function listApplications(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError('');
    try{setApplications(await market<CompanyApplication[]>('/admin/companies',{adminKey}));}
    catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  async function approve(application:CompanyApplication){
    setBusy(true);setError('');try{
      await market('/admin/companies/'+application.id+'/approve',{method:'POST',adminKey,body:{}});
      setApplications(await market<CompanyApplication[]>('/admin/companies',{adminKey}));
    }catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  async function importFile(file:File|null){
    if(!file)return;setBusy(true);setError('');setNotice('');
    try{
      if(file.size>10_000_000)throw new Error('Размер файла не должен превышать 10 МБ.');
      const result=await market<{text:string}>('/company/opportunities/import',{method:'POST',key,file});
      setImportedFile(file.name);setDescription(result.text);setSourceMode('upload');
      setNotice('Текст извлечён. Проверьте и исправьте его перед созданием вакансии.');
    }catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  async function createJob(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError('');setNotice('');
    try{
      const job=await market<Opportunity>('/company/opportunities',{method:'POST',key,body:{title,description,level,stack:stack.split(',').map(x=>x.trim()).filter(Boolean),salary_min_rub:salaryMin?Number(salaryMin):null,salary_max_rub:salaryMax?Number(salaryMax):null,employment_type:employment}});
      setTitle('');setDescription('');setRawVacancy('');setImportedFile('');
      await load(key,job.id);await choose(job.id);
      setNotice('Вакансия сохранена. Для профессий пилота её можно открыть по общему интервью; если нужен узкий навык, добавьте и утвердите дополнительные вопросы.');
    }catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  async function choose(id:string,panel:'template'|'candidates'='template'){
    setSelected(id);setActivePanel(panel);setTemplate(null);setPlan(null);setSettings(null);setPeople([]);setJobGeneralCandidates([]);setDirty(false);setError('');
    if(id)window.requestAnimationFrame(()=>window.requestAnimationFrame(()=>{
      workbenchRef.current?.scrollIntoView({behavior:'smooth',block:'start'});
      workbenchRef.current?.focus({preventScroll:true});
    }));
    try{
      let job=jobs.find(item=>item.id===id);
      if(id&&!job){
        const latest=await market<Opportunity[]>('/company/opportunities',{key});
        setJobs(latest);job=latest.find(item=>item.id===id);
      }
      const [candidates,value,general]=await Promise.all([
        market<CandidateResult[]>('/company/candidates'+(id?'?opportunity_id='+encodeURIComponent(id):''),{key}),
        id?market<Template>('/company/opportunities/'+id+'/template',{key}).catch(e=>{if(e instanceof MarketError&&e.status===404)return null;throw e;}):Promise.resolve(null),
        job?.profession_id?market<GeneralCandidate[]>('/company/general-candidates?profession_id='+encodeURIComponent(job.profession_id)+'&opportunity_id='+encodeURIComponent(id),{key}):Promise.resolve([])
      ]);
      setPeople(candidates);setJobGeneralCandidates(general);setTemplate(value);setPlan(value?clone(value.plan):null);setSettings(value?clone(value.settings):null);
    }catch(e){setError(getError(e));}
  }
  async function generate(){
    if(!selected)return;setBusy(true);setError('');setNotice('');
    try{
      const value=await market<Template>('/company/opportunities/'+selected+'/template/draft',{method:'POST',key,body:{}});
      setTemplate(value);setPlan(clone(value.plan));setSettings(clone(value.settings));setDirty(false);
      setNotice('Черновик сгенерирован. Проверьте каждый вопрос и критерий.');
    }catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  async function saveDraft(){
    if(!selected||!plan||!settings)return null;
    const value=await market<Template>('/company/opportunities/'+selected+'/template/draft',{method:'PUT',key,body:{plan,settings}});
    setTemplate(value);setPlan(clone(value.plan));setSettings(clone(value.settings));setDirty(false);return value;
  }
  async function save(){setBusy(true);setError('');try{await saveDraft();setNotice('Правки сохранены. Шаблон пока не опубликован.');}catch(e){setError(getError(e));}finally{setBusy(false);}}
  async function approveTemplate(){
    if(!selected||!plan)return;setBusy(true);setError('');setNotice('');
    try{
      if(dirty)await saveDraft();
      const value=await market<Template>('/company/opportunities/'+selected+'/template/approve',{method:'POST',key,body:{}});
      setTemplate(value);setPlan(clone(value.plan));setSettings(clone(value.settings));setDirty(false);
      await load(key,selected);
      setNotice('Шаблон утверждён. Вакансия открыта кандидатам; начатые интервью сохранят эту версию.');
    }catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  async function reviseTemplate(){
    if(!selected)return;setBusy(true);setError('');setNotice('');
    try{
      const value=await market<Template>('/company/opportunities/'+selected+'/template/revision',{method:'POST',key,body:{}});
      setTemplate(value);setPlan(clone(value.plan));setSettings(clone(value.settings));setDirty(false);
      setNotice('Создана новая редакция. Измените вопросы и настройки, затем утвердите. Уже начатые интервью сохраняют прежнюю версию.');
    }catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  async function loadGeneralCandidates(){
    if(!key||!ratingProfession)return;
    setBusy(true);setError('');
    try{setGeneralCandidates(await market<GeneralCandidate[]>('/company/general-candidates?profession_id='+encodeURIComponent(ratingProfession),{key}));}
    catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  async function changeStatus(job:Opportunity){
    setBusy(true);setError('');try{
      await market('/company/opportunities/'+job.id,{method:'PATCH',key,body:{status:job.status==='open'?'closed':'open'}});
      await load(key,selected);
    }catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  async function openVideo(id:string){
    setBusy(true);setError('');try{const url=await recordingUrl(id,key);setVideoUrls(v=>({...v,[id]:url}));}
    catch(e){setError(getError(e));}finally{setBusy(false);}
  }
  function logout(){sessionStorage.removeItem('company-key');setKey('');setKeyInput('');setJobs([]);setPeople([]);setGeneralCandidates(null);setJobGeneralCandidates([]);setSelected('');setActivePanel('template');setTemplate(null);setPlan(null);setSettings(null);setError('');}
  const selectedJob=jobs.find(job=>job.id===selected);
  const locked=template?.status==='approved';
  const generalOnlyVacancy=Boolean(selectedJob?.profession_id&&!template&&selectedJob.status!=='draft');
  const candidatePanel=(
<section className="market-section" id="employer-results"><div className="market-heading"><div><span className="eyebrow">03 / КАНДИДАТЫ</span><h2>{generalOnlyVacancy?'Кандидаты по общей оценке':'Отчёты после интервью'}</h2></div><select aria-label="Фильтр по вакансии" value={selected} onChange={e=>void choose(e.target.value,'candidates')}><option value="">Все мои вакансии</option>{jobs.map(job=><option value={job.id} key={job.id}>{job.title}</option>)}</select></div><p className="note">{generalOnlyVacancy?'Здесь кандидаты, выбравшие эту вакансию и разрешившие показать предварительную общую оценку. Видео и полный ответ остаются у кандидата.':'Видны только кандидаты, давшие согласие на интервью по вашим вакансиям. Отчёт показывает знания и решения рабочих ситуаций; практические навыки и допуски проверяйте отдельно. Окончательное решение принимает человек.'}</p>
          <div className="market-list">{generalOnlyVacancy&&jobGeneralCandidates.map((person,index)=><article className="card market-person" key={person.profession_id+'-'+person.candidate_name+'-'+index}><div className="market-item-top"><div><span className="eyebrow">МЕСТО {index+1} · ОБЩЕЕ ИНТЕРВЬЮ</span><h3>{person.candidate_name}</h3><span className="badge green">Выбрал эту вакансию</span><p className="muted">{levelLabels[person.level]} · опыт: {person.years_experience} лет</p></div><span className="badge green">{person.rating.score===null?'Не оценено':person.rating.score+' / '+person.rating.max_score}</span></div><p className="muted">Оценено ответов: {person.rating.assessed_answers} из {person.rating.total_answers}. {person.summary}</p><div className="tags">{person.skills.map(skill=><span key={skill.name}>{skill.name}: {skill.status==='provisional'?'есть основания':'недостаточно данных'}</span>)}</div></article>)}{people.length===0&&(!generalOnlyVacancy||jobGeneralCandidates.length===0)?<div className="card market-empty"><h3>Пока нет завершённых интервью</h3><p>Кандидаты появятся здесь после согласия и завершённого интервью.</p><a className="text-link" href="/?view=candidate">Открыть кабинет кандидата <ArrowRight size={15}/></a></div>:people.map(person=>person.status==='recording_pending'?<article className="card market-person" key={person.assessment_id}><span className="eyebrow">ВИДЕО ЕЩЁ ЗАГРУЖАЕТСЯ</span><h3>{person.profile.name}</h3><p className="muted">Отчёт появится после завершения защищённой загрузки записи кандидатом.</p></article>:<article className="card market-person" key={person.assessment_id}><div className="market-item-top"><div><h3>{person.profile.name}</h3><p className="muted">{person.profile.role||person.profile.stack[0]||'Специалист'} · {levelLabels[person.profile.level]} · опыт: {person.profile.years_experience} лет</p></div>{person.interested&&<span className="badge green">Выбрал вакансию</span>}</div><p>{person.summary}</p><div className="tags">{person.profile.stack.map(item=><span key={item}>{item}</span>)}</div>{person.profile.github_url&&<a className="text-link" href={person.profile.github_url} target="_blank" rel="noreferrer">Портфолио <ArrowRight size={15}/></a>}<p className="tiny muted">Зарплатное ожидание: {salary(person.profile.desired_salary_rub)}</p>
            {person.skills.map(skill=><details className="market-skill" key={skill.skill}><summary>{skillNames[skill.skill]||skill.skill} · {skill.demonstrated_level||'Недостаточно данных'} · ответов: {skill.evaluated_answers}/{skill.answers_received}</summary>{skill.evidence.length===0?<p>Проверенных оснований пока нет.</p>:skill.evidence.map(e=><blockquote key={e.id}>{e.question_text&&<><span className="market-skill-question">Вопрос: {e.question_text}</span><br/></>}<strong>{e.claim}</strong><br/>{e.quote}</blockquote>)}</details>)}
            <button className="secondary" onClick={()=>setOpenReport(value=>value===person.assessment_id?'':person.assessment_id)}>{openReport===person.assessment_id?'Скрыть полный отчёт':'Открыть полный отчёт'}</button>{openReport===person.assessment_id&&<EmployerReport sessionId={person.assessment_id} companyKey={key}/>}<div className="market-video"><button className="secondary" disabled={busy} onClick={()=>void openVideo(person.assessment_id)}><Video size={15}/> {videoUrls[person.assessment_id]?'Обновить ссылку на запись':'Открыть запись'}</button>{videoUrls[person.assessment_id]&&<video controls preload="none" src={videoUrls[person.assessment_id]}>Браузер не поддерживает воспроизведение видео.</video>}</div>
          </article>)}</div>
        </section>
  );
  return <div className="market market--employer"><header className="market-header"><a href="/" className="brand-word" aria-label="MIMAS — на главную"><BrandLogo tone="light" width={145} className="market-brand-logo"/></a><nav><a href="/" className="text-link"><ArrowLeft size={16}/> На главную</a><a href="/?view=candidate" className="text-link">Для кандидатов <ArrowRight size={16}/></a></nav></header>
    <main className="market-main"><section className="market-intro" aria-labelledby="employer-intro-title"><div className="market-intro-copy"><span className="eyebrow">MIMAS · КОМПАНИЯ</span><h1 id="employer-intro-title">Находите мастеров <em>по знаниям.</em></h1><p>Опубликуйте вакансию сварщика, электрика, слесаря или токаря. Утвердите вопросы о профессии и рабочих ситуациях, затем изучите ответы кандидатов.</p></div><div className="market-intro-art" aria-hidden="true"><span className="market-intro-orbit"><BrandLogo tone="light" width={235} className="market-intro-logo"/></span><span className="market-intro-signal">ВОПРОСЫ · ОТВЕТЫ · КОНТЕКСТ</span></div></section>
    <nav className="market-quicklinks" aria-label="Разделы работодателя">{key?<><a href="#employer-general">01 · Общий рейтинг</a><a href="#employer-jobs">02 · Вакансии</a><a href="#employer-create">03 · Доп. вопросы</a><a href="#employer-results">04 · Кандидаты</a></>:<><a href="#employer-login">01 · Вход</a><a href="#employer-apply">02 · Заявка</a><a href="#employer-admin">03 · Проверка</a></>}</nav><div className="market-board">
      {error&&<div role="alert" className="error-box">{error}</div>}{notice&&<div role="status" className="note">{notice}</div>}
      {!key?<div className="market-onboard">
        {claimToken&&<section className="card market-form"><span className="eyebrow">ЗАЯВКА КОМПАНИИ</span><h2>{claimStatus?.name||companyName||'Проверяем статус'}</h2><p className="muted">Статус: {claimStatus?.status==='approved'?'одобрена':claimStatus?.status==='claimed'?'ключ получен':claimStatus?.status==='pending'?'на рассмотрении':claimStatus?.status||'загрузка…'}</p>
          {applicationLink&&<><label>Ваша приватная ссылка<input readOnly value={applicationLink}/></label><button className="secondary" onClick={()=>void navigator.clipboard.writeText(applicationLink)}><Copy size={15}/> Копировать ссылку</button></>}
          {claimStatus?.status==='approved'&&!claimKey&&<button className="primary" disabled={busy} onClick={()=>void claim()}>Получить ключ компании один раз <ArrowRight size={16}/></button>}
          {claimKey&&<div className="market-secret"><p className="note">Сохраните ключ сейчас. После закрытия страницы он больше не будет показан.</p><label>Ключ компании<input readOnly value={claimKey}/></label><button className="secondary" onClick={()=>void navigator.clipboard.writeText(claimKey)}><Copy size={15}/> Копировать ключ</button></div>}
          {claimStatus?.status==='pending'&&<button className="secondary" disabled={busy} onClick={()=>void market<ClaimStatus>('/companies/claim',{claimToken}).then(setClaimStatus).catch(e=>setError(getError(e)))}>Проверить статус</button>}
        </section>}
        <section className="card market-form" id="employer-login"><h2>Вход компании</h2><form onSubmit={login}><label>Личный ключ компании<input type="password" required value={keyInput} onChange={e=>setKeyInput(e.target.value)}/></label><button className="primary" disabled={busy}>Открыть кабинет <ArrowRight size={16}/></button></form></section>
        {!claimToken&&<section className="card market-form" id="employer-apply"><span className="eyebrow">НОВАЯ КОМПАНИЯ</span><h2>Подать заявку</h2><p className="muted">После ручного одобрения по приватной ссылке вы получите ключ доступа. Укажите рабочий адрес для связи; ключ по электронной почте не отправляется.</p><form onSubmit={apply}><label>Название компании<input required minLength={2} maxLength={100} value={companyName} onChange={e=>setCompanyName(e.target.value)}/></label><label>Контактный email<input type="email" required value={contact} onChange={e=>setContact(e.target.value)}/></label><button className="secondary" disabled={busy}>Отправить заявку</button></form></section>}
        <details className="card market-admin" id="employer-admin"><summary>Администрирование заявок</summary><form onSubmit={listApplications}><label>Ключ администратора<input type="password" required value={adminKey} onChange={e=>setAdminKey(e.target.value)}/></label><button className="secondary" disabled={busy}>Загрузить заявки</button></form>{applications.map(app=><div className="market-admin-row" key={app.id}><div><strong>{app.name}</strong><p className="tiny muted">{app.contact_email} · {app.status}</p></div>{app.status==='pending'&&<button className="secondary" disabled={busy} onClick={()=>void approve(app)}>Одобрить</button>}</div>)}</details>
      </div>:<>
        <section className="market-section" id="employer-general"><div className="market-heading"><div><span className="eyebrow">01 / ОБЩЕЕ ИНТЕРВЬЮ</span><h2>Рейтинг по профессии</h2></div></div>
          <p className="note">Здесь видны только кандидаты, которые завершили общее интервью и отдельно согласились показать предварительную оценку одобренным компаниям. Баллы относятся к устным ответам; практические навыки проверяются отдельно.</p>
          <div className="button-row"><label>Профессия<select value={ratingProfession} onChange={event=>{setRatingProfession(event.target.value);setGeneralCandidates(null);}}>{professions.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</select></label><button className="primary" disabled={busy||!ratingProfession} onClick={()=>void loadGeneralCandidates()}>{busy?<Loader2 className="spin" size={16}/>:<ArrowRight size={16}/>} Показать рейтинг</button></div>
          {generalCandidates!==null&&<div className="market-list">{generalCandidates.length===0?<div className="card market-empty">Пока нет завершённых общих интервью с разрешением на показ результата.</div>:generalCandidates.map((person,index)=><article className="card market-person" key={person.profession_id+'-'+person.candidate_name+'-'+index}><div className="market-item-top"><div><span className="eyebrow">МЕСТО {index+1} · ПРЕДВАРИТЕЛЬНО</span><h3>{person.candidate_name}</h3>{person.interested_in_your_vacancy&&<span className="badge green">Выбрал вашу вакансию</span>}<p className="muted">{levelLabels[person.level]} · опыт: {person.years_experience} лет</p></div><span className="badge green">{person.rating.score===null?'Не оценено':person.rating.score+' / '+person.rating.max_score}</span></div><p className="muted">Оценено ответов: {person.rating.assessed_answers} из {person.rating.total_answers}. {person.summary}</p><div className="tags">{person.skills.map(skill=><span key={skill.name}>{skill.name}: {skill.status==='provisional'?'есть основания':'недостаточно данных'}</span>)}</div></article>)}</div>}
        </section>
        <div className="market-heading" id="employer-jobs"><div><span className="eyebrow">01 / ВАКАНСИИ</span><h2>Ваши вакансии</h2></div><div className="market-statuses"><button className="secondary" onClick={()=>void load(key,selected)}>Обновить</button><button className="secondary" onClick={logout}>Выйти</button></div></div>
        <div className="market-list">{jobs.length===0?<div className="card market-empty">Создайте первую вакансию ниже.</div>:jobs.map(job=><article key={job.id} className={'card market-opportunity market-company-opportunity '+(selected===job.id?'market-selected':'')}><button type='button' className='market-opportunity-open' aria-label={'Открыть вакансию «'+job.title+'» и конструктор'} disabled={busy} onClick={()=>void choose(job.id)}/><span className="eyebrow">{job.company_name}</span><h3>{job.title}</h3><p className="muted">{job.description}</p><div className="tags">{job.stack.map(value=><span key={value}>{value}</span>)}</div><span className={job.status==='open'?'badge green':'badge amber'}>{job.status==='open'?'Открыта':job.status==='draft'?'Нужен утверждённый шаблон':'Закрыта'}</span><div className="button-row"><button className="secondary" disabled={busy} onClick={()=>void choose(job.id)}>Шаблон и кандидаты</button>{job.status!=='draft'&&<button className="secondary" disabled={busy} onClick={()=>void changeStatus(job)}>{job.status==='open'?'Закрыть вакансию':'Открыть снова'}</button>}</div></article>)}</div>
        <section className="card market-form" id="employer-create"><span className="eyebrow">НОВАЯ ВАКАНСИЯ</span><h2>Добавить вакансию</h2><div className="market-source-tabs" role="group" aria-label="Как добавить вакансию"><button type="button" className={sourceMode==='manual'?'secondary selected':'secondary'} onClick={()=>setSourceMode('manual')}>Вручную</button><button type="button" className={sourceMode==='paste'?'secondary selected':'secondary'} onClick={()=>setSourceMode('paste')}>Вставить текст</button><button type="button" className={sourceMode==='upload'?'secondary selected':'secondary'} onClick={()=>setSourceMode('upload')}>Загрузить файл</button></div>
          {sourceMode==='paste'&&<div className="market-import"><label>Текст вакансии<textarea value={rawVacancy} onChange={e=>setRawVacancy(e.target.value)} placeholder="Вставьте вакансию сюда…"/></label><button className="secondary" type="button" disabled={!rawVacancy.trim()} onClick={()=>{setDescription(rawVacancy);setNotice('Текст перенесён в описание. Проверьте его и заполните остальные поля.');}}>Перенести для проверки</button></div>}
          {sourceMode==='upload'&&<div className="market-import"><label>PDF, DOCX или изображение<input type="file" accept=".pdf,.docx,.png,.jpg,.jpeg,image/png,image/jpeg" disabled={busy} onChange={e=>void importFile(e.target.files?.[0]||null)}/></label>{importedFile&&<p className="tiny muted"><FileText size={14}/> Текст извлечён из файла: {importedFile}</p>}</div>}
          <form onSubmit={createJob}><label>Название вакансии<input required minLength={2} maxLength={120} value={title} onChange={e=>setTitle(e.target.value)} placeholder="Сварщик (ручная дуговая сварка)"/></label><label>Описание после проверки<textarea required minLength={10} maxLength={16000} value={description} onChange={e=>setDescription(e.target.value)} placeholder="Чтение чертежей, подготовка деталей, выбор режима сварки, безопасная организация рабочего места."/></label><p className="tiny muted">Исправьте ошибки распознавания и уберите личные данные перед генерацией теста.</p>
            <div className="market-fields"><label>Уровень опыта<select value={level} onChange={e=>setLevel(e.target.value as Level)}><option value="junior">{levelLabels.junior}</option><option value="middle">{levelLabels.middle}</option><option value="senior">{levelLabels.senior}</option></select></label><label>Формат<select value={employment} onChange={e=>setEmployment(e.target.value as 'full_time'|'contract')}><option value="full_time">Полная занятость</option><option value="contract">Проектная работа</option></select></label></div>
            <label>Профессия и навыки через запятую<input required value={stack} onChange={e=>setStack(e.target.value)} placeholder="Сварщик, ручная дуговая сварка, чтение чертежей"/></label><div className="market-fields"><label>Зарплата от, ₽<input type="number" min="0" value={salaryMin} onChange={e=>setSalaryMin(e.target.value)}/></label><label>Зарплата до, ₽<input type="number" min="0" value={salaryMax} onChange={e=>setSalaryMax(e.target.value)}/></label></div>
            <button className="primary" disabled={busy}>{busy?<Loader2 className="spin" size={16}/>:<UploadCloud size={16}/>} Сохранить черновик</button>
          </form>
        </section>
        {selectedJob&&<section ref={workbenchRef} tabIndex={-1} className="card market-form market-workbench"><span className="eyebrow">02 / ВАКАНСИЯ</span><h2>{selectedJob.title}</h2><div className="market-workbench-tabs" role="group" aria-label="Разделы вакансии"><button type="button" className={activePanel==='template'?'secondary selected':'secondary'} aria-pressed={activePanel==='template'} onClick={()=>setActivePanel('template')}>Шаблон</button><button type="button" className={activePanel==='candidates'?'secondary selected':'secondary'} aria-pressed={activePanel==='candidates'} onClick={()=>setActivePanel('candidates')}>Кандидаты ({generalOnlyVacancy?jobGeneralCandidates.length:people.length})</button></div>{activePanel==='candidates'?candidatePanel:!template?<><p className="muted">Если для вакансии достаточно общего интервью по профессии, дополнительных вопросов не требуется. Для узких задач можно подготовить отдельный короткий шаблон; уже проверенные базовые темы не нужно повторять.</p><div className="button-row">{selectedJob.profession_id&&selectedJob.status==='draft'&&<button className="primary" disabled={busy} onClick={()=>void changeStatus(selectedJob)}>Открыть по общему интервью <ArrowRight size={16}/></button>}<button className="secondary" disabled={busy} onClick={()=>void generate()}>{busy?<Loader2 className="spin" size={16}/>:<ArrowRight size={16}/>} Добавить доп. вопросы</button></div></>:plan&&settings&&<><SettingsEditor settings={settings} readOnly={Boolean(locked)} onChange={next=>{setSettings(next);setDirty(true);}}/><TemplateEditor template={template} plan={plan} readOnly={Boolean(locked)} onChange={next=>{setPlan(next);setDirty(true);}}/><div className="button-row">{locked?<button className="secondary" disabled={busy} onClick={()=>void reviseTemplate()}>Изменить вопросы и настройки</button>:<><button className="secondary" disabled={busy||!dirty} onClick={()=>void save()}>Сохранить правки</button><button className="primary" disabled={busy} onClick={()=>void approveTemplate()}><CheckCircle2 size={16}/> Утвердить и открыть вакансию</button></>}</div></>}</section>}
        {!selectedJob&&candidatePanel}
      </>}
      <p className="market-footer"><ShieldCheck size={15}/> Доступ к отчётам ограничен владельцем вакансии.</p>
    </div></main>
  </div>;
}
