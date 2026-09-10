from fastapi.testclient import TestClient


def workflow_payload(*, status: str = "active") -> dict[str, object]:
    return {
        "name": "employee-access-review",
        "description": "Reference access review",
        "status": status,
        "steps": [
            {
                "name": "assign-owner",
                "kind": "assign",
                "config": {"target": "owner", "value": "iam-operations"},
            }
        ],
    }


def create_workflow(client: TestClient, *, status: str = "active") -> dict[str, object]:
    response = client.post("/api/v1/workflows", json=workflow_payload(status=status))
    assert response.status_code == 201
    return response.json()


def test_workflow_creation_requires_admin_role(client: TestClient) -> None:
    response = client.post(
        "/api/v1/workflows",
        json=workflow_payload(),
        headers={"X-Dev-Roles": "operator"},
    )

    assert response.status_code == 403


def test_duplicate_workflow_version_is_rejected(client: TestClient) -> None:
    create_workflow(client)

    response = client.post("/api/v1/workflows", json=workflow_payload())

    assert response.status_code == 409


def test_workflow_definition_rejects_embedded_secrets(client: TestClient) -> None:
    payload = workflow_payload()
    steps = payload["steps"]
    assert isinstance(steps, list)
    step = steps[0]
    assert isinstance(step, dict)
    step["config"] = {"api_key": "must-not-be-stored"}

    response = client.post("/api/v1/workflows", json=payload)

    assert response.status_code == 422


def test_draft_workflow_cannot_be_executed(client: TestClient) -> None:
    workflow = create_workflow(client, status="draft")

    response = client.post(
        f"/api/v1/workflows/{workflow['id']}/executions",
        json={"input_payload": {}},
        headers={"X-Idempotency-Key": "draft-run-0001"},
    )

    assert response.status_code == 409


def test_execution_request_is_idempotent(client: TestClient) -> None:
    workflow = create_workflow(client)
    path = f"/api/v1/workflows/{workflow['id']}/executions"
    headers = {
        "X-Idempotency-Key": "access-review-user-42",
        "X-Correlation-ID": "correlation-user-42",
    }

    first = client.post(path, json={"input_payload": {"risk": "high"}}, headers=headers)
    replay = client.post(path, json={"input_payload": {"risk": "low"}}, headers=headers)

    assert first.status_code == 202
    assert replay.status_code == 202
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["input_payload"] == {"risk": "high"}


def test_execution_and_audit_are_visible_to_viewer(client: TestClient) -> None:
    workflow = create_workflow(client)
    execution = client.post(
        f"/api/v1/workflows/{workflow['id']}/executions",
        json={"input_payload": {"risk": "high"}},
        headers={"X-Idempotency-Key": "access-review-user-43"},
    ).json()
    viewer_headers = {"X-Dev-Roles": "viewer"}

    execution_response = client.get(
        f"/api/v1/executions/{execution['id']}",
        headers=viewer_headers,
    )
    audit_response = client.get(
        f"/api/v1/executions/{execution['id']}/audit",
        headers=viewer_headers,
    )

    assert execution_response.status_code == 200
    assert execution_response.json()["status"] == "queued"
    assert audit_response.status_code == 200
    assert [event["event_type"] for event in audit_response.json()] == ["execution_requested"]


def test_manual_retry_requires_dead_letter_state(client: TestClient) -> None:
    workflow = create_workflow(client)
    execution = client.post(
        f"/api/v1/workflows/{workflow['id']}/executions",
        json={"input_payload": {}},
        headers={"X-Idempotency-Key": "access-review-user-44"},
    ).json()

    response = client.post(f"/api/v1/executions/{execution['id']}/retry")

    assert response.status_code == 409


def test_platform_health_endpoints(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "python_info" in metrics.text
