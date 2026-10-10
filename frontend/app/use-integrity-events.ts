'use client';

import {useCallback, useEffect, useRef} from 'react';
import {request, type Access, type Session} from './ai-session';

type EventType = 'PASTE_DETECTED' | 'COPY_DETECTED' | 'FOCUS_LOST' | 'FOCUS_RETURNED';
type ClientEvent = {id:string; type:EventType; question_id:string; size:number};
type Acknowledgement = {accepted:boolean; reason?:string};

function readQueue(key:string):ClientEvent[] {
  const value = JSON.parse(sessionStorage.getItem(key) || '[]');
  if (!Array.isArray(value)) throw new Error('Не удалось прочитать очередь событий интервью.');
  return value;
}

/** Durable observation outbox, serialized before answer/finish requests. */
export function useIntegrityEvents(
  access:Access|null, session:Session|null, busy:boolean, onError:(message:string)=>void,
) {
  const chain = useRef<Promise<void>>(Promise.resolve());
  const flushEvents = useCallback(() => {
    if (!access) return Promise.resolve();
    const key = `ai-events-${access.id}`;
    const task = chain.current.catch(() => {}).then(async () => {
      let queue = readQueue(key);
      while (queue.length) {
        const sentId = queue[0].id;
        const ack = await request<Acknowledgement>(`/${access.id}/events`, access.token, queue[0]);
        // Re-read to retain observations queued while this request was in flight.
        queue = readQueue(key).filter(event => event.id !== sentId);
        sessionStorage.setItem(key, JSON.stringify(queue));
        if (!ack.accepted && ack.reason === 'event_limit') {
          onError('Достигнут лимит записи событий. Ответы и завершение интервью остаются доступны.');
        }
      }
    });
    chain.current = task;
    return task;
  }, [access, onError]);

  const questionId = session?.current_question?.id;
  const pending = !!session?.pending_answer;
  const track = useCallback((type:EventType, size=0) => {
    if (!access || !questionId || busy || pending) return;
    try {
      const key = `ai-events-${access.id}`;
      const queue = readQueue(key);
      queue.push({id:crypto.randomUUID(), type, question_id:questionId, size});
      sessionStorage.setItem(key, JSON.stringify(queue));
      void flushEvents().catch(() => onError('Не удалось сохранить событие. Перед отправкой ответа попробуем снова.'));
    } catch {
      onError('Не удалось сохранить событие в браузере.');
    }
  }, [access, questionId, busy, pending, flushEvents, onError]);

  const pageFocused = useRef(true);
  useEffect(() => {
    // A hidden tab and a blurred window can fire together. Record one
    // transition, without claiming to know which other app or tab is active.
    pageFocused.current = document.visibilityState === 'visible' && document.hasFocus();
    const observe = () => {
      const focused = document.visibilityState === 'visible' && document.hasFocus();
      if (focused === pageFocused.current) return;
      pageFocused.current = focused;
      track(focused ? 'FOCUS_RETURNED' : 'FOCUS_LOST');
    };
    window.addEventListener('blur', observe);
    window.addEventListener('focus', observe);
    document.addEventListener('visibilitychange', observe);
    return () => {
      window.removeEventListener('blur', observe);
      window.removeEventListener('focus', observe);
      document.removeEventListener('visibilitychange', observe);
    };
  }, [track]);
  return {flushEvents, track};
}
