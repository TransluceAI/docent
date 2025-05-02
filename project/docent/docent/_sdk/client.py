from typing import Any

import requests
from docent._frames.filters import FrameDimension, FrameFilterTypes
from docent._frames.types import Datapoint
from log_util.logger import get_logger

logger = get_logger(__name__)


class DocentClient:
    def __init__(self, server_url: str, web_url: str, api_key: str | None = None):
        self._server_url = server_url.rstrip("/")
        self._web_url = web_url.rstrip("/")
        self._api_key = api_key

        # Use requests.Session for connection pooling and persistent headers
        self._session = requests.Session()
        if api_key:
            self._session.headers.update({"Authorization": f"Bearer {self._api_key}"})

    def create_framegrid(
        self, fg_id: str | None = None, add_default_dimensions: bool = True
    ) -> str:
        url = f"{self._server_url}/rest/create"
        payload = {"fg_id": fg_id} if fg_id else {}

        response = self._session.post(url, json=payload)
        response.raise_for_status()

        response_data = response.json()
        fg_id = response_data.get("fg_id")
        if fg_id is None:
            raise ValueError("Failed to create frame grid: 'fg_id' missing in response.")

        logger.info(f"Successfully created FrameGrid with id='{fg_id}'")

        if add_default_dimensions:
            self.add_dimension(
                fg_id,
                FrameDimension(name="sample", metadata_key="sample_id", maintain_mece=True),
                is_sample_dim=True,
            )
            self.add_dimension(
                fg_id,
                FrameDimension(name="experiment", metadata_key="experiment_id", maintain_mece=True),
                is_experiment_dim=True,
            )

        logger.info(f"FrameGrid creation complete. Frontend available at: {self._web_url}/{fg_id}")
        return fg_id

    def add_dimension(
        self,
        fg_id: str,
        dim: FrameDimension,
        is_sample_dim: bool = False,
        is_experiment_dim: bool = False,
    ) -> dict[str, Any]:
        url = f"{self._server_url}/rest/dimension"
        payload = {
            "fg_id": fg_id,
            "dim": dim.model_dump(),
            "is_sample_dim": is_sample_dim,
            "is_experiment_dim": is_experiment_dim,
        }

        response = self._session.post(url, json=payload)
        response.raise_for_status()

        logger.info(f"Successfully added dimension '{dim.name}' to FrameGrid '{fg_id}'")
        return response.json()

    def add_datapoints(self, fg_id: str, datapoints: list[Datapoint]) -> dict[str, Any]:
        url = f"{self._server_url}/rest/datapoints"
        payload = {"fg_id": fg_id, "datapoints": [dp.model_dump() for dp in datapoints]}

        response = self._session.post(url, json=payload)
        response.raise_for_status()

        logger.info(f"Successfully added {len(datapoints)} datapoints to FrameGrid '{fg_id}'")
        return response.json()

    def set_base_filter(self, fg_id: str, filter: FrameFilterTypes | None) -> dict[str, Any]:
        url = f"{self._server_url}/rest/base_filter"
        payload = {
            "fg_id": fg_id,
            "filter": filter.model_dump() if filter else None,
        }

        response = self._session.post(url, json=payload)
        response.raise_for_status()

        logger.info(f"Successfully set base filter for FrameGrid '{fg_id}'")
        return response.json()
