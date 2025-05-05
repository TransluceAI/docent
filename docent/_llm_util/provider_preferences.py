import json
from functools import cached_property
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from docent._llm_util.types import ModelOption


def find_docent_llm_prefs_file() -> str:
    """
    Find the docent_llm_prefs.json file in the project directory. Stops ascending at the project root.
    Raises an error with the list of paths explored if no docent_llm_prefs.json file is found.
    """
    current_dir = Path(__file__).parent.resolve()
    paths_explored: list[str] = []

    while True:
        paths_explored.append(str(current_dir))
        env_file = current_dir / "docent_llm_prefs.json"
        if env_file.is_file():
            return str(env_file)
        if is_project_root(current_dir):
            break
        if current_dir == current_dir.parent:
            break
        current_dir = current_dir.parent

    raise FileNotFoundError(
        f"A docent_llm_prefs.json file is required to use docent, but none was found. (Check the README for instructions on how to create one.) Paths explored: {', '.join(paths_explored)}"
    )


def is_project_root(directory: Path):
    return (directory / ".root").exists()


class ProviderPreferences(BaseModel):
    _preferences: dict[str, list[ModelOption]]

    def __init__(self, preferences: dict[str, Any]):
        super().__init__()
        self._preferences = {
            function_name: [
                ModelOption.model_validate(raw_option) for raw_option in raw_dict["model_options"]
            ]
            for function_name, raw_dict in preferences.items()
        }

    @cached_property
    def handle_ta_message(self) -> list[ModelOption]:
        return self._preferences["handle_ta_message"]

    @cached_property
    def rewrite_search_query(self) -> list[ModelOption]:
        return self._preferences["rewrite_search_query"]

    @cached_property
    def generate_new_queries(self) -> list[ModelOption]:
        return self._preferences["generate_new_queries"]

    @cached_property
    def diff_transcripts(self) -> list[ModelOption]:
        return self._preferences["diff_transcripts"]

    @cached_property
    def compare_transcripts(self) -> list[ModelOption]:
        return self._preferences["compare_transcripts"]

    @cached_property
    def summarize_intended_solution(self) -> list[ModelOption]:
        return self._preferences["summarize_intended_solution"]

    @cached_property
    def summarize_agent_actions(self) -> list[ModelOption]:
        return self._preferences["summarize_agent_actions"]

    @cached_property
    def group_actions_into_high_level_steps(self) -> list[ModelOption]:
        return self._preferences["group_actions_into_high_level_steps"]

    @cached_property
    def interesting_agent_observations(self) -> list[ModelOption]:
        return self._preferences["interesting_agent_observations"]

    @cached_property
    def describe_insertion_intervention(self) -> list[ModelOption]:
        return self._preferences["describe_insertion_intervention"]

    @cached_property
    def describe_replacement_intervention(self) -> list[ModelOption]:
        return self._preferences["describe_replacement_intervention"]

    @cached_property
    def propose_clusters(self) -> list[ModelOption]:
        return self._preferences["propose_clusters"]

    @cached_property
    def extract_attributes(self) -> list[ModelOption]:
        return self._preferences["extract_attributes"]

    @cached_property
    def cluster_assign_o3_mini(self) -> list[ModelOption]:
        return self._preferences["cluster_assign_o3-mini"]

    @cached_property
    def cluster_assign_sonnet_37_thinking(self) -> list[ModelOption]:
        return self._preferences["cluster_assign_sonnet-37-thinking"]


# Load preferences
prefs_file = find_docent_llm_prefs_file()
with open(prefs_file, "r") as f:
    prefs: dict[str, Any] = json.load(f)
PROVIDER_PREFERENCES = ProviderPreferences(prefs)
