import itertools
import os
from pathlib import Path
from typing import Any

import requests
from tqdm import tqdm

from docent._log_util.logger import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.judge import JudgeRunLabel
from docent.loaders import load_inspect

logger = get_logger(__name__)


class Docent:
    """Client for interacting with the Docent API.

    This client provides methods for creating and managing Collections,
    dimensions, agent runs, and filters in the Docent system.

    Args:
        server_url: URL of the Docent API server.
        web_url: URL of the Docent web UI.
        email: Email address for authentication.
        password: Password for authentication.
    """

    def __init__(
        self,
        server_url: str = "https://api.docent.transluce.org",
        web_url: str = "https://docent.transluce.org",
        api_key: str | None = None,
    ):
        self._server_url = server_url.rstrip("/") + "/rest"
        self._web_url = web_url.rstrip("/")

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
        """Handle API response and raise informative errors.
        TODO: make this more informative."""
        response.raise_for_status()

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

    def add_agent_runs(
        self, collection_id: str, agent_runs: list[AgentRun], batch_size: int = 1000
    ) -> dict[str, Any]:
        """Adds agent runs to a Collection.

        Agent runs represent execution traces that can be visualized and analyzed.
        This method batches the insertion in groups of 1,000 for better performance.

        Args:
            collection_id: ID of the Collection.
            agent_runs: List of AgentRun objects to add.

        Returns:
            dict: API response data.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        from tqdm import tqdm

        url = f"{self._server_url}/{collection_id}/agent_runs"
        total_runs = len(agent_runs)

        # Process agent runs in batches
        with tqdm(total=total_runs, desc="Adding agent runs", unit="runs") as pbar:
            for i in range(0, total_runs, batch_size):
                batch = agent_runs[i : i + batch_size]
                payload = {"agent_runs": [ar.model_dump(mode="json") for ar in batch]}

                response = self._session.post(url, json=payload)
                self._handle_response_errors(response)

                pbar.update(len(batch))

        url = f"{self._server_url}/{collection_id}/compute_embeddings"
        response = self._session.post(url)
        self._handle_response_errors(response)

        logger.info(f"Successfully added {total_runs} agent runs to Collection '{collection_id}'")
        return {"status": "success", "total_runs_added": total_runs}

    def list_collections(self) -> list[dict[str, Any]]:
        """Lists all available Collections.

        Returns:
            list: List of dictionaries containing Collection information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/collections"
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
            dict: Dictionary containing rubric run state with results, job_id, and total_agent_runs.

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

    def add_label(
        self,
        collection_id: str,
        rubric_id: str,
        label: JudgeRunLabel,
    ) -> dict[str, Any]:
        """Attach a manual label to an agent run for a rubric.

        Args:
            collection_id: ID of the Collection that owns the rubric.
            rubric_id: ID of the rubric the label applies to.
            label: A `JudgeRunLabel` that must comply with the rubric's output schema.

        Returns:
            dict: API response containing a status message.

        Raises:
            ValueError: If the label does not target the rubric specified in the path.
            requests.exceptions.HTTPError: If the API request fails or validation errors occur.
        """
        if label.rubric_id != rubric_id:
            raise ValueError("Label rubric_id must match the rubric_id argument")

        url = f"{self._server_url}/rubric/{collection_id}/rubric/{rubric_id}/label"
        payload = {"label": label.model_dump(mode="json")}
        response = self._session.post(url, json=payload)
        self._handle_response_errors(response)
        return response.json()

    def add_labels(
        self,
        collection_id: str,
        rubric_id: str,
        labels: list[JudgeRunLabel],
    ) -> dict[str, Any]:
        """Attach multiple manual labels to a rubric.

        Args:
            collection_id: ID of the Collection that owns the rubric.
            rubric_id: ID of the rubric the labels apply to.
            labels: List of `JudgeRunLabel` objects.

        Returns:
            dict: API response containing status information.

        Raises:
            ValueError: If no labels are provided.
            ValueError: If any label targets a different rubric.
            requests.exceptions.HTTPError: If the API request fails.
        """
        if not labels:
            raise ValueError("labels must contain at least one entry")

        rubric_ids = {label.rubric_id for label in labels}
        if rubric_ids != {rubric_id}:
            raise ValueError(
                "All labels must specify the same rubric_id that is provided to add_labels"
            )

        payload = {"labels": [l.model_dump(mode="json") for l in labels]}

        url = f"{self._server_url}/rubric/{collection_id}/rubric/{rubric_id}/labels"
        response = self._session.post(url, json=payload)
        self._handle_response_errors(response)
        return response.json()

    def get_labels(self, collection_id: str, rubric_id: str) -> list[dict[str, Any]]:
        """Retrieve all manual labels for a rubric.

        Args:
            collection_id: ID of the Collection that owns the rubric.
            rubric_id: ID of the rubric to fetch labels for.

        Returns:
            list: List of label dictionaries. Each includes agent_run_id and label content.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rubric/{collection_id}/rubric/{rubric_id}/labels"
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
                batches = itertools.batched(runs_generator, batch_size)

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

        # Compute embeddings after all files are processed
        if total_runs_added > 0:
            logger.info("Computing embeddings for added runs...")
            url = f"{self._server_url}/{collection_id}/compute_embeddings"
            response = self._session.post(url)
            self._handle_response_errors(response)

        logger.info(
            f"Successfully ingested {total_runs_added} total agent runs from {len(eval_files)} files"
        )
