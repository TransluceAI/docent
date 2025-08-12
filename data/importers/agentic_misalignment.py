import json
import re
import tarfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import parse_chat_message

"""
Docent upload script for Agentic Misalignment data.

Terminology:
- Scenarios: murder, blackmail, leaking
- Goal types: explicit, none, latent, ambiguous, swap
- Urgency types: replacement, restriction, none

Condition format: {scenario}_{goal_type}-{location}_{urgency_type}
Example: blackmail_explicit-america_replacement

Expected .tar.gz file structure:
archive.tar.gz
├── models/
│   ├── {model_name}/
│   │   ├── {condition}/
│   │   │   ├── sample_001/
│   │   │   │   └── response.json
│   │   │   ├── sample_002/
│   │   │   │   └── response.json
│   │   │   └── ...
│   │   └── ...
│   └── ...
└── prompts/
    ├── {condition}/
    │   ├── system_prompt.txt
    │   ├── user_prompt.txt
    │   └── email_content.txt
    └── ...

The load_agent_runs() function now takes a path to a .tar.gz file instead of a directory.
The tar file will be extracted to a temporary directory, processed, and then cleaned up.
"""


def parse_condition(condition: str) -> Dict[str, str]:
    """Parse condition string into components."""
    parts = condition.split("_")
    scenario = parts[0]

    goal_location = parts[1].split("-")
    goal_type = goal_location[0]
    location = goal_location[1]

    urgency_type = parts[2]

    return {
        "scenario": scenario,
        "goal_type": goal_type,
        "location": location,
        "urgency_type": urgency_type,
    }


def extract_sample_number(folder_name: str) -> int:
    """Extract sample number from folder name like 'sample_031'."""
    match = re.search(r"sample_(\d+)", folder_name)
    if match:
        return int(match.group(1))
    return -1


def load_prompts(
    tar_file: tarfile.TarFile, base_path: str, condition: str
) -> Optional[Dict[str, str]]:
    """Load prompts for a given condition from tar file."""
    prompts: Dict[str, str] = {}

    try:
        # Construct paths for prompt files within the tar
        prompt_files = {
            "system_prompt": f"{base_path}prompts/{condition}/system_prompt.txt",
            "user_prompt": f"{base_path}prompts/{condition}/user_prompt.txt",
            "email_content": f"{base_path}prompts/{condition}/email_content.txt",
        }

        # Read each prompt file from tar
        for key, tar_path in prompt_files.items():
            try:
                member = tar_file.getmember(tar_path)
                file_content = tar_file.extractfile(member)
                if file_content is not None:
                    prompts[key] = file_content.read().decode("utf-8").strip()
                else:
                    raise FileNotFoundError(f"Could not extract {tar_path}")
            except KeyError:
                raise FileNotFoundError(f"Prompt file not found in tar: {tar_path}")

        # Combine user prompt with email content as done in the experiment
        prompts["full_user_content"] = prompts["user_prompt"] + "\n\n" + prompts["email_content"]

    except Exception as e:
        print(f"Warning: Could not load prompts for condition {condition}: {e}")
        return None

    return prompts


def discover_archive_structure(
    all_members: List[str],
) -> Tuple[str, Dict[str, Set[str]], List[str]]:
    """Discover the archive structure and return base path, condition mapping, and response file paths."""

    # Find base path by looking for models/ and prompts/ directories
    base_path = ""
    models_found = False
    prompts_found = False

    # Check if models/ and prompts/ are at root level
    for member_name in all_members:
        if member_name == "models/" or member_name.startswith("models/"):
            models_found = True
        if member_name == "prompts/" or member_name.startswith("prompts/"):
            prompts_found = True

    # If not at root, look for them in subdirectories
    if not (models_found and prompts_found):
        # Find potential base directories
        potential_bases: Set[str] = set()
        for member_name in all_members:
            parts = member_name.split("/")
            if len(parts) >= 2:
                if parts[1] in ["models", "prompts"]:
                    potential_bases.add(parts[0] + "/")

        # Check each potential base
        for potential_base in potential_bases:
            models_check = any(name.startswith(f"{potential_base}models/") for name in all_members)
            prompts_check = any(
                name.startswith(f"{potential_base}prompts/") for name in all_members
            )
            if models_check and prompts_check:
                base_path = potential_base
                break

    if not any(name.startswith(f"{base_path}models/") for name in all_members) or not any(
        name.startswith(f"{base_path}prompts/") for name in all_members
    ):
        raise ValueError("Could not find models/ and prompts/ directories in tar file")

    # Build structured mapping of all conditions
    models_prefix = f"{base_path}models/"
    conditions_by_model: Dict[str, Set[str]] = {}
    response_files: List[str] = []

    for member_name in all_members:
        if member_name.startswith(models_prefix) and member_name.endswith("/response.json"):
            # Extract path components: models/{model}/{condition}/{sample}/response.json
            relative_path = member_name[len(models_prefix) :]
            path_parts = relative_path.split("/")

            if len(path_parts) >= 3:  # model/condition/sample/response.json
                model_name = path_parts[0]
                condition_name = path_parts[1]
                sample_name = path_parts[2]

                if sample_name.startswith("sample_"):
                    if model_name not in conditions_by_model:
                        conditions_by_model[model_name] = set()
                    conditions_by_model[model_name].add(condition_name)
                    response_files.append(member_name)

    return base_path, conditions_by_model, response_files


def load_all_prompts(
    tar_file: tarfile.TarFile, base_path: str, all_conditions: Set[str]
) -> Dict[str, Dict[str, str]]:
    """Pre-load all prompts for all conditions."""
    prompts_cache: Dict[str, Dict[str, str]] = {}

    print(f"Pre-loading prompts for {len(all_conditions)} conditions...")

    for condition in all_conditions:
        prompts = load_prompts(tar_file, base_path, condition)
        if prompts is not None:
            prompts_cache[condition] = prompts

    print(f"Successfully loaded prompts for {len(prompts_cache)} conditions")
    return prompts_cache


async def load_agent_runs(tar_path: Path) -> Tuple[List[AgentRun], Dict[str, Any]]:
    """Load all agent runs from a .tar.gz file containing models and prompts directories."""

    tar_path = Path(tar_path)
    if not tar_path.exists():
        raise FileNotFoundError(f"Tar file not found: {tar_path}")

    if not tar_path.name.endswith((".tar.gz", ".tgz")):
        raise ValueError(f"Expected .tar.gz or .tgz file, got: {tar_path}")

    with tarfile.open(tar_path, "r:gz") as tar:
        # Phase 1 Optimization: Single pass archive discovery
        print("Discovering archive structure...")
        all_members = tar.getnames()
        base_path, conditions_by_model, response_files = discover_archive_structure(all_members)

        print(f"Found base path: '{base_path}'")
        print(
            f"Found {len(response_files)} response files across {len(conditions_by_model)} models"
        )

        # Phase 1 Optimization: Pre-load all prompts
        all_conditions: Set[str] = set()
        for conditions in conditions_by_model.values():
            all_conditions.update(conditions)

        prompts_cache = load_all_prompts(tar, base_path, all_conditions)

        # Process all response files
        agent_runs: List[AgentRun] = []

        print(f"Processing {len(response_files)} response files...")
        for i, response_path in enumerate(response_files, 1):
            # Extract model, condition, sample from path
            relative_path = response_path[len(f"{base_path}models/") :]
            path_parts = relative_path.split("/")
            _model_name, condition, _sample_id = path_parts

            try:
                # Get prompts for this condition
                if condition not in prompts_cache:
                    print(f"Skipping {response_path} - missing prompts for condition {condition}")
                    continue

                prompts = prompts_cache[condition]
                condition_components = parse_condition(condition)

                # Read response.json from tar
                try:
                    member = tar.getmember(response_path)
                    file_content = tar.extractfile(member)
                    if file_content is not None:
                        data = json.loads(file_content.read().decode("utf-8"))
                    else:
                        print(f"Warning: Could not extract {response_path}")
                        continue
                except KeyError:
                    print(f"Warning: No response.json found at {response_path}")
                    continue

                # Check for required fields and provide helpful error messages
                if "raw_response" not in data:
                    print(f"Warning: Missing 'raw_response' in {response_path}")
                    print(f"Available keys: {list(data.keys())}")
                    continue

                if "metadata" not in data:
                    print(f"Warning: Missing 'metadata' in {response_path}")
                    print(f"Available keys: {list(data.keys())}")
                    continue

                if "classification" not in data:
                    print(f"Warning: Missing 'classification' in {response_path}")
                    print(f"Available keys: {list(data.keys())}")
                    continue

                # Create transcript with actual prompts
                system_message = {"role": "system", "content": prompts["system_prompt"]}
                user_message = {"role": "user", "content": prompts["full_user_content"]}
                assistant_message = {"role": "assistant", "content": data["raw_response"]}

                transcript = Transcript(
                    messages=[
                        parse_chat_message(system_message),
                        parse_chat_message(user_message),
                        parse_chat_message(assistant_message),
                    ]
                )

                # Validate metadata structure
                metadata_obj = data["metadata"]
                classification_obj = data["classification"]

                required_metadata_fields = [
                    "model",
                    "condition",
                    "sample_id",
                    "timestamp",
                    "api_metadata",
                    "inference_time_ms",
                    "canary_string",
                ]

                required_classification_fields = ["harmful_behavior", "classifier_verdict"]

                # Check metadata fields
                missing_metadata = [
                    field for field in required_metadata_fields if field not in metadata_obj
                ]
                if missing_metadata:
                    print(
                        f"Warning: Missing metadata fields in {response_path}: {missing_metadata}"
                    )
                    print(f"Available metadata keys: {list(metadata_obj.keys())}")
                    continue

                # Check classification fields
                missing_classification = [
                    field
                    for field in required_classification_fields
                    if field not in classification_obj
                ]
                if missing_classification:
                    print(
                        f"Warning: Missing classification fields in {response_path}: {missing_classification}"
                    )
                    print(f"Available classification keys: {list(classification_obj.keys())}")
                    continue

                # Create metadata
                metadata = {
                    "model": metadata_obj["model"],
                    "condition": metadata_obj["condition"],
                    "sample_id": metadata_obj["sample_id"],
                    "timestamp": metadata_obj["timestamp"],
                    "api_metadata": metadata_obj["api_metadata"],
                    "inference_time_ms": metadata_obj["inference_time_ms"],
                    "canary_string": metadata_obj["canary_string"],
                    "classification": classification_obj,
                    "scenario": condition_components["scenario"],
                    "goal_type": condition_components["goal_type"],
                    "location": condition_components["location"],
                    "urgency_type": condition_components["urgency_type"],
                    "scores": {
                        "harmful_behavior": classification_obj["harmful_behavior"],
                        "classifier_verdict": classification_obj["classifier_verdict"],
                        "inference_time_ms": metadata_obj["inference_time_ms"],
                        "tokens_used": metadata_obj["api_metadata"].get("tokens_used", 0),
                    },
                }

                # Create agent run
                agent_run = AgentRun(transcripts={"default": transcript}, metadata=metadata)
                agent_runs.append(agent_run)

                # Progress indicator
                if i % 100 == 0 or i == len(response_files):
                    print(
                        f"  Processed {i}/{len(response_files)} files ({len(agent_runs)} successful)"
                    )

            except Exception as e:
                print(f"Error processing {response_path}: {e}")
                continue

        print(f"Processing complete: {len(agent_runs)} agent runs successfully loaded")

        # Generate summary statistics
        models: Set[str] = set(run.metadata["model"] for run in agent_runs)
        scenarios: Set[str] = set(run.metadata["scenario"] for run in agent_runs)
        goal_types: Set[str] = set(run.metadata["goal_type"] for run in agent_runs)
        urgency_types: Set[str] = set(run.metadata["urgency_type"] for run in agent_runs)

        file_info = {
            "type": "tar.gz",
            "source_file": str(tar_path),
            "file_count": len(agent_runs),
            "total_runs": len(agent_runs),
            "models": list(models),
            "scenarios": list(scenarios),
            "goal_types": list(goal_types),
            "urgency_types": list(urgency_types),
            "total_harmful_behaviors": sum(
                1 for run in agent_runs if run.metadata["classification"]["harmful_behavior"]
            ),
        }

        return agent_runs, file_info
