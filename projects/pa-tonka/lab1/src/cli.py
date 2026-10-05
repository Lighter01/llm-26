import argparse
from pathlib import Path
from statistics import fmean, stdev

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from client import CompletionResult
from globals import DEFAULT_PROMPTS_DIR

#====================================================#
#=================== CLI arguments ==================#

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run llama.cpp experiments for one GGUF model."
    )

    parser.add_argument(
        "--model",
        type=Path,
        required=True,
        help="Path to the GGUF model.",
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Human-readable model name used in result files.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="Number of repetitions for every prompt/mode pair.",
    )
    parser.add_argument(
        "--base-seed",
        type=int,
        default=42,
        help="Seed used for the first repetition.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=(
            "Result directory. "
            "Defaults to results/<model-name>."
        ),
    )
    parser.add_argument(
        "--prompts-dir",
        type=Path,
        default=DEFAULT_PROMPTS_DIR,
        help="Directory containing experiment prompts.",
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=9931,
    )
    parser.add_argument(
        "--context-size",
        type=int,
        default=4096,
    )

    parser.add_argument(
        "--server-command",
        default="llama serve",
        help=(
            "Command used to start llama.cpp server. "
            'Example: "llama serve".'
        ),
    )

    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite previous results in the output directory.",
    )

    args = parser.parse_args()

    if args.repeats <= 0:
        parser.error("--repeats must be greater than zero")

    return args


#====================================================#
#==================== Rich output ===================#

console = Console()

def create_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        TextColumn("[dim]{task.fields[status]}[/dim]"),
        console=console,
        expand=True,
    )

def format_mean_std(
    values: list[float],
    unit: str,
) -> str:
    if not values:
        return "n/a"

    mean = fmean(values)

    if len(values) == 1:
        return f"{mean:.1f} {unit}"

    std = stdev(values)

    return f"{mean:.1f} ± {std:.1f} {unit}"


def make_mode_summary(
    prompt_id: str,
    mode_name: str,
    results: list[CompletionResult],
) -> Table:
    ttft_values = [
        result.ttft_ms
        for result in results
        if result.ttft_ms is not None
    ]

    wall_values = [
        result.wall_time_ms
        for result in results
    ]

    generation_values = [
        value
        for result in results
        if (
            value := result.timings.get(
                "predicted_per_second"
            )
        ) is not None
    ]

    output_token_values = [
        value
        for result in results
        if (
            value := result.usage.get(
                "completion_tokens"
            )
        ) is not None
    ]

    table = Table.grid(
        padding=(0, 2),
    )

    table.add_column(
        style="bold cyan",
        no_wrap=True,
    )
    table.add_column()
    table.add_column()
    table.add_column()
    table.add_column()

    table.add_row(
        f"{prompt_id} / {mode_name}",
        f"TTFT {format_mean_std(ttft_values, 'ms')}",
        f"Wall {format_mean_std(wall_values, 'ms')}",
        f"Gen {format_mean_std(generation_values, 'tok/s')}",
        f"Out {format_mean_std(output_token_values, 'tok')}",
    )

    return table