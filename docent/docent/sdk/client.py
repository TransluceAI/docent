import gzip
import json
import os
import time
import webbrowser
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal, TypeVar, cast

import pandas as pd
import requests
from pydantic_core import to_jsonable_python
from tqdm import tqdm

from docent._log_util.logger import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.judge import Label
from docent.judges.util.meta_schema import validate_judge_result_schema
from docent.loaders import load_inspect
from docent.sdk.llm_context import LLMContext, LLMContextItem

MAX_AGENT_RUN_PAYLOAD_BYTES = 100 * 1024 * 1024  # 100MB backend limit
_AGENT_RUNS_PAYLOAD_PREFIX = b'{"agent_runs":['
_AGENT_RUNS_PAYLOAD_SUFFIX = b"]}"


_T = TypeVar("_T")


def batched(iterable: Iterable[_T], n: int) -> Iterator[tuple[_T, ...]]:
    """Backport of itertools.batched for Python <3.12."""
    if n < 1:
        raise ValueError("n must be at least one")
    it = iter(iterable)
    while batch := tuple(islice(it, n)):
        yield batch


def _serialize_agent_run(agent_run: AgentRun) -> bytes:
    """Serialize an AgentRun to compact JSON bytes."""
    return json.dumps(to_jsonable_python(agent_run), separators=(",", ":")).encode("utf-8")


def _build_agent_runs_payload(serialized_runs: list[bytes]) -> bytes:
    """Wrap serialized individual runs into the API payload envelope."""
    body = b",".join(serialized_runs)
    return _AGENT_RUNS_PAYLOAD_PREFIX + body + _AGENT_RUNS_PAYLOAD_SUFFIX


def _yield_agent_run_batches_by_size(
    agent_runs: list[AgentRun], max_payload_bytes: int
) -> Iterator[tuple[int, bytes]]:
    """Yield batches of agent runs whose serialized payloads stay within max_payload_bytes."""
    envelope_len = len(_AGENT_RUNS_PAYLOAD_PREFIX) + len(_AGENT_RUNS_PAYLOAD_SUFFIX)
    comma_len = 1

    current_serialized: list[bytes] = []
    current_size = envelope_len

    for agent_run in agent_runs:
        serialized = _serialize_agent_run(agent_run)
        serialized_len = len(serialized)

        if envelope_len + serialized_len > max_payload_bytes:
            raise ValueError(
                f"A single agent run (id={agent_run.id}) exceeds the maximum payload size of "
                f"{max_payload_bytes} bytes. Reduce the size of that run before uploading."
            )

        delimiter = 0 if not current_serialized else comma_len
        projected_size = current_size + delimiter + serialized_len

        # If adding the next run would exceed the max payload size, yield the current batch
        if current_serialized and projected_size > max_payload_bytes:
            yield len(current_serialized), _build_agent_runs_payload(current_serialized)

            # Add the "next run" as the first run in the next batch
            current_serialized = [serialized]
            current_size = envelope_len + serialized_len
        # Otherwise, add to the current batch and continue
        else:
            current_serialized.append(serialized)
            current_size = projected_size

    if current_serialized:
        yield len(current_serialized), _build_agent_runs_payload(current_serialized)


logger = get_logger(__name__)


class Docent:
    """Client for interacting with the Docent API.

    This client provides methods for creating and managing Collections,
    dimensions, agent runs, and filters in the Docent system. It handles
    authentication via API keys and provides a high-level interface for
    logging, querying, and analyzing agent traces.

    Example:
        >>> from docent import Docent
        >>> client = Docent(api_key="your-api-key")
        >>> collection_id = client.create_collection(name="My Collection")
    """

    def __init__(
        self,
        *,
        domain: str = "docent.transluce.org",
        use_https: bool = True,
        api_key: str | None = None,
        # Deprecated
        server_url: str | None = None,  # Use domain instead
        web_url: str | None = None,  # Use domain instead
    ):
        """Initialize the Docent client.

        Args:
            domain: The domain of the Docent instance. Defaults to "docent.transluce.org".
                The API and web URLs will be constructed from this domain automatically.
            api_key: API key for authentication. If not provided, will attempt to read
                from the DOCENT_API_KEY environment variable.
            server_url: (Deprecated) Direct URL of the Docent API server. Use `domain` instead.
            web_url: (Deprecated) Direct URL of the Docent web UI. Use `domain` instead.

        Raises:
            ValueError: If no API key is provided and DOCENT_API_KEY is not set.

        Example:
            >>> client = Docent(domain="my-instance.docent.com", api_key="sk-...")
        """
        # Warn about deprecated parameters
        if server_url is not None:
            logger.warning(
                "The 'server_url' parameter is deprecated and will be removed in a future version. "
                "Please use 'domain' instead."
            )
        if web_url is not None:
            logger.warning(
                "The 'web_url' parameter is deprecated and will be removed in a future version. "
                "Please use 'domain' instead."
            )

        self._domain = domain

        # Set server URL; server_url takes precedence over domain
        prefix = "https://" if use_https else "http://"
        server_url = (server_url or f"{prefix}api.{domain}").rstrip("/")
        if not server_url.endswith("/rest"):
            server_url = f"{server_url}/rest"
        self._server_url = server_url

        # Set web URL; web_url takes precedence over domain
        self._web_url = (web_url or f"{prefix}{domain}").rstrip("/")

        # Use requests.Session for connection pooling and persistent headers
        self._session = requests.Session()

        api_key = api_key or os.getenv("DOCENT_API_KEY")

        if api_key is None:
            raise ValueError(
                "api_key is required. Please provide an "
                "api_key or set the DOCENT_API_KEY environment variable."
            )

        self._login(api_key)

    def _handle_response_errors(self, response: requests.Response):
        """Handle API response and raise informative errors."""
        status_code = cast(int | None, response.status_code)
        if status_code is not None and status_code >= 400:
            try:
                error_data = response.json()
                detail = error_data.get("detail", response.text)
            except Exception:
                detail = response.text

            raise requests.HTTPError(f"HTTP {response.status_code}: {detail}", response=response)

    def _login(self, api_key: str):
        """Login with email/password to establish session."""
        self._session.headers.update({"Authorization": f"Bearer {api_key}"})

        url = f"{self._server_url}/api-keys/test"
        response = self._session.get(url)
        self._handle_response_errors(response)

        logger.info("Logged in with API key")
        return

    def create_collection(
        self,
        collection_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> str:
        """Creates a new Collection.

        Creates a new Collection and sets up a default MECE dimension
        for grouping on the homepage.

        Args:
            collection_id: Optional ID for the new Collection. If not provided, one will be generated.
            name: Optional name for the Collection.
            description: Optional description for the Collection.

        Returns:
            str: The ID of the created Collection.

        Raises:
            ValueError: If the response is missing the Collection ID.
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/create"
        payload = {
            "collection_id": collection_id,
            "name": name,
            "description": description,
        }

        response = self._session.post(url, json=payload)
        self._handle_response_errors(response)

        response_data = response.json()
        collection_id = response_data.get("collection_id")
        if collection_id is None:
            raise ValueError("Failed to create collection: 'collection_id' missing in response.")

        logger.info(f"Successfully created Collection with id='{collection_id}'")

        logger.info(
            f"Collection creation complete. Frontend available at: {self._web_url}/dashboard/{collection_id}"
        )
        return collection_id

    def update_collection(
        self,
        collection_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Updates a Collection's name and/or description.

        Requires WRITE permission on the collection.

        Args:
            collection_id: ID of the Collection to update.
            name: New name for the Collection. If None, the name will be cleared.
            description: New description for the Collection. If None, the description will be cleared.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/{collection_id}/collection"
        payload: dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description

        response = self._session.put(url, json=payload)
        self._handle_response_errors(response)

        logger.info(f"Successfully updated Collection '{collection_id}'")

    def add_agent_runs(
        self,
        collection_id: str,
        agent_runs: list[AgentRun],
        *,
        compression: Literal["gzip", "none"] = "gzip",
        wait: bool = True,
        poll_interval: float = 1.0,
        # Deprecated
        batch_size: int | None = None,
    ) -> dict[str, Any]:
        """Adds agent runs to a Collection.

        Agent runs represent execution traces that can be visualized and analyzed.
        Requests are automatically chunked to stay under the backend's payload limit.

        Args:
            collection_id: ID of the Collection.
            agent_runs: List of AgentRun objects to add.
            compression: Compression algorithm for request bodies. Defaults to gzip.
                Set to "none" to retain legacy behavior.
            wait: If True (default), wait for all ingestion jobs to complete before returning.
                If False, return immediately after enqueuing jobs.
            poll_interval: Seconds between status checks when wait=True. Defaults to 1.0.

        Returns:
            dict: API response data containing:
                - status: "success" if all jobs completed, "enqueued" if wait=False
                - total_runs_added: Number of agent runs submitted
                - job_ids: List of job IDs for tracking

        Raises:
            ValueError: If any single agent run exceeds the maximum payload size.
            requests.exceptions.HTTPError: If the API request fails.
            RuntimeError: If any job fails during processing (when wait=True).
        """

        if batch_size is not None:
            logger.warning(
                "The 'batch_size' parameter is deprecated and will be removed in a future version. "
                "We have transitioned to a new batching strategy based on the size of the payload."
            )

        url = f"{self._server_url}/{collection_id}/agent_runs"
        total_runs = len(agent_runs)
        job_ids: list[str] = []

        # Process agent runs in batches
        desc = f"Uploading agent runs (compression={compression})"
        with tqdm(total=total_runs, desc=desc, unit="runs") as pbar:
            for batch_size, payload_bytes in _yield_agent_run_batches_by_size(
                agent_runs, MAX_AGENT_RUN_PAYLOAD_BYTES
            ):
                request_kwargs: dict[str, Any] = {}
                if compression == "none":
                    request_kwargs["data"] = payload_bytes
                    request_kwargs["headers"] = {"Content-Type": "application/json"}
                elif compression == "gzip":
                    request_kwargs["data"] = gzip.compress(payload_bytes)
                    request_kwargs["headers"] = {
                        "Content-Type": "application/json",
                        "Content-Encoding": "gzip",
                    }
                else:
                    raise ValueError(f"Unsupported compression '{compression}'")

                response = self._session.post(url, **request_kwargs)
                self._handle_response_errors(response)

                # Server returns 202 with job_id for async processing
                response_data = response.json()
                job_id = response_data.get("job_id")
                if job_id:
                    job_ids.append(job_id)

                pbar.update(batch_size)

        if not wait:
            logger.info(
                f"Enqueued {total_runs} agent runs to Collection '{collection_id}' "
                f"({len(job_ids)} job(s)). Use get_agent_run_job_status() to check progress."
            )
            return {
                "status": "enqueued",
                "total_runs_added": total_runs,
                "job_ids": job_ids,
            }

        # Wait for all jobs to complete
        if job_ids:
            logger.info(
                f"Uploaded {total_runs} agent runs in {len(job_ids)} batch(es). "
                f"Waiting for server-side processing to complete... "
                f"(set wait=False to skip waiting)"
            )
            self._wait_for_jobs(collection_id, job_ids, poll_interval)

        logger.info(
            f"Successfully added {total_runs} agent runs to Collection '{collection_id}'. "
            f"All {len(job_ids)} job(s) completed."
        )
        return {"status": "success", "total_runs_added": total_runs, "job_ids": job_ids}

    def _wait_for_jobs(
        self,
        collection_id: str,
        job_ids: list[str],
        poll_interval: float = 1.0,
    ) -> None:
        """Wait for all jobs to complete, showing progress.

        Args:
            collection_id: ID of the Collection.
            job_ids: List of job IDs to wait for.
            poll_interval: Seconds between status checks.

        Raises:
            RuntimeError: If any job fails or is canceled.
        """
        pending_jobs = set(job_ids)
        failed_jobs: dict[str, str] = {}

        with tqdm(total=len(job_ids), desc="Waiting for server processing", unit="jobs") as pbar:
            while pending_jobs:
                statuses = self.get_agent_run_job_statuses(collection_id, list(pending_jobs))

                for job_status in statuses:
                    job_id = job_status["job_id"]
                    status = job_status["status"]

                    if status == "completed":
                        pending_jobs.discard(job_id)
                        pbar.update(1)
                    elif status == "canceled":
                        pending_jobs.discard(job_id)
                        failed_jobs[job_id] = "Job was canceled"
                        pbar.update(1)

                if pending_jobs:
                    time.sleep(poll_interval)

        if failed_jobs:
            failed_msg = ", ".join(f"{k}: {v}" for k, v in failed_jobs.items())
            raise RuntimeError(f"Some jobs failed: {failed_msg}")

    def get_agent_run_job_statuses(
        self, collection_id: str, job_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Get the status of multiple agent run ingestion jobs.

        Args:
            collection_id: ID of the Collection.
            job_ids: List of job IDs to check (max 100).

        Returns:
            list: List of job status dictionaries, each containing:
                - job_id: The job ID
                - status: One of "pending", "running", "completed", "canceled"
                - type: The job type
                - created_at: ISO timestamp of job creation

        Raises:
            ValueError: If more than 100 job IDs are provided.
            requests.exceptions.HTTPError: If the API request fails.
        """
        if len(job_ids) > 100:
            raise ValueError("Cannot request more than 100 job IDs at once")

        url = f"{self._server_url}/{collection_id}/agent_runs/jobs/batch_status"
        response = self._session.post(url, json={"job_ids": job_ids})
        self._handle_response_errors(response)
        return response.json()["jobs"]

    def get_agent_run_job_status(self, collection_id: str, job_id: str) -> dict[str, Any]:
        """Get the status of an agent run ingestion job.

        Args:
            collection_id: ID of the Collection.
            job_id: The ID of the job to check.

        Returns:
            dict: Job status information including:
                - job_id: The job ID
                - status: One of "pending", "running", "completed", "canceled"
                - type: The job type
                - created_at: ISO timestamp of job creation

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/{collection_id}/agent_runs/jobs/{job_id}"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def list_collections(self) -> list[dict[str, Any]]:
        """Lists all available Collections.

        Returns:
            list: List of Collection objects.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/collections"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def get_collection(self, collection_id: str) -> dict[str, Any] | None:
        """Get details about a specific Collection.

        Requires READ permission on the collection.

        Args:
            collection_id: ID of the Collection to retrieve.

        Returns:
            Collection: Collection object with id, name, description, created_at, and created_by.
                       Returns None if collection not found.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/{collection_id}/collection_details"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def list_rubrics(self, collection_id: str) -> list[dict[str, Any]]:
        """List all rubrics for a given collection.

        Args:
            collection_id: ID of the Collection.

        Returns:
            list: List of dictionaries containing rubric information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rubric/{collection_id}/rubrics"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def get_rubric_run_state(
        self, collection_id: str, rubric_id: str, version: int | None = None
    ) -> dict[str, Any]:
        """Get rubric run state for a given collection and rubric.

        Args:
            collection_id: ID of the Collection.
            rubric_id: The ID of the rubric to get run state for.
            version: The version of the rubric to get run state for. If None, the latest version is used.

        Returns:
            dict: Dictionary containing rubric run state with results, job_id, and total_results_needed.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rubric/{collection_id}/{rubric_id}/rubric_run_state"
        response = self._session.get(url, params={"version": version})
        self._handle_response_errors(response)
        return response.json()

    def get_clustering_state(self, collection_id: str, rubric_id: str) -> dict[str, Any]:
        """Get clustering state for a given collection and rubric.

        Args:
            collection_id: ID of the Collection.
            rubric_id: The ID of the rubric to get clustering state for.

        Returns:
            dict: Dictionary containing job_id, centroids, and assignments.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rubric/{collection_id}/{rubric_id}/clustering_job"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def get_cluster_centroids(self, collection_id: str, rubric_id: str) -> list[dict[str, Any]]:
        """Get centroids for a given collection and rubric.

        Args:
            collection_id: ID of the Collection.
            rubric_id: The ID of the rubric to get centroids for.

        Returns:
            list: List of dictionaries containing centroid information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        clustering_state = self.get_clustering_state(collection_id, rubric_id)
        return clustering_state.get("centroids", [])

    def get_cluster_assignments(self, collection_id: str, rubric_id: str) -> dict[str, list[str]]:
        """Get centroid assignments for a given rubric.

        Args:
            collection_id: ID of the Collection.
            rubric_id: The ID of the rubric to get assignments for.

        Returns:
            dict: Dictionary mapping centroid IDs to lists of judge result IDs.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        clustering_state = self.get_clustering_state(collection_id, rubric_id)
        return clustering_state.get("assignments", {})

    def create_label_set(
        self,
        collection_id: str,
        name: str,
        label_schema: dict[str, Any],
        description: str | None = None,
    ) -> str:
        """Create a new label set with a JSON schema.

        Args:
            collection_id: ID of the collection.
            name: Name of the label set.
            label_schema: JSON schema for validating labels in this set.
            description: Optional description of the label set.

        Returns:
            str: The ID of the created label set.

        Raises:
            ValueError: If the response is missing the label_set_id.
            jsonschema.ValidationError: If the label schema is invalid.
            requests.exceptions.HTTPError: If the API request fails.
        """
        validate_judge_result_schema(label_schema)

        url = f"{self._server_url}/label/{collection_id}/label_set"
        payload = {
            "name": name,
            "label_schema": label_schema,
            "description": description,
        }
        response = self._session.post(url, json=payload)
        self._handle_response_errors(response)
        return response.json()["label_set_id"]

    def add_label(
        self,
        collection_id: str,
        label: Label,
    ) -> dict[str, str]:
        """Create a label in a label set.

        Args:
            collection_id: ID of the Collection.
            label: A `Label` object that must comply with the label set's schema.

        Returns:
            dict: API response containing the label_id.

        Raises:
            requests.exceptions.HTTPError: If the API request fails or validation errors occur.
        """
        url = f"{self._server_url}/label/{collection_id}/label"
        payload = {"label": label.model_dump(mode="json")}
        response = self._session.post(url, json=payload)
        self._handle_response_errors(response)
        return response.json()

    def add_labels(
        self,
        collection_id: str,
        labels: list[Label],
    ) -> dict[str, Any]:
        """Create multiple labels.

        Args:
            collection_id: ID of the Collection.
            labels: List of `Label` objects.

        Returns:
            dict: API response containing label_ids list and optional errors list.

        Raises:
            ValueError: If no labels are provided.
            requests.exceptions.HTTPError: If the API request fails.
        """
        if not labels:
            raise ValueError("labels must contain at least one entry")

        url = f"{self._server_url}/label/{collection_id}/labels"
        payload = {"labels": [label.model_dump(mode="json") for label in labels]}
        response = self._session.post(url, json=payload)
        self._handle_response_errors(response)
        return response.json()

    def get_label_sets(self, collection_id: str) -> list[dict[str, Any]]:
        """Retrieve all label sets in a collection.

        Args:
            collection_id: ID of the Collection.

        Returns:
            list: List of label set dictionaries.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/label/{collection_id}/label_sets"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def get_labels(
        self, collection_id: str, label_set_id: str, filter_valid_labels: bool = False
    ) -> list[dict[str, Any]]:
        """Retrieve all labels in a label set.

        Args:
            collection_id: ID of the Collection.
            label_set_id: ID of the label set to fetch labels for.
            filter_valid_labels: If True, only return labels that match the label set schema
                INCLUDING requirements. Default is False (returns all labels).

        Returns:
            list: List of label dictionaries.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/label/{collection_id}/label_set/{label_set_id}/labels"
        params = {"filter_valid_labels": filter_valid_labels}
        response = self._session.get(url, params=params)
        self._handle_response_errors(response)
        return response.json()

    def tag_transcript(self, collection_id: str, agent_run_id: str, value: str) -> None:
        """Add a tag to an agent run transcript.

        Args:
            collection_id: ID of the Collection.
            agent_run_id: The agent run to tag.
            value: The tag value (max length enforced by the server).

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/label/{collection_id}/tag"
        payload = {"agent_run_id": agent_run_id, "value": value}
        response = self._session.post(url, json=payload)
        self._handle_response_errors(response)

    def get_tags(self, collection_id: str, value: str | None = None) -> list[dict[str, Any]]:
        """Get all tags in a collection, optionally filtered by value."""
        url = f"{self._server_url}/label/{collection_id}/tags"
        params = {"value": value} if value is not None else None
        response = self._session.get(url, params=params)
        self._handle_response_errors(response)
        return response.json()

    def get_tags_for_agent_run(self, collection_id: str, agent_run_id: str) -> list[dict[str, Any]]:
        """Get all tags attached to a specific agent run."""
        url = f"{self._server_url}/label/{collection_id}/agent_run/{agent_run_id}/tags"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def delete_tag(self, collection_id: str, tag_id: str) -> None:
        """Delete a tag by ID."""
        url = f"{self._server_url}/label/{collection_id}/tag/{tag_id}"
        response = self._session.delete(url)
        self._handle_response_errors(response)

    def get_comments(self, collection_id: str) -> list[dict[str, Any]]:
        """Get all comments in a collection.

        Args:
            collection_id: ID of the Collection.

        Returns:
            list: List of comment dictionaries.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/label/{collection_id}/comments"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def get_comments_for_agent_run(
        self, collection_id: str, agent_run_id: str
    ) -> list[dict[str, Any]]:
        """Get all comments for a specific agent run.

        Args:
            collection_id: ID of the Collection.
            agent_run_id: ID of the agent run to get comments for.

        Returns:
            list: List of comment dictionaries.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/label/{collection_id}/agent_run/{agent_run_id}/comments"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def get_agent_run(self, collection_id: str, agent_run_id: str) -> AgentRun | None:
        """Get a specific agent run by its ID.

        Args:
            collection_id: ID of the Collection.
            agent_run_id: The ID of the agent run to retrieve.

        Returns:
            dict: Dictionary containing the agent run information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/{collection_id}/agent_run"
        response = self._session.get(url, params={"agent_run_id": agent_run_id})
        self._handle_response_errors(response)
        if response.json() is None:
            return None
        else:
            # We do this to avoid metadata validation failing
            # TODO(mengk): kinda hacky
            return AgentRun.model_validate(response.json())

    def get_chat_sessions(self, collection_id: str, agent_run_id: str) -> list[dict[str, Any]]:
        """Get all chat sessions for an agent run, excluding judge result sessions.

        Args:
            collection_id: ID of the Collection.
            agent_run_id: The ID of the agent run to retrieve chat sessions for.

        Returns:
            list: List of chat session dictionaries.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/chat/{collection_id}/{agent_run_id}/sessions"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def make_collection_public(self, collection_id: str) -> dict[str, Any]:
        """Make a collection publicly accessible to anyone with the link.

        Args:
            collection_id: ID of the Collection to make public.

        Returns:
            dict: API response data.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/{collection_id}/make_public"
        response = self._session.post(url)
        self._handle_response_errors(response)

        logger.info(f"Successfully made Collection '{collection_id}' public")
        return response.json()

    def share_collection_with_email(self, collection_id: str, email: str) -> dict[str, Any]:
        """Share a collection with a specific user by email address.

        Args:
            collection_id: ID of the Collection to share.
            email: Email address of the user to share with.

        Returns:
            dict: API response data.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/{collection_id}/share_with_email"
        payload = {"email": email}
        response = self._session.post(url, json=payload)

        self._handle_response_errors(response)

        logger.info(f"Successfully shared Collection '{collection_id}' with {email}")
        return response.json()

    def get_my_organizations(self) -> list[dict[str, Any]]:
        """List organizations the authenticated user belongs to."""
        url = f"{self._server_url}/organizations"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def get_organization_users(self, organization_id: str) -> list[dict[str, Any]]:
        """List users in an organization.

        Args:
            organization_id: Organization ID.
        """
        url = f"{self._server_url}/organizations/{organization_id}/users"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def get_collection_collaborators(self, collection_id: str) -> list[dict[str, Any]]:
        """List collaborators (users, organizations, public) for a collection."""
        url = f"{self._server_url}/collections/{collection_id}/collaborators"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def share_collection_with_organization(
        self,
        collection_id: str,
        organization_id: str,
        *,
        permission: Literal["read", "write", "admin"] = "read",
    ) -> dict[str, Any]:
        """Share a collection with an organization.

        Note: The backend requires admin permission on the collection to manage sharing.
        """
        if permission not in {"read", "write", "admin"}:
            raise ValueError("permission must be one of ['admin', 'read', 'write']")

        url = f"{self._server_url}/collections/{collection_id}/collaborators/upsert"
        payload = {
            "subject_id": organization_id,
            "subject_type": "organization",
            "collection_id": collection_id,
            "permission_level": permission,
        }
        response = self._session.put(url, json=payload)
        self._handle_response_errors(response)
        return response.json()

    def unshare_collection_with_organization(
        self, collection_id: str, organization_id: str
    ) -> None:
        """Remove an organization's access to a collection."""
        url = f"{self._server_url}/collections/{collection_id}/collaborators/delete"
        payload = {
            "subject_id": organization_id,
            "subject_type": "organization",
            "collection_id": collection_id,
        }
        response = self._session.delete(url, json=payload)
        self._handle_response_errors(response)
        return None

    def collection_exists(self, collection_id: str) -> bool:
        """Check if a collection exists without raising if it does not."""
        url = f"{self._server_url}/{collection_id}/exists"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return bool(response.json())

    def has_collection_permission(self, collection_id: str, permission: str = "write") -> bool:
        """Check whether the authenticated user has a specific permission on a collection.

        Args:
            collection_id: Collection to check.
            permission: Permission level to verify (`read`, `write`, or `admin`).

        Returns:
            bool: True if the current API key has the requested permission; otherwise False.

        Raises:
            ValueError: If an unsupported permission value is provided.
            requests.exceptions.HTTPError: If the API request fails.
        """
        valid_permissions = {"read", "write", "admin"}
        if permission not in valid_permissions:
            raise ValueError(f"permission must be one of {sorted(valid_permissions)}")

        url = f"{self._server_url}/{collection_id}/has_permission"
        response = self._session.get(url, params={"permission": permission})
        self._handle_response_errors(response)

        payload = response.json()
        return bool(payload.get("has_permission", False))

    def get_dql_schema(self, collection_id: str) -> dict[str, Any]:
        """Retrieve the DQL schema for a collection.

        Args:
            collection_id: ID of the Collection.

        Returns:
            dict: Dictionary containing available tables, columns, and metadata for DQL queries.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/dql/{collection_id}/schema"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def execute_dql(self, collection_id: str, dql: str) -> dict[str, Any]:
        """Execute a DQL query against a collection.

        Args:
            collection_id: ID of the Collection.
            dql: The DQL query string to execute.

        Returns:
            dict: Query execution results including rows, columns, execution metadata, and selected columns.

        Raises:
            ValueError: If `dql` is empty.
            requests.exceptions.HTTPError: If the API request fails or the query is invalid.
        """
        if not dql.strip():
            raise ValueError("dql must be a non-empty string")

        url = f"{self._server_url}/dql/{collection_id}/execute"
        response = self._session.post(url, json={"dql": dql})
        self._handle_response_errors(response)
        return response.json()

    def dql_result_to_dicts(self, dql_result: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert a DQL result to a list of dictionaries."""
        cols = dql_result["columns"]
        rows = dql_result["rows"]
        return [dict(zip(cols, row)) for row in rows]

    def dql_result_to_df_experimental(self, dql_result: dict[str, Any]):
        """The implementation is not stable by any means!"""

        cols = dql_result["columns"]
        rows = dql_result["rows"]

        def _cast_value(v: Any) -> Any:
            """Cast a value to int, float, bool, or str as appropriate."""
            if v is None:
                return None
            if isinstance(v, (bool, int, float)):
                return v

            # If a string, try to cast into a number
            if isinstance(v, str):
                try:
                    if "." not in v:
                        return int(v)
                except (ValueError, TypeError):
                    pass

                try:
                    return float(v)
                except (ValueError, TypeError):
                    pass

            # Keep as original
            return v

        dicts: list[dict[str, Any]] = []
        for row in rows:
            combo = list(zip(cols, row))
            combo = {k: _cast_value(v) for k, v in combo}
            dicts.append(combo)

        return pd.DataFrame(dicts)

    def select_agent_run_ids(
        self,
        collection_id: str,
        where_clause: str | None = None,
        limit: int | None = None,
    ) -> list[str]:
        """Convenience helper to fetch agent run IDs via DQL.

        Args:
            collection_id: ID of the Collection to query.
            where_clause: Optional DQL WHERE clause applied to the agent_runs table.
            limit: Optional LIMIT applied to the underlying DQL query.

        Returns:
            list[str]: Agent run IDs matching the criteria.

        Raises:
            ValueError: If the inputs are invalid.
            requests.exceptions.HTTPError: If the API request fails.
        """
        query = "SELECT agent_runs.id AS agent_run_id FROM agent_runs"

        if where_clause:
            where_clause = where_clause.strip()
            if not where_clause:
                raise ValueError("where_clause must be a non-empty string when provided")
            query += f" WHERE {where_clause}"

        if limit is not None:
            if limit <= 0:
                raise ValueError("limit must be a positive integer when provided")
            query += f" LIMIT {limit}"

        result = self.execute_dql(collection_id, query)
        rows = result.get("rows", [])
        agent_run_ids = [str(row[0]) for row in rows if row]

        if result.get("truncated"):
            logger.warning(
                "DQL query truncated at applied limit %s; returning %s agent run IDs",
                result.get("applied_limit"),
                len(agent_run_ids),
            )

        return agent_run_ids

    def list_agent_run_ids(self, collection_id: str) -> list[str]:
        """Get all agent run IDs for a collection.

        Args:
            collection_id: ID of the Collection.

        Returns:
            str: JSON string containing the list of agent run IDs.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/{collection_id}/agent_run_ids"
        response = self._session.get(url)
        self._handle_response_errors(response)
        return response.json()

    def recursively_ingest_inspect_logs(self, collection_id: str, fpath: str):
        """Recursively search directory for .eval files and ingest them as agent runs.

        Args:
            collection_id: ID of the Collection to add agent runs to.
            fpath: Path to directory to search recursively.

        Raises:
            ValueError: If the path doesn't exist or isn't a directory.
            requests.exceptions.HTTPError: If any API requests fail.
        """
        root_path = Path(fpath)
        if not root_path.exists():
            raise ValueError(f"Path does not exist: {fpath}")
        if not root_path.is_dir():
            raise ValueError(f"Path is not a directory: {fpath}")

        # Find all .eval files recursively
        eval_files = list(root_path.rglob("*.eval"))

        if not eval_files:
            logger.info(f"No .eval files found in {fpath}")
            return

        logger.info(f"Found {len(eval_files)} .eval files in {fpath}")

        total_runs_added = 0
        batch_size = 100

        # Process each .eval file
        for eval_file in tqdm(eval_files, desc="Processing .eval files", unit="files"):
            # Get total samples for progress tracking
            total_samples = load_inspect.get_total_samples(eval_file, format="eval")

            if total_samples == 0:
                logger.info(f"No samples found in {eval_file}")
                continue

            # Load runs from file
            with open(eval_file, "rb") as f:
                _, runs_generator = load_inspect.runs_from_file(f, format="eval")

                # Process runs in batches
                runs_from_file = 0
                batches = batched(runs_generator, batch_size)

                with tqdm(
                    total=total_samples,
                    desc=f"Processing {eval_file.name}",
                    unit="runs",
                    leave=False,
                ) as file_pbar:
                    for batch in batches:
                        batch_list = list(batch)  # Convert generator batch to list
                        if not batch_list:
                            break

                        # Add batch to collection
                        url = f"{self._server_url}/{collection_id}/agent_runs"
                        payload = {"agent_runs": [ar.model_dump(mode="json") for ar in batch_list]}

                        response = self._session.post(url, json=payload)
                        self._handle_response_errors(response)

                        runs_from_file += len(batch_list)
                        file_pbar.update(len(batch_list))

            total_runs_added += runs_from_file
            logger.info(f"Added {runs_from_file} runs from {eval_file}")

        logger.info(
            f"Successfully ingested {total_runs_added} total agent runs from {len(eval_files)} files"
        )

    def start_chat(
        self,
        context: LLMContext | list[LLMContextItem],
        model_string: str | None = None,
        reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = None,
    ) -> str:
        """Start a chat session with multiple objects and open it in the browser.

        This method creates a new chat session with the provided objects (agent runs,
        transcripts, or formatted versions) and opens the chat UI in your default browser.

        Args:
            objects: List of objects to include in the chat context. Can include:
                    - AgentRun or FormattedAgentRun instances
                    - Transcript or FormattedTranscript instances
            chat_model: Optional model to use for the chat. If None, uses default.

        Returns:
            str: The session ID of the created chat session.

        Raises:
            ValueError: If objects list is empty or contains unsupported types.
            requests.exceptions.HTTPError: If the API request fails.

        Example:
            ```python
            from docent.sdk import Docent

            client = Docent()
            run1 = client.get_agent_run(collection_id, run_id_1)
            run2 = client.get_agent_run(collection_id, run_id_2)

            session_id = client.start_chat([run1, run2])
            # Opens browser to chat UI
            ```
        """
        if isinstance(context, LLMContext):
            context = context
        else:
            context = LLMContext(items=context)

        serialized_context = context.to_dict()

        url = f"{self._server_url}/chat/start"
        payload = {
            "context_serialized": serialized_context,
            "model_string": model_string,
            "reasoning_effort": reasoning_effort,
        }

        response = self._session.post(url, json=payload)
        self._handle_response_errors(response)

        response_data = response.json()
        session_id = response_data.get("session_id")
        if not session_id:
            raise ValueError("Failed to create chat session: 'session_id' missing in response")

        chat_url = f"{self._web_url}/chat/{session_id}"
        logger.info(f"Chat session created. Opening browser to: {chat_url}")

        webbrowser.open(chat_url)

        return session_id

    def open_agent_run(self, collection_id: str, agent_run_id: str) -> str:
        """Open an agent run in the browser.

        Args:
            collection_id: ID of the Collection containing the agent run.
            agent_run_id: ID of the agent run to open.

        Returns:
            str: The URL that was opened.

        Example:
            ```python
            from docent.sdk import Docent

            client = Docent()
            client.open_agent_run(collection_id, agent_run_id)
            # Opens browser to agent run page
            ```
        """
        agent_run_url = f"{self._web_url}/dashboard/{collection_id}/agent_run/{agent_run_id}"
        logger.info(f"Opening agent run in browser: {agent_run_url}")

        webbrowser.open(agent_run_url)

        return agent_run_url

    def open_rubric(
        self,
        collection_id: str,
        rubric_id: str,
        agent_run_id: str | None = None,
        judge_result_id: str | None = None,
    ) -> str:
        """Open a rubric, agent run, or judge result in the browser.

        Args:
            collection_id: ID of the Collection.
            rubric_id: ID of the rubric.
            agent_run_id: Optional ID of the agent run to view within the rubric.
            judge_result_id: Optional ID of the judge result to view. Requires agent_run_id.

        Returns:
            str: The URL that was opened.

        Raises:
            ValueError: If judge_result_id is provided without agent_run_id.

        Example:
            ```python
            from docent.sdk import Docent

            client = Docent()
            # Open rubric overview
            client.open_rubric(collection_id, rubric_id)
            # Open specific agent run within rubric
            client.open_rubric(collection_id, rubric_id, agent_run_id)
            # Open specific judge result
            client.open_rubric(collection_id, rubric_id, agent_run_id, judge_result_id)
            ```
        """
        if judge_result_id is not None and agent_run_id is None:
            raise ValueError("judge_result_id requires agent_run_id to be specified")

        url = f"{self._web_url}/dashboard/{collection_id}/rubric/{rubric_id}"
        if agent_run_id is not None:
            url += f"/agent_run/{agent_run_id}"
        if judge_result_id is not None:
            url += f"/result/{judge_result_id}"

        logger.info(f"Opening rubric in browser: {url}")
        webbrowser.open(url)

        return url
