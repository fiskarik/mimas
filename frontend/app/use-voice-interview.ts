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

  const stopPlayback=useCallback(()=>{
    if(listenTimer.current){clearTimeout(listenTimer.current);listenTimer.current=null;}
    for(const source of playing.current){try{source.stop();}catch{/* source already ended */}}
    playing.current.clear();playbackAt.current=audio.current?.currentTime||0;
  },[]);
  const stopGraph=useCallback(()=>{
    processor.current?.disconnect();input.current?.disconnect();sink.current?.disconnect();
    processor.current=null;input.current=null;sink.current=null;stopPlayback();
    const context=audio.current;audio.current=null;
    if(context&&context.state!=='closed')void context.close();
  },[stopPlayback]);
  const disconnect=useCallback(()=>{
    closed.current=true;generation.current++;
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

  const connect=useCallback(async(access:Access,stream:MediaStream)=>{
    if(!stream.getAudioTracks().some(track=>track.readyState==='live')){
      setError('Микрофон недоступен. Разрешите доступ к нему в браузере и повторите подключение.');
      return;
    }
    if(socket.current)disconnect();closed.current=false;finished.current=false;awaitingPlayback.current=false;interrupted.current=false;setError('');setLines([]);setPhase('connecting');
    prepare();
    const protocol=window.location.protocol==='https:'?'wss:':'ws:';
    const url=protocol+'//'+window.location.host+'/api/ai/sessions/'+encodeURIComponent(access.id)+'/voice';
    const current=new WebSocket(url);socket.current=current;
    const epoch=++generation.current;
    current.onopen=()=>current.send(JSON.stringify({type:'auth',token:access.token}));
    current.onerror=()=>{if(epoch===generation.current)setError('Не удалось установить голосовое соединение. Проверьте сеть и подключитесь снова.');};
    current.onclose=()=>{
      if(epoch!==generation.current||closed.current)return;
      socket.current=null;stopGraph();
      setPhase(previous=>previous==='completed'?'completed':'disconnected');
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
              if(epoch!==generation.current||mutedRef.current||current.readyState!==WebSocket.OPEN||context.currentTime<playbackAt.current+0.16)return;
              if(current.bufferedAmount>1024*1024){
                if(!congestion.current){congestion.current=true;setError('Сеть замедлилась. Часть звука не отправляется; проверьте соединение.');}
                return;
              }
              if(congestion.current){congestion.current=false;setError('');}
              current.send(JSON.stringify({type:'audio',audio:toPcm(samples,context.sampleRate)}));
            };
            if(context.audioWorklet){
              // A worklet receives 128 samples per callback. Batch roughly 90 ms of audio.
              const code="class MimasCapture extends AudioWorkletProcessor{constructor(){super();this.buffer=new Float32Array(4096);this.offset=0;}process(inputs){const channel=inputs[0]&&inputs[0][0];if(channel){let cursor=0;while(cursor<channel.length){const length=Math.min(channel.length-cursor,this.buffer.length-this.offset);this.buffer.set(channel.subarray(cursor,cursor+length),this.offset);this.offset+=length;cursor+=length;if(this.offset===this.buffer.length){this.port.postMessage(this.buffer,[this.buffer.buffer]);this.buffer=new Float32Array(4096);this.offset=0;}}}return true;}}registerProcessor('mimas-capture',MimasCapture);";
              const moduleUrl=URL.createObjectURL(new Blob([code],{type:'text/javascript'}));
              try{await context.audioWorklet.addModule(moduleUrl);}finally{URL.revokeObjectURL(moduleUrl);}
              if(epoch!==generation.current)return;
              const node=new AudioWorkletNode(context,'mimas-capture');
              node.port.onmessage=(audioEvent:MessageEvent<Float32Array>)=>send(audioEvent.data);
              source.connect(node);node.connect(mutedSink);processor.current=node;
            }else{
              const node=context.createScriptProcessor(2048,1,1);
              node.onaudioprocess=audioEvent=>send(new Float32Array(audioEvent.inputBuffer.getChannelData(0)));
              source.connect(node);node.connect(mutedSink);processor.current=node;
            }
            setPhase('connecting');
          }catch(cause){setError('Не удалось подключить микрофон: '+(cause as Error).message);current.close();}
        })();
        return;
      }
      if(message.type==='audio'&&message.audio){
        awaitingPlayback.current=true;
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
        setLines(previous=>[...previous,{speaker,text:message.text!,id:++sequence.current}]);
        if(speaker==='candidate')setPhase('thinking');
        else awaitingPlayback.current=true;
        return;
      }
      if(message.type==='state'&&message.session){
        callback.current(message.session);
        if(message.session.phase==='COMPLETED'){
          finished.current=true;setPhase('completed');processor.current?.disconnect();input.current?.disconnect();
        }
        return;
      }
      if(message.type==='speech_started'){
        if(!awaitingPlayback.current&&!finished.current)setPhase('candidate_speaking');
        return;
      }
      if(message.type==='speech_stopped'){
        if(finished.current)return;
        if(interrupted.current){interrupted.current=false;setPhase('listening');return;}
        if(!awaitingPlayback.current){setPhase('thinking');return;}
        if(listenTimer.current)clearTimeout(listenTimer.current);
        const delay=Math.max(0,(playbackAt.current-(audio.current?.currentTime||0))*1000)+160;
        listenTimer.current=setTimeout(()=>{
          listenTimer.current=null;awaitingPlayback.current=false;
          if(current.readyState===WebSocket.OPEN)current.send(JSON.stringify({type:'playback_done'}));
          setPhase('listening');
        },delay);
        return;
      }
      if(message.type==='error')setError(message.message||'Голосовое интервью временно недоступно.');
    };
  },[disconnect,prepare,stopGraph]);

  const toggleMute=useCallback(()=>setMuted(previous=>{
    mutedRef.current=!previous;return !previous;
  }),[]);
  const interrupt=useCallback(()=>{
    stopPlayback();awaitingPlayback.current=false;interrupted.current=true;
    if(socket.current?.readyState===WebSocket.OPEN){
      socket.current.send(JSON.stringify({type:'interrupt'}));
      socket.current.send(JSON.stringify({type:'playback_done'}));
    }
    setPhase('listening');
  },[stopPlayback]);

  return {phase,error,lines,muted,prepare,connect,disconnect,toggleMute,interrupt};
}
