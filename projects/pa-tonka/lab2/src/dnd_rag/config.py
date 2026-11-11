"""Strict, model-free configuration and explicit project-relative paths."""

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dnd_rag.contracts import RagError


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if key in result:
            raise ValueError(f'Duplicate YAML key: {key}')
        result[key] = loader.construct_object(value_node)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def read_yaml(path: Path) -> dict:
    try:
        data = yaml.load(path.read_text(encoding='utf-8'), Loader=UniqueKeyLoader)
        if not isinstance(data, dict):
            raise ValueError('Expected a YAML mapping')
        return data
    except (OSError, UnicodeError, ValueError, TypeError, yaml.YAMLError) as exc:
        raise RagError('invalid_config', f'{path}: {exc}') from exc


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True, validate_default=True)


class CorpusConfig(ConfigModel):
    directory: Path


class ChunkingConfig(ConfigModel):
    strategy: Literal['markdown', 'recursive', 'source_map_recursive'] = 'markdown'
    chunk_size: int = Field(default=512, ge=100, le=1000)
    chunk_overlap: int = Field(default=64, ge=0)
    max_heading_level: int = Field(default=4, ge=1, le=6)

    @model_validator(mode='after')
    def check_overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError('chunk_overlap must be smaller than chunk_size')
        return self


class EmbeddingConfig(ConfigModel):
    model_id: str = Field(default='google/embeddinggemma-2', min_length=1)
    revision: str = Field(pattern=r'^[a-f0-9]{40}$')
    dimension: Literal[128, 256, 512, 768] = 768
    include_title: bool = True
    strip_markdown_headings: bool = False
    query_prompt_name: Literal['QuestionAnswering', 'SearchQuery'] = 'QuestionAnswering'
    document_dtype: Literal['bfloat16', 'float32'] = 'bfloat16'
    document_batch_size: int = Field(default=16, gt=0)


class HnswConfig(ConfigModel):
    m: int = Field(default=16, ge=2)
    ef_construction: int = Field(default=100, gt=0)


class IndexConfig(ConfigModel):
    hnsw: HnswConfig = Field(default_factory=HnswConfig)
    quantization: Literal['none', 'scalar_int8', 'turboquant_4bit'] = 'none'


class RetrievalConfig(ConfigModel):
    mode: Literal['dense', 'hybrid'] = 'dense'
    limit: int = Field(default=10, gt=0)
    ef_search: int = Field(default=128, gt=0)
    hybrid_candidates_per_branch: int = Field(default=20, gt=0)
    rrf_constant: int = Field(default=2, gt=0)


class StemmerConfig(ConfigModel):
    type: Literal['snowball'] = 'snowball'
    language: Literal['english'] = 'english'


class BM25Config(ConfigModel):
    tokenizer: Literal['word'] = 'word'
    lowercase: bool = True
    stemmer: StemmerConfig | None = Field(default_factory=StemmerConfig)
    stopwords: Literal['english'] | None = 'english'
    k1: float = Field(default=1.2, ge=0, allow_inf_nan=False)
    b: float = Field(default=0.75, ge=0, le=1, allow_inf_nan=False)


class EvaluationConfig(ConfigModel):
    questions: Path = Path('data/questions/validated/questions.yaml')
    k: list[int] = Field(default_factory=lambda: [1, 5, 10])
    mrr_k: Literal[10] = 10

    @model_validator(mode='after')
    def check_ks(self):
        if self.k != [1, 5, 10]:
            raise ValueError('evaluation.k must be [1, 5, 10]')
        return self


class ExperimentConfig(ConfigModel):
    schema_version: Literal[1] = 1
    corpus: CorpusConfig
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    embedding: EmbeddingConfig
    index: IndexConfig = Field(default_factory=IndexConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    bm25: BM25Config = Field(default_factory=BM25Config)
    evaluation: EvaluationConfig = Field(default_factory=EvaluationConfig)

    @model_validator(mode='after')
    def check_limits(self):
        if self.retrieval.limit < max(self.evaluation.k):
            raise ValueError('retrieval.limit must cover evaluation.k')
        if (
            self.retrieval.mode == 'hybrid'
            and self.retrieval.hybrid_candidates_per_branch < self.retrieval.limit
        ):
            raise ValueError('hybrid candidates must cover retrieval.limit')
        return self


class LLMProfile(ConfigModel):
    context_size: Literal[8192] = 8192
    max_output_tokens: Literal[1536] = 1536
    safety_margin: Literal[256] = 256
    max_context_chunks: Literal[5] = 5
    thinking: Literal[False] = False
    server_subcommand: Literal['serve'] | None = None
    model_alias: str = 'dnd-nemotron'
    gpu_layers: int | None = Field(default=None, ge=0)
    batch_size: int | None = Field(default=None, gt=0)
    ubatch_size: int | None = Field(default=None, gt=0)
    cache_type_k: Literal['f16', 'q8_0', 'q4_0'] | None = None
    cache_type_v: Literal['f16', 'q8_0', 'q4_0'] | None = None
    kv_offload: bool = True
    flash_attention: Literal['on', 'off'] = 'on'
    threads: int = Field(default=8, gt=0)
    temperature: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    top_p: float = Field(default=1.0, gt=0, le=1, allow_inf_nan=False)
    top_k: int = Field(default=40, ge=0)
    min_p: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    seed: int = Field(default=42, ge=0)
    startup_timeout_seconds: float = Field(default=120.0, gt=0)
    http_timeout_seconds: float = Field(default=180.0, gt=0)

    @model_validator(mode='after')
    def check_batches(self):
        if self.batch_size and self.ubatch_size and self.ubatch_size > self.batch_size:
            raise ValueError('ubatch_size must not exceed batch_size')
        return self


class RuntimeSettings(ConfigModel):
    project_root: Path
    qdrant_url: str = 'http://127.0.0.1:6333'
    llama_server_bin: str = 'llama-server'
    model_path: Path
    llm_base_url: str = 'http://127.0.0.1:8080/v1'
    embedding_cache_dir: Path | None = None
    rag_api_url: str = 'http://127.0.0.1:8000'


def resolve_path(path: str | Path, root: Path) -> Path:
    path = Path(path).expanduser()
    return (root / path).resolve() if not path.is_absolute() else path.resolve()


def load_experiment(path: Path, *, project_root: Path) -> ExperimentConfig:
    data = read_yaml(resolve_path(path, project_root))
    try:
        # Convert only path fields explicitly; all other YAML types remain strict.
        corpus = data.get('corpus', {})
        if isinstance(corpus, dict) and isinstance(corpus.get('directory'), str):
            corpus['directory'] = resolve_path(corpus['directory'], project_root)
        evaluation = data.setdefault('evaluation', {})
        if isinstance(evaluation, dict):
            questions = evaluation.get('questions', 'data/questions/validated/questions.yaml')
            if isinstance(questions, str):
                evaluation['questions'] = resolve_path(questions, project_root)
        return ExperimentConfig.model_validate(data)
    except (ValidationError, ValueError, TypeError) as exc:
        raise RagError('invalid_config', f'{path}: {exc}') from exc


def load_llm_profile(path: Path) -> LLMProfile:
    try:
        return LLMProfile.model_validate(read_yaml(path))
    except ValidationError as exc:
        raise RagError('invalid_config', f'{path}: {exc}') from exc


def load_settings(project_root: Path) -> RuntimeSettings:
    values = {**dotenv_values(project_root / '.env'), **os.environ}

    def value(key, default):
        return values.get(key) or default

    cache = value('EMBEDDING_CACHE_DIR', None)
    return RuntimeSettings(
        project_root=project_root.resolve(),
        qdrant_url=value('QDRANT_URL', 'http://127.0.0.1:6333'),
        llama_server_bin=value('LLAMA_SERVER_BIN', 'llama-server'),
        model_path=resolve_path(
            value(
                'LLM_MODEL_PATH',
                '~/hf_models/gemma/nemotron/nemotron-3.5/bolt/'
                'NVIDIA-Nemotron-3.5-Bolt-E4B-UD-Q4_K_XL.gguf',
            ),
            project_root,
        ),
        llm_base_url=value('LLM_BASE_URL', 'http://127.0.0.1:8080/v1'),
        embedding_cache_dir=resolve_path(cache, project_root) if cache else None,
        rag_api_url=value('RAG_API_URL', 'http://127.0.0.1:8000'),
    )
