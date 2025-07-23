import httpx
import pytest


@pytest.mark.integration
async def test_default_chart(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
):
    # Upload a bit of data
    with open("tests/integration/test_data/ctf.json", "rb") as f:
        file_content = f.read()
    response = await authed_client.post(
        f"/rest/{test_collection_id}/import_runs_from_file",
        files={"file": ("abc.json", file_content, "application/json")},
    )

    # Create a chart, leave default settings
    response = await authed_client.post(
        f"/rest/chart/{test_collection_id}/create",
        json={},
    )
    assert response.status_code == 200
    data = response.json()
    chart_id = data["id"]
    assert chart_id is not None

    # Backend should choose default settings that show us some sort of data
    response = await authed_client.get(
        f"/rest/chart/{test_collection_id}/{chart_id}/data",
    )
    assert response.status_code == 200
    data = response.json()
    stats = data["result"]["binStats"]

    assert stats != {}
