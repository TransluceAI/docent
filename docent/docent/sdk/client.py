import os
from typing import Any

import requests

from docent._log_util.logger import get_logger
from docent.data_models.agent_run import AgentRun

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
        server_url: str = "https://aws-docent-backend.transluce.org",
        web_url: str = "https://docent-alpha.transluce.org",
        email: str | None = None,
        password: str | None = None,
    ):
        self._server_url = server_url.rstrip("/") + "/rest"
        self._web_url = web_url.rstrip("/")

        self._email = email or os.getenv("DOCENT_EMAIL")
        if self._email is None:
            raise ValueError(
                "Email address must be provided through keyword argument or DOCENT_EMAIL environment variable"
            )

        self._password = password or os.getenv("DOCENT_PASSWORD")
        if self._password is None:
            raise ValueError(
                "Password must be provided through keyword argument or DOCENT_PASSWORD environment variable"
            )

        # Use requests.Session for connection pooling and persistent headers
        self._session = requests.Session()
        self._login()

    def _login(self):
        """Login with email/password to establish session."""
        login_url = f"{self._server_url}/login"
        response = self._session.post(
            login_url, json={"email": self._email, "password": self._password}
        )

        if response.status_code == 401:
            raise ValueError(
                "Invalid username/password combination. "
                f"If you don't already have an account, please sign up at {self._web_url}/signup"
            )

        response.raise_for_status()
        logger.info(f"Successfully logged in as {self._email}")

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

    def get_dimensions(
        self, collection_id: str, dim_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Retrieves dimensions for a Collection.

        Args:
            collection_id: ID of the Collection.
            dim_ids: Optional list of dimension IDs to retrieve. If None, retrieves all dimensions.

        Returns:
            list: List of dictionaries containing dimension information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/{collection_id}/get_dimensions"
        payload = {
            "dim_ids": dim_ids,
        }
        response = self._session.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def list_attribute_searches(
        self, collection_id: str, base_data_only: bool = True
    ) -> list[dict[str, Any]]:
        """Lists available attribute searches for a Collection.

        Attribute searches allow finding collections with specific metadata attributes.

        Args:
            collection_id: ID of the Collection.
            base_data_only: If True, returns only basic search information.

        Returns:
            list: List of dictionaries containing attribute search information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/{collection_id}/attribute_searches"
        params = {
            "base_data_only": base_data_only,
        }
        response = self._session.get(url, params=params)
        response.raise_for_status()
        return response.json()
