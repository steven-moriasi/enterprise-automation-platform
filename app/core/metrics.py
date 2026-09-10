from prometheus_client import Counter, Histogram

execution_outcomes = Counter(
    "automation_execution_outcomes_total",
    "Workflow execution terminal outcomes",
    ["status"],
)
execution_duration = Histogram(
    "automation_execution_duration_seconds",
    "Workflow execution attempt duration",
)
step_outcomes = Counter(
    "automation_step_outcomes_total",
    "Workflow step outcomes",
    ["kind", "status"],
)
