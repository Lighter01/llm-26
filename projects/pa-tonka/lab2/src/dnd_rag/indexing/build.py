"""GPU worker entrypoint. No lock acquisition: the parent passes its inherited fd."""

import argparse
import json
import os
import traceback
from pathlib import Path
from time import perf_counter

from dnd_rag.config import ExperimentConfig, RuntimeSettings
from dnd_rag.contracts import IndexIdentity, RagError, StageEvent
from dnd_rag.indexing.chunking import split_corpus
from dnd_rag.indexing.corpus import load_corpus
from dnd_rag.indexing.identity import assign_ids, library_versions, make_identity
from dnd_rag.indexing.store import QdrantStore


def build_index(config, settings, identity, *, on_stage=None):
    import torch

    from dnd_rag.indexing.embedding import DocumentEncoder, load_token_counter

    stages = []

    def record(name, before):
        event = StageEvent(
            name=name, status='executed', elapsed_ms=(perf_counter() - before) * 1000
        )
        emit(event)

    def emit(event):
        stages.append(event)
        if on_stage is not None:
            on_stage(event)

    before = perf_counter()
    corpus = load_corpus(config.corpus.directory)
    if (
        make_identity(
            config, corpus, library_versions(identity.build_spec['versions']['qdrant-server'])
        )
        != identity
    ):
        raise RagError(
            'build_inputs_changed', 'Corpus or dependencies changed before worker startup'
        )
    record('worker_corpus_validation', before)
    before = perf_counter()
    count = load_token_counter(config.embedding, settings.embedding_cache_dir)
    record('tokenizer_load', before)
    before = perf_counter()
    chunks = assign_ids(split_corpus(corpus, config.chunking, count), identity)
    record('splitting', before)
    before = perf_counter()
    encoder = DocumentEncoder(config.embedding, settings)
    record('document_model_load', before)
    store = QdrantStore(settings)
    ready = store.build(identity, chunks, encoder.iter_batches(chunks, corpus), on_stage=emit)
    provenance = {
        **ready.build_provenance,
        'stages': [s.model_dump() for s in stages],
        'conditions': {
            'document_device': torch.cuda.get_device_name(),
            'document_dtype': config.embedding.document_dtype,
            'document_batch_size': config.embedding.document_batch_size,
            'gpu_peak_allocated_bytes': torch.cuda.max_memory_allocated(),
            'gpu_peak_reserved_bytes': torch.cuda.max_memory_reserved(),
        },
        'timing_note': 'Embedding/upload interleave; Qdrant optimization overlaps upload.',
    }
    store._call('update_collection', collection_name=identity.collection, metadata=provenance)
    return ready.model_copy(update={'build_provenance': provenance})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    stages = []

    def on_stage(event):
        stages.append(event.model_dump())
        with Path(request['stages_path']).open('a') as stream:
            stream.write(event.model_dump_json() + '\n')

    result_path = Path(request['result_path'])
    result = {}
    try:
        fd = int(os.environ['DND_RAG_LOCK_FD'])
        os.fstat(fd)
        config = ExperimentConfig.model_validate_json(json.dumps(request['config']))
        settings = RuntimeSettings.model_validate_json(json.dumps(request['settings']))
        identity = IndexIdentity.model_validate(request['identity'])
        ready = build_index(config, settings, identity, on_stage=on_stage)
        result['index'] = ready.model_dump(mode='json')
    except Exception as exc:
        traceback.print_exc()
        error = exc if isinstance(exc, RagError) else RagError('build_failed', str(exc))
        result['error'] = error.as_dict()
    result['stages'] = stages
    temp = result_path.with_suffix('.tmp')
    temp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    temp.replace(result_path)
    return 1 if 'error' in result else 0


if __name__ == '__main__':
    raise SystemExit(main())
