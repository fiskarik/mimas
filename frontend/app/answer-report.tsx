'use client';

type Finding = {claim:string; quote:string};
export type AnswerReview = {question_id:string; skill:string; question:string; answer:string; points:number|null; max_points:number; reason:string; strengths:Finding[]; errors:Finding[]; uncertainties:Finding[]; missing_concepts:string[]; follow_up_goal:string; failures:string[]};
export type ScoringRubric = {description:string; rules:string[]};

function HighlightedAnswer({text, errors}:{text:string; errors:Finding[]}) {
  const ranges:{start:number; end:number}[]=[];
  for(const finding of errors){
    if(!finding.quote)continue;
    let at=text.indexOf(finding.quote);
    while(at!==-1){ranges.push({start:at,end:at+finding.quote.length});at=text.indexOf(finding.quote,at+finding.quote.length);}
  }
  ranges.sort((a,b)=>a.start-b.start);
  const merged:{start:number;end:number}[]=[];
  for(const range of ranges){const last=merged[merged.length-1];if(last&&range.start<=last.end)last.end=Math.max(last.end,range.end);else merged.push({...range});}
  const pieces:React.ReactNode[]=[];let cursor=0;
  for(const range of merged){pieces.push(text.slice(cursor,range.start));pieces.push(<mark key={range.start}>{text.slice(range.start,range.end)}</mark>);cursor=range.end;}
  pieces.push(text.slice(cursor));
  return <pre className="review-answer">{pieces}</pre>;
}

export function AnswerReport({reviews,rubric,names}:{reviews:AnswerReview[];rubric?:ScoringRubric;names:Record<string,string>}){
  return <section className="answer-reviews" aria-label="Разбор ответов">
    <h2>Баллы и разбор каждого ответа</h2>
    <p className="muted">Балл рассчитан по оценке AI. Подсвеченные фрагменты — основания замечаний; неполный ответ и техническая ошибка показаны отдельно.</p>
    {rubric&&<details className="card scoring-rubric"><summary>Как считаются баллы от 0 до 5</summary><p>{rubric.description}</p><ul>{rubric.rules.map(rule=><li key={rule}>{rule}</li>)}</ul></details>}
    {!reviews.length&&<p className="note">Пока нет сохранённых ответов для разбора.</p>}
    {reviews.map((review,index)=><article className="card answer-review" key={review.question_id}>
      <header><div><span className="eyebrow">ОТВЕТ {index+1} · {names[review.skill]||review.skill}</span><h3>{review.question}</h3></div><div className={`answer-points ${review.points===null?'unrated':review.points>=4?'good':review.points>=2?'partial':'weak'}`} aria-label={review.points===null?'Ответ не оценён':`Балл за ответ: ${review.points} из ${review.max_points}`}><strong>{review.points===null?'—':review.points}</strong><span>{review.points===null?'Не оценено':`из ${review.max_points}`}</span></div></header>
      <p className="score-reason">{review.reason}</p>
      <h4>Ваш ответ</h4><HighlightedAnswer text={review.answer} errors={review.errors}/>
      <div className="review-findings">
        <section className="review-errors"><h4>Где ошибка</h4>{review.errors.length?review.errors.map((e,i)=><div className="review-finding" key={i}><blockquote>{e.quote}</blockquote><p>{e.claim}</p></div>):<p className="muted">{review.points===null?'Технические ошибки не установлены: ответ не оценён.':'AI не отметил конкретных технических ошибок.'}</p>}</section>
        <section className="review-strengths"><h4>Что засчитано</h4>{review.strengths.length?review.strengths.map((e,i)=><div className="review-finding" key={i}><p>{e.claim}</p><blockquote>{e.quote}</blockquote></div>):<p className="muted">Нет подтверждённых пунктов.</p>}</section>
      </div>
      {(review.missing_concepts.length>0||review.uncertainties.length>0||review.follow_up_goal)&&<section className="review-improvements"><h4>Что дополнить или уточнить</h4>{review.missing_concepts.length>0&&<ul>{review.missing_concepts.map((item,i)=><li key={i}>{item}</li>)}</ul>}{review.uncertainties.map((e,i)=><p key={i}>{e.claim} <q>{e.quote}</q></p>)}{review.follow_up_goal&&<p>{review.follow_up_goal}</p>}</section>}
    </article>)}
  </section>;
}
