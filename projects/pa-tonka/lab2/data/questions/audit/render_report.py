"""Render the mechanical audit and hash-bound manual review as a local report."""

import hashlib
import html
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
auto = json.loads((HERE / 'mechanical_report.json').read_text(encoding='utf-8'))
review = json.loads((HERE / 'semantic_review.json').read_text(encoding='utf-8'))
raw_bytes = (ROOT / auto['input']).read_bytes()
raw = yaml.safe_load(raw_bytes)
assert hashlib.sha256(raw_bytes).hexdigest() == auto['raw_input_sha256'] == review['raw_input_sha256']
assert review['status'] == auto['summary']['status'] == 'PASS'
assert not review['remaining_issues']
assert [q['id'] for q in raw['questions']] == [q['id'] for q in review['questions']]
assert len(raw['questions']) == 23
for name, version in auto['corpus'].items():
    data = (ROOT / 'data/markdown/5etools/c3d53956346388b222aaaaf4637776f563e201b8' / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == version['file_sha256']
    assert review['corpus_body_sha256'][name] == version['body_sha256']

esc = html.escape
def bullets(values):
    return '<ul>' + ''.join(f'<li>{esc(value)}</li>' for value in values) + '</ul>'

parts = ['''<!doctype html><html lang="ru"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Самопроверка questions_codex.yaml — 5 ноября 2026</title>
<style>
body{font:16px/1.6 system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 24px;color:#202934;background:#fafafa}
h1{font-size:2rem;line-height:1.25}h2{margin-top:2.4rem}h3{margin-top:1.6rem}
table{border-collapse:collapse;width:100%;margin:20px 0}th,td{border:1px solid #ccd3da;padding:10px;vertical-align:top;text-align:left}
th{background:#edf1f5}.pass{border-left:5px solid #257b46;padding:18px;background:#edf9f0}
code,pre{font:13px/1.5 ui-monospace,monospace}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#eef1f4;padding:16px;border-radius:6px}
details{margin:12px 0}summary{cursor:pointer;font-weight:600}article{margin-top:32px;padding-top:10px;border-top:2px solid #ccd3da}
.muted{color:#596573}.question{font-style:italic}nav a{display:inline-block;margin:3px 10px 3px 0}a{color:#1659a0}
@media(prefers-color-scheme:dark){body{color:#dce3eb;background:#171b22}th,pre{background:#242c36}th,td,article{border-color:#46505e}.pass{background:#203426}.muted{color:#b5bfcc}a{color:#8dc1ff}}
</style><body><h1>Самопроверка нового набора вопросов</h1>''']
s = auto['summary']
parts.append(f'<p class="muted">{esc(review["date"])} · <code>{esc(auto["input"])}</code></p>')
parts.append(f'<p class="pass"><strong>PASS.</strong> 23 вопроса: 20 ответимых и 3 insufficient. '
             f'{s["facts"]} необходимых фактов, {s["alternatives"]} альтернатив; '
             'все цитаты имеют точное однозначное вхождение в указанном разделе. '
             'Все 23 вопроса прошли отдельную смысловую самопроверку; открытых ошибок нет.</p>')
parts.append(f'<p>{esc(review["review_type"])}</p><p>{esc(review["scope"])}</p>')
parts.append('<h2>Проверки требований</h2>' + bullets(list(review['criteria'].values())))
parts.append('<p>Вычисленное независимо дерево Markdown-заголовков совпадает с source_map '
             'по всем разделам трёх книг. Цитаты сравнивались без изменения пробелов, '
             'переносов, Markdown, регистра или пунктуации. Координаты остались только в '
             'отдельном отчёте аудита, сырой YAML не расширен.</p>')
parts.append('<h2>Итерации</h2>')
for item in review['iterations']:
    parts.append(f'<h3>Итерация {item["iteration"]}</h3><p>{esc(item["mechanical_result"])}</p>'
                 + bullets(item['semantic_findings_and_repairs']))
parts.append('<h2>Поиск альтернатив</h2><p>' + esc(review['alternatives_search']['method']) + '</p>')
parts.append(bullets(review['alternatives_search']['included']))
parts.append('<details><summary>Проверенные совпадения, которые не являются альтернативами</summary>'
             + bullets(review['alternatives_search']['excluded_as_not_equivalent']) + '</details>')
parts.append('<p>' + esc(review['alternatives_search']['completeness_statement']) + '</p>')
parts.append('<h2>Все вопросы</h2><nav>')
parts.extend(f'<a href="#{q["id"]}">{q["id"]}</a>' for q in raw['questions'])
parts.append('</nav>')
for q, mechanical, semantic in zip(raw['questions'], auto['questions'], review['questions'], strict=True):
    assert q['id'] == mechanical['id'] == semantic['id']
    assert len(semantic['fact_checks']) == len(q['evidence']), q['id']
    parts.append(f'<article id="{q["id"]}"><h3>{q["id"]} · PASS</h3>'
                 f'<p class="question" lang="en">{esc(q["question"])}</p>'
                 f'<p lang="en"><strong>Эталон:</strong> {esc(q["reference_answer"])}</p>')
    parts.append(bullets(semantic['fact_checks']))
    for field, label in [('answer_derivation', 'Расчёт'), ('scope_check', 'Границы ответа'),
                         ('source_necessity', 'Необходимость книг'),
                         ('insufficiency_proof', 'Недостаток сведений'),
                         ('expected_behavior', 'Ожидаемое поведение')]:
        if field in semantic:
            parts.append(f'<p><strong>{label}:</strong> {esc(semantic[field])}</p>')
    if 'cross_section_witness' in semantic:
        parts.append('<p><strong>Требуются разные разделы:</strong> '
                     + esc(' + '.join(semantic['cross_section_witness'])) + '</p>')
    if q['answerable']:
        parts.append(f'<details><summary>Все факты и {mechanical["alternative_count"]} точных альтернатив</summary>')
        for fact_index, (fact, verified) in enumerate(zip(q['evidence'], mechanical['facts'], strict=True), 1):
            parts.append(f'<p lang="en"><strong>Факт {fact_index}:</strong> {esc(fact["fact"])}</p>')
            for alt, located in zip(fact['alternatives'], verified['alternatives'], strict=True):
                parts.append(f'<p><code>{esc(alt["file"])}:{located["file_line_start"]}–{located["file_line_end"]}</code>'
                             '<br>' + esc(' > '.join(alt['heading_path'])) + '</p>'
                             f'<pre lang="en">{esc(alt["quote"])}</pre>')
        parts.append('</details>')
    else:
        parts.append('<p><code>answerable: false</code>, <code>evidence: []</code>.</p>')
    parts.append('</article>')
parts.append('<h2>Версии и границы проверки</h2>' + bullets(review['limits']))
parts.append('<p>Номера строк в отчёте относятся к полным файлам книг, включая front matter. '
             'В самих вопросах номеров строк нет.</p>')
parts.append('<details><summary>SHA-256 исходного набора и корпуса</summary><pre>' + esc(json.dumps({
    'raw_input_sha256': auto['raw_input_sha256'],
    'prompt_sha256': auto['prompt_sha256'],
    'source_map_sha256': auto['source_map_sha256'],
    'corpus': auto['corpus'],
}, ensure_ascii=False, indent=2)) + '</pre></details></body></html>')
(HERE / 'report.html').write_text('\n'.join(parts) + '\n', encoding='utf-8')
print('Rendered report.html; 23 semantic reviews are bound to the exact input and corpus hashes.')
