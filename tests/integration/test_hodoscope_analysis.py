import httpx
import pytest


@pytest.mark.integration
async def test_hodoscope_analysis_endpoints_start_reuse_and_cancel(
    authed_client: httpx.AsyncClient,
    test_collection_id: str,
    monkeypatch: pytest.MonkeyPatch,
):
    enqueued_jobs: list[str] = []
    canceled_jobs: list[str] = []

    async def fake_enqueue_job(_ctx, job_id: str):
        enqueued_jobs.append(job_id)

    async def fake_cancel_job(job_id: str):
        canceled_jobs.append(job_id)

    monkeypatch.setattr(
        "docent_core.docent.services.hodoscope.enqueue_job",
        fake_enqueue_job,
    )
    monkeypatch.setattr(
        "docent_core.docent.services.hodoscope.cancel_job",
        fake_cancel_job,
    )

    response = await authed_client.post(
        f"/rest/hodoscope/{test_collection_id}/analyses",
        json={
            "name": "pytest hodoscope",
            "group_by": "metadata.model",
            "limit": 25,
            "seed": 42,
            "projection_method": "tsne",
        },
    )
    assert response.status_code == 200
    started = response.json()
    assert started["collection_id"] == test_collection_id
    assert started["status"] == "pending"
    assert started["stage"] == "pending"
    assert started["config"]["group_by"] == "metadata.model"
    assert started["config"]["limit"] == 25
    assert len(enqueued_jobs) == 1

    response = await authed_client.post(
        f"/rest/hodoscope/{test_collection_id}/analyses",
        json={"name": "should reuse active analysis"},
    )
    assert response.status_code == 200
    reused = response.json()
    assert reused["id"] == started["id"]
    assert len(enqueued_jobs) == 1

    response = await authed_client.get(f"/rest/hodoscope/{test_collection_id}/analyses")
    assert response.status_code == 200
    listed = response.json()
    assert [analysis["id"] for analysis in listed] == [started["id"]]

    response = await authed_client.get(
        f"/rest/hodoscope/{test_collection_id}/analyses/{started['id']}"
    )
    assert response.status_code == 200
    assert response.json()["id"] == started["id"]

    response = await authed_client.get(
        f"/rest/hodoscope/{test_collection_id}/analyses/{started['id']}/projection"
    )
    assert response.status_code == 409

    response = await authed_client.get(
        f"/rest/hodoscope/{test_collection_id}/analyses/{started['id']}/artifact"
    )
    assert response.status_code == 409

    response = await authed_client.post(
        f"/rest/hodoscope/{test_collection_id}/analyses/{started['id']}/cancel"
    )
    assert response.status_code == 200
    canceled = response.json()
    assert canceled["status"] == "canceled"
    assert canceled["stage"] == "canceled"
    assert canceled["error"] == "Canceled by user"
    assert canceled_jobs == [started["job_id"]]
