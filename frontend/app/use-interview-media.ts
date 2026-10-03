'use client';

import {useCallback,useEffect,useRef,useState} from 'react';
import type {Access} from './ai-session';

type MediaStatus='idle'|'starting'|'recording'|'uploading'|'complete'|'interrupted'|'error';
type StoredChunk={key:string;sessionId:string;seq:number;blob:Blob};
type StoredPart={key:string;sessionId:string;partNumber:number;blob:Blob;etag?:string};
type StoredMeta={sessionId:string;partSize:number;started:boolean;completed:boolean;uploadId:string|null};
const DB_NAME='mimas-interview-recordings';
const DB_VERSION=1;
function openDb():Promise<IDBDatabase>{
  return new Promise((resolve,reject)=>{
    const request=indexedDB.open(DB_NAME,DB_VERSION);
    request.onupgradeneeded=()=>{
      const db=request.result;
      if(!db.objectStoreNames.contains('chunks'))db.createObjectStore('chunks',{keyPath:'key'});
      if(!db.objectStoreNames.contains('parts'))db.createObjectStore('parts',{keyPath:'key'});
      if(!db.objectStoreNames.contains('meta'))db.createObjectStore('meta',{keyPath:'sessionId'});
    };
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(request.error||new Error('Локальное хранилище записи недоступно.'));
  });
}
async function readOne<T>(store:string,key:string):Promise<T|undefined>{
  const db=await openDb();
  return new Promise((resolve,reject)=>{
    const transaction=db.transaction(store,'readonly');
    const request=transaction.objectStore(store).get(key);
    request.onsuccess=()=>resolve(request.result as T|undefined);
    request.onerror=()=>reject(request.error);
    transaction.oncomplete=()=>db.close();
    transaction.onerror=()=>{db.close();reject(transaction.error);};
  });
}
async function readAll<T>(store:string,sessionId:string):Promise<T[]>{
  const db=await openDb();
  return new Promise((resolve,reject)=>{
    const transaction=db.transaction(store,'readonly');
    const request=transaction.objectStore(store).getAll();
    request.onsuccess=()=>resolve((request.result as (T&{sessionId:string})[]).filter(item=>item.sessionId===sessionId));
    request.onerror=()=>reject(request.error);
    transaction.oncomplete=()=>db.close();
    transaction.onerror=()=>{db.close();reject(transaction.error);};
  });
}
async function writeOne(store:string,value:unknown):Promise<void>{
  const db=await openDb();
  return new Promise((resolve,reject)=>{
    const transaction=db.transaction(store,'readwrite');
    transaction.objectStore(store).put(value);
    transaction.oncomplete=()=>{db.close();resolve();};
    transaction.onerror=()=>{db.close();reject(transaction.error);};
  });
}
async function deleteOne(store:string,key:string):Promise<void>{
  const db=await openDb();
  return new Promise((resolve,reject)=>{
    const transaction=db.transaction(store,'readwrite');
    transaction.objectStore(store).delete(key);
    transaction.oncomplete=()=>{db.close();resolve();};
    transaction.onerror=()=>{db.close();reject(transaction.error);};
  });
}
async function parseError(response:Response){
  const body=await response.json().catch(()=>({}));
  return new Error(typeof body.detail==='string'?body.detail:'Ошибка загрузки записи ('+response.status+')');
}
class RecordingController{
  readonly id:string;
  private token:string;
  private stream:MediaStream;
  private onStatus:(status:MediaStatus)=>void;
  private onError:(text:string)=>void;
  private recorder:MediaRecorder|null=null;
  private partSize=5*1024*1024;
  private chunks:StoredChunk[]=[];
  private size=0;
  private nextChunk=1;
  private nextPart=1;
  private writeQueue:Promise<void>=Promise.resolve();
  private uploadQueue:Promise<void>=Promise.resolve();
  private interrupted=false;
  private finished=false;
  private completed=false;
  private uploadId:string|null=null;
  constructor(access:Access,stream:MediaStream,onStatus:(status:MediaStatus)=>void,onError:(text:string)=>void){
    this.id=access.id;this.token=access.token;this.stream=stream;this.onStatus=onStatus;this.onError=onError;
  }
  private async api(path:string,body?:unknown):Promise<unknown>{
    const response=await fetch('/api/ai/sessions/'+this.id+'/recording'+path,{method:'POST',headers:{'X-Interview-Token':this.token,'Content-Type':'application/json'},body:JSON.stringify(body||{}),cache:'no-store'});
    if(!response.ok)throw await parseError(response);
    return response.json();
  }
  private async init():Promise<string>{
    const result=await this.api('/init') as {upload_id:string|null;part_size:number;status:string};
    if(result.part_size>=5*1024*1024)this.partSize=result.part_size;
    const previous=await readOne<StoredMeta>('meta',this.id);
    if(previous?.uploadId&&result.upload_id&&previous.uploadId!==result.upload_id){
      const parts=await readAll<StoredPart>('parts',this.id);
      for(const part of parts)await writeOne('parts',{...part,etag:undefined} satisfies StoredPart);
    }
    this.uploadId=result.upload_id;
    if(previous)await writeOne('meta',{...previous,uploadId:result.upload_id} satisfies StoredMeta);
    return result.status;
  }
  async start(){
    this.onStatus('starting');
    if(typeof indexedDB==='undefined')throw new Error('Для сохранения записи требуется браузер с IndexedDB.');
    const previous=await readOne<StoredMeta>('meta',this.id);
    const serverStatus=await this.init();
    if(serverStatus==='completed'){this.completed=true;this.onStatus('complete');return;}
    if(previous&&!previous.completed){
      this.interrupted=true;this.partSize=previous.partSize||this.partSize;
      const parts=await readAll<StoredPart>('parts',this.id);
      const chunks=await readAll<StoredChunk>('chunks',this.id);
      this.nextPart=Math.max(0,...parts.map(p=>p.partNumber))+1;
      this.nextChunk=Math.max(0,...chunks.map(p=>p.seq))+1;
      this.onStatus('interrupted');
      this.onError('Запись была прервана. Сохранённые фрагменты можно повторно загрузить. Новое видео не будет незаметно добавлено к старому.');
      return;
    }
    if(previous?.completed){this.completed=true;this.onStatus('complete');return;}
    const type=['video/webm;codecs=vp8,opus','video/webm'].find(value=>MediaRecorder.isTypeSupported(value));
    if(!type)throw new Error('Браузер не поддерживает запись видео. Попробуйте Chrome или Edge.');
    await writeOne('meta',{sessionId:this.id,partSize:this.partSize,started:true,completed:false,uploadId:this.uploadId} satisfies StoredMeta);
    this.recorder=new MediaRecorder(this.stream,{mimeType:type,videoBitsPerSecond:750000});
    this.recorder.ondataavailable=event=>{
      if(!event.data.size)return;
      const chunk:StoredChunk={key:this.id+':chunk:'+this.nextChunk,sessionId:this.id,seq:this.nextChunk++,blob:event.data};
      this.chunks.push(chunk);this.size+=event.data.size;
      this.writeQueue=this.writeQueue.then(()=>writeOne('chunks',chunk));
      if(this.size>=this.partSize)this.flushPart(false);
    };
    this.recorder.onerror=()=>{this.onStatus('error');this.onError('Ошибка записи камеры. Сохраните доступные фрагменты и завершите интервью.');};
    this.recorder.start(1000);
    this.onStatus('recording');
  }
  private flushPart(force:boolean){
    if(!this.chunks.length||(!force&&this.size<this.partSize))return;
    const selected=this.chunks;this.chunks=[];this.size=0;
    const number=this.nextPart++;
    const part:StoredPart={key:this.id+':part:'+number,sessionId:this.id,partNumber:number,blob:new Blob(selected.map(c=>c.blob),{type:this.recorder?.mimeType||'video/webm'})};
    this.writeQueue=this.writeQueue.then(async()=>{
      await writeOne('parts',part);
      await Promise.all(selected.map(chunk=>deleteOne('chunks',chunk.key)));
    });
    this.uploadQueue=this.uploadQueue.catch(()=>{}).then(async()=>{
      await this.writeQueue;
      await this.uploadPart(part);
    }).catch(e=>this.onError('Не удалось загрузить видео: '+(e as Error).message+'. Сохранённые части можно отправить повторно.'));
  }
  private async uploadPart(part:StoredPart){
    const signed=await this.api('/parts/'+part.partNumber+'/url') as {url:string};
    const response=await fetch(signed.url,{method:'PUT',body:part.blob,headers:{'Content-Type':part.blob.type||'application/octet-stream'}});
    if(!response.ok)throw new Error('хранилище вернуло '+response.status);
    const etag=response.headers.get('ETag')||response.headers.get('etag');
    if(!etag)throw new Error('хранилище не открыло ETag; проверьте CORS бакета');
    await writeOne('parts',{...part,etag} satisfies StoredPart);
  }
  private async recoverChunks(){
    const chunks=(await readAll<StoredChunk>('chunks',this.id)).sort((a,b)=>a.seq-b.seq);
    if(!chunks.length)return;
    const parts=await readAll<StoredPart>('parts',this.id);
    const number=Math.max(0,...parts.map(p=>p.partNumber))+1;
    const part:StoredPart={key:this.id+':part:'+number,sessionId:this.id,partNumber:number,blob:new Blob(chunks.map(c=>c.blob),{type:'video/webm'})};
    await writeOne('parts',part);
    await Promise.all(chunks.map(chunk=>deleteOne('chunks',chunk.key)));
  }
  private async uploadMissing(){
    const parts=(await readAll<StoredPart>('parts',this.id)).sort((a,b)=>a.partNumber-b.partNumber);
    for(const part of parts)if(!part.etag)await this.uploadPart(part);
    return (await readAll<StoredPart>('parts',this.id)).sort((a,b)=>a.partNumber-b.partNumber);
  }
  async retry():Promise<boolean>{
    if(this.completed){this.onStatus('complete');return true;}
    if(!this.recorder&&!this.interrupted&&!this.finished){try{await this.start();return true;}catch(e){this.onStatus('error');this.onError((e as Error).message);return false;}}
    this.onStatus('uploading');this.onError('');
    try{
      const serverStatus=await this.init();
      if(serverStatus==='completed'){this.completed=true;this.onStatus('complete');return true;}
      await this.writeQueue;await this.uploadQueue;
      if(this.interrupted||this.finished)await this.recoverChunks();
      const parts=await this.uploadMissing();
      if(this.interrupted||this.finished)await this.complete(parts);
      else this.onStatus('recording');
      return true;
    }catch(e){this.onStatus(this.interrupted?'interrupted':'error');this.onError('Видео осталось в этом браузере. Повторите загрузку: '+(e as Error).message);return false;}
  }
  private async complete(parts:StoredPart[]){
    if(!parts.length)throw new Error('Запись пуста. Попробуйте начать интервью заново.');
    if(parts.some((part,index)=>part.partNumber!==index+1||!part.etag))throw new Error('Не все части записи загружены.');
    await this.api('/complete',{parts:parts.map(part=>({part_number:part.partNumber,etag:part.etag})),interrupted:this.interrupted});
    await writeOne('meta',{sessionId:this.id,partSize:this.partSize,started:true,completed:true,uploadId:null} satisfies StoredMeta);
    await Promise.all(parts.map(part=>deleteOne('parts',part.key)));
    this.completed=true;this.onStatus('complete');this.onError(this.interrupted?'Загружена частичная запись: браузер прервал исходную съёмку.':'');
  }
  async finish(interrupted=false):Promise<boolean>{
    if(this.completed)return true;
    if(interrupted)this.interrupted=true;
    if(this.finished)return this.retry();
    this.finished=true;this.onStatus('uploading');
    if(this.recorder&&this.recorder.state!=='inactive'){
      const recorder=this.recorder;
      await new Promise<void>(resolve=>{recorder.addEventListener('stop',()=>resolve(),{once:true});recorder.stop();});
    }
    this.flushPart(true);
    return this.retry();
  }
  stop(){
    if(this.recorder&&this.recorder.state!=='inactive')this.recorder.stop();
  }
}
export function useInterviewMedia(access?:Access,stream?:MediaStream){
  const [status,setStatus]=useState<MediaStatus>('idle');
  const [error,setError]=useState('');
  const videoRef=useRef<HTMLVideoElement>(null);
  const controllerRef=useRef<RecordingController|null>(null);
  useEffect(()=>{if(videoRef.current)videoRef.current.srcObject=stream||null;},[stream,status]);
  useEffect(()=>{
    if(!access||!stream)return;
    const controller=new RecordingController(access,stream,setStatus,setError);controllerRef.current=controller;
    void controller.start().catch(e=>{setStatus('error');setError((e as Error).message);});
    return ()=>{controller.stop();controllerRef.current=null;};
  },[access?.id,access?.token,stream]);
  const finish=useCallback(async(interrupted=false)=>await controllerRef.current?.finish(interrupted)??false,[]);
  const retry=useCallback(async()=>await controllerRef.current?.retry()??false,[]);
  return {status,error,videoRef,finish,retry,ready:status==='recording'||status==='complete'||status==='interrupted'};
}
