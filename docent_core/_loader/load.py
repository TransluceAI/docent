from docent_core._loader.load_custom import load_custom
from docent_core._loader.load_epoch import load_epoch_aime, load_epoch_swebench
from docent_core._loader.load_inspect import (
    load_agentharm,
    load_cybench,
    load_frontier_math,
    load_k8s,
    load_picoctf_4o,
    load_picoctf_36,
    load_swebench,
)
from docent_core._loader.load_oh_swe_bench import load_oh_swe_bench
from docent_core._loader.load_tau_bench import load_tau_bench

EVALS_SPECS_DICT = {
    "prod": {
        "picoCTF": load_picoctf_4o,
        "picoCTFSonnet": load_picoctf_36,
        "agentharm": load_agentharm,
        "cybench": load_cybench,
        "tau_bench_airline": load_tau_bench,
    },
    "dev": {
        "picoCTF": load_picoctf_4o,
        "picoCTFSonnet": load_picoctf_36,
    },
    "swe-bench": {
        "swebench-sonnet-37": load_swebench,
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
    "epoch-aime": {
        "epoch-aime": load_epoch_aime,
    },
    "epoch-swebench": {
        "epoch-swebench": load_epoch_swebench,
    },
    "custom": {"your_custom_eval": load_custom},
}
