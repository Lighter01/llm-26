import json
from pathlib import Path

import pytest
import yaml

from dnd_rag.contracts import RagError
from dnd_rag.evaluation.gold import load_gold
from dnd_rag.indexing.corpus import load_corpus

ROOT = Path(__file__).resolve().parents[2]
GOLD = ROOT / 'data/questions/validated/questions.yaml'
REPORT = GOLD.parent / 'validation_report.json'
CORPUS = ROOT / 'data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8'


@pytest.fixture
def corpus():
    return load_corpus(CORPUS)


def test_20_answerable_and_3_separate(corpus):
    gold = load_gold(GOLD, corpus, REPORT)
    assert len(gold.answerable) == 20
    assert len(gold.insufficient) == 3
    assert sum(len(q.evidence) for q in gold.answerable) == 59


@pytest.mark.parametrize('damage', ['hash', 'quote', 'range', 'map'])
def test_stale_hash_or_changed_quote_rejected(corpus, tmp_path, damage):
    data = yaml.safe_load(GOLD.read_text())
    span = data['questions'][0]['evidence'][0]['alternatives'][0]
    if damage == 'hash':
        data['corpus']['files']['xphb.md']['body_sha256'] = '0' * 64
    if damage == 'map':
        data['corpus']['source_map_sha256'] = '0' * 64
    if damage == 'quote':
        span['quote'] = 'X' + span['quote'][1:]
    if damage == 'range':
        span['end_char'] += 1
    path = tmp_path / 'gold.yaml'
    path.write_text(yaml.safe_dump(data))
    with pytest.raises(RagError):
        load_gold(path, corpus, REPORT)


@pytest.mark.parametrize('damage', ['FAIL', 'previous_preserved', 'raw_hash'])
def test_failed_report_not_old_pass(corpus, tmp_path, damage):
    data = json.loads(REPORT.read_text())
    if damage == 'FAIL':
        data['status'] = 'FAIL'
    if damage == 'previous_preserved':
        data['output_state'] = 'previous_preserved'
    if damage == 'raw_hash':
        data['raw_input_sha256'] = '0' * 64
    path = tmp_path / 'report.json'
    path.write_text(json.dumps(data))
    with pytest.raises(RagError):
        load_gold(GOLD, corpus, path)
