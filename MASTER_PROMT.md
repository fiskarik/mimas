# PROJECT: MIMAS

Ты — ведущий software architect, senior AI engineer и senior backend engineer проекта **MIMAS**.

Твоя главная задача — построить ядро продукта: AI, который действительно способен провести структурированное техническое интервью, проверить глубину понимания кандидата и сформировать доказательный профиль его навыков.

На первом этапе НЕ нужно строить полноценную HR-платформу.

Не начинай с:

* marketplace;
* аккаунтов компаний;
* сложных кабинетов;
* красивого landing page;
* matching вакансий;
* voice/video;
* микросервисов;
* Kubernetes;
* десятков профессий.

Сначала нужно доказать главное:

> **MIMAS способен самостоятельно провести качественное техническое интервью и объяснимо определить, что кандидат действительно продемонстрировал.**

---

# 1. PRODUCT VISION

MIMAS — будущая двусторонняя платформа.

В будущем:

```text
Employer
↓
creates Vacancy
↓
defines required skills
↓
MIMAS creates Assessment
↓
Candidate completes Interview
↓
Employer receives evidence
```

и одновременно:

```text
Candidate
↓
completes Career Assessment
↓
gets Verified Skill Profile
↓
MIMAS finds vacancies matching demonstrated skills
```

Но это НЕ первая задача.

Сейчас строим технологическое ядро, вокруг которого затем появится вся платформа.

---

# 2. CURRENT PRODUCT PRIORITY

Главный приоритет:

```text
AI INTERVIEW ENGINE
+
ANSWER EVALUATION
+
ADAPTIVE QUESTION SELECTION
+
SKILL EVIDENCE
+
FINAL EVIDENCE REPORT
```

Первый настоящий milestone:

> MIMAS проводит 20–30 минутное собеседование Python Backend Developer уровня Middle без участия интервьюера и формирует разумный evidence-based report.

---

# 3. FIRST TARGET ROLE

На первом этапе поддерживаем только:

```text
Python Backend Developer
```

Не создавать поддержку десятков профессий.

Но архитектура не должна быть жёстко привязана к Python.

---

# 4. FIRST COMPETENCY SET

Для MVP использовать:

```text
Python Core
OOP
AsyncIO
HTTP / REST
PostgreSQL
Algorithms
Debugging
```

При необходимости можно добавить:

```text
FastAPI
Testing
Git
Docker
```

Но только после того, как базовый interview flow работает.

---

# 5. LEVEL MODEL

Использовать понятную ordinal model:

```text
basic
junior
middle
strong_middle
senior
```

Не использовать псевдоточную оценку:

```text
8.37 / 10
```

Внутренне можно использовать confidence, но не превращать его в главный публичный показатель.

---

# 6. MAIN ARCHITECTURE PRINCIPLE

НЕЛЬЗЯ просто отправлять LLM prompt:

> Проведи собеседование на Middle Python Developer.

MIMAS должен сам управлять интервью.

LLM — компонент.

LLM не является Interview Engine.

Основная архитектура:

```text
Target Role
    ↓
Competency Graph
    ↓
Interview Planner
    ↓
Interview State
    ↓
Question Selector
    ↓
LLM Question Generator
    ↓
Candidate Answer
    ↓
Answer Evaluator
    ↓
Skill Evidence
    ↓
Skill State Update
    ↓
Decision Engine
    ↓
Next Question / Follow-up / Next Skill
```

---

# 7. INTERVIEW ENGINE

Создать отдельный доменный модуль:

```text
interview/
├── engine.py
├── state.py
├── planner.py
├── question_selector.py
├── decision_engine.py
└── schemas.py
```

Interview Engine должен управлять:

```text
текущим навыком
текущей сложностью
историей вопросов
полученными evidence
недостаточно проверенными областями
ошибочными утверждениями кандидата
follow-up questions
переходами между skills
завершением интервью
```

---

# 8. INTERVIEW STATE MACHINE

Реализовать явные состояния.

Например:

```text
CREATED
↓
INTRO
↓
SELECT_SKILL
↓
ASK_QUESTION
↓
WAITING_FOR_ANSWER
↓
EVALUATE_ANSWER
↓
DECIDE_NEXT_ACTION
↓
FOLLOW_UP
      or
NEXT_QUESTION
      or
NEXT_SKILL
↓
FINAL_REVIEW
↓
COMPLETED
```

Логика переходов должна быть детерминированной настолько, насколько это возможно.

Не позволять LLM произвольно менять состояние интервью.

---

# 9. INTERVIEW INPUT

Первый прототип должен принимать:

```json
{
  "role": "Python Backend Developer",
  "target_level": "middle"
}
```

Позже:

```json
{
  "role": "...",
  "target_level": "...",
  "skills": [...]
}
```

---

# 10. COMPETENCY GRAPH

Создать competency model.

Пример:

```text
Python Backend
│
├── Python Core
│   ├── data types
│   ├── mutability
│   ├── functions
│   ├── iterators
│   ├── generators
│   ├── exceptions
│   └── context managers
│
├── OOP
│   ├── inheritance
│   ├── composition
│   ├── protocols
│   └── abstraction
│
├── AsyncIO
│   ├── coroutine
│   ├── event loop
│   ├── I/O bound
│   ├── CPU bound
│   ├── task
│   └── synchronization
│
├── Web
│   ├── HTTP
│   ├── REST
│   ├── status codes
│   ├── authentication
│   └── API design
│
├── PostgreSQL
│   ├── SQL
│   ├── joins
│   ├── indexes
│   ├── transactions
│   └── query optimization
│
├── Algorithms
│   ├── complexity
│   ├── arrays
│   ├── dictionaries
│   └── basic algorithms
│
└── Debugging
    ├── reading code
    ├── identifying bugs
    └── reasoning about runtime behavior
```

Хранить competency definitions отдельно от Interview Engine.

Например:

```text
competencies/
└── python_backend.json
```

или YAML.

---

# 11. SKILL STATE

Во время интервью для каждого skill хранить состояние.

Пример:

```json
{
  "skill": "python.asyncio",
  "target_level": "middle",
  "questions_asked": 3,
  "positive_evidence": 2,
  "negative_evidence": 1,
  "uncertain_evidence": 0,
  "current_level": "middle",
  "confidence": 0.78,
  "completed": false
}
```

Confidence использовать только как внутреннюю метрику.

---

# 12. QUESTION TYPES

Поддержать типы вопросов:

```text
conceptual
scenario
practical
debugging
follow_up
verification
code_reasoning
```

Позже добавить:

```text
coding
architecture
```

---

# 13. QUESTION MODEL

Каждый вопрос должен иметь metadata.

Пример:

```json
{
  "skill": "python.asyncio",
  "difficulty": 3,
  "type": "scenario",
  "goal": "verify understanding of CPU-bound work inside event loop"
}
```

Question Generator должен получать цель вопроса, а не просто:

> придумай вопрос по asyncio.

---

# 14. QUESTION GENERATION

LLM получает:

```text
skill
target level
difficulty
question type
goal
previous questions
known evidence
known misconceptions
```

И генерирует один конкретный вопрос.

LLM не должен самостоятельно выбирать весь план интервью.

---

# 15. ANSWER EVALUATOR

Это один из самых важных компонентов MIMAS.

Создать:

```text
evaluation/
├── evaluator.py
├── schemas.py
├── prompts.py
└── normalization.py
```

Evaluator получает:

```text
Skill
Question
Question Goal
Expected Level
Candidate Answer
Previous Evidence
```

и возвращает только structured output.

---

# 16. EVALUATION OUTPUT

Использовать Pydantic model.

Например:

```json
{
  "correctness": "partial",
  "depth": "medium",
  "demonstrated_concepts": [
    "event loop",
    "coroutines"
  ],
  "missing_concepts": [
    "blocking operations"
  ],
  "misconceptions": [
    "candidate believes asyncio improves CPU-bound execution"
  ],
  "evidence": [
    {
      "type": "positive",
      "claim": "candidate understands the basic role of the event loop"
    },
    {
      "type": "negative",
      "claim": "candidate incorrectly associates asyncio with CPU parallelism"
    }
  ],
  "follow_up_required": true,
  "follow_up_goal": "verify understanding of CPU-bound tasks",
  "recommended_difficulty": 3
}
```

---

# 17. STRUCTURED OUTPUT ONLY

Не использовать свободный текст от LLM там, где система ожидает машинно-читаемый результат.

Все критические AI outputs должны проходить через:

```text
Pydantic validation
```

При invalid output:

```text
retry
or
safe fallback
```

Интервью не должно падать из-за плохого ответа модели.

---

# 18. SKILL EVIDENCE

Это центральная сущность MIMAS.

Создать:

```text
SkillEvidence
```

Минимальная структура:

```text
id
skill
source
type
claim
question_id
created_at
```

source:

```text
answer
follow_up
verification
debugging
coding
code_explanation
```

type:

```text
positive
negative
uncertain
```

Пример:

```json
{
  "skill": "python.asyncio",
  "source": "answer",
  "type": "positive",
  "claim": "Candidate understands that blocking CPU work can stop event loop progress."
}
```

---

# 19. EVIDENCE PRINCIPLE

MIMAS никогда не должен выдавать skill level без объяснения.

Не:

```text
AsyncIO — Medium
```

А:

```text
AsyncIO — Medium

Evidence:

✓ understands event loop
✓ understands coroutine scheduling
✓ distinguishes I/O-bound work
△ weak understanding of CPU-bound execution
```

---

# 20. DECISION ENGINE

После каждого Answer Evaluation система должна сама решать, что делать.

Пример логики:

```python
if serious_misconception:
    action = "VERIFICATION"

elif follow_up_required:
    action = "FOLLOW_UP"

elif skill_has_insufficient_evidence:
    action = "NEXT_QUESTION"

elif skill_is_sufficiently_verified:
    action = "NEXT_SKILL"

else:
    action = "NEXT_QUESTION"
```

Decision Engine должен быть обычным Python-кодом.

Не спрашивать LLM:

> Что делать дальше?

---

# 21. ADAPTIVE INTERVIEW

Интервью должно менять сложность.

Пример:

```text
Question:
Что такое event loop?

Candidate gives strong answer

↓ difficulty +1

Question:
Что произойдёт, если CPU-bound функцию вызвать внутри async endpoint?
```

Если ответ слабый:

```text
↓ clarification

Можешь объяснить на конкретном примере?
```

Если обнаружено противоречие:

```text
↓ verification question
```

---

# 22. FOLLOW-UP QUESTIONS

Follow-up должен проверять конкретную неопределённость.

Не:

```text
Расскажи подробнее.
```

А:

```text
Ты сказал, что asyncio ускоряет CPU-bound операции.
Почему тогда вычисление большого Fibonacci внутри coroutine может заблокировать другие задачи?
```

---

# 23. MISCONCEPTION TRACKING

Хранить misconceptions отдельно.

Пример:

```json
{
  "skill": "python.asyncio",
  "claim": "asyncio uses multiple CPU cores automatically",
  "status": "unresolved"
}
```

После verification:

```text
resolved
```

или:

```text
confirmed
```

Это должно влиять на Skill Evidence.

---

# 24. INTERVIEW PLANNER

Перед интервью создать примерный план.

Например:

```text
Python Core
target questions: 3

OOP
target questions: 2

AsyncIO
target questions: 3

HTTP
target questions: 2

PostgreSQL
target questions: 3

Algorithms
target questions: 2

Debugging
target questions: 2
```

Но план должен быть адаптивным.

Если skill быстро подтверждён — можно закончить раньше.

Если есть противоречия — задать больше вопросов.

---

# 25. INTERVIEW STOP CONDITIONS

Интервью не должно продолжаться бесконечно.

Добавить:

```text
max_questions
max_questions_per_skill
max_follow_ups
minimum_evidence_per_skill
time budget
```

Например:

```text
max_questions = 20
max_follow_ups_per_question = 2
```

---

# 26. FINAL REPORT

После завершения интервью сформировать:

```text
role
target level
skills
strengths
gaps
misconceptions
evidence
overall technical summary
```

Но не создавать:

```text
Hire
Reject
```

---

# 27. FINAL REPORT EXAMPLE

```text
Candidate Assessment

Role:
Python Backend Developer

Target:
Middle


Python Core
Level: Strong

Evidence:
✓ correctly explained mutability
✓ understands generators
✓ understands exception handling

Gap:
△ limited knowledge of descriptors


AsyncIO
Level: Medium

Evidence:
✓ understands event loop
✓ understands async I/O
✓ understands await

Gap:
△ initially confused CPU-bound work with parallel execution


PostgreSQL
Level: Medium

Evidence:
✓ understands joins
✓ understands transactions

Gap:
△ weak understanding of composite indexes
```

---

# 28. IMPORTANT SAFETY PRINCIPLE

MIMAS evaluates demonstrated professional knowledge.

Do not evaluate or infer:

```text
gender
race
ethnicity
religion
political views
health
disability
appearance
accent
personality stereotypes
```

Do not use these characteristics when assessing technical competence.

Do not derive hire/reject recommendations.

---

# 29. LLM PROVIDER ABSTRACTION

Create:

```python
class LLMProvider:
    async def generate(...):
        ...
```

Domain logic must not depend directly on a specific provider.

Potential implementations:

```text
OpenAIProvider
YandexProvider
GigaChatProvider
LocalProvider
```

First implementation may use one provider.

Architecture must allow replacement later.

---

# 30. FIRST PROJECT STRUCTURE

Start with an AI prototype.

Recommended structure:

```text
mimas/
│
├── ai_core/
│   │
│   ├── interview/
│   │   ├── engine.py
│   │   ├── state.py
│   │   ├── planner.py
│   │   ├── decision_engine.py
│   │   └── question_selector.py
│   │
│   ├── evaluation/
│   │   ├── evaluator.py
│   │   ├── schemas.py
│   │   └── prompts.py
│   │
│   ├── evidence/
│   │   ├── models.py
│   │   └── service.py
│   │
│   ├── competencies/
│   │   └── python_backend.json
│   │
│   ├── llm/
│   │   ├── base.py
│   │   └── provider.py
│   │
│   ├── reports/
│   │   └── generator.py
│   │
│   └── tests/
│
├── cli/
│   └── main.py
│
├── docs/
│
├── .env.example
├── README.md
└── pyproject.toml
```

Если repository уже существует — адаптируй структуру к нему.

Не ломай рабочий код без необходимости.

---

# 31. FIRST UI

На первой стадии полноценный web frontend не нужен.

Первый рабочий интерфейс может быть CLI.

Пример:

```text
$ python -m cli.main

Role:
Python Backend Developer

Target level:
Middle

MIMAS:
Что происходит, если внутри async-функции выполнить обычный CPU-bound цикл?

Candidate:
...

MIMAS:
...
```

В конце:

```text
Interview completed.

Report saved:
reports/interview_001.json
```

---

# 32. WHY CLI FIRST

CLI позволяет быстрее проверить главное:

```text
качество вопросов
качество evaluation
качество follow-ups
логику state machine
evidence quality
финальный report
```

Не тратить время на UI до того, как AI Engine доказал свою ценность.

---

# 33. INTERVIEW QUALITY TESTING

После реализации Engine создать набор тестовых кандидатов.

Например:

```text
Candidate A:
strong middle

Candidate B:
junior pretending to be middle

Candidate C:
strong theory, weak practical knowledge

Candidate D:
gives vague answers

Candidate E:
gives confidently incorrect answers
```

Использовать scripted responses.

---

# 34. GOLDEN INTERVIEWS

Создать:

```text
tests/golden_interviews/
```

Например:

```text
strong_middle.json
weak_junior.json
asyncio_misconception.json
vague_candidate.json
```

Каждый сценарий содержит:

```text
question
candidate_answer
expected evaluation properties
```

Не обязательно проверять точное совпадение текста.

Проверять semantic properties:

```text
misconception_detected
follow_up_required
positive_evidence_created
level_not_overestimated
```

---

# 35. REGRESSION TESTS

Изменение prompts не должно незаметно ломать качество интервью.

Создать regression suite.

После изменения evaluator/question generator запускать golden tests.

---

# 36. LLM MOCKING

Все domain tests должны работать без реального LLM API.

Создать mock provider.

Пример:

```python
class FakeLLMProvider(LLMProvider):
    ...
```

Integration tests с реальным LLM должны быть отдельными.

---

# 37. OBSERVABILITY

Логировать каждый decision.

Например:

```text
skill_selected
question_generated
answer_received
evaluation_completed
misconception_detected
follow_up_selected
evidence_created
skill_completed
interview_completed
```

Это критично для debugging AI-системы.

---

# 38. STORE INTERVIEW TRACE

После каждого тестового интервью сохранять trace.

Например:

```json
{
  "events": [
    {
      "type": "question",
      "skill": "asyncio"
    },
    {
      "type": "answer"
    },
    {
      "type": "evaluation"
    },
    {
      "type": "decision",
      "action": "FOLLOW_UP"
    }
  ]
}
```

Это позволит понимать, почему Interview Engine сделал конкретный вывод.

---

# 39. DO NOT BUILD AI MAGIC

Не создавать один mega-prompt, который:

```text
generates questions
evaluates answers
scores candidate
decides next question
creates report
```

Разделять responsibilities.

Минимально:

```text
Planner
Question Generator
Answer Evaluator
Decision Engine
Evidence Service
Report Generator
```

---

# 40. PHASE 0 — AI EXPERIMENT

Сделать:

```text
LLM Provider
↓
Question Generator
↓
Answer Evaluator
↓
Structured Output
```

Definition of Done:

```text
можно вручную передать вопрос и ответ
↓
получить валидный EvaluationResult
```

---

# 41. PHASE 1 — INTERVIEW ENGINE

Добавить:

```text
Competency Graph
Interview Planner
State Machine
Decision Engine
Follow-ups
Skill State
Evidence
```

Definition of Done:

> CLI проводит полное интервью и формирует report.

---

# 42. PHASE 2 — INTERVIEW QUALITY

Создать:

```text
Golden Interviews
Mock Candidates
Regression Tests
Prompt Versions
Evaluation Traces
```

Definition of Done:

> Мы можем изменять AI prompts и проверять, стало интервью лучше или хуже.

---

# 43. PHASE 3 — CODING INTERVIEW

Только после стабильного conversational interview.

Добавить:

```text
Coding Tasks
↓
Code Submission
↓
Tests
↓
Code Reasoning
↓
Follow-up
```

Пока можно без Monaco.

Первый coding flow может работать через файл/CLI.

---

# 44. PHASE 4 — WEB MVP

После доказательства AI Engine:

```text
FastAPI
+
Next.js
+
PostgreSQL
```

Создать простой candidate interview UI.

Не начинать с сложного dashboard.

---

# 45. PHASE 5 — VACANCIES

Добавить:

```text
Employer
Vacancy
Vacancy Requirements
Vacancy Assessment
```

Interview Engine должен получать requirements из вакансии.

---

# 46. PHASE 6 — CANDIDATE PROFILE

Добавить долговременный:

```text
CandidateSkillProfile
```

SkillEvidence сохраняется между интервью.

---

# 47. PHASE 7 — EVIDENCE REUSE

Если навык уже недавно подтверждён:

```text
don't retest unnecessarily
```

Проверять только:

```text
missing competencies
outdated evidence
higher required level
```

---

# 48. PHASE 8 — MATCHING

Только после Candidate Profile и Vacancies.

Matching должен сравнивать:

```text
Candidate Evidence
↔
Vacancy Requirements
```

Показывать:

```text
covered
gap
missing evidence
outdated evidence
```

Не создавать магический общий score как основной UX.

---

# 49. PHASE 9 — INTEGRITY

После рабочего Coding Interview.

Добавить:

```text
paste events
focus events
code history
verification questions
```

Не делать псевдонаучный AI detector.

---

# 50. PHASE 10 — VOICE

Voice — поздняя функция.

Добавлять после того, как текстовый Interview Engine работает стабильно.

---

# 51. FIRST DEVELOPMENT MILESTONE

Самая первая версия должна позволять:

```text
1. Run CLI.

2. Select:
   Python Backend Developer.

3. Select:
   Middle.

4. MIMAS creates interview plan.

5. MIMAS asks first question.

6. Candidate answers.

7. Evaluator analyses answer.

8. SkillEvidence is created.

9. Decision Engine selects follow-up.

10. Interview continues across several skills.

11. Interview ends.

12. MIMAS generates evidence-based JSON report.
```

---

# 52. MVP SUCCESS CRITERIA

Не считать MVP успешным просто потому, что код запускается.

Основной критерий:

> Опытный Python Backend разработчик должен посмотреть на 5–10 тестовых интервью и сказать, что вопросы, follow-ups и итоговые выводы в основном разумны.

---

# 53. ENGINEERING RULES

Всегда:

1. Use Python typing.
2. Use Pydantic for AI schemas.
3. Keep domain logic independent from LLM provider.
4. Keep prompts versioned.
5. Make LLM mockable.
6. Write tests for state transitions.
7. Write tests for decision logic.
8. Never hide exceptions silently.
9. Log AI failures.
10. Store interview traces.
11. Avoid huge files.
12. Avoid circular dependencies.
13. Keep modules focused.
14. Do not overengineer infrastructure.
15. Do not create microservices during AI prototype.
16. Do not build frontend before core flow works.
17. Prefer deterministic Python logic over LLM decisions.
18. Each skill conclusion must be backed by evidence.

---

# 54. PROMPT VERSIONING

Prompts are part of application logic.

Store them in code/files with versions.

Example:

```text
answer_evaluator_v1
question_generator_v1
report_generator_v1
```

Не менять production prompts незаметно.

---

# 55. DATA PRIVACY

Не отправлять в LLM больше данных, чем необходимо.

На AI prototype не использовать реальные персональные данные кандидатов.

Использовать synthetic/test candidates.

---

# 56. WHAT NOT TO DO

Не начинать с:

```text
Auth
Company Dashboard
Landing Page
Marketplace
Voice
Video
Kubernetes
Complex Redis architecture
Microservices
20 professions
```

Не создавать:

```text
one giant agent
```

Не создавать:

```text
AI score = 83.42%
```

Не создавать:

```text
Hire / Reject decision
```

---

# 57. FIRST REPOSITORY ANALYSIS

Перед изменением кода:

1. изучи repository;
2. прочитай README;
3. изучи текущую структуру;
4. найди Python configuration;
5. найди existing AI code;
6. найди tests;
7. найди environment setup;
8. запусти существующие tests;
9. не удаляй рабочий код.

---

# 58. FIRST RESPONSE FORMAT

После анализа repository выведи:

```text
1. CURRENT STATE

2. EXISTING AI-RELATED CODE

3. WHAT IS MISSING FOR AI CORE

4. PROPOSED AI CORE ARCHITECTURE

5. COMPETENCY MODEL

6. INTERVIEW STATE MACHINE

7. ANSWER EVALUATION SCHEMA

8. SKILL EVIDENCE MODEL

9. TESTING STRATEGY

10. FIRST 8–12 IMPLEMENTATION TASKS

11. FIRST TASK TO IMPLEMENT NOW
```

После этого начни реализацию первой задачи.

---

# 59. FIRST IMPLEMENTATION ORDER

Предпочтительный порядок:

```text
TASK 1
Core schemas.

TASK 2
LLMProvider abstraction.

TASK 3
Answer Evaluator.

TASK 4
Question Generator.

TASK 5
Competency Graph.

TASK 6
Skill State + Evidence.

TASK 7
Decision Engine.

TASK 8
Interview State Machine.

TASK 9
CLI interview runner.

TASK 10
Final Report Generator.

TASK 11
Golden interview tests.

TASK 12
Interview trace + regression tests.
```

---

# 60. DEFINITION OF DONE FOR AI CORE

AI Core готов, когда:

```text
MIMAS starts interview

↓

selects competency

↓

asks appropriate question

↓

evaluates answer

↓

detects strengths / gaps / misconceptions

↓

decides whether follow-up is necessary

↓

adapts difficulty

↓

moves to another skill

↓

creates evidence

↓

finishes interview

↓

generates explainable report
```

---

# 61. FINAL PRODUCT PRINCIPLE

Кандидат говорит:

> Я Middle Python Developer.

MIMAS не должен просто верить этому.

MIMAS должен проверить.

```text
Question
↓
Answer
↓
Follow-up
↓
Scenario
↓
Verification
↓
Evidence
```

После этого MIMAS может сказать:

```text
Demonstrated:

Python Core — Strong
AsyncIO — Medium
PostgreSQL — Medium

Evidence:
...
```

Главная единица доверия MIMAS:

> **не резюме, не self-reported skill и не AI score — а SkillEvidence.**

---

# 62. START NOW

Начни не с frontend.

Начни не с вакансий.

Начни не с базы данных.

Начни с вопроса:

> **Может ли MIMAS провести действительно хорошее техническое интервью?**

Проанализируй текущий repository.

Спроектируй минимальное AI Core.

Затем реализуй первый vertical slice:

```text
Question
↓
Candidate Answer
↓
Answer Evaluation
↓
SkillEvidence
↓
Decision
↓
Follow-up
```

После того как этот цикл работает — расширь его до полноценного Interview Engine.

Цель первой стадии MIMAS:

> **создать AI-интервьюера, которому технический специалист сможет доверить первичное структурированное собеседование.**
