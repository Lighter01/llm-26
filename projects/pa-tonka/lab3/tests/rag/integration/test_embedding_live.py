"""Explicit, bounded model probe; never a full-corpus embedding run."""

import gc
import json
import statistics
from pathlib import Path
from time import perf_counter

import numpy as np
import pytest

from dnd_rag.config import load_experiment, load_settings
from dnd_rag.indexing.chunking import split_corpus
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.indexing.embedding import DocumentEncoder, QueryEncoder, load_token_counter

pytestmark = pytest.mark.rag_models
ROOT = Path(__file__).resolve().parents[3]


def test_real_corpus_offsets_and_text_only_encoders(tmp_path):
    import torch

    settings = load_settings(ROOT)
    config = load_experiment(
        Path('configs/experiments/g1_splitters/markdown.yaml'), project_root=ROOT
    )
    corpus = load_corpus(config.corpus.directory)
    counter = load_token_counter(config.embedding, settings.embedding_cache_dir)
    report = {'corpus': corpus.passport(), 'strategies': {}, 'dimensions': {}}
    samples = None
    for strategy in ('markdown', 'recursive', 'source_map_recursive'):
        before = perf_counter()
        chunks = split_corpus(
            corpus, config.chunking.model_copy(update={'strategy': strategy}), counter
        )
        lengths = [c.metadata.token_count for c in chunks]
        assert max(lengths) <= 512
        assert all(
            c.page_content
            == corpus.books[c.metadata.source_file].body[
                c.metadata.start_char : c.metadata.end_char
            ]
            for c in chunks
        )
        report['strategies'][strategy] = {
            'count': len(chunks),
            'min': min(lengths),
            'median': statistics.median(lengths),
            'max': max(lengths),
            'elapsed_ms': (perf_counter() - before) * 1000,
            'exact_slice_violations': 0,
        }
        if strategy == 'markdown':
            samples = chunks[:4]
    encoder = DocumentEncoder(config.embedding, settings)
    model = encoder.model[0].auto_model
    assert model.config.vision_config is None and model.config.audio_config is None
    report['text_only'] = True
    report['max_seq_length'] = min(8192, encoder.model.max_seq_length)
    report['document_dtype'] = str(next(model.parameters()).dtype)
    for dimension in (128, 256, 512, 768):
        encoder.config = config.embedding.model_copy(update={'dimension': dimension})
        batches = list(encoder.iter_batches(samples, corpus))
        vectors = np.asarray(batches[0].vectors)
        assert vectors.shape == (4, dimension) and np.isfinite(vectors).all()
        report['dimensions'][dimension] = {
            'gpu_shape': list(vectors.shape),
            'gpu_ms': batches[0].embedding_elapsed_ms,
        }
    report['gpu_peak_bytes'] = torch.cuda.max_memory_allocated()
    del model, encoder
    gc.collect()
    torch.cuda.empty_cache()
    before = perf_counter()
    query = QueryEncoder(config.embedding, settings)
    report['cpu_model_load_ms'] = (perf_counter() - before) * 1000
    report['prompts'] = sorted(query.model.prompts)
    query_times = []
    for dimension in (128, 256, 512, 768):
        query.config = config.embedding.model_copy(update={'dimension': dimension})
        before = perf_counter()
        vector = query.encode('How does Subtle Spell change Material components?')
        query_times.append((perf_counter() - before) * 1000)
        assert len(vector) == dimension and np.isfinite(vector).all()
        report['dimensions'][dimension]['cpu_shape'] = [len(vector)]
    report['cpu_query_ms_sequential'] = query_times
    output = tmp_path / 'embedding-probe.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
