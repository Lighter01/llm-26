from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from tests.rag.test_qa_service import service

UI = Path(__file__).resolve().parents[2] / 'src/dnd_rag/ui.py'


def test_ui_uses_http_and_displays_one_current_answer(monkeypatch):
    rag, _ = service()
    result = rag.ask('First?').result.model_dump(mode='json')
    calls = []
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: httpx.Response(200, json={'qa_ready': True}))

    def post(url, *, json, **kwargs):
        calls.append(json)
        return httpx.Response(200, json={**result, 'question': json['question']})

    monkeypatch.setattr(httpx, 'post', post)
    app = AppTest.from_file(str(UI)).run()
    assert not app.exception
    app.text_area[0].set_value('First?')
    app.button[0].click().run()
    assert calls == [{'question': 'First?'}]
    assert len(app.expander) == 1
    assert any('inherited' in c.value for c in app.caption)
    assert any(result['sources'][0]['page_content'] == c.value for c in app.code)
    assert len(app.warning) == 1  # unknown citation diagnostic, no duplicate bibliography
    app.text_area[0].set_value('Second?')
    app.button[0].click().run()
    assert calls == [{'question': 'First?'}, {'question': 'Second?'}]
    assert app.session_state['current_result']['question'] == 'Second?'
    assert 'First?' not in [element.value for element in app.markdown]


def test_ui_disables_question_until_qa_ready(monkeypatch):
    monkeypatch.setattr(httpx, 'get', lambda *a, **k: httpx.Response(200, json={'qa_ready': False}))
    app = AppTest.from_file(str(UI)).run()
    assert not app.exception and app.button[0].disabled
    assert 'not ready' in app.warning[0].value.lower()
