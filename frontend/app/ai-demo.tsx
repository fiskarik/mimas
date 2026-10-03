'use client';

import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,Loader2,Mic,RefreshCw,Square,Video,Volume2} from 'lucide-react';
import {GlassOrb} from './design';
import {AnswerReport} from './answer-report';
import {request,type Access,type Session} from './ai-session';
import {useIntegrityEvents} from './use-integrity-events';
import {IntegritySummary} from './integrity-summary';
import {useInterviewMedia} from './use-interview-media';

const names:Record<string,string>={'python.core':'Python Core','python.oop':'ООП','python.asyncio':'AsyncIO','web.http':'HTTP / REST','db.postgresql':'PostgreSQL','cs.algorithms':'Алгоритмы','engineering.debugging':'Отладка'};
const levels:Record<string,string>={basic:'Базовый',junior:'Junior',middle:'Middle',strong_middle:'Strong Middle',senior:'Senior'};
const failureNames:Record<string,string>={provider_error:'сбой AI API',invalid_output:'неверный формат ответа модели',unsupported_evidence:'оценка не прошла проверку цитат или цели вопроса',rate_limit:'достигнут лимит AI API',authentication_error:'неверный API-ключ',access_denied:'AI-провайдер запретил доступ',model_unavailable:'модель недоступна',output_truncated:'ответ модели обрезан',network_error:'сбой соединения с AI-провайдером',invalid_provider_response:'неверный ответ API'};
type OpportunityLabel={title:string;company_name:string};

export default function AIDemo({linkedAccess,onExit,linkedOpportunity,mediaStream}:{
  linkedAccess?:Access;onExit?:()=>void;linkedOpportunity?:OpportunityLabel;mediaStream?:MediaStream;
}={}){
  const [access,setAccess]=useState<Access|null>(linkedAccess||null);
  const [data,setData]=useState<Session|null>(null);
  const [key,setKey]=useState('demo-company');
  const [answer,setAnswer]=useState('');
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [ready,setReady]=useState(false);
  const [speaking,setSpeaking]=useState(false);
  const [dictating,setDictating]=useState(false);
  const [transcribing,setTranscribing]=useState(false);
  const [transcriptNotice,setTranscriptNotice]=useState('');
  const [videoUrl,setVideoUrl]=useState('');
  const [recordingStatus,setRecordingStatus]=useState<{status:string;incomplete:boolean;expires_at:number|null}|null>(null);
  const answerRef=useRef<HTMLTextAreaElement>(null);
  const voiceRecorder=useRef<MediaRecorder|null>(null);
  const voiceChunks=useRef<Blob[]>([]);
  const voiceTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const {flushEvents,track}=useIntegrityEvents(access,data,busy,setError);
  const media=useInterviewMedia(linkedAccess||undefined,mediaStream);
  const requiresVideo=Boolean(linkedAccess&&mediaStream&&!data?.report);
  useEffect(()=>{
    if(linkedAccess){setAccess(linkedAccess);setReady(true);return;}
    setKey(sessionStorage.getItem('company-key')||'demo-company');
    try{const saved=sessionStorage.getItem('ai-access');if(saved){const value=JSON.parse(saved);if(typeof value.id==='string'&&typeof value.token==='string')setAccess(value);}}
    catch{sessionStorage.removeItem('ai-access');}
    setReady(true);
  },[linkedAccess]);
  useEffect(()=>{
    if(!access)return;let cancelled=false;
    request<Session>('/'+access.id,access.token).then(value=>{if(!cancelled){setData(value);if(value.pending_answer)setAnswer(value.pending_answer.text);}})
      .catch(e=>{if(!cancelled)setError(e.message);});
    return ()=>{cancelled=true;};
  },[access]);
  useEffect(()=>{if(data?.report&&access&&linkedAccess)void refreshRecordingStatus();},[Boolean(data?.report),access?.id,access?.token,Boolean(linkedAccess)]);
  const current=data?.current_question;
  useEffect(()=>{
    setSpeaking(false);setTranscriptNotice('');
    return ()=>{if(typeof window!=='undefined'&&'speechSynthesis' in window)window.speechSynthesis.cancel();};
  },[current?.id]);

  async function create(){
    setBusy(true);setError('');
    try{
      const next=await request<Access>('',undefined,{},key);
      sessionStorage.setItem('ai-access',JSON.stringify(next));setAccess(next);
      setData(await request<Session>('/'+next.id+'/start',next.token,{}));setAnswer('');
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function act(action:'answers'|'start'|'finish'){
    if(!access)return;
    if(action==='start'&&requiresVideo&&!media.ready){setError('Дождитесь запуска записи камеры.');return;}
    setBusy(true);setError('');
    try{
      await flushEvents();
      if(action==='finish'&&mediaStream){
        const uploaded=await media.finish();
        if(!uploaded)throw new Error('Видео пока не загружено. Повторите загрузку сохранённых частей перед завершением.');
        await refreshRecordingStatus();
      }
      const body=action==='answers'?(data?.pending_answer||{question_id:data?.current_question?.id,text:answer}):{};
      const next=await request<Session>('/'+access.id+'/'+action,access.token,body);
      let visible=next;
      if(next.phase==='COMPLETED'&&mediaStream){
        const uploaded=await media.finish();
        if(!uploaded){setData(next);throw new Error('Ответ сохранён, но видео ещё загружается. Повторите загрузку и обновите отчёт.');}
        await refreshRecordingStatus();
        visible=await request<Session>('/'+access.id,access.token);
        mediaStream.getTracks().forEach(track=>track.stop());
      }
      setData(visible);
      if(action==='answers')setAnswer('');
    }catch(e){
      const message=(e as Error).message;
      setError(message);
      if(!message.includes('видео')){
        try{const latest=await request<Session>('/'+access.id,access.token);setData(latest);if(latest.pending_answer)setAnswer(latest.pending_answer.text);}catch{/* Keep the original error. */}
      }
    }finally{setBusy(false);answerRef.current?.focus();}
  }
  async function refresh(){
    if(!access)return;setBusy(true);setError('');
    try{const next=await request<Session>('/'+access.id,access.token);setData(next);if(next.pending_answer)setAnswer(next.pending_answer.text);}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function leave(){
    if(linkedAccess){
      if(mediaStream&&media.status==='recording'&&!data?.report){
        if(!window.confirm('Выход прервёт видеозапись. Интервью можно продолжить позже, но запись будет неполной. Выйти?'))return;
        if(!await media.finish(true)){setError('Видео не загружено. Повторите загрузку сохранённых частей перед выходом.');return;}
      }
      onExit?.();return;
    }
    sessionStorage.removeItem('ai-access');setAccess(null);setData(null);setAnswer('');setError('');
  }
  function speakQuestion(){
    if(!current)return;
    if(!('speechSynthesis' in window)){setError('Озвучивание не поддерживается этим браузером. Вопрос доступен текстом.');return;}
    if(speaking){window.speechSynthesis.cancel();setSpeaking(false);return;}
    window.speechSynthesis.cancel();
    const utterance=new SpeechSynthesisUtterance(current.text);
    utterance.lang='ru-RU';utterance.rate=0.95;
    const voice=window.speechSynthesis.getVoices().find(item=>item.lang.toLowerCase().startsWith('ru'));
    if(voice)utterance.voice=voice;
    utterance.onend=()=>setSpeaking(false);utterance.onerror=()=>setSpeaking(false);
    setSpeaking(true);window.speechSynthesis.speak(utterance);
  }
  async function toggleDictation(){
    if(dictating){voiceRecorder.current?.stop();return;}
    if(!mediaStream||!access){setError('Микрофон недоступен. Ответ можно ввести текстом.');return;}
    const tracks=mediaStream.getAudioTracks();
    if(!tracks.length){setError('Микрофон не найден.');return;}
    const type=['audio/webm;codecs=opus','audio/webm'].find(value=>MediaRecorder.isTypeSupported(value));
    if(!type){setError('Браузер не поддерживает запись звука WebM.');return;}
    voiceChunks.current=[];
    const recorder=new MediaRecorder(new MediaStream(tracks),{mimeType:type});
    voiceRecorder.current=recorder;
    recorder.ondataavailable=e=>{if(e.data.size)voiceChunks.current.push(e.data);};
    recorder.onerror=()=>{setDictating(false);setError('Не удалось записать ответ. Текст можно ввести вручную.');};
    recorder.onstop=async()=>{
      if(voiceTimer.current){clearTimeout(voiceTimer.current);voiceTimer.current=null;}
      setDictating(false);setTranscribing(true);setError('');
      try{
        const blob=new Blob(voiceChunks.current,{type});
        if(!blob.size)throw new Error('Запись звука пуста.');
        const form=new FormData();form.append('audio',blob,'answer.webm');
        const response=await fetch('/api/ai/sessions/'+access.id+'/transcribe',{method:'POST',headers:{'X-Interview-Token':access.token},body:form,cache:'no-store'});
        if(!response.ok){const value=await response.json().catch(()=>({}));throw new Error(typeof value.detail==='string'?value.detail:'Распознавание не удалось.');}
        const result=await response.json() as {text:string};
        if(result.text.trim()){setAnswer(value=>value.trim()?value.trim()+'\n'+result.text.trim():result.text.trim());setTranscriptNotice('Проверьте распознанный текст и исправьте ошибки перед отправкой.');answerRef.current?.focus();}
      }catch(e){setError((e as Error).message);}finally{setTranscribing(false);}
    };
    recorder.start();setDictating(true);
    voiceTimer.current=setTimeout(()=>{if(recorder.state!=='inactive')recorder.stop();},170000);
  }
  async function refreshRecordingStatus(){
    if(!access)return;
    const response=await fetch('/api/ai/sessions/'+access.id+'/recording/status',{headers:{'X-Interview-Token':access.token},cache:'no-store'});
    if(response.ok)setRecordingStatus(await response.json());
  }
  async function finalizeRecording(){
    if(!access)return;
    if(!mediaStream){setError('Для восстановления записи вернитесь в профиль и снова откройте интервью.');return;}
    setBusy(true);setError('');
    try{
      const uploaded=await media.finish();
      if(!uploaded)throw new Error('Не все части видео загружены. Повторите попытку.');
      await refreshRecordingStatus();
      mediaStream.getTracks().forEach(track=>track.stop());
      const latest=await request<Session>('/'+access.id,access.token);
      setData(latest);
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function openVideo(){
    if(!access)return;setError('');
    try{
      const response=await fetch('/api/ai/sessions/'+access.id+'/recording/url',{headers:{'X-Interview-Token':access.token},cache:'no-store'});
      if(!response.ok){const value=await response.json().catch(()=>({}));throw new Error(typeof value.detail==='string'?value.detail:'Запись пока недоступна.');}
      const value=await response.json() as {url:string};setVideoUrl(value.url);
    }catch(e){setError((e as Error).message);}
  }
  const notice=data?.evaluation_notice?.replace(/provider_error|invalid_output|unsupported_evidence|rate_limit|authentication_error|access_denied|model_unavailable|output_truncated|network_error|invalid_provider_response/g,value=>failureNames[value]);
  return <div className="ai-demo"><header className="candidate-header"><a href="/" className="brand-word">mimas.</a>{linkedAccess?<button className="text-link" onClick={()=>void leave()}>К вакансиям <ArrowRight size={16}/></button>:<a href="/?view=employer" className="text-link">Кабинет <ArrowRight size={16}/></a>}</header>
    <main className="ai-demo-main">{linkedAccess?<button className="text-link" onClick={()=>void leave()}><ArrowLeft size={15}/> К профилю</button>:<a href="/" className="text-link"><ArrowLeft size={15}/> На главную</a>}
      <div className="ai-demo-heading"><div><span className="eyebrow">MIMAS · AI-ИНТЕРВЬЮ</span><h1>{linkedOpportunity?'Интервью по вакансии':'Обсудим, как это работает.'}</h1><p className="muted">{linkedOpportunity?linkedOpportunity.title+' · '+linkedOpportunity.company_name:'Технический диалог'}</p></div><GlassOrb compact state={busy?'thinking':'idle'}/></div>
      {linkedAccess?<div className="note">Вопросы формируются для выбранной вакансии по утверждённому шаблону. Запись камеры и микрофона загружается в защищённое хранилище. Распознанный ответ можно проверить и исправить до отправки.</div>:<div className="note">Вопросы можно озвучить голосом браузера. Ответы сохраняются на сервере и отправляются настроенному AI-провайдеру.</div>}
      <p className="tiny muted">Фиксируются вставка, копирование и смена фокуса окна. Эти события сами по себе не снижают оценку.</p>
      {mediaStream&&<section className="card ai-media-panel"><div className="ai-media-preview"><video ref={media.videoRef} autoPlay muted playsInline/><span className="ai-rec-badge"><span className={media.status==='recording'?'ai-rec-dot active':'ai-rec-dot'}/> {media.status==='recording'?'Идёт запись':media.status==='uploading'?'Загрузка видео…':media.status==='complete'?'Видео сохранено':media.status==='interrupted'?'Запись прервана':media.status==='error'?'Ошибка записи':'Подключаем запись…'}</span></div><div><p className="tiny muted">Камера обязательна для интервью. Не закрывайте вкладку, пока идёт загрузка видео.</p>{(media.status==='interrupted'||media.status==='error')&&<button className="secondary" onClick={()=>void media.retry()}>Повторить загрузку сохранённых частей</button>}</div></section>}
      {media.error&&<div role="status" className="warning">{media.error}</div>}
      {error&&<div role="alert" className="error-box">{error}</div>}
      {notice&&<div role="status" className="warning">{notice}</div>}
      {!ready?<p>Загрузка…</p>:!access?<section className="card ai-start"><h2>Начать собеседование</h2><p className="muted">Если не знаете ответ, так и напишите — это не считается ошибочным утверждением.</p><form onSubmit={e=>{e.preventDefault();void create();}}><label>Ключ команды<input type="password" value={key} onChange={e=>setKey(e.target.value)} required/></label><button className="primary" disabled={busy}>{busy?<Loader2 className="spin" size={17}/>:<ArrowRight size={17}/>} Начать AI-интервью</button></form></section>
      :!data?<section className="card ai-start"><p>Загружаем сессию…</p><button className="secondary" disabled={busy} onClick={()=>void refresh()}>Повторить загрузку</button></section>
      :<><div className="ai-session-bar"><span>{data.model} · сохранено ответов: {data.answers.length}</span><button className="text-link" disabled={busy} onClick={()=>void refresh()}><RefreshCw size={14}/> Обновить</button></div>
        {data.phase==='CREATED'&&<button className="primary" disabled={busy||Boolean(requiresVideo&&!media.ready)} onClick={()=>void act('start')}>Получить первый вопрос</button>}
        {data.resume_required&&<section className="card ai-start"><p>Сохранён незавершённый этап интервью. Продолжим с последней контрольной точки.</p><button className="primary" disabled={busy||Boolean(requiresVideo&&!media.ready)} onClick={()=>void act('start')}>Продолжить обработку</button></section>}
        {data.phase==='COMPLETED'&&!data.report&&<section className="card ai-start"><h2>Интервью завершено, ожидаем запись</h2><p className="muted">Текстовые ответы сохранены. Отчёт откроется после успешной загрузки всех частей видеозаписи.</p><div className="button-row"><button className="primary" disabled={busy||!mediaStream} onClick={()=>void finalizeRecording()}>{busy?<Loader2 className="spin" size={16}/>:<Video size={16}/>} Завершить загрузку видео</button><button className="secondary" disabled={busy} onClick={()=>void refresh()}>Проверить отчёт</button></div>{!mediaStream&&<p className="tiny muted">Вернитесь к вакансии и откройте интервью с доступом к камере, чтобы восстановить запись.</p>}</section>}
        {current&&<section className="card ai-question"><div className="section-top"><span className="badge purple">{names[current.skill]||current.skill}</span><span className="muted tiny">Вопрос {data.questions.length} · {current.type==='verification'?'Проверка утверждения':current.type==='follow_up'?'Уточнение':'Основной вопрос'}</span></div>
          <h2>{current.text}</h2><button type="button" className="secondary" onClick={speakQuestion} aria-label={speaking?'Остановить озвучивание вопроса':'Озвучить вопрос'}>{speaking?<Square size={16}/>:<Volume2 size={16}/>} {speaking?'Остановить':'Озвучить вопрос'}</button><p className="tiny muted">Голос зависит от браузера и установленных языков.</p>{current.generation==='fallback'&&<p className="tiny muted">Использован резервный вопрос из банка.</p>}
          <form onSubmit={e=>{e.preventDefault();void act('answers');}}><label>Ваш ответ или код<textarea ref={answerRef} value={answer} onChange={e=>setAnswer(e.target.value)} onPaste={e=>track('PASTE_DETECTED',e.clipboardData.getData('text').length)} onCopy={()=>track('COPY_DETECTED')} readOnly={!!data.pending_answer||busy} maxLength={16000} placeholder="Объясните своими словами. Код можно вставить с переносами строк."/></label>
            {mediaStream&&<div className="ai-dictation"><button type="button" className="secondary" disabled={busy||transcribing||!!data.pending_answer} onClick={()=>void toggleDictation()}>{dictating?<Square size={16}/>:<Mic size={16}/>} {dictating?'Остановить диктовку':transcribing?'Распознаём…':'Продиктовать ответ'}</button><span className="tiny muted">После распознавания текст появится в поле выше.</span></div>}
            {transcriptNotice&&<p role="status" className="note">{transcriptNotice}</p>}
            {data.pending_answer&&<p className="note">Ответ уже сохранён. Повторная отправка продолжит обработку без дубликата.</p>}
            <div className="button-row"><button className="primary" disabled={busy||dictating||transcribing||!answer.trim()}>{busy?<Loader2 className="spin" size={17}/>:<ArrowRight size={17}/>} {busy?'AI обрабатывает ответ…':data.pending_answer?'Повторить обработку':'Отправить проверенный ответ'}</button><button type="button" className="secondary" disabled={busy||dictating||transcribing||!!data.pending_answer} onClick={()=>void act('finish')}>Завершить и показать отчёт</button></div>
          </form>
        </section>}
        {data.report&&<section className="ai-report"><div className="section-top"><div><h2>Отчёт по интервью</h2><p className="muted">{data.report.overall_technical_summary}</p></div><button className="secondary" onClick={()=>void leave()}>{linkedAccess?'К вакансиям':'Новое интервью'}</button></div>
          <p className="note">Уровни предварительные. Отсутствие ответа или сбой оценки не доказывают отсутствие навыка.</p><AnswerReport reviews={data.report.answer_reviews||[]} rubric={data.report.scoring_rubric} names={names}/>
          <details className="skill-profile"><summary>Профиль по навыкам</summary><div className="report-skills">{data.report.skills.map(skill=><article className="card" key={skill.skill}><h3>{names[skill.skill]||skill.skill}</h3><span className="badge">{skill.demonstrated_level?levels[skill.demonstrated_level]:'Недостаточно данных'}</span><p>Ответов: {skill.answers_received} · обработано: {skill.evaluated_answers}</p>{skill.evidence.map(e=><div className="ai-evidence" key={e.id}><strong>{e.type==='positive'?'Подтверждение':e.type==='negative'?'Ошибка в утверждении':'Неопределённость'}</strong><p>{e.claim}</p><blockquote>{e.quote}</blockquote></div>)}</article>)}</div></details>
          {linkedAccess&&<div className="ai-report-video">{recordingStatus?.incomplete&&<p role="status" className="warning">Видеозапись была прервана и содержит только сохранённую часть интервью.</p>}<button className="secondary" onClick={()=>void openVideo()}><Video size={16}/> {videoUrl?'Обновить ссылку на запись':'Посмотреть запись'}</button>{videoUrl&&<video controls preload="none" src={videoUrl}>Браузер не поддерживает воспроизведение видео.</video>}<p className="tiny muted">Запись удаляется через 30 дней. Текстовый отчёт остаётся доступен.</p></div>}
        </section>}
        {data.report?.integrity&&<IntegritySummary report={data.report.integrity} questions={data.questions}/>}
        {!data.report&&data.answers.length>0&&<details className="card ai-history"><summary>История ответов ({data.answers.length})</summary>{data.answers.map(value=><article key={value.question_id}><h3>{data.questions.find(q=>q.id===value.question_id)?.text}</h3><pre>{value.text}</pre></article>)}</details>}
      </>}
    </main>
  </div>;
}
