import hashlib
import hmac

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.domain.enums import ExecutionStatus
from app.domain.models import Execution


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


def webhook_signature(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


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


def test_manual_endpoint_rejects_trigger_classification_override(client: TestClient) -> None:
    workflow = create_workflow(client)

    response = client.post(
        f"/api/v1/workflows/{workflow['id']}/executions",
        json={"input_payload": {}, "trigger_type": "webhook"},
        headers={"X-Idempotency-Key": "classification-override-0001"},
    )

    assert response.status_code == 422


def test_signed_webhook_is_idempotent(client: TestClient, webhook_secret: str) -> None:
    workflow = create_workflow(client)
    body = b'{"risk":"high","source":"identity-provider"}'
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Event-ID": "identity-event-0001",
        "X-Webhook-Signature": webhook_signature(body, webhook_secret),
    }
    path = f"/api/v1/workflows/{workflow['id']}/webhook"

    first = client.post(path, content=body, headers=headers)
    replay = client.post(path, content=body, headers=headers)

    assert first.status_code == 202
    assert first.json()["trigger_type"] == "webhook"
    assert first.json()["input_payload"]["source"] == "identity-provider"
    assert replay.headers["Idempotent-Replay"] == "true"
    assert replay.json()["id"] == first.json()["id"]


def test_webhook_rejects_invalid_signature(client: TestClient) -> None:
    workflow = create_workflow(client)

    response = client.post(
        f"/api/v1/workflows/{workflow['id']}/webhook",
        content=b'{"risk":"high"}',
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Event-ID": "identity-event-0002",
            "X-Webhook-Signature": "sha256=invalid",
        },
    )

    assert response.status_code == 401


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


def test_execution_history_can_be_filtered(client: TestClient) -> None:
    first_workflow = create_workflow(client)
    second_payload = workflow_payload()
    second_payload["name"] = "vendor-access-review"
    second_workflow = client.post("/api/v1/workflows", json=second_payload).json()
    first_execution = client.post(
        f"/api/v1/workflows/{first_workflow['id']}/executions",
        json={"input_payload": {}},
        headers={"X-Idempotency-Key": "history-request-0001"},
    ).json()
    client.post(
        f"/api/v1/workflows/{second_workflow['id']}/executions",
        json={"input_payload": {}},
        headers={"X-Idempotency-Key": "history-request-0002"},
    )

    response = client.get(
        "/api/v1/executions",
        params={"workflow_id": first_workflow["id"], "status": "queued"},
        headers={"X-Dev-Roles": "viewer"},
    )

    assert response.status_code == 200
    assert [execution["id"] for execution in response.json()] == [first_execution["id"]]


def test_manual_retry_requires_dead_letter_state(client: TestClient) -> None:
    workflow = create_workflow(client)
    execution = client.post(
        f"/api/v1/workflows/{workflow['id']}/executions",
        json={"input_payload": {}},
        headers={"X-Idempotency-Key": "access-review-user-44"},
    ).json()

    response = client.post(f"/api/v1/executions/{execution['id']}/retry")

    assert response.status_code == 409


def test_manual_retry_resets_attempt_budget(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> None:
    workflow = create_workflow(client)
    execution_data = client.post(
        f"/api/v1/workflows/{workflow['id']}/executions",
        json={"input_payload": {}},
        headers={"X-Idempotency-Key": "access-review-user-45"},
    ).json()
    with session_factory() as session:
        execution = session.get(Execution, execution_data["id"])
        assert execution is not None
        execution.status = ExecutionStatus.DEAD_LETTER
        execution.attempt_count = 3
        execution.last_error_code = "dependency_unavailable"
        execution.last_error_message = "Dependency unavailable"
        session.commit()

    response = client.post(f"/api/v1/executions/{execution_data['id']}/retry")

    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    assert response.json()["attempt_count"] == 0
    assert response.json()["last_error_code"] is None
    audit = client.get(f"/api/v1/executions/{execution_data['id']}/audit").json()
    assert audit[-1]["details"]["prior_attempt_count"] == 3


def test_operator_can_cancel_queued_execution(client: TestClient) -> None:
    workflow = create_workflow(client)
    execution = client.post(
        f"/api/v1/workflows/{workflow['id']}/executions",
        json={"input_payload": {}},
        headers={"X-Idempotency-Key": "cancel-request-0001"},
    ).json()

    response = client.post(
        f"/api/v1/executions/{execution['id']}/cancel",
        headers={"X-Dev-Roles": "operator"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "cancelled"
    assert response.json()["finished_at"] is not None


def test_admin_can_schedule_active_workflow(client: TestClient) -> None:
    workflow = create_workflow(client)

    created = client.post(
        f"/api/v1/workflows/{workflow['id']}/schedules",
        json={"interval_seconds": 300},
    )
    listed = client.get(
        f"/api/v1/workflows/{workflow['id']}/schedules",
        headers={"X-Dev-Roles": "viewer"},
    )

    assert created.status_code == 201
    assert created.json()["interval_seconds"] == 300
    assert listed.status_code == 200
    assert [schedule["id"] for schedule in listed.json()] == [created.json()["id"]]


def test_draft_workflow_cannot_be_scheduled(client: TestClient) -> None:
    workflow = create_workflow(client, status="draft")

    response = client.post(
        f"/api/v1/workflows/{workflow['id']}/schedules",
        json={"interval_seconds": 300},
    )

    assert response.status_code == 409


def test_schedule_start_requires_timezone(client: TestClient) -> None:
    workflow = create_workflow(client)

    response = client.post(
        f"/api/v1/workflows/{workflow['id']}/schedules",
        json={"interval_seconds": 300, "starts_at": "2026-09-10T12:00:00"},
    )

    assert response.status_code == 422


def test_platform_health_endpoints(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/ready").json() == {"status": "ready"}
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "python_info" in metrics.text
