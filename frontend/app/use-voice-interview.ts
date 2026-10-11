'use client';

import {useCallback,useEffect,useRef,useState} from 'react';
import type {Access,Session} from './ai-session';

export type VoicePhase='idle'|'connecting'|'listening'|'candidate_speaking'|'speaking'|'thinking'|'disconnected'|'completed';
export type VoiceLine={speaker:'candidate'|'mimas';text:string;id:number};
type Message={type:string;sample_rate?:number;audio?:string;speaker?:string;text?:string;message?:string;session?:Session};
const RATE=44100;

function toPcm(input:Float32Array,inputRate:number):string{
  const count=Math.max(1,Math.round(input.length*RATE/inputRate));
  const bytes=new Uint8Array(count*2);
  const view=new DataView(bytes.buffer);
  for(let i=0;i<count;i++){
    const position=i*inputRate/RATE;
    const left=Math.min(input.length-1,Math.floor(position)),right=Math.min(input.length-1,left+1);
    const value=Math.max(-1,Math.min(1,input[left]+(input[right]-input[left])*(position-left)));
    view.setInt16(i*2,value<0?value*32768:value*32767,true);
  }
  let binary='';for(const byte of bytes)binary+=String.fromCharCode(byte);
  return btoa(binary);
}

function fromPcm(value:string,context:AudioContext,rate:number):AudioBuffer{
  const binary=atob(value);
  const count=Math.floor(binary.length/2);
  const result=context.createBuffer(1,count,rate);
  const samples=result.getChannelData(0);
  for(let i=0;i<count;i++){
    const raw=binary.charCodeAt(2*i)|(binary.charCodeAt(2*i+1)<<8);
    samples[i]=(raw>=32768?raw-65536:raw)/32768;
  }
  return result;
}

export function useVoiceInterview(onSession:(session:Session)=>void){
  const [phase,setPhase]=useState<VoicePhase>('idle');
  const [error,setError]=useState('');
  const [muted,setMuted]=useState(false);
  const [lines,setLines]=useState<VoiceLine[]>([]);
  const callback=useRef(onSession);callback.current=onSession;
  const socket=useRef<WebSocket|null>(null);
  const audio=useRef<AudioContext|null>(null);
  const input=useRef<MediaStreamAudioSourceNode|null>(null);
  const processor=useRef<AudioWorkletNode|ScriptProcessorNode|null>(null);
  const sink=useRef<GainNode|null>(null);
  const playing=useRef(new Set<AudioBufferSourceNode>());
  const playbackAt=useRef(0);
  const generation=useRef(0);
  const sequence=useRef(0);
  const mutedRef=useRef(false);
  const closed=useRef(false);
  const rate=useRef(RATE);
  const listenTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const congestion=useRef(false);
  const awaitingPlayback=useRef(false);
  const finished=useRef(false);
  const interrupted=useRef(false);
  const sendingAudio=useRef(false);
  const answerPending=useRef(false);
  const holdingAnswer=useRef(false);
  const answerFlushPending=useRef(false);
  const answerFlushTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const graphReady=useRef(false);
  const answerAllowed=useRef(false);
  const reconnectTimer=useRef<ReturnType<typeof setTimeout>|null>(null);
  const reconnectAttempts=useRef(0);
  const resumeConnection=useRef<((access:Access,stream:MediaStream,resume:boolean)=>Promise<void>)|null>(null);

  const stopPlayback=useCallback(()=>{
    if(listenTimer.current){clearTimeout(listenTimer.current);listenTimer.current=null;}
    for(const source of playing.current){try{source.stop();}catch{/* source already ended */}}
    playing.current.clear();playbackAt.current=audio.current?.currentTime||0;
  },[]);
  const stopGraph=useCallback(()=>{
    if(answerFlushTimer.current){clearTimeout(answerFlushTimer.current);answerFlushTimer.current=null;}
    holdingAnswer.current=false;answerFlushPending.current=false;sendingAudio.current=false;graphReady.current=false;answerAllowed.current=false;
    processor.current?.disconnect();input.current?.disconnect();sink.current?.disconnect();
    processor.current=null;input.current=null;sink.current=null;stopPlayback();
    const context=audio.current;audio.current=null;
    if(context&&context.state!=='closed')void context.close();
  },[stopPlayback]);
  const disconnect=useCallback(()=>{
    if(reconnectTimer.current){clearTimeout(reconnectTimer.current);reconnectTimer.current=null;}
    closed.current=true;generation.current++;sendingAudio.current=false;answerPending.current=false;holdingAnswer.current=false;answerFlushPending.current=false;graphReady.current=false;answerAllowed.current=false;
    const current=socket.current;socket.current=null;
    if(current?.readyState===WebSocket.OPEN)current.send(JSON.stringify({type:'stop'}));
    current?.close();stopGraph();
    setPhase(previous=>previous==='completed'?'completed':'disconnected');
  },[stopGraph]);
  useEffect(()=>()=>disconnect(),[disconnect]);

  const prepare=useCallback(()=>{
    if(!audio.current||audio.current.state==='closed')audio.current=new AudioContext({sampleRate:RATE});
    void audio.current.resume();
  },[]);

  const completeAnswer=useCallback(()=>{
    if(!answerFlushPending.current)return;
    answerFlushPending.current=false;
    if(answerFlushTimer.current){clearTimeout(answerFlushTimer.current);answerFlushTimer.current=null;}
    sendingAudio.current=false;
    const current=socket.current;
    if(current?.readyState===WebSocket.OPEN)current.send(JSON.stringify({type:'finish_answer'}));
    else {answerPending.current=false;setPhase('disconnected');}
  },[]);

  const connect=useCallback(async(access:Access,stream:MediaStream,resume=false)=>{
    if(!stream.getAudioTracks().some(track=>track.readyState==='live')){
      setError('Микрофон недоступен. Разрешите доступ к нему в браузере и повторите подключение.');
      return;
    }
    if(reconnectTimer.current){clearTimeout(reconnectTimer.current);reconnectTimer.current=null;}
    if(socket.current)disconnect();
    if(!resume)reconnectAttempts.current=0;
    closed.current=false;finished.current=false;awaitingPlayback.current=false;interrupted.current=false;sendingAudio.current=false;answerPending.current=false;holdingAnswer.current=false;answerFlushPending.current=false;graphReady.current=false;answerAllowed.current=false;setError('');if(!resume)setLines([]);setPhase('connecting');
    prepare();
    const protocol=window.location.protocol==='https:'?'wss:':'ws:';
    const url=protocol+'//'+window.location.host+'/api/ai/sessions/'+encodeURIComponent(access.id)+'/voice';
    const current=new WebSocket(url);socket.current=current;
    const epoch=++generation.current;
    current.onopen=()=>current.send(JSON.stringify({type:'auth',token:access.token}));
    current.onerror=()=>{if(epoch===generation.current)setError('Не удалось установить голосовое соединение. Проверьте сеть и подключитесь снова.');};
    current.onclose=(closeEvent)=>{
      if(epoch!==generation.current||closed.current)return;
      const answerInterrupted=holdingAnswer.current||answerPending.current;
      socket.current=null;stopGraph();
      if(finished.current){setPhase('completed');return;}
      if(closeEvent.code!==4401&&reconnectAttempts.current<3&&stream.getAudioTracks().some(track=>track.readyState==='live')){
        const attempt=++reconnectAttempts.current;
        setError(answerInterrupted
          ?'Связь прервалась во время ответа. После подключения повторите ответ целиком.'
          :'Голосовой сервис прервал связь. Подключаемся снова…');
        setPhase('connecting');
        reconnectTimer.current=setTimeout(()=>{
          reconnectTimer.current=null;
          if(!closed.current&&epoch===generation.current)void resumeConnection.current?.(access,stream,true);
        },Math.min(5000,attempt*1500));
        return;
      }
      setError(answerInterrupted
        ?'Связь прервалась во время ответа. Нажмите «Подключиться» и повторите ответ целиком.'
        :'Голосовой сервис сейчас недоступен. Нажмите «Подключиться», чтобы попробовать снова.');
      setPhase('disconnected');
    };
    current.onmessage=(event:MessageEvent<string>)=>{
      let message:Message;try{message=JSON.parse(event.data) as Message;}catch{return;}
      if(message.type==='ready'){
        rate.current=message.sample_rate||RATE;
        const context=audio.current;if(!context){setError('Аудиоустройство отключилось.');current.close();return;}
        void (async()=>{
          try{
            await context.resume();
            const source=context.createMediaStreamSource(new MediaStream(stream.getAudioTracks()));
            const mutedSink=context.createGain();mutedSink.gain.value=0;mutedSink.connect(context.destination);
            input.current=source;sink.current=mutedSink;
            const send=(samples:Float32Array)=>{
              if(epoch!==generation.current||!sendingAudio.current||mutedRef.current||current.readyState!==WebSocket.OPEN||context.currentTime<playbackAt.current+0.16)return;
              if(current.bufferedAmount>1024*1024){
                if(!congestion.current){congestion.current=true;setError('Сеть замедлилась. Часть звука не отправляется; проверьте соединение.');}
                return;
              }
              if(congestion.current){congestion.current=false;setError('');}
              current.send(JSON.stringify({type:'audio',audio:toPcm(samples,context.sampleRate)}));
            };
            if(context.audioWorklet){
              // A worklet receives 128 samples per callback. Batch roughly 90 ms of audio.
              const code="class MimasCapture extends AudioWorkletProcessor{constructor(){super();this.buffer=new Float32Array(4096);this.offset=0;this.port.onmessage=event=>{if(event.data?.type==='flush'){if(this.offset){const tail=this.buffer.subarray(0,this.offset);this.port.postMessage(tail,[this.buffer.buffer]);this.buffer=new Float32Array(4096);this.offset=0;}this.port.postMessage({type:'flushed'});}};}process(inputs){const channel=inputs[0]&&inputs[0][0];if(channel){let cursor=0;while(cursor<channel.length){const length=Math.min(channel.length-cursor,this.buffer.length-this.offset);this.buffer.set(channel.subarray(cursor,cursor+length),this.offset);this.offset+=length;cursor+=length;if(this.offset===this.buffer.length){this.port.postMessage(this.buffer,[this.buffer.buffer]);this.buffer=new Float32Array(4096);this.offset=0;}}}return true;}}registerProcessor('mimas-capture',MimasCapture);";
              const moduleUrl=URL.createObjectURL(new Blob([code],{type:'text/javascript'}));
              try{await context.audioWorklet.addModule(moduleUrl);}finally{URL.revokeObjectURL(moduleUrl);}
              if(epoch!==generation.current)return;
              const node=new AudioWorkletNode(context,'mimas-capture');
              node.port.onmessage=(audioEvent:MessageEvent<Float32Array|{type:string}>)=>{
                if(audioEvent.data instanceof Float32Array)send(audioEvent.data);
                else if(audioEvent.data?.type==='flushed')completeAnswer();
              };
              source.connect(node);node.connect(mutedSink);processor.current=node;
            }else{
              const node=context.createScriptProcessor(2048,1,1);
              node.onaudioprocess=audioEvent=>send(new Float32Array(audioEvent.inputBuffer.getChannelData(0)));
              source.connect(node);node.connect(mutedSink);processor.current=node;
            }
            if(epoch!==generation.current)return;
            graphReady.current=true;
            if(answerAllowed.current&&!answerPending.current&&!holdingAnswer.current)setPhase('listening');
          }catch(cause){setError('Не удалось подключить микрофон: '+(cause as Error).message);current.close();}
        })();
        return;
      }
      if(message.type==='audio'&&message.audio){
        answerAllowed.current=false;answerPending.current=false;holdingAnswer.current=false;
        awaitingPlayback.current=true;
        sendingAudio.current=false;
        if(listenTimer.current){clearTimeout(listenTimer.current);listenTimer.current=null;}
        const context=audio.current;if(!context)return;
        try{
          const sound=context.createBufferSource();sound.buffer=fromPcm(message.audio,context,rate.current);
          sound.connect(context.destination);playing.current.add(sound);
          sound.onended=()=>playing.current.delete(sound);
          const when=Math.max(context.currentTime+0.025,playbackAt.current);
          sound.start(when);playbackAt.current=when+sound.buffer.duration;setPhase('speaking');
        }catch{setError('Не удалось воспроизвести речь MIMAS. Подключитесь повторно.');}
        return;
      }
      if(message.type==='transcript'&&message.text&&(message.speaker==='candidate'||message.speaker==='mimas')){
        const speaker=message.speaker;
        setLines(previous=>previous.at(-1)?.speaker===speaker&&previous.at(-1)?.text===message.text
          ?previous:[...previous,{speaker,text:message.text!,id:++sequence.current}]);
        if(speaker==='candidate'){answerAllowed.current=false;holdingAnswer.current=false;sendingAudio.current=false;setPhase('thinking');}
        else awaitingPlayback.current=true;
        return;
      }
      if(message.type==='state'&&message.session){
        callback.current(message.session);
        if(message.session.phase==='COMPLETED'){
          finished.current=true;answerAllowed.current=false;holdingAnswer.current=false;sendingAudio.current=false;setPhase('completed');processor.current?.disconnect();input.current?.disconnect();
        }
        return;
      }
      if(message.type==='speech_started'){
        if(!awaitingPlayback.current&&!finished.current&&holdingAnswer.current)setPhase('candidate_speaking');
        return;
      }
      if(message.type==='speech_stopped'){
        if(finished.current)return;
        reconnectAttempts.current=0;
        if(answerPending.current||holdingAnswer.current)return;
        if(interrupted.current){interrupted.current=false;if(graphReady.current&&answerAllowed.current)setPhase('listening');return;}
        if(!awaitingPlayback.current){if(graphReady.current&&answerAllowed.current)setPhase('listening');return;}
        if(listenTimer.current)clearTimeout(listenTimer.current);
        const delay=Math.max(0,(playbackAt.current-(audio.current?.currentTime||0))*1000)+160;
        listenTimer.current=setTimeout(()=>{
          listenTimer.current=null;awaitingPlayback.current=false;
          if(current.readyState===WebSocket.OPEN){
            current.send(JSON.stringify({type:'playback_done'}));
            answerAllowed.current=true;
          }
          setPhase(graphReady.current&&answerAllowed.current?'listening':'connecting');
        },delay);
        return;
      }
      if(message.type==='answer_retry'){
        answerPending.current=false;holdingAnswer.current=false;answerFlushPending.current=false;sendingAudio.current=false;answerAllowed.current=true;
        if(answerFlushTimer.current){clearTimeout(answerFlushTimer.current);answerFlushTimer.current=null;}
        setError(message.message||'Не услышал ответ. Удерживайте кнопку и повторите.');
        setPhase(graphReady.current?'listening':'connecting');
        return;
      }
      if(message.type==='error'){
        if(answerPending.current||holdingAnswer.current){
          answerPending.current=false;holdingAnswer.current=false;answerFlushPending.current=false;sendingAudio.current=false;answerAllowed.current=true;
          if(answerFlushTimer.current){clearTimeout(answerFlushTimer.current);answerFlushTimer.current=null;}
          setPhase(graphReady.current?'listening':'connecting');
        }
        setError(message.message||'Голосовое интервью временно недоступно.');
      }
    };
  },[completeAnswer,disconnect,prepare,stopGraph]);
  resumeConnection.current=connect;

  const toggleMute=useCallback(()=>setMuted(previous=>{
    mutedRef.current=!previous;return !previous;
  }),[]);
  const interrupt=useCallback(()=>{
    stopPlayback();awaitingPlayback.current=false;interrupted.current=true;
    if(socket.current?.readyState===WebSocket.OPEN){
      socket.current.send(JSON.stringify({type:'interrupt'}));
      socket.current.send(JSON.stringify({type:'playback_done'}));
      answerAllowed.current=true;
    }
    setPhase(graphReady.current&&answerAllowed.current?'listening':'connecting');
  },[stopPlayback]);

  const startAnswer=useCallback(()=>{
    const current=socket.current;
    if(phase!=='listening'||!graphReady.current||!answerAllowed.current||holdingAnswer.current||answerPending.current||mutedRef.current||awaitingPlayback.current||finished.current||current?.readyState!==WebSocket.OPEN)return;
    holdingAnswer.current=true;
    answerAllowed.current=false;
    current.send(JSON.stringify({type:'start_answer'}));
    sendingAudio.current=true;
    setError('');
    setPhase('candidate_speaking');
  },[phase]);

  const finishAnswer=useCallback(()=>{
    if(!holdingAnswer.current||answerPending.current)return;
    holdingAnswer.current=false;
    answerPending.current=true;
    answerFlushPending.current=true;
    setPhase('thinking');
    const node=processor.current;
    if(node&&'port' in node){
      try{
        node.port.postMessage({type:'flush'});
        answerFlushTimer.current=setTimeout(completeAnswer,4000);
      }catch{completeAnswer();}
    }else completeAnswer();
  },[completeAnswer]);

  return {phase,error,lines,muted,prepare,connect,disconnect,toggleMute,interrupt,startAnswer,finishAnswer};
}
