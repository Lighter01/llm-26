import json
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.panel import Panel

from cli import console, create_progress, make_mode_summary, parse_args
from client import CompletionResult, LlamaClient
from globals import DEFAULT_RESULTS_DIR, EXPERIMENT_MODES, PROMPT_FILES
from server import LlamaServer

#=============================================#
#================== Helpers ==================#

def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def load_prompts(
    prompts_dir: Path,
) -> dict[str, dict[str, Any]]:
    prompts: dict[str, dict[str, Any]] = {}

    for prompt_id, filename in PROMPT_FILES.items():
        path = prompts_dir / filename

        if not path.is_file():
            raise FileNotFoundError(
                f"Prompt file does not exist: {path}"
            )

        content = path.read_text(encoding="utf-8")

        if not content.strip():
            raise ValueError(
                f"Prompt file is empty: {path}"
            )

        prompts[prompt_id] = {
            "path": path,
            "content": content,
        }

    return prompts


def make_messages(prompt: str) -> list[dict[str, str]]:
    return [
        {
            "role": "user",
            "content": prompt,
        }
    ]


def write_json(
    path: Path,
    value: Any,
) -> None:
    with path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            value,
            file,
            ensure_ascii=False,
            indent=2,
        )


def append_jsonl(
    path: Path,
    value: Any,
) -> None:
    with path.open(
        "a",
        encoding="utf-8",
    ) as file:
        file.write(
            json.dumps(
                value,
                ensure_ascii=False,
            )
        )
        file.write("\n")


def prepare_output_directory(
    output_dir: Path,
    *,
    overwrite: bool,
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    metadata_path = output_dir / "metadata.json"
    runs_path = output_dir / "runs.jsonl"
    log_path = output_dir / "server.log"

    existing = [
        path
        for path in (
            metadata_path,
            runs_path,
            log_path,
        )
        if path.exists()
    ]

    if existing and not overwrite:
        existing_files = ", ".join(
            str(path)
            for path in existing
        )

        raise FileExistsError(
            "Output files already exist. "
            "Use --overwrite to replace them: "
            f"{existing_files}"
        )

    if overwrite:
        for path in (
            metadata_path,
            runs_path,
            log_path,
        ):
            if path.exists():
                path.unlink()

    return metadata_path, runs_path, log_path


def run_warmup(
    client: LlamaClient,
    *,
    seed: int,
) -> None:
    client.chat_completion(
        messages=[
            {
                "role": "user",
                "content": "Ответь одним словом: готов.",
            }
        ],
        seed=seed,
        parameters={
            # "cache_prompt": False,
            "max_tokens": 8,
        },
    )


def create_run_record(
    *,
    model_name: str,
    prompt_id: str,
    mode: str,
    repetition: int,
    seed: int,
    parameters: dict[str, Any],
    result: CompletionResult,
) -> dict[str, Any]:
    prompt_tokens = result.usage.get(
        "prompt_tokens"
    )

    completion_tokens = result.usage.get(
        "completion_tokens"
    )

    total_tokens = result.usage.get(
        "total_tokens"
    )

    prompt_token_details = (
        result.usage.get("prompt_tokens_details")
        or {}
    )

    return {
        "model": model_name,
        "prompt": prompt_id,
        "mode": mode,
        "repetition": repetition,
        "seed": seed,

        "request_parameters": parameters,

        "response": {
            "text": result.text,
            "finish_reason": result.finish_reason,
            "response_id": result.response_id,
        },

        "metrics": {
            "ttft_ms": result.ttft_ms,
            "wall_time_ms": result.wall_time_ms,

            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,

            "cached_prompt_tokens": (
                prompt_token_details.get(
                    "cached_tokens"
                )
            ),

            "cache_n": (
                result.timings.get("cache_n")
            ),

            "prompt_ms": (
                result.timings.get("prompt_ms")
            ),
            "prompt_tokens_per_second": (
                result.timings.get(
                    "prompt_per_second"
                )
            ),

            "generation_ms": (
                result.timings.get(
                    "predicted_ms"
                )
            ),
            "generation_tokens_per_second": (
                result.timings.get(
                    "predicted_per_second"
                )
            ),
        },

        # Keep the original server-provided values as well.
        "usage": result.usage,
        "timings": result.timings,
    }


def check_cache_not_reused(
    result: CompletionResult,
) -> None:
    cache_n = result.timings.get("cache_n")

    if cache_n not in (None, 0):
        raise RuntimeError(
            "Prompt cache was unexpectedly reused: "
            f"cache_n={cache_n}"
        )

    prompt_token_details = (
        result.usage.get("prompt_tokens_details")
        or {}
    )

    cached_tokens = prompt_token_details.get(
        "cached_tokens"
    )

    if cached_tokens not in (None, 0):
        raise RuntimeError(
            "Prompt cache was unexpectedly reused: "
            f"cached_tokens={cached_tokens}"
        )


#===========================================================#
#================== Main Experiment Logic ==================#

def main() -> None:
    args = parse_args()

    model_path = args.model.expanduser().resolve()

    if not model_path.is_file():
        raise FileNotFoundError(
            f"Model does not exist: {model_path}"
        )

    prompts_dir = (
        args.prompts_dir
        .expanduser()
        .resolve()
    )

    prompts = load_prompts(prompts_dir)

    output_dir = (
        args.output.expanduser().resolve()
        if args.output is not None
        else DEFAULT_RESULTS_DIR / args.name
    )

    (
        metadata_path,
        runs_path,
        log_path,
    ) = prepare_output_directory(
        output_dir,
        overwrite=args.overwrite,
    )

    server_command = tuple(
        shlex.split(args.server_command)
    )

    base_url = (
        f"http://{args.host}:{args.port}"
    )

    modes = EXPERIMENT_MODES

    server = LlamaServer(
        model_path=model_path,
        command=server_command,
        host=args.host,
        port=args.port,
        context_size=args.context_size,
        log_path=log_path,
    )

    metadata: dict[str, Any] = {
        "created_at": utc_now(),
        "status": "initializing",

        "model": {
            "name": args.name,
            "path": str(model_path),
        },

        "experiment": {
            "context_size": args.context_size,
            "repeats": args.repeats,
            "base_seed": args.base_seed,

            # "common_request_parameters": (
            #     COMMON_REQUEST_PARAMETERS
            # ),
            "modes": modes,
        },

        "server": {
            "command": list(server_command),
            "host": args.host,
            "port": args.port,
        },

        "prompts": {},
    }

    write_json(
        metadata_path,
        metadata,
    )

    try:
        with server, LlamaClient(
            base_url=base_url
        ) as client:

            # -------------------------
            # Server/model metadata
            # -------------------------

            props = client.props()

            metadata["server"]["props"] = props

            # Count model-specific input tokens for
            # every prompt before the experiment.
            for (
                prompt_id,
                prompt_data,
            ) in prompts.items():

                content = prompt_data["content"]
                messages = make_messages(content)

                input_tokens = (
                    client.count_input_tokens(
                        messages
                    )
                )

                if (
                    input_tokens
                    >= args.context_size
                ):
                    raise ValueError(
                        f"{prompt_id} contains "
                        f"{input_tokens} input tokens, "
                        "which does not fit into "
                        f"context size "
                        f"{args.context_size}"
                    )

                metadata["prompts"][prompt_id] = {
                    "file": str(
                        prompt_data["path"]
                    ),
                    "content": content,
                    "input_tokens": input_tokens,
                }

            metadata["status"] = "running"

            write_json(
                metadata_path,
                metadata,
            )

            # -------------------------
            # Application-level warm-up
            # -------------------------

            # --- rich console output ---------------------
            with console.status(
                f"[bold yellow]Warming up {args.name}..."
            ):
                run_warmup(
                    client,
                    seed=args.base_seed,
                )

            console.print(
                "[green]✓[/green] Warm-up complete"
            )
            # ---------------------------------------------

            # Забыл удалить, но эксперименты уже прогнал
            run_warmup(
                client,
                seed=args.base_seed,
            )

            # -------------------------
            # Measured experiment
            # -------------------------

            total_runs = (
                len(prompts)
                * len(modes)
                * args.repeats
            )

            # --- rich console output----------------------
            console.print(
                Panel.fit(
                    (
                        f"[bold]{args.name}[/bold]\n"
                        f"Prompts: {len(prompts)}\n"
                        f"Modes: {len(modes)}\n"
                        f"Repeats: {args.repeats}\n"
                        f"Total requests: {total_runs}"
                    ),
                    title="LLM experiment",
                    border_style="cyan",
                )
            )
            # ---------------------------------------------

            with create_progress() as progress:
                # --- rich console output ---------------------
                overall_task = progress.add_task(
                    "[cyan]Overall",
                    total=total_runs,
                    status="starting",
                )

                repetition_task = progress.add_task(
                    "[green]Current",
                    total=args.repeats,
                    status="waiting",
                )
                # ---------------------------------------------

                for (
                    prompt_id,
                    prompt_data,
                ) in prompts.items():

                    messages = make_messages(
                        prompt_data["content"]
                    )

                    for (
                        mode_name,
                        mode_parameters,
                    ) in modes.items():

                        # --- rich console output ---------------------
                        progress.reset(
                            repetition_task,
                            total=args.repeats,
                            description=(
                                f"[green]{prompt_id} / {mode_name}"
                            ),
                            status="starting",
                        )

                        progress.update(
                            overall_task,
                            status=f"{prompt_id} / {mode_name}",
                        )

                        mode_results: list[CompletionResult] = []
                        # ---------------------------------------------

                        for repetition_index in range(
                            args.repeats
                        ):
                            seed = (
                                args.base_seed
                                + repetition_index
                            )

                            # Common technical settings +
                            # experimental sampling settings.
                            parameters = {
                                # **COMMON_REQUEST_PARAMETERS,
                                **mode_parameters,
                            }

                            # --- rich console output ---------------------
                            progress.update(
                                repetition_task,
                                status=f"seed={seed}",
                            )
                            # ---------------------------------------------

                            result = (
                                client.chat_completion(
                                    messages=messages,
                                    seed=seed,
                                    parameters=parameters,
                                )
                            )

                            check_cache_not_reused(
                                result
                            )

                            record = create_run_record(
                                model_name=args.name,
                                prompt_id=prompt_id,
                                mode=mode_name,
                                repetition=(
                                    repetition_index + 1
                                ),
                                seed=seed,
                                parameters=parameters,
                                result=result,
                            )

                            # Append immediately so already
                            # completed runs survive a later
                            # failure/interruption.
                            append_jsonl(
                                runs_path,
                                record,
                            )

                            generation_speed = (
                                result.timings.get(
                                    "predicted_per_second"
                                )
                            )

                            # --- rich console output ---------------------
                            mode_results.append(result)

                            ttft_text = (
                                f"{result.ttft_ms:.1f} ms"
                                if result.ttft_ms is not None
                                else "n/a"
                            )

                            generation_text = (
                                f"{generation_speed:.1f} tok/s"
                                if generation_speed is not None
                                else "n/a"
                            )

                            progress.advance(
                                repetition_task
                            )

                            progress.advance(
                                overall_task
                            )

                            progress.update(
                                repetition_task,
                                status=(
                                    f"seed={seed} · "
                                    f"TTFT {ttft_text} · "
                                    f"gen {generation_text}"
                                ),
                            )
                            # ---------------------------------------------

                        # --- rich console output ---------------------
                        progress.console.print(
                            make_mode_summary(
                                prompt_id,
                                mode_name,
                                mode_results,
                            )
                        )
                        # ---------------------------------------------


        metadata["status"] = "completed"
        metadata["finished_at"] = utc_now()

        write_json(
            metadata_path,
            metadata,
        )
        
        # --- rich console output ---------------------
        console.print()

        console.print(
            Panel.fit(
                (
                    "[bold green]Experiment completed[/bold green]\n"
                    f"[dim]{output_dir}[/dim]"
                ),
                border_style="green",
            )
        )
        # ---------------------------------------------

    except BaseException as error:
        metadata["status"] = "failed"
        metadata["finished_at"] = utc_now()
        metadata["error"] = repr(error)

        write_json(
            metadata_path,
            metadata,
        )

        # --- rich console output ---------------------
        console.print(
            Panel.fit(
                (
                    "[bold red]Experiment failed[/bold red]\n"
                    f"{error!r}"
                ),
                border_style="red",
            )
        )
        # ---------------------------------------------

        raise


#==========================================#
#================== Main ==================#

if __name__ == "__main__":
    main()