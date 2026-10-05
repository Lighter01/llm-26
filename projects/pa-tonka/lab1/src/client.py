import json
from collections.abc import Mapping
from dataclasses import dataclass
from time import perf_counter_ns
from typing import Any

from httpx import Client

Message = dict[str, Any]


@dataclass(slots=True)
class CompletionResult:
    text: str
    ttft_ms: float | None
    wall_time_ms: float

    usage: dict[str, Any]
    timings: dict[str, Any]

    finish_reason: str | None
    response_id: str | None


class LlamaClient:
    def __init__(
        self,
        base_url: str,
    ):
        self.client = Client(
            base_url=base_url,
            timeout=None,
        )

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
        return False

    def props(self) -> dict[str, Any]:
        response = self.client.get("/props")
        response.raise_for_status()

        return response.json()

    def count_input_tokens(
        self,
        messages: list[Message],
        *,
        parameters: Mapping[str, Any] | None = None,
    ) -> int:
        payload: dict[str, Any] = {
            "messages": messages,
        }

        if parameters:
            payload.update(parameters)

        response = self.client.post(
            "/v1/chat/completions/input_tokens",
            json=payload,
        )
        response.raise_for_status()

        data = response.json()

        return int(data["input_tokens"])

    def chat_completion(
        self,
        messages: list[Message],
        *,
        seed: int,
        parameters: Mapping[str, Any] | None = None,
    ) -> CompletionResult:
        reserved_parameters = {
            "messages",
            "seed",
            "stream",
            "stream_options",
        }

        if parameters:
            invalid_parameters = reserved_parameters & parameters.keys()

            if invalid_parameters:
                raise ValueError(
                    "The following parameters are controlled by "
                    f"LlamaClient: {sorted(invalid_parameters)}"
                )

        payload: dict[str, Any] = {
            "messages": messages,
            "seed": seed,
            "stream": True,
            "stream_options": {
                "include_usage": True,
            },
        }

        if parameters:
            payload.update(parameters)

        text_parts: list[str] = []

        usage: dict[str, Any] | None = None
        timings: dict[str, Any] | None = None

        finish_reason: str | None = None
        response_id: str | None = None

        started_ns = perf_counter_ns()
        first_content_ns: int | None = None

        with self.client.stream(
            "POST",
            "/v1/chat/completions",
            json=payload,
        ) as response:
            response.raise_for_status()

            for line in response.iter_lines():
                # SSE may contain empty lines separating events.
                if not line:
                    continue

                # SSE comments / keep-alive messages.
                if line.startswith(":"):
                    continue

                if not line.startswith("data:"):
                    continue

                data = line[len("data:"):].lstrip()

                if data == "[DONE]":
                    break

                event = json.loads(data)

                if response_id is None:
                    response_id = event.get("id")

                if event.get("usage") is not None:
                    usage = event["usage"]

                if event.get("timings") is not None:
                    timings = event["timings"]

                for choice in event.get("choices", []):
                    current_finish_reason = choice.get("finish_reason")

                    if current_finish_reason is not None:
                        finish_reason = current_finish_reason

                    delta = choice.get("delta") or {}
                    content = delta.get("content")

                    if not isinstance(content, str) or not content:
                        continue

                    if first_content_ns is None:
                        first_content_ns = perf_counter_ns()

                    text_parts.append(content)

        finished_ns = perf_counter_ns()

        if usage is None:
            raise RuntimeError(
                "Streaming response did not contain usage statistics"
            )

        if timings is None:
            raise RuntimeError(
                "Streaming response did not contain llama.cpp timings"
            )

        ttft_ms = None

        if first_content_ns is not None:
            ttft_ms = (first_content_ns - started_ns) / 1_000_000

        wall_time_ms = (
            finished_ns - started_ns
        ) / 1_000_000

        return CompletionResult(
            text="".join(text_parts),
            ttft_ms=ttft_ms,
            wall_time_ms=wall_time_ms,
            usage=usage,
            timings=timings,
            finish_reason=finish_reason,
            response_id=response_id,
        )


if __name__ == "__main__":
    ...