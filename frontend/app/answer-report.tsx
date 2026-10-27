'use client';

type Finding = {claim:string; quote:string};
export type AnswerReview = {question_id:string; skill:string; question:string; answer:string; points:number|null; max_points:number; reason:string; strengths:Finding[]; errors:Finding[]; uncertainties:Finding[]; missing_concepts:string[]; follow_up_goal:string; failures:string[]; anchor?:{level:number; description:string}|null; red_flags?:Finding[]};
export type ScoringRubric = {description:string; rules:string[]; not_assessed?:string[]; max_points?:number};
export type OverallRating = {score:number|null; assessed_answers:number; total_answers:number; max_score:number};

// Scores are 1-10; older reports stay readable through review.max_points.
function scoreTone(points:number|null,max:number){
  if(points===null)return 'unrated';
  const share=points/max;
  return share>=0.7?'good':share>=0.4?'partial':'weak';
}

export function OverallScore({rating}:{rating?:OverallRating|null}){
  if(!rating)return null;
  return <div className={`card overall-score ${scoreTone(rating.score,rating.max_score)}`} aria-label={rating.score===null?'Итоговый балл не выставлен':`Итоговый балл: ${rating.score} из ${rating.max_score}`}>
    <div className="overall-score-value"><strong>{rating.score===null?'—':rating.score}</strong><span>{rating.score===null?'Не оценено':`из ${rating.max_score}`}</span></div>
    <div><h3>Итоговый балл</h3><p>Среднее по оценённым вопросам: {rating.assessed_answers} из {rating.total_answers}. Вопросы без оценки не считаются нулём. Оценка предварительная; решение принимает человек.</p></div>
  </div>;
}

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
    <p className="muted">AI оценивает только содержание устного ответа: профессиональные знания и решения рабочих ситуаций. Подсвеченные фрагменты показывают основания замечаний. Практический навык и допуск к работе здесь не подтверждаются.</p>
    {rubric&&<details className="card scoring-rubric"><summary>Как считаются баллы{rubric.max_points===10?' от 1 до 10':''}</summary><p>{rubric.description}</p><ul>{rubric.rules.map(rule=><li key={rule}>{rule}</li>)}</ul>{rubric.not_assessed?.length?<p>Не влияет на балл: {rubric.not_assessed.join(', ')}.</p>:null}</details>}
    {!reviews.length&&<p className="note">Пока нет сохранённых ответов для разбора.</p>}
    {reviews.map((review,index)=><article className="card answer-review" key={review.question_id}>
      <header><div><span className="eyebrow">ОТВЕТ {index+1} · {names[review.skill]||review.skill}</span><h3>{review.question}</h3></div><div className={`answer-points ${scoreTone(review.points,review.max_points)}`} aria-label={review.points===null?'Ответ не оценён':`Балл за ответ: ${review.points} из ${review.max_points}`}><strong>{review.points===null?'—':review.points}</strong><span>{review.points===null?'Не оценено':`из ${review.max_points}`}</span></div></header>
      <p className="score-reason">{review.reason}</p>
      {review.anchor&&<p className="score-anchor">Ближе всего к описанию: «{review.anchor.description}»</p>}
      <h4>Ваш ответ</h4><HighlightedAnswer text={review.answer} errors={[...review.errors,...(review.red_flags||[])]}/>
      {review.red_flags?.length?<section className="review-red-flags"><h4>Красные флаги</h4>{review.red_flags.map((flag,i)=><div className="review-finding" key={i}><p>{flag.claim}</p><blockquote>{flag.quote}</blockquote></div>)}</section>:null}
      <div className="review-findings">
        <section className="review-errors"><h4>Где ошибка</h4>{review.errors.length?review.errors.map((e,i)=><div className="review-finding" key={i}><blockquote>{e.quote}</blockquote><p>{e.claim}</p></div>):<p className="muted">{review.points===null?'Ответ не оценён; подтверждённых ошибок в объяснении нет.':'AI не отметил конкретных ошибок в объяснении.'}</p>}</section>
        <section className="review-strengths"><h4>Что засчитано</h4>{review.strengths.length?review.strengths.map((e,i)=><div className="review-finding" key={i}><p>{e.claim}</p><blockquote>{e.quote}</blockquote></div>):<p className="muted">Нет подтверждённых пунктов.</p>}</section>
      </div>
      {(review.missing_concepts.length>0||review.uncertainties.length>0||review.follow_up_goal)&&<section className="review-improvements"><h4>Что дополнить или уточнить</h4>{review.missing_concepts.length>0&&<ul>{review.missing_concepts.map((item,i)=><li key={i}>{item}</li>)}</ul>}{review.uncertainties.map((e,i)=><p key={i}>{e.claim} <q>{e.quote}</q></p>)}{review.follow_up_goal&&<p>{review.follow_up_goal}</p>}</section>}
    </article>)}
  </section>;
}
