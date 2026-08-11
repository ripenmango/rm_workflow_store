"""
Seeds the global (tenant_id=NULL) node type catalog -- the 13 node types
that used to live as a hardcoded array in rm_workflow_client's mockData.ts
(defaultNodeDefinitions + dynamicNodeDefinitions), each with the
propertiesSchema PropertyField[] the frontend's PropertyFieldRenderer
consumes (see property-dsl.ts). Idempotent: safe to re-run, e.g. after
adding a new node type here -- matched on (tenant_id=None, type), existing
rows are updated in place rather than duplicated.

Run after `migrate`:
    python manage.py seed_node_types

NOTE: the 'transition' category (transitionNode, below) is NOT currently in
rm_workflow.validation.category_schemas.NODE_CATEGORIES on the backend --
this command does not call full_clean(), so seeding succeeds regardless,
but StageGraphView.put() will reject any stage graph that actually places a
transitionNode today (GraphValidationError: unknown category). This is a
pre-existing frontend/backend mismatch this command surfaces, not one it
introduces -- flag to whoever owns category_schemas.py: either add
"transition" to NODE_CATEGORIES, or change transitionNode's category to an
existing one.
"""
from django.core.management.base import BaseCommand

from rm_workflow.node_types.models import NodeType


def field(type_, key, label, **kwargs):
    return {"id": f"prop_{key}", "key": key, "type": type_, "label": label, "validation": kwargs.pop("validation", {}), **kwargs}


NODE_TYPES = [
    {
        "type": "inputNode", "label": "Input", "category": "input", "icon": "ArrowDownToLine",
        "description": "Data entry point",
        "properties_schema": [
            field("text", "source", "Source", placeholder="e.g. upload, api, manual"),
            field("select", "format", "Format", defaultValue="json", options=[
                {"label": "JSON", "value": "json"}, {"label": "CSV", "value": "csv"}, {"label": "XML", "value": "xml"},
            ]),
        ],
    },
    {
        "type": "processNode", "label": "Process", "category": "process", "icon": "Cog",
        "description": "Transform or process data",
        "properties_schema": [
            field("select", "operation", "Operation", defaultValue="transform", options=[
                {"label": "Transform", "value": "transform"}, {"label": "Validate", "value": "validate"}, {"label": "Enrich", "value": "enrich"},
            ]),
            field("textarea", "script", "Script", placeholder="Transformation logic..."),
        ],
    },
    {
        "type": "outputNode", "label": "Output", "category": "output", "icon": "ArrowUpFromLine",
        "description": "Data output destination",
        "properties_schema": [
            field("text", "destination", "Destination", placeholder="e.g. database, webhook, file"),
            field("select", "format", "Format", defaultValue="json", options=[
                {"label": "JSON", "value": "json"}, {"label": "CSV", "value": "csv"}, {"label": "XML", "value": "xml"},
            ]),
        ],
    },
    {
        "type": "decisionNode", "label": "Decision", "category": "decision", "icon": "GitBranch",
        "description": "Conditional branching",
        "properties_schema": [
            field("text", "condition", "Condition", placeholder='e.g. status == "approved"', validation={"required": True}),
            field("text", "trueLabel", "True branch label", defaultValue="Yes"),
            field("text", "falseLabel", "False branch label", defaultValue="No"),
        ],
    },
    {
        "type": "apiCallNode", "label": "API Call", "category": "custom", "icon": "Globe",
        "description": "Make HTTP requests",
        "properties_schema": [
            field("url", "url", "URL", placeholder="https://api.example.com/endpoint", validation={"required": True}),
            field("select", "method", "Method", defaultValue="GET", options=[
                {"label": m, "value": m} for m in ["GET", "POST", "PUT", "PATCH", "DELETE"]
            ]),
            field("keyValue", "headers", "Headers"),
            field("checkbox", "useAuth", "Requires authentication"),
            field("text", "token", "Token", secret=True, visibleWhen={"field": "useAuth", "op": "equals", "value": "true"}),
        ],
    },
    {
        "type": "emailNode", "label": "Send Email", "category": "custom", "icon": "Mail",
        "description": "Send email notifications",
        "properties_schema": [
            field("text", "to", "To", placeholder="recipient@example.com", validation={"required": True}),
            field("text", "subject", "Subject"),
            field("textarea", "body", "Body"),
        ],
    },
    {
        "type": "delayNode", "label": "Delay", "category": "custom", "icon": "Clock",
        "description": "Wait for specified time",
        "properties_schema": [
            field("number", "duration", "Duration", defaultValue=5, validation={"min": 0}),
            field("select", "unit", "Unit", defaultValue="seconds", options=[
                {"label": "Seconds", "value": "seconds"}, {"label": "Minutes", "value": "minutes"}, {"label": "Hours", "value": "hours"},
            ]),
        ],
    },
    {
        "type": "filterNode", "label": "Filter", "category": "process", "icon": "Filter",
        "description": "Filter data by conditions",
        "properties_schema": [
            field("text", "field", "Field", validation={"required": True}),
            field("select", "operator", "Operator", defaultValue="equals", options=[
                {"label": "Equals", "value": "equals"}, {"label": "Contains", "value": "contains"},
                {"label": "Greater than", "value": "greaterThan"}, {"label": "Less than", "value": "lessThan"},
            ]),
            field("text", "value", "Value"),
        ],
    },
    {
        "type": "webhookNode", "label": "Webhook", "category": "input", "icon": "Webhook",
        "description": "Listen for webhook events",
        "properties_schema": [
            field("text", "path", "Path", defaultValue="/webhook"),
            field("select", "method", "Method", defaultValue="POST", options=[
                {"label": "POST", "value": "POST"}, {"label": "PUT", "value": "PUT"},
            ]),
        ],
    },
    {
        "type": "workflowTriggerNode", "label": "Workflow Trigger", "category": "output", "icon": "Workflow",
        "description": "Trigger another workflow when this completes",
        "properties_schema": [
            field("select", "triggerOn", "Trigger on", defaultValue="completion", options=[
                {"label": "Completion", "value": "completion"}, {"label": "Error", "value": "error"},
            ]),
        ],
    },
    {
        "type": "actionNode", "label": "Action", "category": "action", "icon": "Zap",
        "description": "Perform an action within a step",
        "properties_schema": [
            field("text", "action", "Action", validation={"required": True}),
            field("keyValue", "params", "Params"),
        ],
    },
    {
        "type": "conditionNode", "label": "Condition", "category": "condition", "icon": "GitBranch",
        "description": "Evaluate a condition before proceeding",
        "properties_schema": [
            field("text", "expression", "Expression", validation={"required": True}),
            field("text", "trueLabel", "True branch label", defaultValue="Yes"),
            field("text", "falseLabel", "False branch label", defaultValue="No"),
        ],
    },
    {
        "type": "transitionNode", "label": "Transition", "category": "transition", "icon": "ArrowRightLeft",
        "description": "Move to the next step or stage",
        "properties_schema": [
            field("text", "target", "Target"),
            field("select", "mode", "Mode", defaultValue="auto", options=[
                {"label": "Auto", "value": "auto"}, {"label": "Manual", "value": "manual"},
            ]),
        ],
    },
]


class Command(BaseCommand):
    help = "Seeds the global node type catalog (see this file's module docstring)."

    def handle(self, *args, **options):
        created, updated = 0, 0
        for entry in NODE_TYPES:
            obj, was_created = NodeType.objects.update_or_create(
                tenant_id=None,
                type=entry["type"],
                defaults={
                    "label": entry["label"],
                    "category": entry["category"],
                    "icon": entry["icon"],
                    "description": entry["description"],
                    "properties_schema": entry["properties_schema"],
                    "is_active": True,
                },
            )
            created += int(was_created)
            updated += int(not was_created)

        self.stdout.write(self.style.SUCCESS(f"Seeded node types: {created} created, {updated} updated."))
