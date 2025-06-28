import os


def get_inspect_fpath():
    return os.path.join(os.path.dirname(__file__), "log.eval")


def get_tau_bench_airline_fpath():
    return os.path.join(os.path.dirname(__file__), "tb_airline.json")
