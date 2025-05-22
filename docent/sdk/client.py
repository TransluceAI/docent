from typing import Any

import requests

from docent._log_util.logger import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.filters import FrameDimension, FrameFilter

logger = get_logger(__name__)


class DocentClient:
    """Client for interacting with the Docent API.

    This client provides methods for creating and managing FrameGrids,
    dimensions, agent runs, and filters in the Docent system.

    Args:
        server_url: URL of the Docent API server.
        web_url: URL of the Docent web UI.
        api_key: Optional API key for authentication.
    """

    def __init__(self, server_url: str, web_url: str, api_key: str | None = None):
        self._server_url = server_url.rstrip("/")
        self._web_url = web_url.rstrip("/")
        self._api_key = api_key

        # Use requests.Session for connection pooling and persistent headers
        self._session = requests.Session()
        if api_key:
            self._session.headers.update({"Authorization": f"Bearer {self._api_key}"})

    def create_framegrid(
        self,
        fg_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> str:
        """Creates a new FrameGrid.

        Creates a new FrameGrid and sets up a default MECE dimension
        for grouping on the homepage.

        Args:
            fg_id: Optional ID for the new FrameGrid. If not provided, one will be generated.
            name: Optional name for the FrameGrid.
            description: Optional description for the FrameGrid.

        Returns:
            str: The ID of the created FrameGrid.

        Raises:
            ValueError: If the response is missing the FrameGrid ID.
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rest/create"
        payload = {
            "fg_id": fg_id,
            "name": name,
            "description": description,
        }

        response = self._session.post(url, json=payload)
        response.raise_for_status()

        response_data = response.json()
        fg_id = response_data.get("fg_id")
        if fg_id is None:
            raise ValueError("Failed to create frame grid: 'fg_id' missing in response.")

        logger.info(f"Successfully created FrameGrid with id='{fg_id}'")

        # Set the default MECE dimension that is used to group the homepage
        default_dim = FrameDimension(name="run_id", metadata_key="run_id", maintain_mece=True)
        self.add_dimension(fg_id, default_dim)
        self.set_io_dims(fg_id, default_dim.id, None)

        logger.info(f"FrameGrid creation complete. Frontend available at: {self._web_url}/{fg_id}")
        return fg_id

    def set_io_dims(self, fg_id: str, inner_dim_id: str | None, outer_dim_id: str | None):
        """Sets inner and outer dimensions for a FrameGrid.

        Configures which dimensions are used for inner and outer organization
        of frames in the UI.

        Args:
            fg_id: ID of the FrameGrid.
            inner_dim_id: ID of the dimension to use for inner organization, or None.
            outer_dim_id: ID of the dimension to use for outer organization, or None.

        Returns:
            dict: API response data.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rest/io_dims"
        payload = {"fg_id": fg_id, "inner_dim_id": inner_dim_id, "outer_dim_id": outer_dim_id}
        response = self._session.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def add_dimension(
        self,
        fg_id: str,
        dim: FrameDimension,
    ) -> dict[str, Any]:
        """Adds a dimension to a FrameGrid.

        Dimensions are used to organize and filter frames in the UI.

        Args:
            fg_id: ID of the FrameGrid.
            dim: FrameDimension object defining the dimension to add.

        Returns:
            dict: API response data.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rest/dimension"
        payload = {
            "fg_id": fg_id,
            "dim": dim.model_dump(),
        }

        response = self._session.post(url, json=payload)
        response.raise_for_status()

        logger.info(f"Successfully added dimension '{dim.name}' to FrameGrid '{fg_id}'")
        return response.json()

    def add_agent_runs(self, fg_id: str, agent_runs: list[AgentRun]) -> dict[str, Any]:
        """Adds agent runs to a FrameGrid.

        Agent runs represent execution traces that can be visualized and analyzed.

        Args:
            fg_id: ID of the FrameGrid.
            agent_runs: List of AgentRun objects to add.

        Returns:
            dict: API response data.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rest/agent_runs"
        payload = {"fg_id": fg_id, "agent_runs": [ar.model_dump() for ar in agent_runs]}

        response = self._session.post(url, json=payload)
        response.raise_for_status()

        logger.info(f"Successfully added {len(agent_runs)} agent runs to FrameGrid '{fg_id}'")
        return response.json()

    def get_base_filter(self, fg_id: str) -> dict[str, Any] | None:
        """Retrieves the base filter for a FrameGrid.

        The base filter defines default filtering applied to all views.

        Args:
            fg_id: ID of the FrameGrid.

        Returns:
            dict or None: Filter data if a filter exists, None otherwise.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rest/base_filter/{fg_id}"
        response = self._session.get(url)
        response.raise_for_status()
        # The endpoint returns the filter model directly or null
        filter_data = response.json()
        return filter_data

    def set_base_filter(self, fg_id: str, filter: FrameFilter | None) -> dict[str, Any]:
        """Sets the base filter for a FrameGrid.

        The base filter defines default filtering applied to all views.

        Args:
            fg_id: ID of the FrameGrid.
            filter: FrameFilter object defining the filter, or None to clear the filter.

        Returns:
            dict: API response data.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rest/base_filter"
        payload = {
            "fg_id": fg_id,
            "filter": filter.model_dump() if filter else None,
        }

        response = self._session.post(url, json=payload)
        response.raise_for_status()

        logger.info(f"Successfully set base filter for FrameGrid '{fg_id}'")
        return response.json()

    def list_framegrids(self) -> list[dict[str, Any]]:
        """Lists all available FrameGrids.

        Returns:
            list: List of dictionaries containing FrameGrid information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rest/framegrids"
        response = self._session.get(url)
        response.raise_for_status()
        return response.json()

    def get_dimensions(self, fg_id: str, dim_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Retrieves dimensions for a FrameGrid.

        Args:
            fg_id: ID of the FrameGrid.
            dim_ids: Optional list of dimension IDs to retrieve. If None, retrieves all dimensions.

        Returns:
            list: List of dictionaries containing dimension information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rest/get_dimensions"
        payload = {
            "fg_id": fg_id,
            "dim_ids": dim_ids,
        }
        response = self._session.post(url, json=payload)
        response.raise_for_status()
        return response.json()

    def list_attribute_searches(
        self, fg_id: str, base_data_only: bool = True
    ) -> list[dict[str, Any]]:
        """Lists available attribute searches for a FrameGrid.

        Attribute searches allow finding frames with specific metadata attributes.

        Args:
            fg_id: ID of the FrameGrid.
            base_data_only: If True, returns only basic search information.

        Returns:
            list: List of dictionaries containing attribute search information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rest/attribute_searches"
        params = {
            "fg_id": fg_id,
            "base_data_only": base_data_only,
        }
        response = self._session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def get_search_results_for_id(
        self, fg_id: str, dim_id: str, base_data_only: bool = True
    ) -> list[dict[str, Any]]:
        """Retrieves search results for a specific dimension.

        Gets attribute search results for frames matching a specific dimension.

        Args:
            fg_id: ID of the FrameGrid.
            dim_id: ID of the dimension to search.
            base_data_only: If True, returns only basic result information.

        Returns:
            list: List of dictionaries containing search result information.

        Raises:
            requests.exceptions.HTTPError: If the API request fails.
        """
        url = f"{self._server_url}/rest/dimension_attributes"
        params = {
            "fg_id": fg_id,
            "dim_id": dim_id,
            "base_data_only": base_data_only,
        }
        response = self._session.get(url, params=params)
        response.raise_for_status()
        return response.json()
