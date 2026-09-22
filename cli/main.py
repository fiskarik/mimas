"""Run with python -m cli.main. Offline preview is the safe default."""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from uuid import uuid4

from ai_core.interview.engine import InterviewEngine
from ai_core.interview.schemas import InterviewInput, Limits
from ai_core.interview.state import Phase
from ai_core.llm.provider import GroqProvider, OfflineProvider
from ai_core.llm.config import configured_groq
from ai_core.llm.factory import create_llm_provider
from ai_core.llm.base import ProviderError
from ai_core.models import Level
from ai_core.reports.generator import generate_report


async def run(args: argparse.Namespace) -> None:
    check_llm = getattr(args, 'check_llm', False)
    provider = configured_groq() if args.check_groq else create_llm_provider() if args.live or check_llm else OfflineProvider()
    if args.live or args.check_groq or check_llm:
        print(f'Проверка {provider.name}: {provider.model}')
        raw = await provider.generate(system='Return only JSON: {"ok": true}.', payload={},
                                      schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}, operation='health')
        if json.loads(raw) != {'ok': True}:
            raise ProviderError('Провайдер ответил, но проверка JSON не пройдена.')
        print('Провайдер подключён. Структурированный JSON-ответ получен.')
        if args.check_groq or check_llm:
            return
    mode = 'live' if args.live else 'offline_preview'
    output = Path(args.output) / uuid4().hex
    output.mkdir(parents=True, exist_ok=False)
    print(f'MIMAS | Python Backend Developer | {args.level} | {mode}')
    print('Только тестовые ответы без персональных данных. /stop — завершить.')
    if not args.live:
        print('Нет подключения к модели. Вопросы из банка, оценки не выставляются.')
    with (output / 'trace.jsonl').open('w', encoding='utf-8') as trace:
        def sink(event: dict) -> None:
            trace.write(json.dumps(event, ensure_ascii=False) + '\n')
            trace.flush()

        engine = InterviewEngine(provider, InterviewInput(target_level=Level(args.level)),
                                 Limits(max_questions=args.max_questions), trace_sink=sink)
        print('План: ' + ' → '.join(s.name for s in engine.plan.skills))
        question = await engine.start()
        while question:
            print(f'\n[{question.skill} / {question.type} / {question.generation}]\n{question.text}')
            try:
                answer = input('\nОтвет> ')
            except EOFError:
                answer = '/stop'
            if answer.strip() == '/stop':
                engine.complete()
                break
            if not answer.strip():
                print('Введите ответ или /stop.')
                continue
            if len(answer) > 16000:
                print('Максимум 16000 символов.')
                continue
            question = await engine.submit(question.id, answer)
        if engine.state.phase == Phase.COMPLETED:
            report = generate_report(engine.state, mode=mode)
            (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            (output / 'state.json').write_text(engine.state.model_dump_json(indent=2), encoding='utf-8')
            print(f'\nОтчёт: {output / "report.json"}\nТрассировка: {output / "trace.jsonl"}')


def main() -> None:
    # Windows redirected streams otherwise inherit a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='MIMAS text interview prototype')
    parser.add_argument('--live', action='store_true', help='Use configured LLM API; default has no API calls')
    parser.add_argument('--check-llm', action='store_true', help='Explicit live structured-output check for selected provider')
    parser.add_argument('--check-groq', action='store_true', help='Check key and model with one short API request')
    parser.add_argument('--level', choices=[v.value for v in Level], default='middle')
    parser.add_argument('--max-questions', type=int, choices=range(1, 51), default=20)
    parser.add_argument('--output', default='data/ai-core')
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    logging.getLogger('ai_core.llm').setLevel(logging.INFO)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print('\nПрервано. Уже полученные ответы сохранены в trace.jsonl.')
    except (ValueError, ProviderError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
