'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {GlassOrb, stateNames} from './design';
import {SammiLanding} from './sammi-landing';
import {BrandLogo} from './brand-logo';
import {CandidateHub, EmployerHub} from './marketplace';
import { ArrowDownToLine, ArrowLeft, ArrowRight, AudioLines, BriefcaseBusiness, Check, CheckCircle2, ChevronRight, Circle, Clipboard, Code2, FileText, LayoutDashboard, Link2, Loader2, Mic, Plus, Radio, ShieldCheck, Square, Video, Volume2, X } from 'lucide-react';

type Interview = {id: string; name: string; status: string; mode: string; created: number; started: number | null; completed: number | null; recording_complete: number};
type Question = {id: string; skill: string; text: string};
type Evaluation = {level: string; rationale: string; evidence: string[]};
type Answer = {question_id: string; text: string; evaluation: Evaluation | null};
type Event = {id: string; kind: string; elapsed: number; detail: string};
type Details = {interview: Interview; questions: Question[]; answers: Answer[]; events: Event[]; uploaded_chunks: number; capabilities: {mode: string; ai_ready: boolean; stt_ready: boolean; runner_ready: boolean}};
type Chunk = {seq: number; blob: Blob; saved: boolean};
const labels: Record<string, string> = {invited: 'Приглашён', active: 'Проходит интервью', completed: 'Завершено', tab_hidden: 'Уход со страницы', window_blur: 'Потеря фокуса окна', paste: 'Вставка текста', camera_off: 'Камера отключена', microphone_off: 'Микрофон отключён', camera_restored: 'Камера восстановлена', recording_error: 'Ошибка записи', basic: 'Базовый', medium: 'Средний', strong: 'Сильный', insufficient_evidence: 'Недостаточно данных'};
const sampleCode = 'def group_users(users):\n    # Сгруппируйте имена пользователей по городам\n    result = {}\n    return result\n';
const clock = (value: number) => `${Math.floor(value / 60).toString().padStart(2, '0')}:${Math.floor(value % 60).toString().padStart(2, '0')}`;

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api${path}`, {...init, cache: 'no-store'});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `Ошибка запроса (${response.status})`);
  }
  return response.json();
}
function Logo() {return <div className="logo"><BrandLogo tone="dark" width={135}/></div>;}
function Badge({children, tone = ''}: {children: React.ReactNode; tone?: string}) {return <span className={`badge ${tone}`}>{children}</span>;}
function ErrorBox({text}: {text: string}) {return text ? <div role="alert" className="error-box">{text}</div> : null;}

export default function Page() {
  const [ai, setAi] = useState(false);
  const [company, setCompany] = useState(false);
  const [candidateHub, setCandidateHub] = useState(false);
  const [employerHub, setEmployerHub] = useState(false);
  const [route, setRoute] = useState<{id: string; token: string} | null | undefined>(undefined);
  useEffect(() => {
    const url = new URL(window.location.href);
    setAi(url.searchParams.get('view') === 'ai');
    setCompany(url.searchParams.get('view') === 'company');
    setCandidateHub(url.searchParams.get('view') === 'candidate');
    setEmployerHub(url.searchParams.get('view') === 'employer');
    setRoute(url.searchParams.has('join') ? {id: url.searchParams.get('join')!, token: url.hash.slice(1)} : null);
  }, []);
  if (route === undefined) return <div className="loading"><Loader2 className="spin"/> Загружаем пространство…</div>;
  return route ? <div className="market"><header className="market-header"><a href="/" className="brand-word" aria-label="MIMAS — на главную"><BrandLogo tone="light" width={145}/></a></header><main className="market-main"><span className="eyebrow">СТАРОЕ ПРИГЛАШЕНИЕ</span><h1>Интервью теперь привязано к вакансии.</h1><p className="muted">Эта ссылка относится к прежней версии MIMAS. Создайте профиль кандидата, выберите вакансию и начните новое интервью.</p><a className="primary" href="/?view=candidate">Открыть кабинет кандидата <ArrowRight size={16}/></a></main></div> : candidateHub ? <CandidateHub/> : employerHub || company ? <EmployerHub/> : ai ? <CandidateHub/> : <SammiLanding/>;
}

function Company() {
  const [key, setKey] = useState('');
  const [keyInput, setKeyInput] = useState('demo-company');
  const [rows, setRows] = useState<Interview[]>([]);
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [invite, setInvite] = useState('');
  const [report, setReport] = useState<Details | null>(null);
  const [mode, setMode] = useState('mock');
  const [copied, setCopied] = useState(false);
  const headers = {'X-Company-Key': key};
  const refresh = useCallback(async (auth: string) => {
    try {setRows(await api<Interview[]>('/interviews', {headers: {'X-Company-Key': auth}}));}
    catch (e) {setError((e as Error).message);}
  }, []);
  useEffect(() => {
    const saved = sessionStorage.getItem('company-key');
    if (saved) {setKey(saved); void refresh(saved);}
    void api<{mode: string}>('/health').then(r => setMode(r.mode)).catch(() => setError('Сервер недоступен. Запустите python run_demo.py.'));
  }, [refresh]);
  async function login(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try {const list = await api<Interview[]>('/interviews', {headers: {'X-Company-Key': keyInput}}); setRows(list); setKey(keyInput); sessionStorage.setItem('company-key', keyInput);}
    catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function create(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError('');
    try {
      const result = await api<{id: string; token: string}>('/interviews', {method: 'POST', headers: {...headers, 'Content-Type': 'application/json'}, body: JSON.stringify({name})});
      setInvite(`${window.location.origin}/?join=${result.id}#${result.token}`); setCopied(false); setName(''); await refresh(key);
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function openReport(id: string) {
    setError(''); try {setReport(await api<Details>(`/company/interviews/${id}`, {headers}));} catch (e) {setError((e as Error).message);}
  }
  return <div className="app-shell">
    <aside className="sidebar"><a href="/" aria-label="На главную"><Logo/></a><div className="workspace-label">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <button className={`nav-item ${!report ? 'selected' : ''}`} onClick={() => {setReport(null); if(key) void refresh(key);}}><LayoutDashboard size={18}/> Обзор <span className="nav-count">{rows.length}</span></button>
      <div className="sidebar-card"><div className="orbit"><ShieldCheck size={23}/></div><strong>Навыки с основаниями</strong><p>Ответы, код и запись интервью в одном отчёте.</p><span className="tiny">PYTHON BACKEND · DEMO</span></div>
      <div className="sidebar-bottom"><div className="avatar">М</div><div><strong>Моя команда</strong><span>Локальное демо</span></div>{key && <button title="Выйти" className="icon-button" onClick={() => {setKey(''); sessionStorage.removeItem('company-key'); setReport(null);}}>↗</button>}</div>
    </aside>
    <main className="main"><header className="topbar"><span>Рабочее пространство <ChevronRight size={14}/> {report ? 'Отчёт кандидата' : 'Обзор'}</span><Badge tone={mode === 'mock' ? 'amber' : 'green'}><Circle size={7} fill="currentColor"/>{mode === 'mock' ? 'Тестовый AI' : 'Live AI'}</Badge></header>
      <div className="content"><ErrorBox text={error}/>
      {!key ? <div className="login card"><span className="eyebrow">ДОБРО ПОЖАЛОВАТЬ</span><h1>Ваш следующий<br/>сильный кандидат.</h1><p className="muted">Войдите в локальный кабинет работодателя.</p><form onSubmit={login}><label>Ключ команды<input value={keyInput} onChange={e => setKeyInput(e.target.value)} type="password" required/></label><button className="primary" disabled={busy}>{busy ? <Loader2 className="spin" size={17}/> : <ArrowRight size={17}/>} Открыть кабинет</button></form><p className="tiny muted">Для локального демо: demo-company. Изменяется через COMPANY_KEY в .env.</p></div>
      : report ? <Report data={report} companyKey={key} onBack={() => {setReport(null); void refresh(key);}}/>
      : <><div className="page-heading"><div><span className="eyebrow">ОТ ПЕРВОГО ВОПРОСА ДО РЕШЕНИЯ</span><h1>Обзор найма</h1><p className="muted">Проверьте знания. Посмотрите ход мысли. Сохраните контекст.</p></div><div className="heading-mark"><GlassOrb/></div></div>
        <div className="stats"><Stat label="Всего приглашений" value={rows.length.toString()} icon={<Link2/>}/><Stat label="Интервью завершено" value={rows.filter(x => x.status === 'completed').length.toString()} icon={<CheckCircle2/>}/><Stat label="Активная специализация" value="Python" icon={<Code2/>}/></div>
        <div className="workspace-grid"><section className="card vacancy"><div className="section-top"><span className="eyebrow">ВАША ВАКАНСИЯ</span><Badge>Шаблон демо</Badge></div><div className="job-icon"><BriefcaseBusiness size={26}/></div><h2>Python Backend Developer</h2><p className="muted">Техническое интервью · 7–10 минут</p><div className="tags"><span>Python</span><span>AsyncIO</span><span>SQL</span></div><div className="vacancy-features"><span><Mic size={16}/> Голос и текст</span><span><Video size={16}/> Запись интервью</span><span><ShieldCheck size={16}/> События прокторинга</span></div><div className="note">{mode === 'mock' ? 'Тестовый режим: вопросы заданы заранее, AI-оценки не выставляются.' : 'Оценка ответов через облачную модель. Решение о найме принимает человек.'}</div></section>
        <section className="card invite-card"><span className="eyebrow">СЛЕДУЮЩИЙ ШАГ</span><h2>Пригласите кандидата</h2><p className="muted">Одна ссылка на интервью, задачу и запись.</p><form onSubmit={create}><label>Имя кандидата<input placeholder="Например, Алексей Иванов" value={name} maxLength={100} onChange={e => setName(e.target.value)} required/></label><button className="primary" disabled={busy || !name.trim()}><Plus size={18}/> Создать приглашение</button></form>{invite && <div className="invite-result"><div className="success-text"><CheckCircle2 size={16}/> Приглашение готово</div><input aria-label="Ссылка приглашения" value={invite} readOnly/><div className="button-row"><button className="secondary" onClick={async () => {try {await navigator.clipboard.writeText(invite); setCopied(true);} catch {setError('Не удалось скопировать. Выделите ссылку вручную.');}}}><Clipboard size={15}/>{copied ? 'Скопировано' : 'Копировать'}</button><a className="text-link" href={invite} target="_blank" rel="noreferrer">Открыть <ArrowRight size={15}/></a></div></div>}</section></div>
        <section className="card interviews"><div className="section-top"><div><h2>Кандидаты <span className="count-inline">{rows.length}</span></h2><p className="muted">Все прохождения по вашей вакансии</p></div><button className="secondary" onClick={() => void refresh(key)}>Обновить</button></div>
        {rows.length === 0 ? <div className="empty"><div className="empty-icon"><FileText size={25}/></div><strong>Здесь появятся первые результаты</strong><p>Создайте приглашение и пройдите интервью,<br/>чтобы увидеть ответы и запись.</p></div> : <div className="table-wrap"><table><thead><tr><th>Кандидат</th><th>Дата</th><th>Статус</th><th>Режим</th><th/></tr></thead><tbody>{rows.map(row => <tr key={row.id}><td><span className="table-name"><span className="avatar pale">{row.name[0]}</span>{row.name}</span></td><td>{new Date(row.created * 1000).toLocaleDateString('ru-RU')}</td><td><Badge tone={row.status === 'completed' ? 'green' : ''}>{labels[row.status]}</Badge></td><td>{row.mode === 'mock' ? 'Тестовый' : 'Live'}</td><td><button className="text-link" onClick={() => void openReport(row.id)}>Отчёт <ArrowRight size={15}/></button></td></tr>)}</tbody></table></div>}</section>
        <footer className="page-footer"><ShieldCheck size={14}/> Оценки навыков и события прокторинга рассматриваются отдельно.</footer></>}
      </div>
    </main>
  </div>;
}
function Stat({label, value, icon}: {label: string; value: string; icon: React.ReactNode}) {return <div className="stat card"><div><span>{label}</span><strong>{value}</strong></div><div className="stat-icon">{icon}</div></div>;}

function Candidate({id, token}: {id: string; token: string}) {
  const [data, setData] = useState<Details | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [consent, setConsent] = useState(false);
  const [running, setRunning] = useState(false);
  const [cameraOk, setCameraOk] = useState(false);
  const [answer, setAnswer] = useState('');
  const [code, setCode] = useState(sampleCode);
  const [elapsed, setElapsed] = useState(0);
  const [warning, setWarning] = useState('');
  const [events, setEvents] = useState<Event[]>([]);
  const [uploaded, setUploaded] = useState(0);
  const [pending, setPending] = useState(0);
  const [speaking, setSpeaking] = useState(false);
  const [audioRecording, setAudioRecording] = useState(false);
  const [stopped, setStopped] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const audioRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Chunk[]>([]);
  const sending = useRef(false);
  const startedAt = useRef(0);
  const activeRef = useRef(false);
  const lastEvent = useRef<Record<string, number>>({});
  const pendingEvents = useRef<Event[]>([]);
  const eventSending = useRef(false);
  const mounted = useRef(true);
  const headers = useCallback(() => ({'X-Interview-Token': token}), [token]);
  const refresh = useCallback(async () => {const d = await api<Details>(`/interviews/${id}`, {headers: headers()}); setData(d); return d;}, [id, headers]);
  useEffect(() => {void refresh().catch(e => setError(e.message));}, [refresh]);
  useEffect(() => {
    mounted.current = true;
    return () => {mounted.current = false; activeRef.current = false; streamRef.current?.getTracks().forEach(t => t.stop()); window.speechSynthesis?.cancel();};
  }, []);
  async function flushEvents() {
    if (eventSending.current) return;
    eventSending.current = true;
    try {
      while (pendingEvents.current.length) {
        await api(`/interviews/${id}/events`, {method: 'POST', headers: {...headers(), 'Content-Type': 'application/json'}, body: JSON.stringify(pendingEvents.current[0])});
        pendingEvents.current.shift();
      }
    } catch { /* Retry while interview is active. Pending state is visible. */ }
    finally {eventSending.current = false; if (mounted.current) setPending(pendingEvents.current.length);}
  }
  const reportEvent = useRef<(kind: string, message: string) => void>(() => {});
  reportEvent.current = (kind, message) => {
    if (!activeRef.current) return;
    const now = Date.now();
    if (now - (lastEvent.current[kind] || 0) < 5000) return;
    lastEvent.current[kind] = now;
    const ev = {id: crypto.randomUUID(), kind, elapsed: (now - startedAt.current) / 1000, detail: message};
    pendingEvents.current.push(ev); setEvents(previous => [...previous, ev]); setWarning(message); setPending(pendingEvents.current.length); void flushEvents();
  };
  useEffect(() => {
    if (!running) return;
    const hidden = () => {if (document.hidden) reportEvent.current('tab_hidden', 'Вы покинули страницу интервью. Вернитесь на вкладку.');};
    const blur = () => reportEvent.current('window_blur', 'Окно интервью потеряло фокус. Вернитесь к заданию.');
    const unload = (e: BeforeUnloadEvent) => {e.preventDefault(); e.returnValue = '';};
    document.addEventListener('visibilitychange', hidden); window.addEventListener('blur', blur); window.addEventListener('beforeunload', unload);
    const interval = window.setInterval(() => {setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)); void flushEvents();}, 1000);
    return () => {clearInterval(interval); document.removeEventListener('visibilitychange', hidden); window.removeEventListener('blur', blur); window.removeEventListener('beforeunload', unload);};
  // flushEvents reads stable session refs; subscriptions follow the recording lifetime.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);
  useEffect(() => {if (videoRef.current && streamRef.current) videoRef.current.srcObject = streamRef.current;}, [cameraOk, running, data]);

  async function checkCamera() {
    setBusy(true); setError('');
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error('Откройте демо в Chrome/Edge на localhost или HTTPS.');
      const stream = await navigator.mediaDevices.getUserMedia({video: {width: {ideal: 960}, height: {ideal: 540}}, audio: {echoCancellation: true, noiseSuppression: true}});
      streamRef.current?.getTracks().forEach(t => t.stop()); streamRef.current = stream; setCameraOk(true);
      stream.getVideoTracks()[0].addEventListener('ended', () => {setCameraOk(false); reportEvent.current('camera_off', 'Камера отключена. Интервью приостановлено: завершите прохождение и создайте новое приглашение.');});
      stream.getAudioTracks()[0].addEventListener('ended', () => {setCameraOk(false); reportEvent.current('microphone_off', 'Микрофон отключён. Завершите прохождение и создайте новое приглашение.');});
    } catch (e) {setError(`Не удалось подключить камеру и микрофон. ${(e as Error).message}`);} finally {setBusy(false);}
  }
  async function flushChunks() {
    if (sending.current) return;
    sending.current = true;
    try {
      for (const chunk of chunksRef.current) {
        if (chunk.saved) continue;
        await api(`/interviews/${id}/recording/${chunk.seq}`, {method: 'PUT', headers: {...headers(), 'Content-Type': 'video/webm'}, body: chunk.blob});
        chunk.saved = true; setUploaded(chunksRef.current.filter(c => c.saved).length);
      }
    } catch {setError('Не все фрагменты видео загружены. Не закрывайте страницу; нажмите «Повторить загрузку».');}
    finally {sending.current = false;}
  }
  async function start() {
    if (!streamRef.current || !cameraOk) return;
    setBusy(true); setError('');
    try {
      const mime = ['video/webm;codecs=vp8,opus', 'video/webm'].find(t => MediaRecorder.isTypeSupported(t));
      if (!mime) throw new Error('Для записи используйте Chrome или Edge с поддержкой WebM.');
      const recorder = new MediaRecorder(streamRef.current, {mimeType: mime, videoBitsPerSecond: 750000});
      recorder.ondataavailable = e => {if (e.data.size) {chunksRef.current.push({seq: chunksRef.current.length, blob: e.data, saved: false}); void flushChunks();}};
      recorder.onerror = () => {setCameraOk(false); reportEvent.current('recording_error', 'Ошибка записи видео. Завершите интервью и проверьте оборудование.');};
      recorderRef.current = recorder;
      await api(`/interviews/${id}/start`, {method: 'POST', headers: {...headers(), 'Content-Type': 'application/json'}, body: JSON.stringify({consent})});
      recorder.start(5000); startedAt.current = Date.now(); activeRef.current = true; setRunning(true); await refresh();
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function submit() {
    if (!data) return;
    const q = data.questions[data.answers.length];
    if (!q) return;
    setBusy(true); setError(''); window.speechSynthesis?.cancel();
    try {
      await api(`/interviews/${id}/answers`, {method: 'POST', headers: {...headers(), 'Content-Type': 'application/json'}, body: JSON.stringify({question_id: q.id, text: q.id === 'coding' ? code : answer})});
      setAnswer(''); await refresh();
    } catch (e) {setError((e as Error).message); await refresh().catch(() => {});} finally {setBusy(false);}
  }
  async function finish() {
    setBusy(true); setError(''); window.speechSynthesis?.cancel();
    try {
      audioRef.current?.state === 'recording' && audioRef.current.stop();
      if (recorderRef.current && recorderRef.current.state !== 'inactive') {
        await new Promise<void>(resolve => {recorderRef.current!.addEventListener('stop', () => resolve(), {once: true}); recorderRef.current!.stop();});
      }
      setStopped(true);
      while (sending.current || eventSending.current) await new Promise(r => setTimeout(r, 100));
      await flushChunks(); await flushEvents();
      if (chunksRef.current.some(c => !c.saved) || pendingEvents.current.length) throw new Error('Загрузка ещё не завершена. Не закрывайте страницу и повторите завершение.');
      await api(`/interviews/${id}/finish`, {method: 'POST', headers: {...headers(), 'Content-Type': 'application/json'}, body: JSON.stringify({expected_chunks: chunksRef.current.length})});
      activeRef.current = false; streamRef.current?.getTracks().forEach(t => t.stop()); setRunning(false); await refresh();
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  function speak(text: string) {
    if (!window.speechSynthesis) {setError('Озвучивание не поддерживается браузером. Вопрос доступен текстом.'); return;}
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text); utterance.lang = 'ru-RU'; utterance.rate = 0.95;
    utterance.onstart = () => setSpeaking(true); utterance.onend = () => setSpeaking(false); utterance.onerror = () => {setSpeaking(false); setError('Озвучивание недоступно. Прочитайте вопрос на экране.');};
    window.speechSynthesis.speak(utterance);
  }
  async function toggleAudio() {
    if (audioRecording) {audioRef.current?.stop(); return;}
    if (!streamRef.current) return;
    window.speechSynthesis.cancel(); setError('');
    const parts: Blob[] = [];
    try {
      const recorder = new MediaRecorder(new MediaStream(streamRef.current.getAudioTracks()), {mimeType: 'audio/webm'});
      audioRef.current = recorder;
      recorder.ondataavailable = e => {if (e.data.size) parts.push(e.data);};
      recorder.onstop = async () => {
        setAudioRecording(false); setBusy(true);
        try {const result = await api<{text: string}>(`/interviews/${id}/transcribe`, {method: 'POST', headers: {...headers(), 'Content-Type': 'audio/webm'}, body: new Blob(parts, {type: 'audio/webm'})}); setAnswer(previous => previous ? `${previous}\n${result.text}` : result.text);}
        catch (e) {setError((e as Error).message);} finally {setBusy(false);}
      };
      recorder.start(); setAudioRecording(true);
    } catch {setError('Не удалось начать запись ответа. Используйте текстовый ввод.');}
  }
  const question = data?.questions[data.answers.length];
  const finished = data?.interview.status === 'completed';
  const interrupted = data?.interview.status === 'active' && !running;
  return <div className="candidate-shell"><header className="candidate-header"><Logo/><span className="muted desktop-only">Python Backend Developer</span><Badge tone={data?.interview.mode === 'live' ? 'green' : 'amber'}>{data?.interview.mode === 'live' ? 'Live AI' : 'Тестовый AI'}</Badge></header>
    <main className="candidate-content"><ErrorBox text={error}/>{!data ? <div className="empty">{error ? 'Проверьте ссылку приглашения.' : 'Загрузка интервью…'}</div> : finished ? <section className="card completion"><div className="completion-icon"><CheckCircle2 size={44}/></div><span className="eyebrow">ИНТЕРВЬЮ ЗАВЕРШЕНО</span><h1>Спасибо, {data.interview.name.split(' ')[0]}.</h1><p className="muted">Ваши ответы сохранены. Работодатель увидит их в отчёте.</p><div className="tags"><span>{data.answers.length} ответов</span><span>{data.events.length} событий</span><span>{data.interview.recording_complete ? 'Видео сохранено' : 'Запись неполная'}</span></div><p className="note">{data.interview.mode === 'mock' ? 'Это тестовое прохождение. AI-оценки не выставлялись.' : 'Результаты требуют проверки работодателем.'}</p></section>
    : <><div className="candidate-title"><div><span className="eyebrow">ВАШЕ ПРОСТРАНСТВО ИНТЕРВЬЮ</span><h1>{running ? 'Покажите, как вы думаете.' : `Здравствуйте, ${data.interview.name.split(' ')[0]}.`}</h1></div>{running && <div className="timer"><Radio size={17}/> {clock(elapsed)}</div>}</div>
      {warning && <div className="warning" role="alert"><ShieldCheck size={21}/><span>{warning}</span><button className="icon-button" aria-label="Закрыть предупреждение" onClick={() => setWarning('')}><X size={18}/></button></div>}
      <div className="agent-status"><GlassOrb compact state={speaking ? 'speaking' : audioRecording ? 'listening' : busy ? 'thinking' : 'idle'}/><div><strong>Ваш AI-интервьюер</strong><span aria-live="polite">{stateNames[speaking ? 'speaking' : audioRecording ? 'listening' : busy ? 'thinking' : 'idle']}</span></div></div>
      <div className="interview-grid"><section className="interview-main">
      {!running ? <div className="card onboarding"><Badge>7–10 минут · 5 этапов</Badge><h2>Небольшая подготовка —<br/>и можно начинать.</h2><p className="muted">Три вопроса о Python, AsyncIO и SQL, задача с кодом и объяснение решения.</p><div className="rule"><Video/><div><strong>Камера и микрофон</strong><p>Запись камеры и вашего голоса будет доступна работодателю.</p></div></div><div className="rule"><ShieldCheck/><div><strong>Прозрачные правила</strong><p>Уход со страницы, потеря фокуса, вставка текста и отключение устройств фиксируются с предупреждением.</p></div></div><div className="note">В этом каркасе распознавание лиц и телефона ещё не подключено. Озвучка браузера может не попасть в запись. Запуск Python отключён до подключения изолированного runner.</div><label className="checkbox"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)}/> Я согласен на запись и передачу ответов и событий работодателю.</label>{interrupted ? <div className="error-box">Это интервью уже запущено. Вернитесь в исходную вкладку. После перезагрузки запись не возобновляется — создайте новое приглашение в кабинете.</div> : <button className="primary" disabled={!consent || !cameraOk || busy} onClick={() => void start()}>Начать интервью <ArrowRight size={18}/></button>}</div>
      : question && !stopped ? <div className="card question-card"><div className="section-top"><Badge tone="purple">Этап {data.answers.length + 1} / {data.questions.length}</Badge><span className="tiny muted">{question.skill}</span></div><div className="interviewer"><span className="ai-avatar"><AudioLines size={23}/></span><div><strong>Интервьюер</strong><span>{data.interview.mode === 'mock' ? 'Подготовленный сценарий' : 'AI · техническое интервью'}</span></div><button className="icon-button" title="Озвучить вопрос голосом браузера" disabled={audioRecording} onClick={() => speak(question.text)}>{speaking ? <AudioLines size={20}/> : <Volume2 size={20}/>}</button></div><h2>{question.text}</h2>
        {question.id === 'coding' ? <><div className="code-toolbar"><span><Code2 size={16}/> solution.py</span><Badge>Python 3</Badge></div><textarea className="code-editor" aria-label="Python-код" spellCheck={false} value={code} onChange={e => setCode(e.target.value)} onPaste={e => reportEvent.current('paste', `Вставка в редактор: ${e.clipboardData.getData('text').length} символов. Будьте готовы объяснить решение.`)}/><div className="code-example">Пример: [{'{'}&quot;name&quot;: &quot;Анна&quot;, &quot;city&quot;: &quot;Москва&quot;{'}'}] → {'{'}&quot;Москва&quot;: [&quot;Анна&quot;]{'}'}</div><div className="note">Код будет сохранён для обсуждения. Проверка тестами ещё не подключена.</div></> : <><label className="answer-label">Ваш ответ<textarea placeholder="Запишите голосовой ответ или напишите здесь…" value={answer} onChange={e => setAnswer(e.target.value)} maxLength={16000} onPaste={e => reportEvent.current('paste', `Вставка в ответ: ${e.clipboardData.getData('text').length} символов.`)}/></label><div className="button-row"><button className={`secondary ${audioRecording ? 'recording-button' : ''}`} disabled={!data.capabilities.stt_ready || busy || !cameraOk} onClick={() => void toggleAudio()}>{audioRecording ? <Square size={16}/> : <Mic size={16}/>} {audioRecording ? 'Завершить запись ответа' : 'Ответить голосом'}</button><span className="tiny muted">{data.capabilities.stt_ready ? 'Проверьте расшифровку перед отправкой' : 'Для распознавания нужен GROQ_API_KEY'}</span></div></>}
        <div className="question-bottom"><span className="tiny muted">{data.interview.mode === 'mock' ? 'Ответ сохранится без AI-оценки' : 'Оценка по профессиональным критериям'}</span><button className="primary" disabled={busy || audioRecording || !cameraOk || !(question.id === 'coding' ? code.trim() : answer.trim())} onClick={() => void submit()}>{busy ? <Loader2 size={17} className="spin"/> : <ArrowRight size={17}/>} Отправить ответ</button></div></div>
      : <div className="card completion"><CheckCircle2 size={40}/><h2>Ответы сохранены</h2><p className="muted">Завершите интервью, чтобы собрать видеозапись и открыть отчёт работодателю.</p><button className="primary" disabled={busy || audioRecording} onClick={() => void finish()}>{busy && <Loader2 size={17} className="spin"/>} Завершить и сохранить</button></div>}
      </section><aside className="interview-side"><div className="card camera-card"><div className="camera-frame"><video ref={videoRef} muted autoPlay playsInline/>{!cameraOk && <div className="camera-placeholder"><Video size={34}/><span>Предпросмотр камеры</span></div>}{running && <span className="rec-label"><Circle size={8} fill="currentColor"/> REC</span>}</div><div className="camera-caption"><span><span className={`status-dot ${cameraOk ? 'online' : ''}`}/>{cameraOk ? 'Камера подключена' : 'Камера не подключена'}</span>{running && <span>{clock(elapsed)}</span>}</div>{!running && !interrupted && <button className="secondary full" disabled={busy} onClick={() => void checkCamera()}><Video size={16}/> Проверить устройства</button>}</div>
        <div className="card checklist"><span className="eyebrow">ПЛАН ИНТЕРВЬЮ</span>{data.questions.map((q, index) => <div className={`step ${index === data.answers.length ? 'current' : ''}`} key={q.id}><span className="step-dot">{index < data.answers.length ? <Check size={13}/> : index + 1}</span><span>{q.skill}</span></div>)}</div>
        {running && <div className="card recording-status"><span className="eyebrow">СОХРАНЕНИЕ</span><p><Video size={16}/> {uploaded} фрагментов загружено</p><p><ShieldCheck size={16}/> {events.length} событий {pending ? `· ${pending} ожидают отправки` : ''}</p><button className="text-link" onClick={() => void flushChunks()}>Повторить загрузку</button><button className="secondary full" disabled={busy || audioRecording} onClick={() => void finish()}>Завершить досрочно</button><p className="tiny muted">Не закрывайте вкладку до подтверждения сохранения.</p></div>}
      </aside></div>
    </>}</main></div>;
}

function Report({data, companyKey, onBack}: {data: Details; companyKey: string; onBack: () => void}) {
  const [tab, setTab] = useState<'skills' | 'answers' | 'recording'>('skills');
  const [url, setUrl] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const ref = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    let objectUrl = ''; let cancelled = false;
    if (data.interview.recording_complete) {
      setLoading(true);
      fetch(`/api/company/interviews/${data.interview.id}/recording`, {headers: {'X-Company-Key': companyKey}})
        .then(async r => {if (!r.ok) throw new Error('Не удалось загрузить видео'); return r.blob();})
        .then(blob => {if (!cancelled) {objectUrl = URL.createObjectURL(blob); setUrl(objectUrl);}})
        .catch(e => {if (!cancelled) setError(e.message);}).finally(() => {if (!cancelled) setLoading(false);});
    }
    return () => {cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl);};
  }, [data.interview.id, data.interview.recording_complete, companyKey]);
  return <><button className="text-link back-link" onClick={onBack}><ArrowLeft size={16}/> Все кандидаты</button><div className="report-heading"><div><span className="eyebrow">ОТЧЁТ ОБ ИНТЕРВЬЮ</span><h1>{data.interview.name}</h1><p className="muted">Python Backend Developer · {new Date(data.interview.created * 1000).toLocaleDateString('ru-RU')}</p></div><Badge tone="green">{labels[data.interview.status]}</Badge></div><ErrorBox text={error}/>
    <div className="note report-note">{data.interview.mode === 'mock' ? 'Тестовое прохождение. AI-оценки не выставлялись. Ответы, события и запись — реальные.' : 'Предварительная AI-оценка. Проверьте основания по ответам кандидата; решение о найме остаётся за вами.'} Код не запускался; результатов тестов нет.</div>
    <div className="stats"><Stat label="Сохранено ответов" value={`${data.answers.length} / 5`} icon={<FileText/>}/><Stat label="События прокторинга" value={String(data.events.length)} icon={<ShieldCheck/>}/><Stat label="Видеозапись" value={data.interview.recording_complete ? 'Сохранена' : 'Неполная'} icon={<Video/>}/></div>
    <div className="report-tabs" aria-label="Разделы отчёта">{([{id:'skills', label:'Навыки'}, {id:'answers', label:'Ответы и код'}, {id:'recording', label:'Запись и события'}] as const).map(item => <button key={item.id} aria-pressed={tab === item.id} onClick={() => setTab(item.id)}>{item.label}</button>)}</div>
    {tab === 'skills' && <div className="report-skills">{data.questions.map(q => {const answer = data.answers.find(a => a.question_id === q.id); return <article className="card" key={q.id}><h3>{q.skill}</h3><Badge tone={answer?.evaluation ? 'purple' : ''}>{answer?.evaluation ? labels[answer.evaluation.level] : answer ? 'Ответ получен' : 'Нет ответа'}</Badge><p>{answer?.evaluation?.rationale || (answer ? 'Ответ доступен для проверки. AI-оценка не выставлена.' : 'Для оценки пока недостаточно данных.')}</p><button className="text-link" onClick={() => setTab('answers')}>Посмотреть основания <ArrowRight size={14}/></button></article>;})}</div>}
    <div className={`report-grid report-${tab}`} style={tab === 'skills' ? {display: 'none'} : undefined}><section><h2>Ответы и основания</h2>{data.answers.length === 0 && <div className="card empty">Кандидат пока не отправил ответы.</div>}{data.answers.map(a => <article className="card answer-card" key={a.question_id}><div className="section-top"><span className="eyebrow">{data.questions.find(q => q.id === a.question_id)?.skill}</span><Badge tone={a.evaluation ? 'purple' : ''}>{a.evaluation ? labels[a.evaluation.level] : 'Не оценено'}</Badge></div><h3>{data.questions.find(q => q.id === a.question_id)?.text}</h3><pre className={a.question_id === 'coding' ? 'code-answer' : 'text-answer'}>{a.text}</pre>{a.evaluation && <div className="evaluation"><strong>Основание оценки</strong><p>{a.evaluation.rationale}</p>{a.evaluation.evidence.map((quote, i) => <blockquote key={i}>{quote}</blockquote>)}</div>}</article>)}</section>
    <aside><section className="card video-report"><h2>Запись интервью</h2>{loading ? <div className="empty"><Loader2 className="spin"/> Загружаем видео…</div> : url ? <><video ref={ref} src={url} controls playsInline/><a className="text-link" href={url} download={`interview-${data.interview.id}.webm`}><ArrowDownToLine size={16}/> Скачать WebM</a></> : <div className="empty"><Video size={27}/><p>Полная запись пока недоступна.<br/>Получено фрагментов: {data.uploaded_chunks}.</p></div>}<p className="tiny muted">Камера и микрофон кандидата. Озвучка браузера может отсутствовать.</p></section><section className="card timeline"><h2>События прокторинга</h2><p className="muted tiny">Сигналы для проверки, а не доказательство списывания. Распознавание лиц и телефона не подключено.</p>{data.events.length === 0 ? <p className="muted">Зарегистрированных событий нет.</p> : data.events.map(event => <div className="timeline-event" key={event.id}><button disabled={!url} className="time-link" onClick={() => {if (ref.current) {ref.current.currentTime = event.elapsed; void ref.current.play().catch(() => {});}}}>{clock(event.elapsed)}</button><div><strong>{labels[event.kind] || event.kind}</strong><p>{event.detail}</p></div></div>)}</section></aside></div>
  </>;
}
