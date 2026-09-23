"""Explicit scripted QA server; never loaded by production or used as live AI."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DATA_DIR'] = str(ROOT / 'data' / 'qa-runtime-browser')
os.environ.pop('DATABASE_URL', None)
os.environ['COMPANY_KEY'] = 'demo-company'

from ai_core.llm.provider import FakeLLMProvider


class ScriptedProvider(FakeLLMProvider):
    model = 'SCRIPTED-QA-NOT-LIVE-AI'

    def __init__(self):
        super().__init__([])
        self.number = 0

    async def generate(self, *, system, payload, schema, operation="question"):
        self.calls.append({'payload':payload})
        if 'answer' in payload:
            return json.dumps({'correctness':'correct', 'depth':'medium',
                               'evidence':[{'type':'positive','claim':'Тестовое подтверждение объяснения',
                                            'quote':payload['answer'][:80]}],
                               'follow_up_required':False, 'recommended_difficulty':3,
                               'verification_outcome':'resolved' if payload.get('verification_target') else 'uncertain'})
        self.number += 1
        return json.dumps({'text':f'Вопрос {self.number}: ' + ('Объясните ключевую мысль предыдущего ответа своими словами?' if payload['spec']['action']=='VERIFY_INTEGRITY' else 'Как работает механизм в этом примере?')})


if __name__ == '__main__':
    import backend.ai_web
    provider = ScriptedProvider()
    backend.ai_web.create_llm_provider = lambda **kwargs:provider
    from backend.app import app
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8001)
