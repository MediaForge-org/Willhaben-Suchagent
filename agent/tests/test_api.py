import httpx
import pytest


@pytest.mark.asyncio
async def test_empty_database_and_health_start_correctly(api_client: httpx.AsyncClient) -> None:
    searches = await api_client.get("/api/v1/searches")
    health = await api_client.get("/health")

    assert searches.status_code == 200
    assert searches.json() == []
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["active_searches"] == 0
    assert health.json()["total_cycle_count"] == 0


@pytest.mark.asyncio
async def test_search_crud_lifecycle(api_client: httpx.AsyncClient) -> None:
    payload = {
        "name": "Notebook",
        "category": "marketplace",
        "query": "ThinkPad",
        "location": "Graz",
        "price_min": "100",
        "price_max": "1200",
        "category_filters": {"condition": "used"},
    }
    created_response = await api_client.post("/api/v1/searches", json=payload)
    assert created_response.status_code == 201
    created = created_response.json()
    assert created["baseline_initialized"] is False

    fetched = await api_client.get(f"/api/v1/searches/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["query"] == "ThinkPad"

    updated = await api_client.patch(
        f"/api/v1/searches/{created['id']}",
        json={"name": "Business Notebook", "enabled": False},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Business Notebook"
    assert updated.json()["enabled"] is False

    listed = await api_client.get("/api/v1/searches")
    assert len(listed.json()) == 1

    deleted = await api_client.delete(f"/api/v1/searches/{created['id']}")
    assert deleted.status_code == 204
    assert (await api_client.get(f"/api/v1/searches/{created['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_search_validation_and_missing_resources(api_client: httpx.AsyncClient) -> None:
    invalid = await api_client.post(
        "/api/v1/searches",
        json={
            "name": "Invalid",
            "category": "marketplace",
            "price_min": 200,
            "price_max": 100,
        },
    )
    assert invalid.status_code == 422
    missing_patch = await api_client.patch(
        "/api/v1/searches/999",
        json={"enabled": False},
    )
    assert missing_patch.status_code == 404
    assert (await api_client.delete("/api/v1/searches/999")).status_code == 404


@pytest.mark.asyncio
async def test_detailed_status_endpoint(api_client: httpx.AsyncClient) -> None:
    response = await api_client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["environment"] == "test"
    assert body["scheduler_running"] is False
    assert body["cycle_interval_seconds"] == 60
    assert body["max_concurrent_requests"] == 2
    assert body["database_counts"] == {
        "searches": 0,
        "listings": 0,
        "search_matches": 0,
        "notifications": 0,
    }
