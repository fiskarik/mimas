export type Level = 'junior'|'middle'|'senior';
export type Profile = {id:string;name:string;role:string;level:Level;stack:string[];years_experience:number;github_url:string|null;desired_salary_rub:number|null;discoverable:boolean};
export type Match = {score:number;reasons:string[];stack_overlap:number;level_match:boolean;salary_match:boolean;compatible:boolean};
export type Opportunity = {id:string;company_name:string;title:string;description:string;role:string;level:Level;stack:string[];salary_min_rub:number|null;salary_max_rub:number|null;employment_type:'full_time'|'contract';status:string;template_status?:string;template_version?:string;match?:Match;interested?:boolean};
export type AssessmentView = {opportunity_id:string;session_id?:string;id?:string;phase?:string;report?:unknown;status?:string};
export type MyProfile = {profile:Profile;interested_opportunity_ids:string[];assessments?:AssessmentView[]|Record<string,AssessmentView>;assessment_opportunities?:Record<string,Pick<Opportunity,'id'|'title'|'company_name'|'status'>>;assessment?:{report?:unknown;phase?:string}|null};
export type Evidence = {id:string;type:string;claim:string;quote:string;question_text:string};
export type CandidateResult = {profile:Profile;assessment_id:string;opportunity_id?:string;status?:string;summary:string|null;skills:{skill:string;demonstrated_level:string|null;status:string;answers_received:number;evaluated_answers:number;evidence:Evidence[]}[];quality_status?:string;match?:Match;interested?:boolean};

export class MarketError extends Error {constructor(public status:number,message:string){super(message);this.name='MarketError';}}
export async function market<T>(path:string, options:{method?:string;token?:string;key?:string;adminKey?:string;claimToken?:string;body?:unknown;file?:File} = {}):Promise<T> {
  const headers:Record<string,string> = {
    ...(options.token?{'X-Candidate-Token':options.token}:{}),
    ...(options.key?{'X-Company-Key':options.key}:{}),
    ...(options.adminKey?{'X-Admin-Key':options.adminKey}:{}),
    ...(options.claimToken?{'X-Claim-Token':options.claimToken}:{})
  };
  let body:BodyInit|undefined;
  if(options.file){const form=new FormData();form.append('file',options.file);body=form;}
  else if(options.body!==undefined){headers['Content-Type']='application/json';body=JSON.stringify(options.body);}
  const response=await fetch('/api/market'+path,{method:options.method||'GET',headers,body,cache:'no-store'});
  if(!response.ok){const value=await response.json().catch(()=>({}));throw new MarketError(response.status,typeof value.detail==='string'?value.detail:'Ошибка сервера ('+response.status+')');}
  return response.json();
}
export const salary=(value:number|null)=>value===null?'не указана':new Intl.NumberFormat('ru-RU').format(value)+' ₽';
export const salaryRange=(min:number|null,max:number|null)=>min!==null&&max!==null?salary(min)+' — '+salary(max):min!==null?'от '+salary(min):max!==null?'до '+salary(max):'Зарплата не указана';
export const levelLabels:Record<Level,string>={junior:'Junior',middle:'Middle',senior:'Senior'};
export const skillNames:Record<string,string>={'python.core':'Python Core','python.oop':'ООП','python.asyncio':'AsyncIO','web.http':'HTTP / REST','db.postgresql':'PostgreSQL','cs.algorithms':'Алгоритмы','engineering.debugging':'Отладка'};
export function assessmentFor(me:MyProfile|null,id:string):AssessmentView|null {
  if(!me?.assessments)return null;
  if(Array.isArray(me.assessments))return me.assessments.find(row=>row.opportunity_id===id)||null;
  return me.assessments[id]||null;
}
