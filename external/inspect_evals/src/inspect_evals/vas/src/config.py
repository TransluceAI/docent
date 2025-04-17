from pathlib import Path


CP_ROOT = Path(
    "/home/ubuntu/clarity/external/inspect_evals/src/inspect_evals/vas/cp_root"
)  # Path(os.environ.get("CP_ROOT", "./cp_root"))
CRS_SCRATCH_SPACE = Path(
    "/home/ubuntu/clarity/external/inspect_evals/src/inspect_evals/vas/crs_scratch"
)  # Path(os.environ.get("CRS_SCRATCH_SPACE", "./crs_scratch"))
PROJECT_PATH = CRS_SCRATCH_SPACE / CP_ROOT.name
OUTPUT_PATH = Path(CRS_SCRATCH_SPACE) / "crs_output"
