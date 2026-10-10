'use client';

import {useCallback,useEffect,useState} from 'react';
import {CheckCircle2,Copy,RefreshCw,ShieldAlert} from 'lucide-react';
import type {Access} from './ai-session';

type ComponentName='extension';
type MonitorComponent={paired:boolean;online:boolean;last_seen:string|number|null};
export type MonitorObservation={
  id:string;product_id:string|null;product_name:string|null;kind:string;
  observed_at:string|number;state?:'detected'|'cleared';summary_only?:boolean;
};
export type MonitorStatus={
  enabled:boolean;consented:boolean;platform:'windows'|'other'|null;start_ready:boolean;
  components:{helper:MonitorComponent;extension:MonitorComponent};
  observations:MonitorObservation[];
};
type PairCode={code:string;expires_at:string|number};

function currentPlatform():'windows'|'other'{
  return typeof navigator!=='undefined'&&/Windows/i.test(navigator.userAgent)?'windows':'other';
}
function readableTime(value:string|number|null|undefined){
  if(value==null)return '';
  const date=new Date(typeof value==='number'&&value<1e12?value*1000:value);
  return Number.isNaN(date.getTime())?'':date.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'});
}
function timeValue(value:string|number){
  return new Date(typeof value==='number'&&value<1e12?value*1000:value).getTime();
}
export function observationText(item:MonitorObservation){
  const product=item.product_name||item.product_id||'Помощник';
  if(item.kind==='agent_offline')return item.state==='cleared'?'Связь с Windows-помощником восстановлена.':'Windows-помощник потерял связь с MIMAS.';
  if(item.kind==='extension_offline')return item.state==='cleared'?'Связь с расширением восстановлена.':'Расширение браузера потеряло связь с MIMAS.';
  if(item.state==='cleared')return 'Совпадение с «'+product+'» больше не обнаруживается.';
  switch(item.kind){
    case 'running_process':return 'Обнаружена запущенная программа «'+product+'».';
    case 'foreground_window':return 'Окно «'+product+'» было активным.';
    case 'topmost_overlay':return 'Окно «'+product+'» находилось поверх интервью.';
    case 'background_tab':return 'Вкладка «'+product+'» была открыта в фоне.';
    case 'active_tab':return 'Вкладка «'+product+'» была активна.';
    default:return 'Зафиксировано совпадение с «'+product+'».';
  }
}
async function monitorRequest<T>(path:string,access:Access,body?:unknown):Promise<T>{
  const response=await fetch('/api/ai/sessions/'+encodeURIComponent(access.id)+'/monitor'+path,{
    method:body===undefined?'GET':'POST',
    headers:{'X-Interview-Token':access.token,...(body===undefined?{}:{'Content-Type':'application/json'})},
    body:body===undefined?undefined:JSON.stringify(body),cache:'no-store',
  });
  if(!response.ok){
    const error=await response.json().catch(()=>({}));
    throw new Error(typeof error.detail==='string'?error.detail:'Не удалось проверить подключение ('+response.status+').');
  }
  return response.json() as Promise<T>;
}
export function useCandidateMonitor(access:Access|null,phase:string|undefined){
  const [status,setStatus]=useState<MonitorStatus|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [codes,setCodes]=useState<Partial<Record<ComponentName,PairCode>>>({});
  const [platform,setPlatform]=useState<'windows'|'other'>('other');
  useEffect(()=>{setPlatform(currentPlatform());},[]);
  const refresh=useCallback(async()=>{
    if(!access)return;
    try{
      const next=await monitorRequest<MonitorStatus>('/status',access);
      setStatus(next);setError('');
    }catch(e){setError((e as Error).message);}
  },[access?.id,access?.token]);
  useEffect(()=>{
    if(!access){setStatus(null);setCodes({});return;}
    void refresh();
    if(phase==='COMPLETED')return;
    const timer=window.setInterval(()=>void refresh(),3000);
    return()=>window.clearInterval(timer);
  },[access?.id,access?.token,phase,refresh]);
  const consent=useCallback(async()=>{
    if(!access)return;
    setBusy(true);setError('');
    try{await monitorRequest('/consent',access,{accepted:true,platform});await refresh();}
    catch(e){setError((e as Error).message);}finally{setBusy(false);}
  },[access?.id,access?.token,platform,refresh]);
  const pair=useCallback(async(component:ComponentName)=>{
    if(!access)return;
    setBusy(true);setError('');
    try{
      const code=await monitorRequest<PairCode>('/pair',access,{component});
      setCodes(previous=>({...previous,[component]:code}));
      await refresh();
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  },[access?.id,access?.token,refresh]);
  return {
    status,error,busy,codes,platform,refresh,consent,pair,
    startReady:Boolean(status&&(!status.enabled||(status.consented&&status.start_ready))),
  };
}
export type CandidateMonitor=ReturnType<typeof useCandidateMonitor>;

function ConnectionLine({label,component,code,busy,onPair}:{
  label:string;component:MonitorComponent;code:PairCode|undefined;busy:boolean;onPair:()=>void;
}){
  const [copied,setCopied]=useState(false);
  async function copyCode(){
    if(!code)return;
    try{await navigator.clipboard.writeText(code.code);setCopied(true);window.setTimeout(()=>setCopied(false),2000);}
    catch{setCopied(false);}
  }
  return <div className="monitor-component">
    <div><strong>{label}</strong><span className={component.online?'badge green':'badge amber'}>{component.online?'Подключён':component.paired?'Нет связи':'Не подключён'}</span></div>
    {!component.online&&<button type="button" className="secondary" disabled={busy} onClick={onPair}>{component.paired?'Новый код подключения':'Получить код'}</button>}
    {code&&!component.online&&<div className="monitor-code"><code>{code.code}</code><button type="button" className="secondary" onClick={()=>void copyCode()}><Copy size={14}/>{copied?'Скопировано':'Копировать'}</button><span className="tiny muted">Код действует до {readableTime(code.expires_at)}. Вставьте его только в {label.toLowerCase()}.</span></div>}
  </div>;
}
export function CandidateMonitorPanel({monitor,phase}:{monitor:CandidateMonitor;phase:string|undefined}){
  const {status,error,busy,codes,refresh,consent,pair}=monitor;
  const [accepted,setAccepted]=useState(false);
  const [dismissed,setDismissed]=useState<string|null>(null);
  if(!status&&!error)return <p className="tiny muted">Проверяем настройки наблюдения…</p>;
  if(!status&&error)return <section className="card monitor-panel"><p role="alert" className="warning">{error}</p><button type="button" className="secondary" onClick={()=>void refresh()}><RefreshCw size={15}/> Повторить проверку</button></section>;
  if(!status?.enabled)return null;
  const preparing=phase==='CREATED';
  const observations=[...status.observations].sort((a,b)=>timeValue(b.observed_at)-timeValue(a.observed_at));
  const recent=observations.slice(0,3);
  const latestAlert=observations.find(item=>item.state==='detected'&&timeValue(item.observed_at)>Date.now()-120000);
  const disconnected=status.consented&&status.components.extension.paired&&!status.components.extension.online&&phase!=='CREATED'&&phase!=='COMPLETED';
  return <><section className="card monitor-panel" aria-label="Проверка среды интервью">
    <div className="section-top"><div><span className="eyebrow">ПРОВЕРКА СРЕДЫ</span><h2>{preparing?'Согласие перед интервью':'Наблюдение во время интервью'}</h2></div><ShieldAlert size={22}/></div>
    <p className="muted">Страница отмечает уход из окна интервью, но не видит названия других программ. Необязательное расширение Chrome/Edge проверяет вкладки с известными помощниками и передаёт только совпадения. Список программ, адреса остальных вкладок, скриншоты и содержимое окон не передаются. Предупреждение не снижает оценку и не означает отказа.</p>
    {!status.consented?<div className="monitor-consent"><label className="market-consent"><input type="checkbox" checked={accepted} onChange={e=>setAccepted(e.target.checked)}/> Я согласен(на) на проверку во время интервью и передачу совпадений компании по этой вакансии.</label><button type="button" className="primary" disabled={!accepted||busy} onClick={()=>void consent()}>Подтвердить проверку</button></div>
      :<><p className="note"><CheckCircle2 size={16}/> Согласие подтверждено. Можно начать интервью без дополнительных программ и расширений.</p>
        <p className="tiny muted">Если хотите проверить вкладки известных помощников, установите расширение Chrome/Edge из пакета команды MIMAS, выберите адрес интервью и введите одноразовый код. Это необязательно: отсутствие расширения не мешает интервью и не влияет на оценку.</p>
        <ConnectionLine label="Расширение Chrome/Edge (необязательно)" component={status.components.extension} code={codes.extension} busy={busy} onPair={()=>void pair('extension')}/>
      </>}
    {disconnected&&<p role="alert" className="warning">Расширение потеряло связь. Интервью продолжается, оценка не меняется. При желании подключите расширение снова.</p>}
    {recent.length>0&&<div className="monitor-observations"><strong>Наблюдения</strong>{recent.map(item=><p key={item.id} role="alert" className="warning">{observationText(item)} <span className="tiny">{readableTime(item.observed_at)}</span></p>)}<p className="tiny muted">Если совпадение ошибочное, сообщите об этом работодателю. Окончательное решение принимает человек.</p></div>}
    {error&&<p role="alert" className="error-box">{error}</p>}
  </section>{latestAlert&&latestAlert.id!==dismissed&&<div className="monitor-toast" role="alert"><ShieldAlert size={18}/><span>{observationText(latestAlert)} Совпадение не влияет автоматически на оценку.</span><button type="button" aria-label="Закрыть предупреждение" onClick={()=>setDismissed(latestAlert.id)}>×</button></div>}</>;
}
type MonitorSummary={product_id:string|null;product_name:string|null;kind:string;detected_count:number};
export function EmployerMonitorReport({sessionId,companyKey}:{sessionId:string;companyKey:string}){
  const [items,setItems]=useState<MonitorObservation[]|null>(null);
  const [summary,setSummary]=useState<MonitorSummary[]>([]);
  const [enabled,setEnabled]=useState(false);
  const [error,setError]=useState('');
  useEffect(()=>{
    let cancelled=false;
    void (async()=>{
      try{
        const response=await fetch('/api/market/company/assessments/'+encodeURIComponent(sessionId)+'/monitor',{headers:{'X-Company-Key':companyKey},cache:'no-store'});
        if(response.status===404)return;
        if(!response.ok)throw new Error('Наблюдения пока недоступны.');
        const body=await response.json() as {enabled?:boolean;observations?:MonitorObservation[];summary?:MonitorSummary[]};
        if(!cancelled){setEnabled(body.enabled!==false);setItems(body.observations||[]);setSummary(body.summary||[]);}
      }catch(e){if(!cancelled)setError((e as Error).message);}
    })();
    return()=>{cancelled=true;};
  },[sessionId,companyKey]);
  if(error)return <p role="status" className="note">{error}</p>;
  if(!enabled||!items)return null;
  return <section className="card monitor-panel" aria-label="Наблюдения во время интервью">
    <span className="eyebrow">СРЕДА ИНТЕРВЬЮ</span><h4>Наблюдения о помощниках</h4>
    <p className="muted tiny">Эти записи показывают только совпадения с каталогом. Открытая фоновая вкладка не доказывает её использование. Ни одна запись не влияет автоматически на техническую оценку.</p>
    {items.length===0&&summary.length===0?<p className="muted">Зафиксированных наблюдений нет.</p>:<>{items.length>0&&<ul className="monitor-report-list">{[...items].sort((a,b)=>timeValue(b.observed_at)-timeValue(a.observed_at)).map(item=><li key={item.id}><strong>{observationText(item)}</strong><span className="tiny muted">{readableTime(item.observed_at)}</span></li>)}</ul>}{summary.length>0&&<div className="monitor-summary"><strong>Сводка после удаления подробностей (30 дней)</strong><ul>{summary.map((item,index)=><li key={index}>{item.product_name||item.product_id||'Проверка подключения'} · {item.kind}: {item.detected_count}</li>)}</ul></div>}</>}
  </section>;
}
