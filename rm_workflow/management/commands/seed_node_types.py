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

Sprint 10 Phase 3 (architecture doc §29.6/§29.7 item 13): `NODE_CATEGORIES`
(rm_workflow.validation.category_schemas) was replaced wholesale with a
TRIGGER/CONTROL/DATA/ACTION/WORKFLOW/HUMAN taxonomy. `CORE_NODE_TYPES`
and `DEMO_NODE_TYPES` below were updated in the same pass to use valid
categories under the new taxonomy (see each list's own comments). The
original 13 frontend-palette `NODE_TYPES` above them were NOT updated,
with one exception: `transitionNode`'s category, previously the
long-flagged `"transition"` bug this docstring used to describe (not in
`NODE_CATEGORIES` even before Phase 3 -- StageGraphView.put() would
reject any stage graph placing it), is fixed here by giving it a real
category (`"workflow"`) instead of adding `"transition"` to
`NODE_CATEGORIES` for just this one type. The other 12 legacy entries'
categories (`input`/`process`/`output`/`decision`/`condition`/`custom`)
are now stale against the new `NODE_CATEGORIES` and deliberately left
that way: this command doesn't call `full_clean()`, so seeding still
succeeds regardless, and nothing in this codebase actually places one of
these 12 into a real stage graph today (see the comment above
`CORE_NODE_TYPES` below for why the Compiler can't resolve them anyway).
Revisit if/when a real builder-type -> canonical-type mapping is built
and one of these 12 needs to be placeable again.

Sprint 10 Phase 4 (architecture doc §29.7 item 14) appends two new
entries to `CORE_NODE_TYPES`: `workflow.call_workflow` and
`workflow.wait_for_workflow`, both category `"workflow"` and
`execution_strategy="intercept"` (same never-dispatched-to-a-Worker
shape as `control.wait`/`human.approval` above -- see
`rm_workflow_engine`'s `rm_node_engine.call_workflow`/`wait_for_workflow`
for the behaviors and `rm_engine_app.services.execution_service.
ExecutionService` for how the engine acts on their directives).

Sprint 10 Phase 5 (architecture doc §29.7 items 15-16, §29.5) adds a new
list, `FORM_FLOW_NODE_TYPES`, seeding exactly one entry:
`data.fetch_form_submission`. Kept out of `CORE_NODE_TYPES` deliberately
-- it is category "data" (same taxonomy category as `data.transform`)
but, unlike everything else in `CORE_NODE_TYPES`, it is NOT run by the
Core Worker (`run_core_worker.py`'s own docstring: no DB access at all)
-- it runs on a dedicated worker in `rm_platform` (`apps.form_store_worker`)
that can import `rm_form_store`. That worker fleet split is exactly why
this entry sets `routing_group="formstore"` (§29.9's flagged trigger
condition, `NodeType.routing_group`): without it, `task_subject()` would
derive `rm.tasks.data` from the `data.` prefix alone, the SAME subject
the Core Worker already exclusively consumes for `data.transform`, and
two different worker fleets consuming the same subject/queue_group would
misroute each other's tasks. `properties_schema` is empty -- this node
has nothing for a workflow author to configure; it reads `submission_id`/
`form_id` straight from its own `NodeInput.data` (§29.5: the Form
trigger's own `{submission_id, form_id}` start input, passed through
unchanged by `trigger.workflow_started`).
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
        "type": "transitionNode", "label": "Transition", "category": "workflow", "icon": "ArrowRightLeft",
        "description": "Move to the next step or stage",
        "properties_schema": [
            field("text", "target", "Target"),
            field("select", "mode", "Mode", defaultValue="auto", options=[
                {"label": "Auto", "value": "auto"}, {"label": "Manual", "value": "manual"},
            ]),
        ],
    },
]

# Sprint 1 (architecture doc §42): the Compiler (rm_workflow.compiler)
# only resolves `core.*` node types against this registry -- everything
# above this point is the pre-existing, frontend-facing builder palette
# (unchanged). These five are the Runtime DSL's own canonical type
# identifiers (§4A.3/§7): "type" IS the compiled runtime type here, no
# separate builder->runtime mapping table exists yet. A Stage graph node
# that wants to compile in Sprint 1 must set `data.nodeType` to one of
# these five values directly -- the older `processNode`/`conditionNode`/
# etc. entries above are NOT resolvable by the Compiler yet (see
# UnsupportedNodeTypeError in rm_workflow.compiler.compiler) until a real
# builder-type -> canonical-type mapping is designed, which is out of
# Sprint 1's scope.
#
# Sprint 10 Phase 3 (architecture doc §29.6/§29.7 item 13): every `type`
# below is renamed from its original `core.*` identifier --
# `core.input`→`trigger.workflow_started`, `core.condition`→
# `control.condition`, `core.process`→`data.transform`,
# `core.delay`→`control.wait`, `core.approval`→`human.approval` -- and
# each `category` is updated to match (see category_schemas.py's own
# Phase 3 note). Pure rename: no behavior, execution_strategy, or
# properties_schema changed for any of these five.
CORE_NODE_TYPES = [
    {
        "type": "trigger.workflow_started", "label": "Workflow Started", "category": "trigger", "icon": "ArrowDownToLine",
        "description": "Runtime input entry point (Engine Runtime DSL, §4A)",
        "properties_schema": [
            field("text", "source", "Source", placeholder="e.g. upload, api, manual"),
            field("select", "format", "Format", defaultValue="json", options=[
                {"label": "JSON", "value": "json"}, {"label": "CSV", "value": "csv"}, {"label": "XML", "value": "xml"},
            ]),
        ],
    },
    {
        "type": "control.condition", "label": "Condition", "category": "control", "icon": "GitBranch",
        "description": "Evaluate a condition before proceeding",
        "properties_schema": [
            field("text", "expression", "Expression", validation={"required": True}),
            field("text", "trueLabel", "True branch label", defaultValue="Yes"),
            field("text", "falseLabel", "False branch label", defaultValue="No"),
        ],
    },
    {
        "type": "data.transform", "label": "Transform", "category": "data", "icon": "Cog",
        "description": "Transform or process data",
        "properties_schema": [
            field("select", "operation", "Operation", defaultValue="transform", options=[
                {"label": "Transform", "value": "transform"}, {"label": "Validate", "value": "validate"}, {"label": "Enrich", "value": "enrich"},
            ]),
            field("textarea", "script", "Script", placeholder="Transformation logic..."),
        ],
    },
    {
        "type": "control.wait", "label": "Wait", "category": "control", "icon": "Clock",
        "description": "Wait for specified time",
        # Sprint 10 Phase 1 (architecture doc §29): handled in-process by
        # the Engine (rm_node_engine, Phase 2+), never dispatched to a
        # Worker -- same WAITING behavior this node type already has
        # today, just reached via execution_strategy instead of
        # WAIT_NODE_TYPES membership once the Engine reads this field.
        "execution_strategy": "intercept",
        "properties_schema": [
            field("number", "duration", "Duration", defaultValue=5, validation={"min": 0}),
            field("select", "unit", "Unit", defaultValue="seconds", options=[
                {"label": "Seconds", "value": "seconds"}, {"label": "Minutes", "value": "minutes"}, {"label": "Hours", "value": "hours"},
            ]),
        ],
    },
    {
        # Sprint 7 (architecture doc §8's HUMAN category / §40.7): the
        # Engine (rm_engine_app) never dispatches this to a Worker -- it
        # goes straight to NodeExecutionStatus.WAITING with no resume_at
        # (see rm_engine_app.services.wait_nodes.compute_resume_at), and
        # only leaves WAITING via the resume API endpoint
        # (POST /api/engine/executions/<id>/nodes/<id>/resume).
        "type": "human.approval", "label": "Approval", "category": "human", "icon": "Zap",
        "description": "Pause the workflow until a human approves or provides input via the resume endpoint",
        # Sprint 10 Phase 1 (architecture doc §29): same rationale as
        # control.wait above -- never dispatched to a Worker.
        "execution_strategy": "intercept",
        "properties_schema": [
            field("textarea", "instructions", "Instructions", placeholder="What should the approver check?"),
            field("text", "assignee", "Assignee", placeholder="e.g. an email or user id (informational only -- not enforced yet)"),
        ],
    },
    {
        # Sprint 10 Phase 4 (architecture doc §29.7 item 14): fire-and-
        # forget -- starts a new WorkflowExecution and immediately
        # succeeds with the new execution's id as output, never blocking
        # on it (workflow.wait_for_workflow, below, is the node that
        # blocks). Never dispatched to a Worker -- same rationale as
        # control.wait/human.approval above.
        "type": "workflow.call_workflow", "label": "Call Workflow", "category": "workflow", "icon": "Workflow",
        "description": "Start another workflow, without waiting for it to finish",
        "execution_strategy": "intercept",
        "properties_schema": [
            field("text", "workflow_id", "Workflow", placeholder="target workflow's public id", validation={"required": True}),
            field("keyValue", "input", "Input", placeholder="optional -- defaults to this node's own input if left empty"),
        ],
    },
    {
        # Sprint 10 Phase 4 (architecture doc §29.7 item 14): suspends
        # until the named WorkflowExecution reaches SUCCESS/FAILED --
        # typically chained after a workflow.call_workflow node via
        # `$call_node.execution_id` (§29.8's `interpolate()`). Never
        # dispatched to a Worker -- same rationale as control.wait/
        # human.approval above.
        "type": "workflow.wait_for_workflow", "label": "Wait For Workflow", "category": "workflow", "icon": "Clock",
        "description": "Pause until another workflow execution finishes, then continue with its result",
        "execution_strategy": "intercept",
        "properties_schema": [
            field("text", "execution_id", "Execution ID", placeholder="e.g. $call_node.execution_id", validation={"required": True}),
        ],
    },
]

# Sprint 5: rm_connector_demo's two capabilities (architecture doc's
# Sprint 5 goal -- prove the full connector path end-to-end). Seeded as
# global (tenant_id=None) node types like CORE_NODE_TYPES above, now that
# the Compiler's allow-list (rm_workflow.conf.RM_WORKFLOW.
# ALLOWED_NODE_TYPE_PREFIXES, default ["*"]) no longer hardcodes core.*
# as the only compilable prefix -- see compiler.py's module docstring.
#
# Sprint 10 Phase 3 (architecture doc §29.6/§29.7 item 13): category
# changed from "custom" (removed by the NODE_CATEGORIES replacement, see
# category_schemas.py's own Phase 3 note) to "action" -- both of these
# node types perform a one-shot side-effecting action, which is the
# closest fit in the new taxonomy. `type` is unaffected: neither is a
# `core.*` identifier, so Phase 3's rename doesn't touch them.
DEMO_NODE_TYPES = [
    {
        "type": "demo.log_message", "label": "Demo: Log Message", "category": "action", "icon": "Zap",
        "description": "Logs a message to the demo connector worker's output -- no connection required.",
        "properties_schema": [
            field("text", "message", "Message", placeholder="Hello from RipenMango", validation={"required": True}),
        ],
    },
    {
        "type": "demo.echo_with_connection", "label": "Demo: Echo With Connection", "category": "action", "icon": "ArrowRightLeft",
        "description": (
            "Round-trips a message plus a Connection's id through the demo connector worker -- "
            "proves connection_id flows end-to-end (§13's TaskMessage.connection_id) without "
            "calling ConnectionManager.resolve() yet (Sprint 5 fakes credential resolution; a "
            "real internal resolve mechanism is a follow-up)."
        ),
        "properties_schema": [
            field("text", "message", "Message", placeholder="Hello from RipenMango", validation={"required": True}),
            field("connectionRef", "connectionId", "Connection", connectionProvider="demo", validation={"required": True}),
        ],
    },
]

# Sprint 10 Phase 5 (architecture doc §29.7 items 15-16, §29.5) -- see this
# file's own module docstring for why this is a separate list from
# CORE_NODE_TYPES rather than appended to it.
#
# Sprint 10 Phase 7 addition (architecture doc §29.7 items 19-21):
# `properties_schema` gained a `form_id` (formRef) field, where Phase 5
# originally left it empty ("this node has nothing for a workflow author
# to configure"). This is a deviation from that Phase 5 statement, not a
# silent edit of it -- recorded here and in the architecture doc's new
# §29.13. The field is a BUILDER-TIME-ONLY hint: it changes nothing about
# how this node runs (it still reads submission_id/form_id from its own
# NodeInput.data at execution time, per §29.5 point 3 -- runtime behavior
# is unaffected by whatever's selected here). Its sole purpose is letting
# rm_workflow_client's `$` autocomplete (getAvailableAttributes, item 20)
# know WHICH form's field schema to fetch and offer downstream, since
# NodeType.output_schema can't express a per-node, per-selection dynamic
# shape (§29.8's documented exception) -- a workflow author picks the
# form this node is expected to see submissions from, purely so the
# builder can show the right `$field` suggestions.
FORM_FLOW_NODE_TYPES = [
    {
        "type": "data.fetch_form_submission", "label": "Fetch Form Submission", "category": "data", "icon": "ArrowDownToLine",
        "description": (
            "Resolves a Form-triggered execution's submission_id/form_id into the submission's "
            "actual field values. The standard first real step after a Form trigger -- runs on a "
            "dedicated worker (rm_platform's apps.form_store_worker), never the Core Worker."
        ),
        # execution_strategy defaults to "worker" (Command.handle()'s own
        # .get() below) -- a real dispatch over the wire, just to a
        # DIFFERENT worker fleet than data.transform/control.condition,
        # which is exactly what routing_group (below) is for.
        "routing_group": "formstore",
        "properties_schema": [
            field(
                "formRef", "form_id", "Form",
                helpText=(
                    "Which form this node resolves submissions against -- used only by the "
                    "workflow builder's $ autocomplete (Phase 7) to know this node's available "
                    "output fields. Not read at runtime: the real submission_id/form_id always "
                    "come from the triggering execution's own input (§29.5), regardless of "
                    "what's selected here."
                ),
            ),
        ],
    },
]

# Sprint 10 Phase 6 (architecture doc §29.7 items 17-18) -- the second
# half of §29.8's first end-to-end use case (data.fetch_form_submission ->
# control.condition -> action.slack_send/action.whatsapp_send). Kept as
# its own list for the same reason FORM_FLOW_NODE_TYPES is: these run on
# yet another dedicated worker fleet (rm_platform's apps.outbound_worker),
# never the Core Worker -- see that app's plugin.py/apps.py docstrings.
#
# Unlike data.fetch_form_submission, no routing_group override is set:
# both node types share the `action.` prefix, and nothing else in this
# codebase runs an `action.*` node type yet (rm_connector_demo's demo.*
# types are their own `demo.` prefix) -- so task_subject()'s ordinary
# prefix-derived "rm.tasks.action" is already collision-free. Revisit only
# if a future `action.*` node type needs its own independently-scaled
# worker fleet separate from this one (§29.9's already-flagged trigger
# condition).
#
# `output_schema` is set on both (item 17: "Each declares a static
# NodeType.output_schema... so Phase 7's frontend work has something to
# read") -- a plain JSON Schema describing NodeResult.output, read by
# Command.handle() below the same way properties_schema/execution_strategy
# already are.
ACTION_NODE_TYPES = [
    {
        "type": "action.slack_send", "label": "Slack: Send Message", "category": "action", "icon": "Zap",
        "description": (
            "Sends a message to a Slack channel via chat.postMessage, using a Slack "
            "connectionId resolved to a real credential at execution time. Runs on the "
            "Outbound Messaging Worker (rm_platform's apps.outbound_worker), never the "
            "Core Worker."
        ),
        "output_schema": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}},
        },
        "properties_schema": [
            field("connectionRef", "connectionId", "Connection", connectionProvider="slack", validation={"required": True}),
            field("text", "channel", "Channel", placeholder="e.g. #general or a channel id", validation={"required": True}),
            field("textarea", "message", "Message", placeholder="Hi $name, welcome to Ripen Mango", validation={"required": True}),
        ],
    },
    {
        "type": "action.whatsapp_send", "label": "WhatsApp: Send Message", "category": "action", "icon": "Zap",
        "description": (
            "Sends a text message via the WhatsApp Cloud API, using a WhatsApp "
            "connectionId resolved to a real credential at execution time. Runs on the "
            "Outbound Messaging Worker (rm_platform's apps.outbound_worker), never the "
            "Core Worker."
        ),
        "output_schema": {
            "type": "object",
            "properties": {"message_id": {"type": "string"}},
        },
        "properties_schema": [
            field("connectionRef", "connectionId", "Connection", connectionProvider="whatsapp", validation={"required": True}),
            field("text", "to", "To (phone number)", placeholder="e.g. 15551234567", validation={"required": True}),
            field("textarea", "message", "Message", placeholder="Hi $name, welcome to Ripen Mango", validation={"required": True}),
        ],
    },
]

NODE_TYPES = NODE_TYPES + CORE_NODE_TYPES + DEMO_NODE_TYPES + FORM_FLOW_NODE_TYPES + ACTION_NODE_TYPES


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
                    "execution_strategy": entry.get("execution_strategy", "worker"),
                    # Sprint 10 Phase 5 (architecture doc §29.7 items
                    # 15-16/§29.9): None for every entry that doesn't set
                    # one (everything before Phase 5) -- see
                    # NodeType.routing_group's own field comment.
                    "routing_group": entry.get("routing_group"),
                    # Sprint 10 Phase 6 (architecture doc §29.7 item 17):
                    # was missing entirely before this phase -- NodeType.
                    # output_schema has existed since Phase 1 (item 3), but
                    # nothing set it here because nothing needed to read it
                    # yet ("unused until Phase 7", NodeType's own field
                    # comment). ACTION_NODE_TYPES is the first entry that
                    # actually declares one; None (unchanged) for every
                    # other entry that doesn't.
                    "output_schema": entry.get("output_schema"),
                    "is_active": True,
                },
            )
            created += int(was_created)
            updated += int(not was_created)

        self.stdout.write(self.style.SUCCESS(f"Seeded node types: {created} created, {updated} updated."))
