from dataclasses import dataclass
from typing import Protocol

from app.domain.types import JsonObject


class StepFailure(RuntimeError):
    code = "step_failed"
    transient = False


class TransientStepFailure(StepFailure):
    transient = True


class PermanentStepFailure(StepFailure):
    transient = False


@dataclass(frozen=True)
class StepContext:
    execution_id: str
    input_payload: JsonObject
    accumulated_output: JsonObject


class StepRunner(Protocol):
    def run(self, kind: str, config: JsonObject, context: StepContext) -> JsonObject: ...


class DefaultStepRunner:
    def run(self, kind: str, config: JsonObject, context: StepContext) -> JsonObject:
        if kind == "assign":
            return self._assign(config)
        if kind == "condition":
            return self._condition(config, context)
        if kind == "emit_event":
            return self._emit_event(config)
        raise PermanentStepFailure(f"Unsupported step kind: {kind}")

    def _assign(self, config: JsonObject) -> JsonObject:
        target = config.get("target")
        if not isinstance(target, str) or not target:
            raise PermanentStepFailure("assign.target must be a non-empty string")
        return {target: config.get("value")}

    def _condition(self, config: JsonObject, context: StepContext) -> JsonObject:
        field = config.get("field")
        if not isinstance(field, str) or not field:
            raise PermanentStepFailure("condition.field must be a non-empty string")
        actual = context.accumulated_output.get(field, context.input_payload.get(field))
        return {"field": field, "matched": actual == config.get("equals")}

    def _emit_event(self, config: JsonObject) -> JsonObject:
        event_name = config.get("event_name")
        if not isinstance(event_name, str) or not event_name:
            raise PermanentStepFailure("emit_event.event_name must be a non-empty string")
        payload = config.get("payload", {})
        if not isinstance(payload, dict):
            raise PermanentStepFailure("emit_event.payload must be an object")
        return {"event_name": event_name, "payload": payload}
