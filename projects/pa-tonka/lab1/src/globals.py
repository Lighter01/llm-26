from pathlib import Path

#====================================================#
#================= Global Variables =================#

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_PROMPTS_DIR = PROJECT_ROOT / "prompts"
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "results"


PROMPT_FILES = {
    "p1_generation": "p1_generation.md",
    "p2_classification": "p2_classification.md",
    "p3_summary": "p3_summary.md",
}


# These parameters apply to every measured request and are not
# considered part of the baseline/tuned sampling comparison.
# COMMON_REQUEST_PARAMETERS = {
#     "cache_prompt": False,
# }


EXPERIMENT_MODES = {
    "baseline": {},

    "conservative": {
        "temperature": 0.2,
        "top_p": 0.8,
    },

    "top_k_focused": {
        "temperature": 0.5,
        "top_k": 20,
    },

    "creative": {
        "temperature": 1.1,
        "top_p": 0.98,
    },
}