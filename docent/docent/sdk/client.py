import os
from typing import Any

import requests

from docent._log_util.logger import get_logger
from docent.data_models.agent_run import AgentRun, AgentRunWithoutMetadataValidator

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

    def _login(self, api_key: str):
        """Login with email/password to establish session."""
        self._session.headers.update({"Authorization": f"Bearer {api_key}"})

        url = f"{self._server_url}/api-keys/test"
        response = self._session.get(url)
        response.raise_for_status()

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
        response.raise_for_status()

        response_data = response.json()
        collection_id = response_data.get("collection_id")
        if collection_id is None:
            raise ValueError("Failed to create collection: 'collection_id' missing in response.")

        logger.info(f"Successfully created Collection with id='{collection_id}'")

        logger.info(
            f"Collection creation complete. Frontend available at: {self._web_url}/dashboard/{collection_id}"
        )
        return collection_id

    def set_io_bin_keys(
        self, collection_id: str, inner_bin_key: str | None, outer_bin_key: str | None
    ):
        """Set inner and outer bin keys for a collection."""
        response = self._session.post(
            f"{self._server_url}/{collection_id}/set_io_bin_keys",
            json={"inner_bin_key": inner_bin_key, "outer_bin_key": outer_bin_key},
        )
        response.raise_for_status()

    def set_inner_bin_key(self, collection_id: str, dim: str):
        """Set the inner bin key for a collection."""
        current_io_bin_keys = self.get_io_bin_keys(collection_id)
        if current_io_bin_keys is None:
            current_io_bin_keys = (None, None)
        self.set_io_bin_keys(collection_id, dim, current_io_bin_keys[1])  # Set inner, keep outer

    def set_outer_bin_key(self, collection_id: str, dim: str):
        """Set the outer bin key for a collection."""
        current_io_bin_keys = self.get_io_bin_keys(collection_id)
        if current_io_bin_keys is None:
            current_io_bin_keys = (None, None)
        self.set_io_bin_keys(collection_id, current_io_bin_keys[0], dim)  # Keep inner, set outer

    def get_io_bin_keys(self, collection_id: str) -> tuple[str | None, str | None] | None:
        """Gets the current inner and outer bin keys for a Collection.

        Args:
            collection_id: ID of the Collection.

        Returns:
            tuple: (inner_bin_key | None, outer_bin_key | None)

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/{collection_id}/io_bin_keys"
        response = self._session.get(url)
        response.raise_for_status()
        data = response.json()
        return (data.get("inner_bin_key"), data.get("outer_bin_key"))

    def add_agent_runs(self, collection_id: str, agent_runs: list[AgentRun]) -> dict[str, Any]:
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
        batch_size = 1000
        total_runs = len(agent_runs)

        # Process agent runs in batches
        with tqdm(total=total_runs, desc="Adding agent runs", unit="runs") as pbar:
            for i in range(0, total_runs, batch_size):
                batch = agent_runs[i : i + batch_size]
                payload = {"agent_runs": [ar.model_dump(mode="json") for ar in batch]}

                response = self._session.post(url, json=payload)
                response.raise_for_status()

                pbar.update(len(batch))

        url = f"{self._server_url}/{collection_id}/compute_embeddings"
        response = self._session.post(url)
        response.raise_for_status()

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
        response.raise_for_status()
        return response.json()

    def list_searches(self, collection_id: str) -> list[dict[str, Any]]:
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
        response.raise_for_status()
        return response.json()

    def get_search_results(
        self, collection_id: str, rubric_id: str, rubric_version: int
    ) -> list[dict[str, Any]]:
        """Get rubric results for a given collection, rubric and version.

        Args:
            collection_id: ID of the Collection.
            rubric_id: The ID of the rubric to get results for.
            rubric_version: The version of the rubric to get results for.

        Returns:
            list: List of dictionaries containing rubric result information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rubric/{collection_id}/{rubric_id}/results"
        response = self._session.get(url, params={"rubric_version": rubric_version})
        response.raise_for_status()
        return response.json()

    def list_search_clusters(
        self, collection_id: str, rubric_id: str, rubric_version: int | None = None
    ) -> list[dict[str, Any]]:
        """List all centroids for a given collection and rubric.

        Args:
            collection_id: ID of the Collection.
            rubric_id: The ID of the rubric to get centroids for.
            rubric_version: Optional version of the rubric. If not provided, uses latest.

        Returns:
            list: List of dictionaries containing centroid information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rubric/{collection_id}/{rubric_id}/centroids"
        params: dict[str, int] = {}
        if rubric_version is not None:
            params["rubric_version"] = rubric_version
        response = self._session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_cluster_matches(
        self, collection_id: str, rubric_id: str, rubric_version: int
    ) -> list[dict[str, Any]]:
        """Get centroid assignments for a given rubric.

        Args:
            collection_id: ID of the Collection.
            rubric_id: The ID of the rubric to get assignments for.
            rubric_version: The version of the rubric to get assignments for.

        Returns:
            list: List of dictionaries containing centroid assignment information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rubric/{collection_id}/{rubric_id}/assignments"
        response = self._session.get(url, params={"rubric_version": rubric_version})
        response.raise_for_status()
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
        response.raise_for_status()
        if response.json() is None:
            return None
        else:
            # We do this to avoid metadata validation failing
            # TODO(mengk): kinda hacky
            return AgentRunWithoutMetadataValidator.model_validate(response.json())

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
        response.raise_for_status()

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

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            if response.status_code == 404:
                raise ValueError(f"The user you are trying to share with ({email}) does not exist.")
            else:
                raise  # Re-raise the original exception

        logger.info(f"Successfully shared Collection '{collection_id}' with {email}")
        return response.json()
