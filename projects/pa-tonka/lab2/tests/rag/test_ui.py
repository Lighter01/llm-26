from pathlib import Path

import httpx
import pytest
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
    captions = [c.value for c in app.caption]
    assert any('enclosing section starts on printed page 42' in caption for caption in captions)
    assert any('first line of book text' in caption for caption in captions)
    assert any(result['sources'][0]['page_content'] == c.value for c in app.code)
    assert len(app.warning) == 1  # unknown citation diagnostic, no duplicate bibliography
    app.text_area[0].set_value('Second?')
    app.button[0].click().run()
    assert calls == [{'question': 'First?'}, {'question': 'Second?'}]
    assert app.session_state['current_result']['question'] == 'Second?'
    assert 'First?' not in [element.value for element in app.markdown]


@pytest.mark.parametrize(
    ('health', 'expected_hint'),
    [
        (httpx.Response(200, json={'mode': 'qa', 'qa_ready': False}), 'demo terminal'),
        (httpx.Response(503, json={'mode': 'qa', 'qa_ready': False}), 'demo terminal'),
        (httpx.Response(200, json={'mode': 'retrieval_only', 'qa_ready': False}), 'search-only'),
        (httpx.ConnectError('connection refused'), 'check that the demo is running'),
    ],
)
def test_ui_disables_question_and_explains_how_to_recover(monkeypatch, health, expected_hint):
    def get_health(*args, **kwargs):
        if isinstance(health, Exception):
            raise health
        return health

    monkeypatch.setattr(httpx, 'get', get_health)
    app = AppTest.from_file(str(UI)).run()
    assert not app.exception and app.button[0].disabled
    assert expected_hint in app.warning[0].value.lower()
