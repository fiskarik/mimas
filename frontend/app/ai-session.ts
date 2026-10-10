import type {AnswerReview, ScoringRubric} from './answer-report';

export type Question = {id:string; skill:string; text:string; type:string; generation:string};
export type Answer = {question_id:string; text:string};
export type IntegrityReport = {note:string; events_truncated?:boolean; signals:{id:string; type:string; timestamp:string; resolved:boolean; severity:string; question_id:string}[]; verifications:{id:string; kind:string; target_id:string; outcome:string; question_id:string|null; evidence_ids:string[]}[]};
export type Evidence = {id:string; question_id:string; claim:string; quote:string; type:string};
export type SkillReport = {skill:string; name?:string; demonstrated_level:string|null; answers_received:number; evaluated_answers:number; evidence:Evidence[]; missing_concepts:string[]};
export type Session = {id:string; model:string; phase:string; deadline_at?:number|null; resume_required?:boolean; progress?:{questions_answered:number; skills_completed:number; skills_total:number}; skill_names?:Record<string,string>; current_question:Question|null; questions:Question[]; answers:Answer[]; pending_answer:Answer|null; evaluation_notice:string|null; report:{skills:SkillReport[]; integrity?:IntegrityReport; overall_technical_summary:string; stop_reason:string; answer_reviews:AnswerReview[]; scoring_rubric:ScoringRubric}|null; max_questions:number};
export type Access = {id:string; token:string};

export async function request<T>(path:string, token?:string, body?:unknown, key?:string):Promise<T> {
  const response = await fetch(`/api/ai/sessions${path}`, {method:body === undefined ? 'GET':'POST',
    headers:{'Content-Type':'application/json',...(token?{'X-Interview-Token':token}:{}),...(key?{'X-Company-Key':key}:{})},
    body:body === undefined ? undefined:JSON.stringify(body),cache:'no-store'});
  if(!response.ok) {const error=await response.json().catch(()=>({}));throw new Error(typeof error.detail==='string'?error.detail:`Ошибка сервера (${response.status}). Ответ можно повторить.`);}
  return response.json();
}
