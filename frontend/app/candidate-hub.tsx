'use client';

import {useCallback,useEffect,useState} from 'react';
import {ArrowLeft,ArrowRight,BriefcaseBusiness,Loader2,ShieldCheck,Video} from 'lucide-react';
import AIDemo from './ai-demo';
import {BrandLogo} from './brand-logo';
import type {Access} from './ai-session';
import {assessmentFor,levelLabels,market,MarketError,salaryRange,type AssessmentView,type Level,type MyProfile,type Opportunity,type Profession} from './marketplace-api';
import type {SkillReport} from './ai-session';
import styles from './candidate-skills.module.css';

type CompletedSkillReport = {id:string;targetId:string;title:string;kind:'general'|'additional';skills:SkillReport[]};

function isCompleted(assessment:AssessmentView|null|undefined):boolean {
  return Boolean(assessment?.report&&assessment.phase==='COMPLETED');
}

function assessedSkills(assessment:AssessmentView|null|undefined):SkillReport[] {
  if(!assessment?.report||!isCompleted(assessment))return [];
  const report=assessment.report as {skills?:SkillReport[]};
  return Array.isArray(report.skills)?report.skills.filter(skill=>skill.answers_received>0):[];
}

function completedSkillReports(me:MyProfile,professions:Profession[],jobs:Opportunity[]):CompletedSkillReport[] {
  const general=Object.entries(me.general_assessments||{}).flatMap(([id,assessment])=>{
    if(!isCompleted(assessment))return [];
    const skills=assessedSkills(assessment);
    const name=professions.find(item=>item.id===id)?.name||me.profile.role||(assessment.report as {role?:string}).role||'Общее интервью';
    return [{id:'general:'+id,targetId:id,title:name,kind:'general' as const,skills}];
  });
  const opportunityAssessments:[string,AssessmentView][]=Array.isArray(me.assessments)
    ?me.assessments.flatMap(item=>item.opportunity_id?[[item.opportunity_id,item] as [string,AssessmentView]]:[])
    :Object.entries(me.assessments||{});
  const additional=opportunityAssessments.flatMap(([id,assessment])=>{
    if(!isCompleted(assessment))return [];
    const skills=assessedSkills(assessment);
    const title=jobs.find(item=>item.id===id)?.title||me.assessment_opportunities?.[id]?.title||'Дополнительное интервью';
    return [{id:'additional:'+id,targetId:id,title,kind:'additional' as const,skills}];
  });
  return [...general,...additional];
}

function demonstratedLevel(level:string|null):string {
  return level==='junior'||level==='middle'||level==='senior'?levelLabels[level]:'Недостаточно данных';
}

function mediaError(error:unknown):Error{
  const name=error instanceof DOMException?error.name:'';
  if(name==='NotAllowedError'||name==='PermissionDeniedError')return new Error('Разрешите доступ к камере и микрофону в браузере и Windows, затем повторите попытку.');
  if(name==='NotFoundError'||name==='DevicesNotFoundError')return new Error('Камера или микрофон не найдены. Подключите оба устройства и повторите попытку.');
  if(name==='NotReadableError'||name==='TrackStartError')return new Error('Камеру или микрофон не удалось запустить. Закройте другие приложения, использующие их, и попробуйте снова.');
  return new Error('Не удалось включить камеру и микрофон. Проверьте подключение и разрешения браузера.');
}

export function CandidateHub(){
  const [token,setToken]=useState('');
  const [loaded,setLoaded]=useState(false);
  const [me,setMe]=useState<MyProfile|null>(null);
  const [jobs,setJobs]=useState<Opportunity[]>([]);
  const [professions,setProfessions]=useState<Profession[]>([]);
  const [access,setAccess]=useState<Access|null>(null);
  const [activeJob,setActiveJob]=useState<Pick<Opportunity,'id'|'title'|'company_name'>|null>(null);
  const [activeGeneral,setActiveGeneral]=useState<Profession|null>(null);
  const [stream,setStream]=useState<MediaStream|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [consentJob,setConsentJob]=useState<Pick<Opportunity,'id'|'title'|'company_name'>|null>(null);
  const [consent,setConsent]=useState(false);
  const [consentProfession,setConsentProfession]=useState<Profession|null>(null);
  const [generalRecordingConsent,setGeneralRecordingConsent]=useState(false);
  const [generalShareConsent,setGeneralShareConsent]=useState(false);
  const [name,setName]=useState('');
  const [level,setLevel]=useState<Level>('middle');
  const [stack,setStack]=useState('Продавец-кассир, работа на кассе, обслуживание покупателей');
  const [years,setYears]=useState('2');
  const [salaryWish,setSalaryWish]=useState('');
  useEffect(()=>{setToken(localStorage.getItem('mimas-candidate-token')||'');setLoaded(true);},[]);
  const refresh=useCallback(async(auth:string)=>{
    const [profile,items,catalog]=await Promise.all([market<MyProfile>('/me',{token:auth}),market<Opportunity[]>('/opportunities',{token:auth}),market<Profession[]>('/professions')]);
    setMe(profile);setJobs(items);setProfessions(catalog);
  },[]);
  useEffect(()=>{if(token)void refresh(token).catch(e=>{
    if(e instanceof MarketError&&e.status===401){localStorage.removeItem('mimas-candidate-token');setToken('');setMe(null);setJobs([]);setError('Профиль недоступен. Создайте новый.');}
    else setError((e as Error).message);
  });},[token,refresh]);
  async function register(event:React.FormEvent){
    event.preventDefault();setBusy(true);setError('');
    try{
      const result=await market<{token:string}>('/candidates',{method:'POST',body:{name,level,stack:stack.split(',').map(x=>x.trim()).filter(Boolean),years_experience:Number(years),desired_salary_rub:salaryWish?Number(salaryWish):null}});
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
        if(!navigator.mediaDevices?.getUserMedia)throw new Error('Для голосового интервью нужен браузер с доступом к камере и микрофону.');
        try{
          camera=await navigator.mediaDevices.getUserMedia({
            video:{facingMode:'user'},
            audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1},
          });
        }catch(error){throw mediaError(error);}
        if(!camera.getVideoTracks().some(track=>track.readyState==='live'))throw new Error('Камера не подключена. Проверьте устройство и повторите попытку.');
        if(!camera.getAudioTracks().some(track=>track.readyState==='live'))throw new Error('Микрофон не подключён. Проверьте устройство и повторите попытку.');
      }
      const response=await fetch('/api/ai/sessions',{method:'POST',headers:{'X-Candidate-Token':token,'Content-Type':'application/json'},body:JSON.stringify({opportunity_id:job.id,consent:true}),cache:'no-store'});
      const body=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'Не удалось открыть интервью.');
      setStream(camera);setActiveJob(job);setActiveGeneral(null);setAccess(body as Access);setConsentJob(null);setConsent(false);
    }catch(e){camera?.getTracks().forEach(track=>track.stop());setError((e as Error).message);}finally{setBusy(false);}
  }
  async function openGeneralInterview(profession:Profession,finished=false){
    if(!finished&&!generalRecordingConsent){setError('Подтвердите согласие на запись перед общим интервью.');return;}
    setBusy(true);setError('');
    let camera:MediaStream|null=null;
    try{
      if(!finished){
        if(!navigator.mediaDevices?.getUserMedia)throw new Error('Для голосового интервью нужен браузер с доступом к камере и микрофону.');
        try{camera=await navigator.mediaDevices.getUserMedia({
          video:{facingMode:'user'},
          audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true,channelCount:1},
        });}catch(error){throw mediaError(error);}
        if(!camera.getVideoTracks().some(track=>track.readyState==='live'))throw new Error('Камера не подключена. Проверьте устройство и повторите попытку.');
        if(!camera.getAudioTracks().some(track=>track.readyState==='live'))throw new Error('Микрофон не подключён. Проверьте устройство и повторите попытку.');
      }
      const response=await fetch('/api/ai/general-sessions',{method:'POST',headers:{'X-Candidate-Token':token,'Content-Type':'application/json'},body:JSON.stringify({profession_id:profession.id,consent:true,share_with_companies:finished?Boolean(generalAssessment?.share_with_companies):generalShareConsent}),cache:'no-store'});
      const body=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'Не удалось открыть общее интервью.');
      setStream(camera);setActiveGeneral(profession);setActiveJob(null);setAccess(body as Access);
      setConsentProfession(null);setGeneralRecordingConsent(false);setGeneralShareConsent(false);
    }catch(e){camera?.getTracks().forEach(track=>track.stop());setError((e as Error).message);}finally{setBusy(false);}
  }
  async function changeGeneralSharing(professionId:string,share:boolean){
    setBusy(true);setError('');
    try{await market('/me/general-sharing',{method:'PATCH',token,body:{profession_id:professionId,share_with_companies:share}});await refresh(token);}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  function leaveInterview(){
    stream?.getTracks().forEach(track=>track.stop());setStream(null);setAccess(null);setActiveJob(null);setActiveGeneral(null);
    void refresh(token).catch(e=>setError((e as Error).message));
  }
  function logout(){
    stream?.getTracks().forEach(track=>track.stop());localStorage.removeItem('mimas-candidate-token');
    setToken('');setMe(null);setJobs([]);setAccess(null);setActiveJob(null);setActiveGeneral(null);setProfessions([]);
  }
  const selectedProfession=professions.find(item=>item.id===me?.profile.profession_id)||professions.find(item=>item.name.toLocaleLowerCase('ru-RU')===me?.profile.role?.toLocaleLowerCase('ru-RU'))||null;
  const profileProfessionId=me?.profile.profession_id||selectedProfession?.id||null;
  const generalAssessment=profileProfessionId?me?.general_assessments?.[profileProfessionId]:null;
  const hasSavedGeneralReport=Object.values(me?.general_assessments||{}).some(isCompleted);
  const generalDone=Boolean(generalAssessment?.report||hasSavedGeneralReport);
  const historical=me?.assessments&&!Array.isArray(me.assessments)?Object.entries(me.assessments).filter(([id])=>!jobs.some(job=>job.id===id)):[];
  const skillReports=me?completedSkillReports(me,professions,jobs):[];
  if(access)return <AIDemo linkedAccess={access} interviewKind={activeGeneral?'general':'additional'} linkedOpportunity={activeGeneral?{title:'Общее интервью · '+activeGeneral.name,company_name:'Отчёт по навыкам'}:activeJob?{title:activeJob.title,company_name:activeJob.company_name}:undefined} mediaStream={stream||undefined} onExit={leaveInterview}/>;
  return <div className="market market--candidate">
    <header className="market-header"><a href="/" className="brand-word" aria-label="MIMAS — на главную"><BrandLogo tone="light" width={145} className="market-brand-logo"/></a><nav><a href="/" className="text-link"><ArrowLeft size={16}/> На главную</a><a href="/?view=employer" className="text-link">Для компаний <ArrowRight size={16}/></a></nav></header>
    <main className="market-main"><section className="market-intro" aria-labelledby="candidate-intro-title"><div className="market-intro-copy"><span className="eyebrow">MIMAS · КАНДИДАТ</span><h1 id="candidate-intro-title">Расскажите, как вы <em>работаете.</em></h1><p>Пройдите одно общее интервью о работе в магазине или на складе, затем выберите вакансию. Компания сможет добавить вопросы по своим рабочим задачам.</p></div><div className="market-intro-art" aria-hidden="true"><span className="market-intro-orbit"><BrandLogo tone="light" width={235} className="market-intro-logo"/></span><span className="market-intro-signal">СЛУШАЮ · ДУМАЮ · ОТВЕЧАЮ</span></div></section>
    <nav className="market-quicklinks" aria-label="Этапы для кандидата"><a href="#candidate-profile">01 · Профиль</a><a href="#candidate-general">02 · Общее интервью</a><a href="#candidate-opportunities">03 · Вакансии</a><a href={consentJob ? "#candidate-interview" : "#candidate-opportunities"}>04 · Дополнительное</a></nav><div className="market-board">
      {error&&<div role="alert" className="error-box">{error}</div>}
      {!loaded?<p>Загрузка…</p>:!token?<section className="card market-form" id="candidate-profile"><h2>Профиль соискателя</h2><p className="note">Укажите направление работы первым пунктом: продавец-кассир, работник торгового зала, сборщик заказов или работник склада. Затем перечислите свой опыт через запятую. Это сведения анкеты; проверенные навыки появятся в профиле после интервью. Доступ к профилю хранится в этом браузере.</p>
        <form onSubmit={register}><label>Имя или псевдоним<input required minLength={2} maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label>
          <div className="market-fields"><label>Уровень опыта<select value={level} onChange={e=>setLevel(e.target.value as Level)}><option value="junior">{levelLabels.junior}</option><option value="middle">{levelLabels.middle}</option><option value="senior">{levelLabels.senior}</option></select></label><label>Опыт, лет<input type="number" min="0" max="60" step="0.5" value={years} onChange={e=>setYears(e.target.value)}/></label></div>
          <label>Направление работы и опыт через запятую<input required value={stack} onChange={e=>setStack(e.target.value)} placeholder="Продавец-кассир, работа на кассе, обслуживание покупателей"/></label>
          <label>Желаемая зарплата, ₽, необязательно<input type="number" min="0" value={salaryWish} onChange={e=>setSalaryWish(e.target.value)}/></label>
          <button className="primary" disabled={busy}>{busy?<Loader2 className="spin" size={17}/>:<ArrowRight size={17}/>} Найти вакансии</button></form>
      </section>:!me?<p>Загружаем профиль…</p>:<>
        <section className={`card market-profile ${styles.profile}`} id="candidate-profile">
          <div><span className="eyebrow">ВАШ ПРОФИЛЬ</span><h2>{me.profile.name}</h2><p className="muted">Указанный в анкете опыт: {me.profile.years_experience} лет</p></div>
          <button className="secondary" onClick={logout}>Выйти из профиля</button>
          <div className={styles.report}>
            <div className={styles.reportHeading}><div><span className="eyebrow">ПО РЕЗУЛЬТАТАМ СОБЕСЕДОВАНИЙ</span><h3>Отчёт по навыкам</h3></div><span className="badge">{skillReports.length} интервью</span></div>
            {skillReports.length===0
              ?<p className={styles.empty}>Пока нет завершённого интервью. После него здесь появятся навыки, по которым MIMAS получил ваши ответы. Если оценка не удалась, это будет видно отдельно.</p>
              :skillReports.map(result=><section className={styles.interview} key={result.id} aria-label={`${result.kind==='general'?'Общее':'Дополнительное'} интервью: ${result.title}`}>
                <div className={styles.interviewHeading}><span className="eyebrow">{result.kind==='general'?'ОБЩЕЕ ИНТЕРВЬЮ':'ДОПОЛНИТЕЛЬНОЕ ИНТЕРВЬЮ'}</span><h4>{result.title}</h4></div>
                {result.skills.length===0?<p className={styles.empty}>В отчёте нет навыков с сохранёнными ответами. Подробности доступны в полном отчёте.</p>:<div className={styles.skillGrid}>{result.skills.map(skill=>{
                  const positive=skill.evidence?.find(item=>item.type==='positive'&&item.claim);
                  return <article className={styles.skill} key={skill.skill}>
                    <div className={styles.skillHeading}><strong>{skill.name||skill.skill}</strong><span className={skill.demonstrated_level?styles.assessed:styles.insufficient}>{skill.demonstrated_level?`Предварительно: ${demonstratedLevel(skill.demonstrated_level)}`:'Недостаточно данных'}</span></div>
                    <p>{skill.evaluated_answers>0?`${skill.evaluated_answers} из ${skill.answers_received} ответов оценено`:'Ответ сохранён, но AI не смог его оценить'}</p>
                    {positive&&<p className={styles.evidence}>По ответу: {positive.claim}</p>}
                  </article>;
                })}</div>}
                {result.kind==='general'&&<button className={`secondary ${styles.reportButton}`} disabled={busy} onClick={()=>void openGeneralInterview({id:result.targetId,name:result.title,description:''},true)}>Открыть полный отчёт <ArrowRight size={16}/></button>}
              </section>)}
            <p className={styles.caveat}>Оценка основана на устных ответах. Практические умения и допуск к работе проверяются отдельно; решение о найме принимает человек.</p>
          </div>
        </section>
        <section className="market-section market-general" id="candidate-general">
          <div className="market-heading"><div><span className="eyebrow">01 / ОБЩЕЕ ИНТЕРВЬЮ</span><h2>Проверьте базовые навыки</h2></div><span className={generalDone?'badge green':'badge'}>{generalDone?'Отчёт готов':generalAssessment?'Интервью начато':'Первый этап'}</span></div>
          <div className="card market-general-card">
            <div><span className="market-general-label">Направление общего интервью</span><strong className="market-general-profession">{me.profile.role}</strong><p className="muted">{selectedProfession?.description||(hasSavedGeneralReport?'Ваше ранее пройденное общее интервью сохранено. Полный отчёт можно открыть в профиле выше.':'Для этого направления пока нет общего интервью. Сейчас доступны продавец-кассир, работник торгового зала, сборщик заказов и работник склада. Укажите нужное направление первым пунктом в новом профиле.')}</p></div>
            <div><h3>Один разговор — общая основа</h3><p className="muted">MIMAS спросит о типовых рабочих ситуациях и составит отчёт на основе ваших устных ответов. После этого можно пройти дополнительные вопросы по конкретной вакансии. Практические навыки и допуск проверяются отдельно.</p>
              {selectedProfession&&(generalDone
                ?<button className="secondary" disabled={busy} onClick={()=>void openGeneralInterview(selectedProfession,true)}>Открыть общий отчёт <ArrowRight size={16}/></button>
                :<button className="primary" disabled={busy} onClick={()=>{setConsentProfession(selectedProfession);setConsentJob(null);setGeneralRecordingConsent(false);setGeneralShareConsent(false);}}>{generalAssessment?'Продолжить общее интервью':'Начать общее интервью'} <ArrowRight size={16}/></button>)}
              {selectedProfession&&generalAssessment&&<label className="market-consent"><input type="checkbox" disabled={busy} checked={Boolean(generalAssessment.share_with_companies)} onChange={event=>void changeGeneralSharing(selectedProfession.id,event.target.checked)}/> Показывать мой предварительный рейтинг одобренным компаниям</label>}
            </div>
          </div>
          {consentProfession&&<div className="card market-assessment market-general-consent" aria-labelledby="general-consent-title">
            <span className="eyebrow">ПЕРЕД ОБЩИМ ИНТЕРВЬЮ</span><h2 id="general-consent-title">{consentProfession.name}</h2>
            <p className="muted">Для разговора нужны камера и микрофон. MIMAS сохранит ответы и видео, а оценка будет предварительной. Подробное согласие на проверку событий браузера появится перед первым вопросом; расширение Chrome/Edge необязательно.</p>
            <label className="market-consent"><input type="checkbox" checked={generalRecordingConsent} onChange={event=>setGeneralRecordingConsent(event.target.checked)}/> Я согласен(на) на запись общего интервью и обработку моих ответов.</label>
            <label className="market-consent"><input type="checkbox" checked={generalShareConsent} onChange={event=>setGeneralShareConsent(event.target.checked)}/> Я разрешаю показывать мой общий рейтинг и краткий отчёт одобренным компаниям. Это необязательно, настройку можно изменить позже. Видео доступно только мне.</label>
            <div className="button-row"><button className="primary" disabled={busy||!generalRecordingConsent} onClick={()=>void openGeneralInterview(consentProfession)}>{busy?<Loader2 size={17} className="spin"/>:<Video size={17}/>} Разрешить камеру и продолжить</button><button className="secondary" disabled={busy} onClick={()=>setConsentProfession(null)}>Отмена</button></div>
          </div>}
        </section>
        <section className="market-section" id="candidate-opportunities"><div className="market-heading"><div><span className="eyebrow">02 / ВАКАНСИИ</span><h2>Что вам подходит</h2></div><span className="badge">{jobs.filter(item=>item.match?.compatible).length} подходят из {jobs.length}</span></div>
          {jobs.length===0?<div className="card market-empty"><BriefcaseBusiness size={26}/><h3>Пока нет вакансий с утверждённым интервью</h3><p className="muted">Новые вакансии появятся здесь после проверки вопросов работодателем.</p></div>:<div className="market-list">{jobs.map(job=>{
            const assessment=assessmentFor(me,job.id);
            const done=Boolean(assessment?.report);
            const interested=Boolean(job.interested||me.interested_opportunity_ids.includes(job.id));
            const professionMismatch=Boolean(job.profession_id&&job.profession_id!==profileProfessionId&&!assessment);
            const needsGeneral=Boolean(job.profession_id&&job.profession_id===profileProfessionId&&!me.general_assessments?.[job.profession_id]?.report&&!assessment);
            const jobProfession=professions.find(item=>item.id===job.profession_id);
            return <article className="card market-opportunity" key={job.id}><div className="market-item-top"><span className="eyebrow">{job.company_name}</span><div className="market-statuses"><span className="badge">{job.additional_required===false?'Общего интервью достаточно':'Дополнительный этап'}</span><span className="badge">{job.employment_type==='contract'?'Подработка / временная работа':'Полная занятость'}</span><span className={job.match?.compatible?'badge green':'badge'}>{job.match?.compatible?'Подходит':'Проверьте условия'}</span></div></div>
              <h3>{job.title}</h3><p className="muted">{job.description}</p><p><strong>{salaryRange(job.salary_min_rub,job.salary_max_rub)}</strong> · {levelLabels[job.level]}</p><div className="tags">{job.stack.map(value=><span key={value}>{value}</span>)}</div><p className="market-reasons">{job.match?.reasons.join(' · ')}</p>
              {!interested?<button className="primary" disabled={busy} onClick={()=>void select(job)}>Выбрать вакансию <ArrowRight size={16}/></button>
                :done?<button className="secondary" disabled={busy} onClick={()=>void openInterview(job,true)}>Открыть мой отчёт <ArrowRight size={16}/></button>
                :professionMismatch?<p className="market-general-required">Для дополнительного интервью нужно направление «{jobProfession?.name||'эта должность'}». Сейчас в анкете указано другое направление.</p>
                :needsGeneral&&jobProfession?<button className="secondary" disabled={busy} onClick={()=>{setConsentProfession(jobProfession);setConsentJob(null);setGeneralRecordingConsent(false);setGeneralShareConsent(false);document.getElementById('candidate-general')?.scrollIntoView({behavior:'smooth'});}}>Сначала общее интервью <ArrowRight size={16}/></button>
                :job.additional_required===false?<p className="market-general-required">Вакансия выбрана. Дополнительных вопросов нет. {generalAssessment?.share_with_companies?'Ваш общий результат доступен одобренным компаниям.':'Чтобы компания увидела общий результат, разрешите показ предварительного рейтинга выше.'}</p>
                :<button className="primary" disabled={busy} onClick={()=>{setConsentJob(job);setConsentProfession(null);setConsent(false);}}>{assessment?'Продолжить дополнительное интервью':'Начать дополнительное интервью'} <ArrowRight size={16}/></button>}
            </article>;
          })}</div>}
        </section>
        {historical.length>0&&<section className="market-section"><div className="market-heading"><div><span className="eyebrow">03 / ИСТОРИЯ</span><h2>Мои прежние интервью</h2></div></div><div className="market-list">{historical.map(([id,assessment])=>{const past=me.assessment_opportunities?.[id]||{id,title:'Вакансия больше не опубликована',company_name:'Компания',status:'closed'};const done=Boolean(assessment.report||assessment.phase==='COMPLETED'||assessment.status==='completed');return <article className="card market-opportunity" key={id}><span className="eyebrow">{past.company_name}</span><h3>{past.title}</h3><span className="badge">{past.status==='closed'?'Вакансия закрыта':'Вакансия недоступна'}</span><p className="muted">Ваше интервью и отчёт сохраняются даже после закрытия вакансии.</p>{done?<button className="secondary" disabled={busy} onClick={()=>void openInterview(past,true)}>Открыть отчёт <ArrowRight size={16}/></button>:<button className="secondary" disabled={busy} onClick={()=>{setConsentJob(past);setConsent(false);}}>Продолжить интервью <ArrowRight size={16}/></button>}</article>;})}</div></section>}
        {consentJob&&<section className="card market-assessment" id="candidate-interview" aria-labelledby="market-consent-title"><span className="eyebrow">04 / ДОПОЛНИТЕЛЬНОЕ ИНТЕРВЬЮ</span><h2 id="market-consent-title">{consentJob.title} · {consentJob.company_name}</h2><p className="muted">MIMAS запросит доступ к камере и микрофону, запишет видео и ответы, передаст их для AI-оценки. Для голосового интервью нужны работающие камера и микрофон. Отчёт и запись смогут просматривать вы и компания «{consentJob.company_name}». Запись удаляется через 30 дней, текстовый отчёт сохраняется. Окончательное решение о найме принимает человек. Интервью проверяет знания и решения рабочих ситуаций, но не подтверждает практический навык или допуск к работе. Перед первым вопросом MIMAS отдельно запросит согласие на наблюдение за событиями браузера. На Windows отдельная программа не нужна. Расширение Chrome/Edge для проверки известных вкладок можно подключить по желанию.</p>
          <label className="market-consent"><input type="checkbox" checked={consent} onChange={e=>setConsent(e.target.checked)}/> Я согласен(на) на запись интервью и передачу результата этой компании.</label>
          <div className="button-row"><button className="primary" disabled={busy||!consent} onClick={()=>void openInterview(consentJob)}>{busy?<Loader2 size={17} className="spin"/>:<Video size={17}/>} Разрешить камеру и продолжить</button><button className="secondary" disabled={busy} onClick={()=>setConsentJob(null)}>Отмена</button></div>
          <p className="tiny muted">Если камера или микрофон недоступны, интервью не начнётся. Проверьте разрешения браузера и повторите попытку.</p>
        </section>}
      </>}
      <p className="market-footer"><ShieldCheck size={15}/> AI-оценка предварительная и не заменяет проверку практических навыков и допусков.</p>
    </div></main></div>;
}
