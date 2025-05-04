import json
from functools import cached_property
from pathlib import Path
from typing import Any

from docent._llm_util.types import ModelCallParams
from pydantic import BaseModel


def find_docent_llm_prefs_file():
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


prefs_file = find_docent_llm_prefs_file()
with open(prefs_file, "r") as f:
    prefs: dict[str, Any] = json.load(f)


class CallPreference(BaseModel):
    default_provider: str
    model_call_params: list[ModelCallParams]

    def create_shallow_dict(self) -> dict[str, Any]:
        return {
            "default_provider": self.default_provider,
            "model_call_params": self.model_call_params,
        }


def create_call_preference(call_preference: dict[str, Any]) -> CallPreference:
    """
    Ensures the llm preferences correspond to a valid provider and model category combination
    """
    assert (
        "model_options" in call_preference
    ), "docent_llm_prefs.json must specify model_options for each call"
    used_providers: list[str] = [call["provider"] for call in call_preference["model_options"]]
    default_provider = used_providers[0]
    call_pref = CallPreference(
        default_provider=default_provider,
        model_call_params=[ModelCallParams(**call) for call in call_preference["model_options"]],
    )
    return call_pref


class ProviderPreferences(BaseModel):
    _preferences: dict[str, Any]

    def __init__(self, preferences: dict[str, Any]):
        super().__init__()
        self._preferences = preferences

    @cached_property
    def handle_ta_message(self) -> CallPreference:
        return create_call_preference(self._preferences["handle_ta_message"])

    @cached_property
    def rewrite_search_query(self) -> CallPreference:
        return create_call_preference(self._preferences["rewrite_search_query"])

    @cached_property
    def generate_new_queries(self) -> CallPreference:
        return create_call_preference(self._preferences["generate_new_queries"])

    @cached_property
    def diff_transcripts(self) -> CallPreference:
        return create_call_preference(self._preferences["diff_transcripts"])

    @cached_property
    def compare_transcripts(self) -> CallPreference:
        return create_call_preference(self._preferences["compare_transcripts"])

    @cached_property
    def summarize_intended_solution(self) -> CallPreference:
        return create_call_preference(self._preferences["summarize_intended_solution"])

    @cached_property
    def summarize_agent_actions(self) -> CallPreference:
        return create_call_preference(self._preferences["summarize_agent_actions"])

    @cached_property
    def group_actions_into_high_level_steps(self) -> CallPreference:
        return create_call_preference(self._preferences["group_actions_into_high_level_steps"])

    @cached_property
    def interesting_agent_observations(self) -> CallPreference:
        return create_call_preference(self._preferences["interesting_agent_observations"])

    @cached_property
    def describe_insertion_intervention(self) -> CallPreference:
        return create_call_preference(self._preferences["describe_insertion_intervention"])

    @cached_property
    def describe_replacement_intervention(self) -> CallPreference:
        return create_call_preference(self._preferences["describe_replacement_intervention"])

    @cached_property
    def propose_clusters(self) -> CallPreference:
        return create_call_preference(self._preferences["propose_clusters"])

    @cached_property
    def extract_attributes(self) -> CallPreference:
        return create_call_preference(self._preferences["extract_attributes"])

    @cached_property
    def assignment_model(self) -> str:
        return self._preferences["assignment_model"]

    @cached_property
    def cluster_assignment(self) -> dict[str, CallPreference]:
        return {
            model: create_call_preference(prefs)
            for model, prefs in self._preferences["cluster_assignment"].items()
        }


PROVIDER_PREFERENCES = ProviderPreferences(prefs)
