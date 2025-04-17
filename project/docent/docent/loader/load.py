"""
This file is imported and invoked by `docent.server.main`.
On server boot, all data is loaded into memory.
"""

from docent.loader.load_custom import load_custom
from docent.loader.load_inspect import (
    load_agentharm,
    load_cybench,
    load_frontier_math,
    load_k8s,
    load_picoctf_4o,
    load_picoctf_36,
)
from docent.loader.load_oh_swe_bench import load_oh_swe_bench
from docent.loader.load_tau_bench import load_tau_bench
from env_util import ENV
from frames.transcript import Transcript

EVALS_SPECS_DICT = {
    "prod": {
        "picoCTF": load_picoctf_4o,
        "picoCTFSonnet": load_picoctf_36,
        "agentharm": load_agentharm,
        "cybench": load_cybench,
        "tau_bench_airline": load_tau_bench,
    },
    "dev": {
        "picoCTF": load_picoctf_36,
    },
    "asa": {
        "k8s": load_k8s,
    },
    "swe": {
        "swe-bench": load_oh_swe_bench,
    },
    "frontier-math": {
        "frontier-math": load_frontier_math,
    },
    "custom": {"your_custom_eval": load_custom},
}

# Use ENV.ENV_TYPE to determine which EVALS_SPECS_DICT to use
EVALS_SPECS = EVALS_SPECS_DICT[ENV.ENV_TYPE or "prod"]

# Load all transcripts
EVALS: dict[str, list[Transcript]] = {}
for eval_id, load_fn in EVALS_SPECS.items():
    EVALS[eval_id] = load_fn()
