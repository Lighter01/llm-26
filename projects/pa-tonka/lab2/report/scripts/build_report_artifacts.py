"""Rebuild the report's figures and tables from saved runs, without model calls.

Run from lab2 using the command documented in report/LAB2_REPORT.md.
All output and Matplotlib's cache stay inside report/.
"""

# Matplotlib reads its cache directory at import; configure it before those imports.
# ruff: noqa: E402

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import os
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / 'report'
ART = REPORT / 'artifacts'
DATA = ART / 'data'
os.environ['MPLCONFIGDIR'] = str(REPORT / '.cache' / 'matplotlib')

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import yaml
from matplotlib.lines import Line2D
from matplotlib.ticker import MultipleLocator

SNAPSHOT = 'c3d53956346388b222aaaaf4637776f563e201b8'
CORPUS = ROOT / 'data/markdown/5etools' / SNAPSHOT
SELECTED = 'g1_source_map_recursive'
RUNS = [
    ('R1', 'g1_markdown_initial', 'G1', 'Markdown'),
    ('R2', 'g1_recursive', 'G1', 'Recursive'),
    ('R3', SELECTED, 'G1', 'Source map H4'),
    ('R4', 'g2_overlap_128', 'G2', 'Overlap 128'),
    ('R5', 'g2_size_768', 'G2', 'Размер 768'),
    ('R6', 'g3_hybrid', 'G3', 'Hybrid'),
    ('R7', 'g4_hnsw_32_200_256', 'G4', 'HNSW 32/200/256'),
    ('R8', 'g4_bm25_no_stem', 'G4', 'BM25 no-stem'),
    ('R9', 'g5_title_strip', 'G5', 'Title + strip'),
    ('R10', 'g5_no_title_keep', 'G5', 'Без title'),
]
GROUP_RUNS = {
    'G1': ['R1', 'R2', 'R3'],
    'G2': ['R3', 'R4', 'R5'],
    'G3': ['R3', 'R6'],
    'G4': ['R6', 'R7', 'R8'],
    'G5': ['R3', 'R9', 'R10'],
}
CATS = ['phb', 'dmg', 'mm', 'multi']
CAT_LABELS = ['PHB', 'DMG', 'MM', 'Несколько книг']
GRADE_FIELDS = ['correctness', 'completeness', 'citation_support']
GRADE_LABELS = ['Корректность', 'Полнота', 'Поддержка цитатами']
GRADE_COLORS = {'yes': '#287D6A', 'partial': '#E8B44E', 'no': '#BD4B55'}
GROUP_COLORS = dict(
    zip(['G1', 'G2', 'G3', 'G4', 'G5'], ['#3265A8', '#D58A35', '#3A8D85', '#9A6CAC', '#BB5D73'])
)
TOPICS = {
    'phb_01': 'Subtle Spell: стоимость и компоненты',
    'phb_02': 'Обезвоживание и снятие истощения',
    'phb_03': 'Confusion: действие и движение',
    'phb_04': 'Бонус от справочной книги',
    'phb_05': 'Концентрация после урона и Incapacitated',
    'dmg_01': 'Ходы Бастиона и отсутствие владельца',
    'dmg_02': 'Тонкий лёд и холодная вода',
    'dmg_03': 'Конфликт с разумным предметом',
    'dmg_04': 'Опознание и использование компьютера',
    'dmg_05': 'Сокровища CR 5–10 и редкость предметов',
    'mm_01': 'Скорость рытья и тоннель анхега',
    'mm_02': 'Поглощение кислоты и Berserk голема',
    'mm_03': 'Святая вода против Drone часмы',
    'mm_04': 'Ржавильщик и металлическое оружие',
    'mm_05': 'Регенерация тролля и его конечности',
    'multi_01': 'Vortex внутри Silence',
    'multi_02': 'Purple Worm Poison против Clay Golem',
    'multi_03': 'Бюджет встречи с двумя Магами',
    'multi_04': 'Изготовление +1 Plate Armor',
    'multi_05': 'Вода для группы и Alchemy Jug',
}
INPUTS: dict[str, str] = {}


def read(path: Path) -> str:
    raw = path.read_bytes()
    INPUTS[str(path.relative_to(ROOT))] = hashlib.sha256(raw).hexdigest()
    return raw.decode('utf-8')


def read_json(path: Path):
    return json.loads(read(path))


def read_jsonl(path: Path):
    return [json.loads(line) for line in read(path).splitlines() if line]


def write_json(name: str, value) -> None:
    (DATA / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def write_csv(name: str, rows: list[dict]) -> None:
    with (DATA / name).open('w', newline='') as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def cell(value) -> str:
    return str(value).replace('|', r'\|').replace('\n', '<br>')


def table(headers, rows, *, best=None) -> str:
    # Select winners before display rounding, retaining every numerical tie.
    rows = [list(row) for row in rows]
    for column, (direction, raw_values) in (best or {}).items():
        optimum = (max if direction == 'max' else min)(raw_values)
        for row, value in zip(rows, raw_values):
            if math.isclose(float(value), float(optimum), rel_tol=1e-12, abs_tol=1e-12):
                row[column] = f'**{row[column]}**'
    return '\n'.join(
        [
            '| ' + ' | '.join(map(cell, headers)) + ' |',
            '| ' + ' | '.join('---' for _ in headers) + ' |',
            *['| ' + ' | '.join(map(cell, row)) + ' |' for row in rows],
        ]
    )


def intersection(a, b):
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def merged_ranges(refs):
    groups = defaultdict(list)
    for ref in refs:
        groups[(ref['source_file'], ref['body_sha256'])].append(
            (ref['start_char'], ref['end_char'])
        )
    for key, spans in groups.items():
        merged = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        groups[key] = merged
    return groups


def evidence_coverage(question, refs, gold):
    ranges = merged_ranges(refs)
    fact_coverages = []
    for fact in question['evidence']:
        alternatives = []
        for span in fact['alternatives']:
            key = (span['file'], gold['corpus']['files'][span['file']]['body_sha256'])
            covered = sum(
                intersection((span['start_char'], span['end_char']), region)
                for region in ranges.get(key, [])
            )
            alternatives.append(covered / (span['end_char'] - span['start_char']))
        fact_coverages.append(max(alternatives))
    return st.mean(fact_coverages)


def verify_run(directory, row, gold, bodies):
    manifest = read_jsonl(directory / 'chunks_manifest.jsonl')
    questions = read_jsonl(directory / 'per_question.jsonl')
    saved = read_json(directory / 'metrics.json')
    run = read_json(directory / 'run.json')
    run_gold = yaml.safe_load(read(directory / 'gold.yaml'))
    read(directory / 'config.yaml')
    read(directory / 'resolved_config.yaml')
    assert run_gold == gold, directory
    assert run['status'] == 'completed' and run['index_action'] == 'built'
    assert len(manifest) == int(row['expected_points']) == run['expected_points']
    assert len(questions) == saved['question_count'] == 20
    assert saved['error_count'] == 0
    by_id = {ref['chunk_id']: ref for ref in manifest}
    assert len(by_id) == len(manifest)
    gold_questions = {q['id']: q for q in gold['questions'] if q['answerable']}
    assert {q['question_id'] for q in questions} == set(gold_questions)
    for ref in manifest:
        assert ref['body_sha256'] == gold['corpus']['files'][ref['source_file']]['body_sha256']
        assert 0 <= ref['start_char'] < ref['end_char'] <= len(bodies[ref['source_file']])
    aggregates = defaultdict(list)
    details = []
    for record in questions:
        assert not record['error']
        question = gold_questions[record['question_id']]
        spans = [s for f in question['evidence'] for s in f['alternatives']]
        relevant = set()
        for ref in manifest:
            for span in spans:
                if ref['source_file'] != span['file']:
                    continue
                shortest = min(
                    ref['end_char'] - ref['start_char'], span['end_char'] - span['start_char']
                )
                if (
                    intersection(
                        (ref['start_char'], ref['end_char']), (span['start_char'], span['end_char'])
                    )
                    >= 0.5 * shortest
                ):
                    relevant.add(ref['chunk_id'])
                    break
        assert relevant == set(record['metrics']['relevant_ids'])
        hits = record['retrieval']['hits']
        hit_refs = []
        for hit in hits:
            chunk = hit['chunk']
            meta = chunk['metadata']
            ref = by_id[meta['chunk_id']]
            assert (
                chunk['page_content']
                == bodies[meta['source_file']][meta['start_char'] : meta['end_char']]
            )
            assert all(meta[k] == v for k, v in ref.items())
            hit_refs.append(ref)
        assert len({r['chunk_id'] for r in hit_refs}) == len(hit_refs)
        rr = next((1 / i for i, r in enumerate(hit_refs[:10], 1) if r['chunk_id'] in relevant), 0.0)
        aggregates['mrr@10'].append(rr)
        assert math.isclose(rr, record['metrics']['rr'], abs_tol=1e-12)
        for k in [1, 5, 10]:
            top = hit_refs[:k]
            found = sum(r['chunk_id'] in relevant for r in top)
            values = {
                'precision': found / k,
                'recall': found / len(relevant) if relevant else 0,
                'evidence_coverage': evidence_coverage(question, top, gold),
            }
            for metric, value in values.items():
                assert math.isclose(value, record['metrics'][metric][str(k)], abs_tol=1e-12)
                aggregates[f'{metric}@{k}'].append(value)
        details.append(
            {
                'run': row['run'],
                'question_id': question['id'],
                'category': question['id'].split('_')[0],
                'ec5': record['metrics']['evidence_coverage']['5'],
                'rr10': rr,
            }
        )
    for key, values in aggregates.items():
        assert math.isclose(st.mean(values), saved['metrics'][key], abs_tol=1e-12)
        assert math.isclose(st.mean(values), float(row[key]), abs_tol=1e-12)
    return details, run, [ref['token_count'] for ref in manifest]


def figure_style():
    plt.rcParams.update(
        {
            'font.family': 'DejaVu Sans',
            'font.size': 10.5,
            'axes.titlesize': 14,
            'axes.titleweight': 'bold',
            'axes.labelsize': 11,
            'axes.spines.top': False,
            'axes.spines.right': False,
            'figure.facecolor': 'white',
            'axes.facecolor': 'white',
            'savefig.facecolor': 'white',
            'axes.unicode_minus': False,
        }
    )


def save(fig, name):
    fig.savefig(ART / name, dpi=190, bbox_inches='tight', pad_inches=0.18)
    plt.close(fig)


def pareto_ids(rows, x_key, y_key, *, maximize_x=True):
    points = [(float(r[x_key]), float(r[y_key])) for r in rows]
    result = []
    for i, (x, y) in enumerate(points):
        dominated = any(
            (other_x >= x if maximize_x else other_x <= x)
            and other_y >= y
            and (other_x != x or other_y != y)
            for other_x, other_y in points
        )
        if not dominated:
            result.append(rows[i]['id'])
    return result


def draw_front(ax, rows, x_key, y_key, *, maximize_x=True):
    ids = pareto_ids(rows, x_key, y_key, maximize_x=maximize_x)
    points = sorted({(float(r[x_key]), float(r[y_key])) for r in rows if r['id'] in ids})
    ax.plot(*zip(*points), color='#287D6A', ls='--', lw=1.6, zorder=2)
    ax.scatter(
        *zip(*points), s=170, facecolors='none', edgecolors='#287D6A', linewidths=1.3, zorder=4
    )
    return ids


def figures(rows, per_question, review, qa):
    labels = [f'{r["id"]}  {r["label"]}' for r in rows]
    y = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.barh(
        y - 0.18,
        [float(r['evidence_coverage@5']) for r in rows],
        0.32,
        label='Evidence Coverage@5',
        color='#287D6A',
    )
    ax.barh(y + 0.18, [float(r['mrr@10']) for r in rows], 0.32, label='MRR@10', color='#6487BE')
    for i, r in enumerate(rows):
        ax.text(
            float(r['evidence_coverage@5']) + 0.008,
            i - 0.18,
            f'{float(r["evidence_coverage@5"]):.2f}',
            va='center',
            fontsize=9,
        )
        ax.text(
            float(r['mrr@10']) + 0.008,
            i + 0.18,
            f'{float(r["mrr@10"]):.2f}',
            va='center',
            fontsize=9,
        )
    ax.axhspan(1.55, 2.45, color='#287D6A', alpha=0.07)
    ax.set(
        yticks=y,
        yticklabels=labels,
        xlim=(0, 1.12),
        xlabel='Значение метрики',
        title='Качество поиска: полнота evidence и ранг первого совпадения',
    )
    ax.set_xticks(np.arange(0, 1.01, 0.2))
    ax.invert_yaxis()
    ax.grid(axis='x', alpha=0.2)
    ax.set_axisbelow(True)
    ax.legend(loc='lower left', bbox_to_anchor=(0, -0.24), ncol=2, frameon=False)
    fig.text(
        0.01,
        0.005,
        '20 вопросов на конфигурацию · R3 — выбранный профиль · ссылки на runs приведены в отчёте',
        fontsize=9,
        color='#555555',
    )
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    save(fig, 'retrieval_quality.png')

    fig, ax = plt.subplots(figsize=(11, 6.5))
    grouped = defaultdict(list)
    for r in rows:
        grouped[(float(r['evidence_coverage@5']), float(r['mrr@10']))].append(r)
    positions = {
        'R1': (12, -22),
        'R2': (-12, 18),
        'R3': (18, 8),
        'R4': (20, -10),
        'R5': (-210, 20),
        'R6': (-110, -40),
        'R8': (20, 45),
        'R10': (16, -24),
    }
    for point, coincident in grouped.items():
        # Concentric outlines retain the exact coordinates of coincident runs.
        for i, r in reversed(list(enumerate(coincident))):
            ax.scatter(
                *point,
                s=52 + i * 60,
                color=GROUP_COLORS[r['group']] if i == 0 else 'none',
                edgecolor=GROUP_COLORS[r['group']],
                linewidth=1.5,
                zorder=3,
            )
        label = '\n'.join(f'{r["id"]}: {r["label"]}' for r in coincident)
        ax.annotate(
            label,
            point,
            xytext=positions[coincident[0]['id']],
            textcoords='offset points',
            fontsize=9,
            arrowprops={'arrowstyle': '-', 'lw': 0.6, 'color': '#666666'},
            bbox={'boxstyle': 'round,pad=.2', 'fc': 'white', 'ec': 'none', 'alpha': 0.9},
        )
    quality_front = draw_front(ax, rows, 'evidence_coverage@5', 'mrr@10')
    ax.set(
        xlim=(0.77, 1.035),
        ylim=(0.70, 1.05),
        xlabel='Evidence Coverage@5 — больше лучше',
        ylabel='MRR@10 — больше лучше',
        title='Парето-фронт качества поиска: EC@5 и MRR@10',
    )
    ax.grid(alpha=0.2)
    ax.set_axisbelow(True)
    ax.legend(
        handles=[
            Line2D(
                [],
                [],
                color='#287D6A',
                ls='--',
                marker='o',
                markerfacecolor='none',
                label='Парето-фронт',
            )
        ],
        loc='lower right',
        frameon=False,
    )
    fig.text(
        0.01,
        0.01,
        '20 вопросов · совпадающие координаты: R3/R9 и R6/R7 · линия соединяет измеренные точки',
        fontsize=9,
        color='#555555',
    )
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    save(fig, 'retrieval_quality_pareto.png')

    fig, ax = plt.subplots(figsize=(11, 6.3))
    offsets = [
        (12, -18),
        (10, 8),
        (-100, 25),
        (70, 20),
        (70, -22),
        (-95, -17),
        (50, -65),
        (100, -8),
        (-70, -38),
        (-83, -18),
    ]
    for r, offset in zip(rows, offsets):
        x = float(r['raw_tokens@5_mean'])
        value = float(r['evidence_coverage@5'])
        ax.scatter(
            x,
            value,
            s=int(r['expected_points']) / 42,
            color=GROUP_COLORS[r['group']],
            alpha=0.8,
            edgecolor='#182F37' if r['id'] == 'R3' else 'white',
            linewidth=2.3 if r['id'] == 'R3' else 1,
            zorder=3,
        )
        ax.annotate(
            f'{r["id"]}: {r["label"]}',
            (x, value),
            xytext=offset,
            textcoords='offset points',
            fontsize=9,
            arrowprops={'arrowstyle': '-', 'lw': 0.6, 'color': '#666666'},
            bbox={'boxstyle': 'round,pad=.2', 'fc': 'white', 'ec': 'none', 'alpha': 0.85},
        )
    handles = [
        Line2D([], [], color=c, marker='o', linestyle='', label=g, markersize=8)
        for g, c in GROUP_COLORS.items()
    ]
    context_front = draw_front(
        ax, rows, 'raw_tokens@5_mean', 'evidence_coverage@5', maximize_x=False
    )
    handles.append(
        Line2D(
            [],
            [],
            color='#287D6A',
            ls='--',
            marker='o',
            markerfacecolor='none',
            label='Парето-фронт',
        )
    )
    ax.legend(handles=handles, loc='lower left', title='Группа', frameon=False, ncol=6)
    ax.set(
        xlim=(850, 2390),
        ylim=(0, 1.08),
        xlabel='Средний объём top-5, токены эмбеддера',
        ylabel='Evidence Coverage@5',
        title='Парето-фронт: покрытие фактов и объём контекста',
    )
    ax.grid(alpha=0.2)
    ax.set_axisbelow(True)
    fig.text(
        0.01,
        0.01,
        'Площадь круга пропорциональна числу чанков индекса · диапазон EC: 0–1 · R3 выделен обводкой',
        fontsize=9,
        color='#555555',
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    save(fig, 'quality_context_tradeoff.png')
    write_json(
        'pareto_fronts.json',
        {
            'quality': {
                'x': 'evidence_coverage@5',
                'y': 'mrr@10',
                'directions': ['max', 'max'],
                'nondominated': quality_front,
            },
            'context': {
                'x': 'raw_tokens@5_mean',
                'y': 'evidence_coverage@5',
                'directions': ['min', 'max'],
                'nondominated': context_front,
            },
            'ties': 'Equal coordinate pairs remain nondominated together; no coordinate jitter.',
        },
    )

    ids = [f'{c}_{n:02d}' for c in CATS for n in range(1, 6)]
    lookup = {(r['run'], r['question_id']): r['ec5'] for r in per_question}
    matrix = np.array([[lookup[(r['run'], q)] for r in rows] for q in ids])
    fig, ax = plt.subplots(figsize=(10.8, 9.2))
    img = ax.imshow(matrix, vmin=0, vmax=1, cmap='YlGnBu', aspect='auto')
    ax.set(
        xticks=np.arange(10),
        xticklabels=[r['id'] for r in rows],
        yticks=np.arange(20),
        yticklabels=ids,
        xlabel='Конфигурация (обозначения раскрыты в отчёте)',
        title='Evidence Coverage@5 на каждом из 20 вопросов',
    )
    for row in range(20):
        for col in range(10):
            if matrix[row, col] < 1 - 1e-12:
                ax.text(
                    col,
                    row,
                    f'{matrix[row, col]:.2f}',
                    ha='center',
                    va='center',
                    fontsize=9,
                    color='white' if matrix[row, col] > 0.68 else '#172D3A',
                )
    for loc in [4.5, 9.5, 14.5]:
        ax.axhline(loc, color='white', lw=2.5)
    ax.set_xticks(np.arange(-0.5, 10, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, 20, 1), minor=True)
    ax.grid(which='minor', color='white', lw=0.45)
    ax.tick_params(which='minor', length=0)
    fig.colorbar(img, ax=ax, label='Покрытие фактов', shrink=0.8, pad=0.025)
    fig.text(
        0.01,
        0.008,
        'Числа подписаны только при неполном покрытии · тёмные ячейки без подписи = 1,00',
        fontsize=9,
        color='#555555',
    )
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    save(fig, 'evidence_coverage_heatmap.png')

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), gridspec_kw={'width_ratios': [1.12, 1]})
    for ax, groups, names, denom in [
        (axes[0], [[r[f] for r in review] for f in GRADE_FIELDS], GRADE_LABELS, 20),
        (
            axes[1],
            [
                [r['correctness'] for r in review if r['question_id'].startswith(c + '_')]
                for c in CATS
            ],
            CAT_LABELS,
            5,
        ),
    ]:
        left = np.zeros(len(groups))
        for grade in ['yes', 'partial', 'no']:
            counts = np.array([x.count(grade) for x in groups])
            ax.barh(
                np.arange(len(groups)),
                counts,
                left=left,
                color=GRADE_COLORS[grade],
                height=0.55,
                label=grade,
            )
            for i, (count, start) in enumerate(zip(counts, left)):
                if count:
                    ax.text(
                        start + count / 2,
                        i,
                        str(count),
                        ha='center',
                        va='center',
                        color='white' if grade != 'partial' else '#342A13',
                        fontweight='bold',
                    )
            left += counts
        ax.set(
            yticks=np.arange(len(names)), yticklabels=names, xlim=(0, denom), xlabel='Число ответов'
        )
        ax.xaxis.set_major_locator(MultipleLocator(5 if denom == 20 else 1))
        ax.invert_yaxis()
    axes[0].set_title('Три критерия, n = 20')
    axes[1].set_title('Корректность по категориям, n = 5')
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles, labels, loc='lower center', bbox_to_anchor=(0.5, 0.075), ncol=3, frameon=False
    )
    fig.suptitle('Смысловая оценка QA20', fontsize=16, fontweight='bold')
    fig.text(
        0.01,
        0.008,
        'Источник: qa_review.csv · OpenAI Codex · agent_assisted · qa20-semantic-v1',
        fontsize=9,
        color='#555555',
    )
    fig.tight_layout(rect=(0, 0.18, 1, 0.94))
    save(fig, 'qa_quality.png')

    fig, ax = plt.subplots(figsize=(12.5, 6.2))
    x = np.arange(20)
    bottom = np.zeros(20)
    stage_names = [
        ('query_embedding', 'Вектор вопроса', '#5676B0'),
        ('search', 'Поиск', '#3C8B80'),
        ('context', 'Контекст', '#DEA354'),
        ('generation', 'Генерация', '#9B7BB4'),
        ('postprocess', 'Обработка цитат', '#C75E68'),
    ]
    for field, label, color in stage_names:
        values = np.array([r['timings_ms'][field] / 1000 for r in qa])
        ax.bar(x, values, bottom=bottom, label=label, color=color, width=0.72)
        bottom += values
    median = st.median(r['timings_ms']['total'] / 1000 for r in qa if not r['cold_first_query'])
    ax.axhline(
        median,
        color='#263B44',
        linestyle='--',
        lw=1.3,
        label=f'Медиана запросов 2–20: {median:.3f} с',
    )
    ax.axvspan(-0.5, 0.5, color='#D9B556', alpha=0.16)
    for i, r in enumerate(qa):
        ax.text(
            i,
            r['timings_ms']['total'] / 1000 + 0.065,
            f'{r["timings_ms"]["total"] / 1000:.2f}',
            ha='center',
            fontsize=8.2,
        )
    ax.set(
        xticks=x,
        xticklabels=[r['question_id'] + ('*' if r['cold_first_query'] else '') for r in qa],
        ylabel='Время полного ответа, с',
        ylim=(0, 5.15),
        title='Время QA20 по вопросам и стадиям',
    )
    ax.tick_params(axis='x', labelrotation=60)
    ax.grid(axis='y', alpha=0.2)
    ax.set_axisbelow(True)
    ax.legend(loc='upper center', ncol=3, fontsize=9, frameon=False)
    fig.text(
        0.01,
        0.008,
        '* Первый запрос после загрузки моделей · загрузка сервера не включена · поиск и обработка цитат занимают малую долю времени',
        fontsize=9,
        color='#555555',
    )
    fig.tight_layout(rect=(0, 0.045, 1, 1))
    save(fig, 'qa_latency.png')


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    raw = list(csv.DictReader(read(ROOT / 'results/retrieval_comparison.csv').splitlines()))
    comparisons = {r['run']: r for r in raw if r['role'] == 'comparison'}
    assert len(raw) == 14 and len(comparisons) == 10
    assert len({r['comparison_cohort'] for r in comparisons.values()}) == 1
    assert set(comparisons) == {r[1] for r in RUNS}
    gold = yaml.safe_load(read(ROOT / 'data/questions/validated/questions.yaml'))
    validation = read_json(ROOT / 'data/questions/validated/validation_report.json')
    assert validation['status'] == 'PASS' and validation['output_state'] == 'written'
    bodies = {}
    corpus_stats = []
    sections = Counter(r['file'] for r in read_jsonl(CORPUS / 'source_map.jsonl'))
    for file in ['xphb.md', 'xdmg.md', 'xmm.md']:
        text = read(CORPUS / file)
        end = text.index('\n---\n', 4)
        meta = yaml.safe_load(text[4:end])
        body = text[end + 5 :]
        assert body.startswith('\n')
        body = body[1:]
        assert meta['upstream_sha'] == SNAPSHOT
        assert (
            hashlib.sha256(body.encode()).hexdigest()
            == gold['corpus']['files'][file]['body_sha256']
        )
        bodies[file] = body
        corpus_stats.append(
            {
                'book': meta['book_id'],
                'title': meta['title'],
                'words': len(body.split()),
                'unicode_characters': len(body),
                'sections': sections[file],
            }
        )
    assert sum(r['words'] for r in corpus_stats) == 687745
    assert sum(r['unicode_characters'] for r in corpus_stats) == 3869486
    assert sum(r['sections'] for r in corpus_stats) == 4536
    assert (
        INPUTS[str((CORPUS / 'source_map.jsonl').relative_to(ROOT))]
        == gold['corpus']['source_map_sha256']
    )
    corpus_hash = hashlib.sha256(
        (ROOT / 'data/questions/validated/questions.yaml').read_bytes()
    ).hexdigest()
    disk = read_json(ROOT / 'results/technical/c4-evidence.json')
    disk_by_run = {r['run']: r for r in disk['runs']}
    rows = []
    per_question = []
    runs = {}
    lengths = {}
    for short, name, group, label in RUNS:
        row = dict(comparisons[name])
        assert row['comparison_eligible'] == 'True'
        assert row['gold_sha256'] == corpus_hash
        row.update(id=short, label=label)
        detailed, run, lens = verify_run(ROOT / 'results' / name, row, gold, bodies)
        row.update(
            collection_allocated_bytes=disk_by_run[name]['collection_allocated_bytes'],
            collection_apparent_bytes=disk_by_run[name]['collection_apparent_bytes'],
        )
        rows.append(row)
        per_question.extend(detailed)
        runs[name] = run
        lengths[name] = lens
        print(
            f'Проверен {short}: {name}, {len(lens)} чанков, 20 вопросов, все retrieval-метрики совпали',
            flush=True,
        )
    review = list(
        csv.DictReader(read(ROOT / 'results/qa_final/qa_review.csv').splitlines(keepends=True))
    )
    qa = read_jsonl(ROOT / 'results/qa_final/qa_answers.jsonl')
    qa_gold = yaml.safe_load(read(ROOT / 'results/qa_final/gold.yaml'))
    qa_run = read_json(ROOT / 'results/qa_final/run.json')
    qa_summary = read_json(ROOT / 'results/qa_final/qa_summary.json')
    read(ROOT / 'results/qa_final/resolved_config.yaml')
    read(ROOT / 'results/qa_final/resolved_llm_profile.yaml')
    read(ROOT / 'results/qa_final/prompts/system.txt')
    read(ROOT / 'results/qa_final/prompts/context_builder.py')
    assert (
        qa_gold == gold and qa_run['status'] == 'completed' and qa_run['index_action'] == 'reused'
    )
    assert len(qa) == len(review) == 20
    assert {r['question_id'] for r in qa} == {r['question_id'] for r in review}
    assert len({r['question_id'] for r in review}) == 20
    assert all(
        r['review_status'] == 'reviewed' and r['review_version'] == 'qa20-semantic-v1'
        for r in review
    )
    context_ec = {}
    gold_by_id = {q['id']: q for q in gold['questions']}
    for r in qa:
        assert not r['error'] and r['finish_reason'] == 'stop' and not r['warnings']
        assert len(r['context']['chunk_ids']) == 5 and not r['context']['dropped_chunk_ids']
        assert (
            r['usage']['input_tokens']
            == r['context']['input_tokens']
            == r['llm_timings']['prompt_n']
        )
        assert r['usage']['input_tokens'] + 1536 + 256 <= 8192
        for source in r['citation_registry'].values():
            m = source['metadata']
            assert (
                source['page_content'] == bodies[m['source_file']][m['start_char'] : m['end_char']]
            )
        context_ec[r['question_id']] = evidence_coverage(
            gold_by_id[r['question_id']],
            [s['metadata'] for s in r['citation_registry'].values()],
            gold,
        )
    grade_counts = {
        f: {v: sum(r[f] == v for r in review) for v in ['yes', 'partial', 'no']}
        for f in GRADE_FIELDS
    }
    cat_counts = {
        c: {
            f: dict(Counter(r[f] for r in review if r['question_id'].startswith(c + '_')))
            for f in GRADE_FIELDS
        }
        for c in CATS
    }
    warm = [r for r in qa if not r['cold_first_query']]
    assert len(warm) == 19 and qa[0]['cold_first_query']
    timings = []
    for r in qa:
        timings.append(
            {
                'question_id': r['question_id'],
                'first_query': r['cold_first_query'],
                **r['timings_ms'],
                **r['usage'],
                'context_ec5': context_ec[r['question_id']],
            }
        )
    times = [r['timings_ms']['total'] / 1000 for r in warm]
    c3 = read_json(ROOT / 'results/technical/c3-demo.json')
    reuse = read_json(ROOT / 'results/g1_markdown_reuse_check/run.json')
    initial = runs['g1_markdown_initial']
    assert reuse['index_action'] == 'reused'
    assert reuse['index_id'] == initial['index_id'] and reuse['build_id'] == initial['build_id']
    stats = {
        'corpus': corpus_stats,
        'gold_counts': validation['counts'],
        'grade_counts': grade_counts,
        'category_grades': cat_counts,
        'fully_positive': sum(all(r[f] == 'yes' for f in GRADE_FIELDS) for r in review),
        'qa_context_ec5': context_ec,
        'qa_context_ec5_mean': st.mean(context_ec.values()),
        'qa_first_seconds': qa[0]['timings_ms']['total'] / 1000,
        'qa_warm_seconds': {
            'min': min(times),
            'mean': st.mean(times),
            'median': st.median(times),
            'max': max(times),
        },
        'qa_input_range': [
            min(r['usage']['input_tokens'] for r in qa),
            max(r['usage']['input_tokens'] for r in qa),
        ],
        'qa_output_range': [
            min(r['usage']['output_tokens'] for r in qa),
            max(r['usage']['output_tokens'] for r in qa),
        ],
        'generation_fraction': sum(r['timings_ms']['generation'] for r in qa)
        / sum(r['timings_ms']['total'] for r in qa),
        'chunk_lengths': {
            name: {'min': min(values), 'median': st.median(values), 'max': max(values)}
            for name, values in lengths.items()
        },
        'verified_retrieval_runs': 10,
        'verified_questions': 200,
        'verification': 'Independent recomputation from corpus, gold, full manifest and ranked hits; tolerance 1e-12',
        'runtime': {
            'python': sys.version.split()[0],
            **{p: importlib.metadata.version(p) for p in ['matplotlib', 'PyYAML', 'numpy']},
        },
    }
    assert grade_counts == {
        'correctness': {'yes': 15, 'partial': 4, 'no': 1},
        'completeness': {'yes': 12, 'partial': 8, 'no': 0},
        'citation_support': {'yes': 15, 'partial': 5, 'no': 0},
    }
    write_csv('corpus.csv', corpus_stats)
    write_csv('retrieval_metrics.csv', rows)
    write_csv('evidence_coverage_by_question.csv', per_question)
    write_csv('qa_timings.csv', timings)
    write_csv('qa_review_summary.csv', [{'criterion': f, **grade_counts[f]} for f in GRADE_FIELDS])
    write_json('report_statistics.json', stats)
    out_tables = {}
    out_tables['corpus'] = table(
        ['Книга', 'Назначение', 'Слов body', 'Разделов'],
        [
            [r['title'], role, r['words'], r['sections']]
            for r, role in zip(
                corpus_stats,
                [
                    'Правила для игроков, классы, снаряжение и заклинания',
                    'Правила и инструменты ведущего, сокровища',
                    'Характеристики и описания монстров',
                ],
            )
        ]
        + [
            [
                '**Всего**',
                '',
                sum(r['words'] for r in corpus_stats),
                sum(r['sections'] for r in corpus_stats),
            ]
        ],
    )
    out_tables['run_keys'] = table(
        ['ID', 'Группа', 'Run', 'Изменение'],
        [
            [r['id'], r['group'], f'[{r["run"]}](../results/{r["run"]}/run.json)', r['label']]
            for r in rows
        ],
    )
    row_by_id = {r['id']: r for r in rows}
    for group, ids in GROUP_RUNS.items():
        selected = [row_by_id[x] for x in ids]
        header = ['Вариант', 'EC@5', 'MRR@10', 'P@5', 'R@5', 'Токенов top-5']
        values = [
            [
                r['id'] + ' ' + r['label'],
                *[
                    f'{float(r[k]):.4f}'
                    for k in ['evidence_coverage@5', 'mrr@10', 'precision@5', 'recall@5']
                ],
                f'{float(r["raw_tokens@5_mean"]):.2f}',
            ]
            for r in selected
        ]
        if group in ['G1', 'G2']:
            header += ['Чанков', 'Подготовка, с']
            for value, r in zip(values, selected):
                value.extend([r['expected_points'], f'{float(r["preparation_ms"]) / 1000:.2f}'])
        best = {
            i + 1: ('max', [float(r[k]) for r in selected])
            for i, k in enumerate(['evidence_coverage@5', 'mrr@10', 'precision@5', 'recall@5'])
        }
        best[5] = ('min', [float(r['raw_tokens@5_mean']) for r in selected])
        if group in ['G1', 'G2']:
            best[6] = ('min', [int(r['expected_points']) for r in selected])
            best[7] = ('min', [float(r['preparation_ms']) for r in selected])
        out_tables[group] = table(header, values, best=best)
    out_tables['retrieval_all'] = table(
        ['ID', 'EC@5', 'EC@10', 'MRR@10', 'P@5', 'R@5', 'Чанков', 'Токенов top-5'],
        [
            [
                r['id'],
                *[
                    f'{float(r[k]):.4f}'
                    for k in [
                        'evidence_coverage@5',
                        'evidence_coverage@10',
                        'mrr@10',
                        'precision@5',
                        'recall@5',
                    ]
                ],
                r['expected_points'],
                f'{float(r["raw_tokens@5_mean"]):.2f}',
            ]
            for r in rows
        ],
    )
    out_tables['costs'] = table(
        ['ID', 'Подготовка, с', 'Весь run, с', 'Медиана retrieval¹, мс', 'Диск allocated, MiB'],
        [
            [
                r['id'],
                f'{float(r["preparation_ms"]) / 1000:.2f}',
                f'{float(r["wall_time_ms"]) / 1000:.2f}',
                f'{float(r["retrieval_warm_median_ms"]):.2f}',
                f'{r["collection_allocated_bytes"] / 2**20:.2f}',
            ]
            for r in rows
        ],
    )
    out_tables['retrieval_extra'] = table(
        ['ID', 'P@1', 'R@1', 'EC@1', 'P@10', 'R@10'],
        [
            [
                r['id'],
                *[
                    f'{float(r[k]):.4f}'
                    for k in [
                        'precision@1',
                        'recall@1',
                        'evidence_coverage@1',
                        'precision@10',
                        'recall@10',
                    ]
                ],
            ]
            for r in rows
        ],
    )
    # These tables compare configurations. Highlight quality maxima and cost minima;
    # QA criteria/stages and memory measurements have no shared winner to rank.
    for name, columns in {
        'retrieval_all': [
            ('max', k)
            for k in [
                'evidence_coverage@5',
                'evidence_coverage@10',
                'mrr@10',
                'precision@5',
                'recall@5',
            ]
        ]
        + [('min', 'expected_points'), ('min', 'raw_tokens@5_mean')],
        'costs': [
            ('min', k)
            for k in [
                'preparation_ms',
                'wall_time_ms',
                'retrieval_warm_median_ms',
                'collection_allocated_bytes',
            ]
        ],
        'retrieval_extra': [
            ('max', k)
            for k in ['precision@1', 'recall@1', 'evidence_coverage@1', 'precision@10', 'recall@10']
        ],
    }.items():
        lines = out_tables[name].splitlines()
        values = [[v.strip() for v in line.strip('|').split('|')] for line in lines[2:]]
        headers = [v.strip() for v in lines[0].strip('|').split('|')]
        out_tables[name] = table(
            headers,
            values,
            best={
                i + 1: (direction, [float(r[key]) for r in rows])
                for i, (direction, key) in enumerate(columns)
            },
        )
    out_tables['qa_grades'] = table(
        ['Критерий', 'yes', 'partial', 'no'],
        [
            [
                label,
                *[
                    f'{grade_counts[f][g]} ({grade_counts[f][g] / 20:.0%})'
                    for g in ['yes', 'partial', 'no']
                ],
            ]
            for f, label in zip(GRADE_FIELDS, GRADE_LABELS)
        ],
    )
    for c in CATS:
        values = []
        for r in review:
            if not r['question_id'].startswith(c + '_'):
                continue
            explanation = r['correctness_reason']
            if r['completeness'] != 'yes':
                explanation += ' ' + r['completeness_reason']
            values.append(
                [
                    r['question_id'],
                    TOPICS[r['question_id']],
                    ' / '.join(r[f] for f in GRADE_FIELDS),
                    explanation,
                ]
            )
        out_tables['qa_' + c] = table(['ID', 'Вопрос', 'К / П / Ц', 'Анализ ответа'], values)
    stage_labels = {
        'query_embedding': 'Векторизация вопроса',
        'search': 'Поиск Qdrant',
        'context': 'Сборка контекста',
        'generation': 'Генерация LLM',
        'postprocess': 'Обработка цитат',
        'total': 'Полный ответ',
    }
    out_tables['qa_stage_times'] = table(
        ['Этап', 'Среднее, мс', 'Медиана, мс', 'Максимум, мс'],
        [
            [
                stage_labels[f],
                *[
                    f'{qa_summary["primary"]["timings_ms"][f]["warm"][agg]:.2f}'
                    for agg in ['mean', 'median', 'max']
                ],
            ]
            for f in stage_labels
        ],
    )
    mem = []
    for name, label in [('g1_markdown_initial', 'Сборка R1'), (SELECTED, 'Сборка R3')]:
        cond = runs[name]['build_provenance']['conditions']
        mem.extend(
            [
                [
                    label,
                    'Torch GPU allocated peak',
                    f'{cond["gpu_peak_allocated_bytes"] / 2**30:.3f} GiB',
                ],
                [
                    label,
                    'Torch GPU reserved peak',
                    f'{cond["gpu_peak_reserved_bytes"] / 2**30:.3f} GiB',
                ],
                [
                    label,
                    'RSS документного worker, peak',
                    f'{cond["process_peak_rss_bytes"] / 2**30:.3f} GiB',
                ],
            ]
        )
    mem.extend(
        [
            [
                'QA20',
                'RSS основного процесса, peak',
                f'{qa_run["process_peak_rss_bytes"] / 2**30:.3f} GiB',
            ],
            [
                'Техническое demo C3',
                'PSS собственного дерева, peak',
                f'{c3["peak_tree_pss_bytes"] / 2**30:.3f} GiB',
            ],
            [
                'Техническое demo C3',
                'NVML всей GPU, sampled peak',
                f'{c3["peak_gpu_used_mib"]} MiB',
            ],
        ]
    )
    out_tables['memory'] = table(['Запуск', 'Область измерения', 'Значение'], mem)
    out_tables['reuse'] = table(
        ['Запуск', 'Действие', 'Время всего запуска, с', 'Чанков'],
        [
            [
                'R1',
                'Полная сборка',
                f'{initial["wall_time_ms"] / 1000:.3f}',
                initial['expected_points'],
            ],
            [
                'g1_markdown_reuse_check',
                'Переиспользование',
                f'{reuse["wall_time_ms"] / 1000:.3f}',
                reuse['expected_points'],
            ],
        ],
    )
    write_json('report_tables.json', out_tables)
    doc = REPORT / 'LAB2_REPORT.md'
    if doc.exists():
        text = doc.read_text()
        for key, value in out_tables.items():
            pattern = (
                rf'(<!-- BEGIN AUTO:{re.escape(key)} -->).*?(<!-- END AUTO:{re.escape(key)} -->)'
            )
            if re.search(pattern, text, re.S):
                text = re.sub(
                    pattern, lambda m: m[1] + '\n\n' + value + '\n\n' + m[2], text, flags=re.S
                )
        doc.write_text(text)
        for target in re.findall(r'(?<!!)\[[^\]\n]+\]\(([^)]+)\)', text):
            if '://' not in target and not target.startswith('#'):
                path = (REPORT / target.split('#', 1)[0]).resolve()
                if path.is_file() and path.is_relative_to(ROOT) and not path.is_relative_to(REPORT):
                    read(path)
    figure_style()
    figures(rows, per_question, review, qa)
    write_json(
        'input_fingerprints.json',
        {
            'inputs': dict(sorted(INPUTS.items())),
            'method': 'SHA-256 of bytes; only report/ outputs are written',
            'runtime': stats['runtime'],
        },
    )
    print(
        json.dumps(
            {
                'figures': 6,
                'inputs': len(INPUTS),
                'verified_runs': 10,
                'verified_questions': 200,
                'qa_grades': grade_counts,
                'qa_context_ec5': context_ec,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
