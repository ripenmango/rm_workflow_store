from drf_base_app.rest_framework import serializers


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------


class WorkspaceSerializer(serializers.RMSerializer):
    public_id = serializers.CharField(read_only=True)
    name = serializers.CharField()
    description = serializers.CharField(required=False, default="")
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class CreateWorkspaceSerializer(serializers.RMSerializer):
    name = serializers.CharField()
    description = serializers.CharField(required=False, default="")


class UpdateWorkspaceSerializer(serializers.RMSerializer):
    name = serializers.CharField(required=False)
    description = serializers.CharField(required=False)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


class StageSerializer(serializers.RMSerializer):
    public_id = serializers.CharField(read_only=True)
    name = serializers.CharField()
    description = serializers.CharField(required=False, default="")
    order = serializers.IntegerField()
    graph = serializers.JSONField()
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class StageSummarySerializer(serializers.RMSerializer):
    """Used in stage list views -- omits `graph` (§7: the graph JSON is
    fetched per-stage, on demand, not as part of a bulk listing)."""

    public_id = serializers.CharField(read_only=True)
    name = serializers.CharField()
    description = serializers.CharField(required=False, default="")
    order = serializers.IntegerField()
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class CreateStageSerializer(serializers.RMSerializer):
    name = serializers.CharField()
    description = serializers.CharField(required=False, default="")
    order = serializers.IntegerField(required=False)
    graph = serializers.JSONField(required=False, default=dict)


class UpdateStageMetadataSerializer(serializers.RMSerializer):
    # Metadata only -- never `graph` (§10: graph edits go through the
    # dedicated PUT .../graph endpoint below).
    name = serializers.CharField(required=False)
    description = serializers.CharField(required=False)
    order = serializers.IntegerField(required=False)


class StageGraphSerializer(serializers.RMSerializer):
    nodes = serializers.ListField(child=serializers.DictField())
    edges = serializers.ListField(child=serializers.DictField())


class BootstrapStageSerializer(serializers.RMSerializer):
    """Nested only inside CreateWorkflowSerializer's optional `stages`
    bootstrap payload (§10) -- not exposed as its own endpoint input."""

    name = serializers.CharField()
    description = serializers.CharField(required=False, default="")
    order = serializers.IntegerField(required=False)
    graph = serializers.JSONField(required=False, default=dict)


# ---------------------------------------------------------------------------
# Workflow versions
# ---------------------------------------------------------------------------


class WorkflowVersionSerializer(serializers.RMSerializer):
    public_id = serializers.CharField(read_only=True)
    version_number = serializers.IntegerField(read_only=True)
    is_published = serializers.BooleanField(read_only=True)
    published_at = serializers.DateTimeField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


class WorkflowSerializer(serializers.RMSerializer):
    public_id = serializers.CharField(read_only=True)
    workspace = serializers.CharField(source="workspace.public_id", read_only=True)
    name = serializers.CharField()
    description = serializers.CharField(required=False, default="")
    current_version = serializers.CharField(
        source="current_version.public_id", read_only=True, allow_null=True
    )
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class CreateWorkflowSerializer(serializers.RMSerializer):
    name = serializers.CharField()
    description = serializers.CharField(required=False, default="")
    workspace = serializers.CharField()  # Workspace public_id
    # Create-time-only bootstrap allowance (§10) -- does NOT reopen a
    # whole-document write path for later edits; see StageViewSet /
    # StageGraphView for the ongoing per-stage paths.
    stages = BootstrapStageSerializer(many=True, required=False, default=list)


class UpdateWorkflowSerializer(serializers.RMSerializer):
    # Metadata only -- name/description. Never touches stages (§5.1/§10).
    name = serializers.CharField(required=False)
    description = serializers.CharField(required=False)
