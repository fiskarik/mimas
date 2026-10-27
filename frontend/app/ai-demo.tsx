'use client';

import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,AudioLines,Loader2,Mic,MicOff,RefreshCw,Square,Video,Volume2} from 'lucide-react';
import {AnswerReport} from './answer-report';
import {BrandLogo} from './brand-logo';
import {CursorDots} from './cursor-dots';
import {request,type Access,type Session} from './ai-session';
import {useIntegrityEvents} from './use-integrity-events';
import {IntegritySummary} from './integrity-summary';
import {useInterviewMedia} from './use-interview-media';
import {CandidateMonitorAlerts,CandidateMonitorPanel,useCandidateMonitor} from './monitor-ui';
import {useVoiceInterview,type VoicePhase} from './use-voice-interview';

const names:Record<string,string>={'python.core':'Python Core','python.oop':'ООП','python.asyncio':'AsyncIO','web.http':'HTTP / REST','db.postgresql':'PostgreSQL','cs.algorithms':'Алгоритмы','engineering.debugging':'Отладка'};
const levels:Record<string,string>={basic:'Базовый',junior:'Начинающий',middle:'С опытом',strong_middle:'Опытный',senior:'Высокий уровень'};
const failureNames:Record<string,string>={provider_error:'сбой AI API',invalid_output:'неверный формат ответа модели',unsupported_evidence:'оценка не прошла проверку цитат или цели вопроса',rate_limit:'достигнут лимит AI API',authentication_error:'неверный API-ключ',access_denied:'AI-провайдер запретил доступ',model_unavailable:'модель недоступна',output_truncated:'ответ модели обрезан',network_error:'сбой соединения с AI-провайдером',invalid_provider_response:'неверный ответ API'};
const voiceLabels:Record<VoicePhase,string>={idle:'Ожидание',connecting:'Подключаем голос',listening:'Готов к ответу',candidate_speaking:'Вы отвечаете',speaking:'MIMAS говорит',thinking:'Обдумывает ответ',disconnected:'Связь прервана',completed:'Интервью завершено'};
type OpportunityLabel={title:string;company_name:string};

export default function AIDemo({linkedAccess,onExit,linkedOpportunity,mediaStream,interviewKind='additional'}:{
  linkedAccess?:Access;onExit?:()=>void;linkedOpportunity?:OpportunityLabel;mediaStream?:MediaStream;interviewKind?:'general'|'additional';
}={}){
  const [access,setAccess]=useState<Access|null>(linkedAccess||null);
  const [data,setData]=useState<Session|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [ready,setReady]=useState(false);
  const [videoUrl,setVideoUrl]=useState('');
  const [recordingStatus,setRecordingStatus]=useState<{status:string;incomplete:boolean;expires_at:number|null}|null>(null);
  const [secondsLeft,setSecondsLeft]=useState<number|null>(null);
  const finalized=useRef(false);
  const ending=useRef(false);
  const {flushEvents}=useIntegrityEvents(access,data,busy,setError);
  const media=useInterviewMedia(linkedAccess||undefined,mediaStream);
  const monitor=useCandidateMonitor(linkedAccess||null,data?.phase);
  const voice=useVoiceInterview(setData);
  const hasMicrophone=Boolean(mediaStream?.getAudioTracks().some(track=>track.readyState==='live'));
  const requiresVideo=Boolean(linkedAccess&&mediaStream&&!data?.report);
  const current=data?.current_question;
  const skillNames:Record<string,string>={...names,...(data?.skill_names||{})};
  for(const skill of data?.report?.skills||[]){if(skill.name)skillNames[skill.skill]=skill.name;}

  useEffect(()=>{setAccess(linkedAccess||null);setReady(true);},[linkedAccess]);
  useEffect(()=>{
    if(!access)return;let cancelled=false;
    request<Session>('/'+access.id,access.token).then(value=>{if(!cancelled)setData(value);})
      .catch(cause=>{if(!cancelled)setError((cause as Error).message);});
    return ()=>{cancelled=true;};
  },[access]);
  useEffect(()=>{
    if(!access||!data?.deadline_at||data.phase==='CREATED'||data.phase==='COMPLETED'){
      setSecondsLeft(null);return;
    }
    let cancelled=false;
    let inFlight=false;
    let nextAttempt=0;
    const tick=()=>{
      const remaining=Math.max(0,Math.ceil(data.deadline_at!*1000-Date.now())/1000);
      setSecondsLeft(Math.ceil(remaining));
      if(remaining>0||inFlight||Date.now()<nextAttempt)return;
      inFlight=true;nextAttempt=Date.now()+3000;
      void request<Session>('/'+access.id,access.token).then(value=>{
        if(cancelled)return;
        setData(value);
        if(value.phase==='COMPLETED'){ending.current=true;voice.disconnect();}
      }).catch(cause=>{
        if(!cancelled)setError((cause as Error).message);
      }).finally(()=>{inFlight=false;});
    };
    tick();
    const interval=window.setInterval(tick,1000);
    return ()=>{cancelled=true;window.clearInterval(interval);};
  },[access?.id,access?.token,data?.deadline_at,data?.phase,voice.disconnect]);
  useEffect(()=>{
    if(media.videoRef.current)media.videoRef.current.srcObject=mediaStream||null;
  },[mediaStream,data?.phase,media.status]);
  useEffect(()=>{
    const track=mediaStream?.getAudioTracks()[0];
    if(!track)return;
    const ended=()=>{if(ending.current||data?.phase==='COMPLETED')return;voice.disconnect();setError('Микрофон отключился. Проверьте устройство и подключитесь повторно.');};
    track.addEventListener('ended',ended);
    return ()=>track.removeEventListener('ended',ended);
  },[mediaStream,voice.disconnect,data?.phase]);
  useEffect(()=>{
    if(data?.report&&access&&linkedAccess)void refreshRecordingStatus();
  },[Boolean(data?.report),access?.id,access?.token,Boolean(linkedAccess)]);
  useEffect(()=>{
    if(!linkedAccess||!mediaStream||data?.phase!=='COMPLETED'||media.status!=='recording'||finalized.current)return;
    finalized.current=true;
    setBusy(true);
    void media.finish().then(async uploaded=>{
      if(!uploaded)throw new Error('Видео осталось в браузере. Повторите загрузку сохранённых частей.');
      await refreshRecordingStatus();
      if(access)setData(await request<Session>('/'+access.id,access.token));
      ending.current=true;mediaStream.getTracks().forEach(track=>track.stop());
    }).catch(cause=>setError((cause as Error).message)).finally(()=>setBusy(false));
  },[data?.phase,media.status,access?.id]);

  async function startVoice(){
    if(!access||!data)return;
    const stream=mediaStream;
    if(!stream?.getAudioTracks().some(track=>track.readyState==='live')){
      setError('Для начала нужен работающий микрофон. Разрешите доступ в браузере и откройте интервью снова.');return;
    }
    if(requiresVideo&&!media.ready){setError('Дождитесь запуска записи камеры.');return;}
    if(linkedAccess&&data.phase==='CREATED'&&!monitor.startReady){
      setError('Подтвердите согласие на проверку перед интервью.');return;
    }
    setBusy(true);setError('');
    try{
      voice.prepare();
      await flushEvents();
      if(data.phase==='CREATED'||data.resume_required){
        const next=await request<Session>('/'+access.id+'/start',access.token,{});
        setData(next);
      }
      await voice.connect(access,stream);
    }catch(cause){setError((cause as Error).message);}finally{setBusy(false);}
  }
  async function finish(){
    if(!access)return;
    ending.current=true;voice.disconnect();setBusy(true);setError('');
    try{
      try{await flushEvents();}
      catch{setError('Некоторые события проверки среды не удалось отправить; ответы и отчёт сохраняются.');}
      // Completing the text interview is free and must not depend on a video upload.
      const next=await request<Session>('/'+access.id+'/finish',access.token,{});
      finalized.current=true;
      setData(next);
      if(mediaStream){
        try{
          const uploaded=await media.finish();
          if(!uploaded)throw new Error('Видео осталось в браузере. Повторите загрузку сохранённых частей.');
          await refreshRecordingStatus();
          setData(await request<Session>('/'+access.id,access.token));
        }catch(uploadError){
          setError('Отчёт готов. Видео пока не загружено: '+(uploadError as Error).message);
        }finally{
          mediaStream.getTracks().forEach(track=>track.stop());
        }
      }
    }catch(cause){
      ending.current=false;setError((cause as Error).message);
      try{setData(await request<Session>('/'+access.id,access.token));}catch{/* original error remains */}
    }finally{setBusy(false);}
  }
  async function refresh(){
    if(!access)return;setBusy(true);setError('');
    try{setData(await request<Session>('/'+access.id,access.token));}
    catch(cause){setError((cause as Error).message);}finally{setBusy(false);}
  }
  async function leave(){
    if(linkedAccess){
      if(mediaStream&&media.status==='recording'&&!data?.report){
        if(!window.confirm('Выход прервёт видеозапись. Выйти?'))return;
        if(!await media.finish(true)){setError('Видео не загружено. Повторите загрузку сохранённых частей.');return;}
      }
      ending.current=true;voice.disconnect();onExit?.();return;
    }
    voice.disconnect();
    window.location.href='/?view=candidate';
  }
  async function refreshRecordingStatus(){
    if(!access)return;
    const response=await fetch('/api/ai/sessions/'+access.id+'/recording/status',{headers:{'X-Interview-Token':access.token},cache:'no-store'});
    if(response.ok)setRecordingStatus(await response.json());
  }
  async function finalizeRecording(){
    if(!access||!mediaStream){setError('Откройте интервью с камерой, чтобы восстановить запись.');return;}
    setBusy(true);setError('');
    try{
      if(!await media.finish())throw new Error('Не все части видео загружены. Повторите попытку.');
      await refreshRecordingStatus();setData(await request<Session>('/'+access.id,access.token));
    }catch(cause){setError((cause as Error).message);}finally{setBusy(false);}
  }
  async function openVideo(){
    if(!access)return;setError('');
    try{
      const response=await fetch('/api/ai/sessions/'+access.id+'/recording/url',{headers:{'X-Interview-Token':access.token},cache:'no-store'});
      if(!response.ok){const value=await response.json().catch(()=>({}));throw new Error(typeof value.detail==='string'?value.detail:'Запись пока недоступна.');}
      const value=await response.json() as {url:string};setVideoUrl(value.url);
    }catch(cause){setError((cause as Error).message);}
  }
  const notice=data?.evaluation_notice?.replace(/provider_error|invalid_output|unsupported_evidence|rate_limit|authentication_error|access_denied|model_unavailable|output_truncated|network_error|invalid_provider_response/g,value=>failureNames[value]);
  const active=Boolean(data&&data.phase!=='CREATED'&&data.phase!=='COMPLETED'&&!data.report);
  const connected=['connecting','listening','candidate_speaking','speaking','thinking'].includes(voice.phase);
  const videoPreview=mediaStream;
  useEffect(()=>{
    if(!active)return;
    const editing=(target:EventTarget|null)=>target instanceof Element&&Boolean(target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"]),button:not([data-voice-ptt]),[role="button"]:not([data-voice-ptt])'));
    const keyDown=(event:KeyboardEvent)=>{
      if(event.code!=='Space'||event.altKey||event.ctrlKey||event.metaKey||editing(event.target))return;
      event.preventDefault();
      if(!event.repeat)voice.startAnswer();
    };
    const keyUp=(event:KeyboardEvent)=>{
      if(event.code!=='Space')return;
      if(!editing(event.target))event.preventDefault();
      voice.finishAnswer();
    };
    const stop=()=>voice.finishAnswer();
    const visibility=()=>{if(document.hidden)stop();};
    window.addEventListener('keydown',keyDown);
    window.addEventListener('keyup',keyUp);
    window.addEventListener('blur',stop);
    document.addEventListener('visibilitychange',visibility);
    return ()=>{
      window.removeEventListener('keydown',keyDown);
      window.removeEventListener('keyup',keyUp);
      window.removeEventListener('blur',stop);
      document.removeEventListener('visibilitychange',visibility);
    };
  },[active,voice.startAnswer,voice.finishAnswer]);

  return <div className="ai-demo voice-page">
    <CursorDots variant="viewport"/>
    <header className="voice-nav"><a href="/" className="brand-word" aria-label="MIMAS — на главную"><BrandLogo tone="light" width={145} className="voice-brand-logo"/></a><button className="voice-nav-exit" onClick={()=>void leave()}><ArrowLeft size={16}/> {linkedAccess?(interviewKind==='general'?'К профилю':'К вакансиям'):'На главную'}</button></header>
    <main className="ai-demo-main">
      {!ready?<p className="voice-load">Загружаем интервью…</p>
      :!access?<section className="voice-preflight">
        <div className="voice-preflight-head"><span className="voice-emblem"><BrandLogo tone="dark" width={132} className="voice-preflight-logo"/></span><div><span className="voice-eyebrow">MIMAS · ГОЛОСОВОЕ AI-ИНТЕРВЬЮ</span><h1>Разговор о ваших навыках</h1></div></div>
        <div className="voice-preflight-steps"><span>01 · Профиль</span><span>02 · Вакансия</span><span>03 · Интервью</span></div>
        <div className="voice-preflight-grid"><article><span className="voice-card-index">НАЧАЛО</span><h2>Выберите вакансию</h2><p>Зарегистрируйтесь как кандидат и выберите вакансию. После проверки устройств MIMAS проведёт голосовое интервью по утверждённому шаблону. Длительность — до 20 минут.</p><a className="voice-cta" href="/?view=candidate"><ArrowRight size={18}/> В кабинет кандидата</a></article><article><span className="voice-card-index">ЧТО ПОНАДОБИТСЯ</span><h2>Проверьте устройства</h2><p>Разрешите доступ к камере и микрофону, наденьте наушники. MIMAS озвучит вопрос, вы ответите голосом, а стенограмма сохранится в отчёте.</p><div className="voice-device-list"><span><Video size={18}/> Камера</span><span><Mic size={18}/> Микрофон</span><span><Volume2 size={18}/> Наушники</span></div></article></div>
      </section>
      :!data?<section className="voice-preflight voice-loading"><Loader2 className="spin" size={32}/><h1>Загружаем интервью</h1><button className="voice-cta" disabled={busy} onClick={()=>void refresh()}>Повторить загрузку</button></section>
      :<div className="voice-session">
        <header className="voice-session-header"><div><span className="voice-eyebrow">MIMAS · {interviewKind==='general'?'ОБЩЕЕ':'ДОПОЛНИТЕЛЬНОЕ'} ГОЛОСОВОЕ ИНТЕРВЬЮ</span><h1>{linkedOpportunity?linkedOpportunity.title:'Профессиональный диалог'}</h1><p>{linkedOpportunity?.company_name||'Голосовое интервью с MIMAS'}</p></div><span className="voice-session-counter">{secondsLeft!==null&&<span aria-label="Осталось времени">{String(Math.floor(secondsLeft/60)).padStart(2,'0')}:{String(secondsLeft%60).padStart(2,'0')} · </span>}{data.answers.length} ответов сохранено</span></header>
        {data.phase==='CREATED'&&<div className="voice-preflight voice-session-preflight">
          <div className="voice-preflight-head"><span className="voice-emblem"><BrandLogo tone="dark" width={132} className="voice-preflight-logo"/></span><div><span className="voice-eyebrow">ГОТОВЫ К ДИАЛОГУ?</span><h2>Проверим связь и начнём</h2></div></div>
          <div className="voice-preflight-steps"><span>Камера {media.ready?'готова':'подключается'}</span><span>Микрофон {hasMicrophone?'готов':'не найден'}</span><span>Запись {media.status==='recording'?'идёт':'ожидает'}</span></div>
          <div className="voice-preflight-grid"><article><span className="voice-card-index">УСТРОЙСТВА</span><h3>Ваше видео</h3><div className="voice-preview-box">{videoPreview?<video ref={media.videoRef} autoPlay muted playsInline/>:<Video size={28}/>}</div><p>Оставьте камеру и микрофон включёнными до завершения интервью. Наденьте наушники, чтобы MIMAS не услышал собственный голос из динамиков.</p></article><article><span className="voice-card-index">СОГЛАСИЕ И ПОДКЛЮЧЕНИЕ</span><h3>Перед первым вопросом</h3><p>{interviewKind==='general'?'Общий отчёт и рейтинг увидите вы и одобренные компании. Видео остаётся доступно только вам. Голосовые ответы сохраняются в отчёте.':'Результат увидите вы и компания, открывшая вакансию. Голосовые ответы распознаются и сохраняются в отчёте.'}</p>{linkedAccess&&<CandidateMonitorPanel monitor={monitor} kind={interviewKind}/>}<button className="voice-cta" disabled={busy||!hasMicrophone||Boolean(requiresVideo&&!media.ready)||Boolean(linkedAccess&&!monitor.startReady)} onClick={()=>void startVoice()}>{busy?<Loader2 className="spin" size={18}/>:<Mic size={18}/>} Начать разговор</button></article></div>
        </div>}
        {active&&<section className="voice-stage" aria-label="Голосовое интервью">
          <div className="voice-stage-top"><div className="voice-stage-left"><span className="voice-live-label"><span className={connected?'voice-live-dot on':'voice-live-dot'}/> {voiceLabels[voice.phase]}</span><h2>{current?.text||'MIMAS готовит следующий вопрос'}</h2><p>{current?skillNames[current.skill]||current.skill:'Дождитесь продолжения диалога'}</p><p className="voice-answer-hint">Удерживайте Пробел или кнопку ответа, пока говорите. Отпустите, когда закончите.</p><div className="voice-sound-bars" aria-hidden="true"><i/><i/><i/><i/><i/><i/><i/><i/></div></div><div className="voice-stage-camera">{videoPreview?<video ref={media.videoRef} autoPlay muted playsInline/>:<div className="voice-camera-empty"><Video size={30}/><span>Камера выключена</span></div>}<span className="voice-camera-label"><span className={media.status==='recording'?'ai-rec-dot active':'ai-rec-dot'}/> {mediaStream?(media.status==='recording'?'Запись идёт':'Камера'):'Предпросмотр'}</span></div></div>
          <div className="voice-stage-controls"><button type="button" disabled={!connected} onClick={voice.toggleMute}>{voice.muted?<MicOff size={19}/>:<Mic size={19}/>} {voice.muted?'Включить микрофон':'Выключить микрофон'}</button><button type="button" data-voice-ptt className="voice-answer-done" disabled={busy||voice.muted||(voice.phase!=='listening'&&voice.phase!=='candidate_speaking')} aria-label={voice.phase==='candidate_speaking'?'Отпустите кнопку, чтобы отправить ответ':'Удерживайте кнопку или Пробел, чтобы ответить голосом'} aria-pressed={voice.phase==='candidate_speaking'} onPointerDown={event=>{if(event.pointerType==='mouse'&&event.button!==0)return;event.preventDefault();event.currentTarget.setPointerCapture(event.pointerId);voice.startAnswer();}} onPointerUp={event=>{event.preventDefault();voice.finishAnswer();if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);}} onPointerCancel={voice.finishAnswer} onLostPointerCapture={voice.finishAnswer} onKeyDown={event=>{if(event.code==='Enter'){event.preventDefault();if(!event.repeat)voice.startAnswer();}}} onKeyUp={event=>{if(event.code==='Enter'){event.preventDefault();voice.finishAnswer();}}} onContextMenu={event=>event.preventDefault()}><Mic size={18}/> {voice.phase==='candidate_speaking'?'Отпустите для отправки':'Удерживайте для ответа'}</button><button type="button" disabled={voice.phase!=='speaking'} onClick={voice.interrupt}><Square size={17}/> Прервать реплику</button>{!connected&&<button type="button" disabled={busy} onClick={()=>void startVoice()}><RefreshCw size={18}/> Подключиться</button>}<button type="button" disabled={busy} onClick={()=>void finish()}><ArrowRight size={19}/> Завершить интервью</button></div>
          <div className="voice-conversation"><div className="voice-conversation-head"><div><span className="voice-eyebrow">ДИАЛОГ В РЕАЛЬНОМ ВРЕМЕНИ</span><h3>Ваш разговор с MIMAS</h3></div><span>{voiceLabels[voice.phase]}</span></div><div className="voice-lines" role="log" aria-live="polite" aria-relevant="additions">{voice.lines.length?voice.lines.map(line=><article key={line.id} className={'voice-line '+line.speaker}><span>{line.speaker==='mimas'?'MIMAS':'ВЫ'}</span><p>{line.text}</p></article>):<div className="voice-line-empty"><AudioLines size={29}/><p>{connected?'Удерживайте Пробел или кнопку ответа, пока говорите. Отпустите, когда закончите.':'Нажмите «Подключиться», чтобы продолжить разговор.'}</p></div>}</div></div>
        </section>}
        {active&&linkedAccess&&<CandidateMonitorAlerts monitor={monitor}/>}

        {data.phase==='COMPLETED'&&!data.report&&<section className="voice-preflight voice-completing"><span className="voice-eyebrow">ЗАВЕРШЕНИЕ</span><h2>Интервью завершено</h2><p>Ответы сохранены. Загружаем видео и готовим отчёт.</p><div className="voice-stage-controls"><button disabled={busy||!mediaStream} onClick={()=>void finalizeRecording()}><Video size={17}/> Завершить загрузку видео</button><button disabled={busy} onClick={()=>void refresh()}><RefreshCw size={17}/> Проверить отчёт</button></div></section>}
        {data.report&&<section className="ai-report voice-report"><div className="section-top"><div><span className="voice-eyebrow">РЕЗУЛЬТАТ ИНТЕРВЬЮ</span><h2>Отчёт по навыкам</h2><p>{data.report.overall_technical_summary}</p></div><button className="voice-cta" onClick={()=>void leave()}>{linkedAccess?(interviewKind==='general'?'К профилю':'К вакансиям'):'Новое интервью'}</button></div><p className="note">Оценка относится к устным ответам. Практические навыки и допуск к работе проверяются отдельно; решение принимает человек.</p><AnswerReport reviews={data.report.answer_reviews||[]} rubric={data.report.scoring_rubric} names={skillNames}/><details className="skill-profile" open><summary>Профиль по навыкам</summary><div className="report-skills">{data.report.skills.map(skill=><article className="card" key={skill.skill}><h3>{skillNames[skill.skill]||skill.skill}</h3><span className="badge">{typeof skill.score==='number'?`Балл: ${skill.score} из 5`:skill.demonstrated_level?levels[skill.demonstrated_level]:'Недостаточно данных'}</span><p>Ответов: {skill.answers_received} · обработано: {skill.evaluated_answers}</p>{skill.evidence.map(evidence=><div className="ai-evidence" key={evidence.id}><strong>{evidence.type==='positive'?'Подтверждение':evidence.type==='negative'?'Ошибка в утверждении':'Неопределённость'}</strong><p>{evidence.claim}</p><blockquote>{evidence.quote}</blockquote></div>)}</article>)}</div></details>{linkedAccess&&<div className="ai-report-video">{recordingStatus?.incomplete&&<p role="status" className="warning">Видеозапись прервана и содержит только сохранённую часть интервью.</p>}<button className="secondary" onClick={()=>void openVideo()}><Video size={16}/> {videoUrl?'Обновить ссылку на запись':'Посмотреть запись'}</button>{videoUrl&&<video controls preload="none" src={videoUrl}>Браузер не поддерживает воспроизведение видео.</video>}<p className="tiny muted">Запись удаляется через 30 дней. Текстовый отчёт остаётся доступен.</p></div>}</section>}
        {data.report?.integrity&&<IntegritySummary report={data.report.integrity} questions={data.questions}/>}
      </div>}
      {media.error&&<p role="status" className="voice-message">{media.error}{(media.status==='interrupted'||media.status==='error')&&<button onClick={()=>void media.retry()}>Повторить загрузку видео</button>}</p>}
      {voice.error&&<p role="alert" className="voice-message">{voice.error}</p>}
      {error&&<p role="alert" className="voice-message">{error}</p>}
      {notice&&<p role="status" className="voice-message">{notice}</p>}
    </main>
  </div>;
}
