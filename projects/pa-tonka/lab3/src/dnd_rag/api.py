"""Fixed-profile, stateless HTTP transport for retrieval and optional grounded QA."""

import traceback
from pathlib import Path
from threading import Lock

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.exceptions import HTTPException

from dnd_rag.contracts import AskResult, RagError, RetrievalResult

ERROR_LOG = Path(__file__).resolve().parents[2] / '.runtime/errors.log'


class AskRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question: str = Field(min_length=1)

    @field_validator('question')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('Question must be nonempty text')
        return value


class RetrieveRequest(AskRequest):
    limit: int | None = Field(default=None, ge=1)


def _status(error):
    if error.code.startswith('invalid_') or error.code in {
        'embedding_input_too_long',
        'context_budget_exceeded',
        'input_too_long',
    }:
        return 422
    if error.code.endswith('_timeout'):
        return 504
    if error.code == 'qa_busy':
        return 429
    if error.code in {'llm_token_mismatch', 'thinking_enabled', 'llm_protocol'}:
        return 500
    return 503


def create_app(retriever, rag=None) -> FastAPI:
    app = FastAPI(title='D&D Rules Q&A', version='0.1.0')
    generation_gate = Lock()

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        # Do not echo the potentially long question or exception objects in details.
        details = [{'field': list(e['loc']), 'message': e['msg']} for e in error.errors()]
        return JSONResponse(
            {
                'error': {
                    'code': 'invalid_request',
                    'message': 'Invalid request fields',
                    'details': details,
                }
            },
            status_code=422,
        )

    @app.exception_handler(RagError)
    async def rag_error(request, error):
        return JSONResponse({'error': error.as_dict()}, status_code=_status(error))

    @app.exception_handler(httpx.TimeoutException)
    async def timeout(request, error):
        return JSONResponse(
            {'error': {'code': 'dependency_timeout', 'message': 'A dependency timed out'}},
            status_code=504,
        )

    @app.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse(
            {'error': {'code': 'http_error', 'message': str(error.detail)}},
            status_code=error.status_code,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, error):
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG.open('a', encoding='utf-8') as stream:
            traceback.print_exception(error, file=stream)
        return JSONResponse(
            {
                'error': {
                    'code': 'internal_error',
                    'message': 'Internal error; see the local runtime log',
                }
            },
            status_code=500,
        )

    def retrieval_readiness():
        try:
            return retriever.readiness()
        except (RagError, httpx.TransportError):
            return {'index_ready': False, 'query_encoder_ready': True}

    def require_retrieval():
        state = retriever.readiness()
        if not all(state.values()):
            raise RagError('index_not_ready', 'Retrieval dependencies are not ready')

    @app.get('/health')
    def health():
        state = retrieval_readiness()
        retrieval_ready = all(state.values())
        qa_ready = bool(retrieval_ready and rag is not None and rag.is_ready())
        return JSONResponse(
            {
                **state,
                'retrieval_ready': retrieval_ready,
                'qa_ready': qa_ready,
                'mode': 'qa' if rag is not None else 'retrieval_only',
                'index_id': retriever.index.index_id,
                'build_id': retriever.index.build_id,
            },
            status_code=200 if retrieval_ready else 503,
        )

    @app.post('/retrieve', response_model=RetrievalResult)
    def retrieve(body: RetrieveRequest):
        if body.limit is not None and body.limit > retriever.config.retrieval.limit:
            raise RagError('invalid_limit', f'Limit must be 1..{retriever.config.retrieval.limit}')
        require_retrieval()
        return retriever.retrieve(body.question, body.limit)

    @app.post('/ask', response_model=AskResult)
    def ask(body: AskRequest):
        if rag is None:
            raise RagError('qa_disabled', 'Q&A is disabled in retrieval-only mode')
        if not generation_gate.acquire(blocking=False):
            raise RagError('qa_busy', 'Another Q&A request is running; try again when it finishes')
        try:
            require_retrieval()
            if not rag.is_ready():
                raise RagError('llm_unavailable', 'The local LLM is not ready')
            return rag.ask(body.question).result
        finally:
            generation_gate.release()

    return app
