from rest_framework import serializers
from rest_framework.exceptions import NotFound, ValidationError

from drf_base_app.rest_framework import Response
from drf_base_app.swagger.decorators import rm_swagger
from drf_base_app.swagger.responses import error_response
from drf_base_app.views import RMAPIView, RMModelViewSet

from rm_auth_tenant.authorization.policy_permission import RequiresPermission
from rm_workflow.api.serializers import (
    CreateStageSerializer,
    CreateWorkflowSerializer,
    CreateWorkspaceSerializer,
    StageGraphSerializer,
    StageSerializer,
    StageSummarySerializer,
    UpdateStageMetadataSerializer,
    UpdateWorkflowSerializer,
    UpdateWorkspaceSerializer,
    WorkflowSerializer,
    WorkflowVersionSerializer,
    WorkspaceSerializer,
)
from rm_workflow.services.graph_service import (
    GraphValidationError,
    StageService,
    StageServiceError,
)
from rm_workflow.services.version_service import VersionService, VersionServiceError
from rm_workflow.services.workflow_service import WorkflowService, WorkflowServiceError
from rm_workflow.services.workspace_service import (
    WorkspaceService,
    WorkspaceServiceError,
)


def _tenant_id(request) -> str:
    return request.security_context.tenant_id


def _get_workflow_or_404(request, workflow_id: str):
    try:
        return WorkflowService().get_workflow(_tenant_id(request), workflow_id)
    except WorkflowServiceError as exc:
        raise NotFound(str(exc))


def _get_version_or_404(request, workflow, version_id: str):
    try:
        return VersionService().get_version(_tenant_id(request), workflow, version_id)
    except VersionServiceError as exc:
        raise NotFound(str(exc))


def _get_stage_or_404(request, workflow_version, stage_id: str):
    try:
        return StageService().get_stage(_tenant_id(request), workflow_version, stage_id)
    except StageServiceError as exc:
        raise NotFound(str(exc))


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------


class WorkspaceViewSet(RMModelViewSet):
    """/api/workflow/workspaces, /api/workflow/workspaces/<workspace_id>"""

    permission_classes = [RequiresPermission("workspace", "manage")]
    lookup_url_kwarg = "workspace_id"

    def get_serializer_class(self):
        if self.action == "create":
            return CreateWorkspaceSerializer
        if self.action in ("update", "partial_update"):
            return UpdateWorkspaceSerializer
        return WorkspaceSerializer

    def get_queryset(self):
        return WorkspaceService().list_workspaces(_tenant_id(self.request))

    def get_object(self):
        try:
            return WorkspaceService().get_workspace(
                _tenant_id(self.request), self.kwargs[self.lookup_url_kwarg]
            )
        except WorkspaceServiceError as exc:
            raise NotFound(str(exc))

    @rm_swagger(
        summary="List workspaces for the current tenant",
        success=WorkspaceSerializer(many=True),
        tags=["Workspaces"],
        auth=["Bearer"],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @rm_swagger(
        summary="Retrieve a workspace",
        success=WorkspaceSerializer,
        responses={404: error_response("Workspace not found.")},
        tags=["Workspaces"],
        auth=["Bearer"],
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @rm_swagger(
        summary="Create a workspace",
        request=CreateWorkspaceSerializer,
        success=WorkspaceSerializer,
        responses={
            400: error_response(
                "Invalid payload, or name already exists for this tenant."
            )
        },
        tags=["Workspaces"],
        auth=["Bearer"],
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        workspace = WorkspaceService().create_workspace(
            _tenant_id(request),
            name=data["name"],
            description=data.get("description", ""),
        )
        return Response(WorkspaceSerializer(workspace).data, status=201)

    @rm_swagger(
        summary="Update a workspace",
        request=UpdateWorkspaceSerializer,
        success=WorkspaceSerializer,
        responses={404: error_response("Workspace not found.")},
        tags=["Workspaces"],
        auth=["Bearer"],
    )
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(
            data=request.data, partial=kwargs.get("partial", False)
        )
        serializer.is_valid(raise_exception=True)

        workspace = WorkspaceService().update_workspace(
            _tenant_id(request), instance.public_id, **serializer.validated_data
        )
        return Response(WorkspaceSerializer(workspace).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @rm_swagger(
        summary="Delete a workspace",
        description="Soft-deletes the workspace (§11) -- it stops appearing "
        "in list/retrieve calls but its rows aren't physically removed.",
        success={"deleted": serializers.BooleanField()},
        responses={404: error_response("Workspace not found.")},
        tags=["Workspaces"],
        auth=["Bearer"],
    )
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        WorkspaceService().delete_workspace(_tenant_id(request), instance.public_id)
        return Response({"deleted": True})


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


class WorkflowViewSet(RMModelViewSet):
    """
    /api/workflow/workflows, /api/workflow/workflows/<workflow_id>

    Update/destroy touch Workflow metadata only -- never stage content (see
    WorkflowService.update_workflow's docstring, and §5.1). Publish/version
    listing/stage management all live on separate endpoints below, not on
    this ViewSet, since they're conceptually distinct operations with their
    own permission checks.
    """

    permission_classes = [RequiresPermission("workflow", "manage")]
    lookup_url_kwarg = "workflow_id"

    def get_serializer_class(self):
        if self.action == "create":
            return CreateWorkflowSerializer
        if self.action in ("update", "partial_update"):
            return UpdateWorkflowSerializer
        return WorkflowSerializer

    def get_queryset(self):
        workspace_id = self.request.query_params.get("workspace")
        return WorkflowService().list_workflows(_tenant_id(self.request), workspace_id)

    def get_object(self):
        return _get_workflow_or_404(self.request, self.kwargs[self.lookup_url_kwarg])

    @rm_swagger(
        summary="List workflows for the current tenant",
        description="Optionally filter by `?workspace=<workspace_id>`.",
        success=WorkflowSerializer(many=True),
        tags=["Workflows"],
        auth=["Bearer"],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @rm_swagger(
        summary="Retrieve a workflow",
        success=WorkflowSerializer,
        responses={404: error_response("Workflow not found.")},
        tags=["Workflows"],
        auth=["Bearer"],
    )
    def retrieve(self, request, *args, **kwargs):
        return super().retrieve(request, *args, **kwargs)

    @rm_swagger(
        summary="Create a workflow",
        description=(
            "Creates a Workflow and its first draft WorkflowVersion. `stages` "
            "is an optional, create-time-only bootstrap (§10) -- pass initial "
            "stages (each with its own `graph`) to seed the draft in the same "
            "request. This is not a general whole-document write path for "
            "later edits; use the stage endpoints below for that."
        ),
        request=CreateWorkflowSerializer,
        success=WorkflowSerializer,
        responses={
            400: error_response(
                "Invalid payload, unknown workspace, or invalid stage graph."
            ),
            404: error_response("Workspace not found."),
        },
        tags=["Workflows"],
        auth=["Bearer"],
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            workflow = WorkflowService().create_workflow(
                tenant_id=_tenant_id(request),
                workspace_public_id=data["workspace"],
                name=data["name"],
                description=data.get("description", ""),
                stages=data.get("stages") or [],
            )
        except WorkflowServiceError as exc:
            message = str(exc)
            if message == "Workspace not found":
                raise NotFound(message)
            raise ValidationError(message)

        return Response(WorkflowSerializer(workflow).data, status=201)

    @rm_swagger(
        summary="Update a workflow",
        description="Metadata only (name/description) -- never touches stages.",
        request=UpdateWorkflowSerializer,
        success=WorkflowSerializer,
        responses={404: error_response("Workflow not found.")},
        tags=["Workflows"],
        auth=["Bearer"],
    )
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(
            data=request.data, partial=kwargs.get("partial", False)
        )
        serializer.is_valid(raise_exception=True)

        workflow = WorkflowService().update_workflow(
            _tenant_id(request), instance.public_id, **serializer.validated_data
        )
        return Response(WorkflowSerializer(workflow).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    @rm_swagger(
        summary="Delete a workflow",
        description="Soft-deletes the workflow (§11).",
        success={"deleted": serializers.BooleanField()},
        responses={404: error_response("Workflow not found.")},
        tags=["Workflows"],
        auth=["Bearer"],
    )
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        WorkflowService().delete_workflow(_tenant_id(request), instance.public_id)
        return Response({"deleted": True})


class PublishWorkflowView(RMAPIView):
    """POST /api/workflow/workflows/<workflow_id>/publish"""

    permission_classes = [RequiresPermission("workflow", "publish")]

    @rm_swagger(
        summary="Publish a workflow's current draft",
        description=(
            "Copy-on-publish (§5.2): creates a new WorkflowVersion, "
            "duplicates every Stage from the current draft onto it, marks it "
            "published, and makes it the workflow's current_version."
        ),
        success=WorkflowVersionSerializer,
        responses={404: error_response("Workflow not found.")},
        tags=["Workflows"],
        auth=["Bearer"],
    )
    def post(self, request, workflow_id):
        workflow = _get_workflow_or_404(request, workflow_id)
        try:
            version = VersionService().publish(_tenant_id(request), workflow)
        except VersionServiceError as exc:
            raise ValidationError(str(exc))
        return Response(WorkflowVersionSerializer(version).data, status=201)


class WorkflowVersionListView(RMAPIView):
    """GET /api/workflow/workflows/<workflow_id>/versions"""

    permission_classes = [RequiresPermission("workflow", "view")]

    @rm_swagger(
        summary="List a workflow's versions",
        success=WorkflowVersionSerializer(many=True),
        responses={404: error_response("Workflow not found.")},
        tags=["Workflows"],
        auth=["Bearer"],
    )
    def get(self, request, workflow_id):
        workflow = _get_workflow_or_404(request, workflow_id)
        versions = VersionService().list_versions(_tenant_id(request), workflow)
        return Response(WorkflowVersionSerializer(versions, many=True).data)


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------


class StageListCreateView(RMAPIView):
    """
    GET/POST /api/workflow/workflows/<workflow_id>/versions/<version_id>/stages

    Ongoing stage creation for an existing draft (as opposed to
    CreateWorkflowSerializer's create-time-only bootstrap, §10).
    """

    permission_classes = [RequiresPermission("workflow", "edit")]

    @rm_swagger(
        summary="List stages for a workflow version",
        description="Returns stage metadata only, without `graph` (§7) -- "
        "fetch a stage individually for its graph content.",
        success=StageSummarySerializer(many=True),
        responses={404: error_response("Workflow or version not found.")},
        tags=["Stages"],
        auth=["Bearer"],
    )
    def get(self, request, workflow_id, version_id):
        workflow = _get_workflow_or_404(request, workflow_id)
        version = _get_version_or_404(request, workflow, version_id)
        stages = StageService().list_stages(_tenant_id(request), version)
        return Response(StageSummarySerializer(stages, many=True).data)

    @rm_swagger(
        summary="Add a stage to a workflow version",
        request=CreateStageSerializer,
        success=StageSerializer,
        responses={
            400: error_response("Invalid payload or invalid graph."),
            404: error_response("Workflow or version not found."),
        },
        tags=["Stages"],
        auth=["Bearer"],
    )
    def post(self, request, workflow_id, version_id):
        workflow = _get_workflow_or_404(request, workflow_id)
        version = _get_version_or_404(request, workflow, version_id)

        serializer = CreateStageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            stage = StageService().create_stage(
                tenant_id=_tenant_id(request),
                workflow_version=version,
                name=data["name"],
                description=data.get("description", ""),
                order=data.get("order"),
                graph=data.get("graph"),
            )
        except GraphValidationError as exc:
            raise ValidationError(str(exc))

        return Response(StageSerializer(stage).data, status=201)


class StageDetailView(RMAPIView):
    """
    GET/PATCH/DELETE
    /api/workflow/workflows/<workflow_id>/versions/<version_id>/stages/<stage_id>

    PATCH here is metadata only (name/description/order) -- see
    StageGraphView for the separate graph write path (§10).
    """

    permission_classes = [RequiresPermission("workflow", "edit")]

    def _get_stage(self, request, workflow_id, version_id, stage_id):
        workflow = _get_workflow_or_404(request, workflow_id)
        version = _get_version_or_404(request, workflow, version_id)
        return _get_stage_or_404(request, version, stage_id)

    @rm_swagger(
        summary="Retrieve a stage",
        success=StageSerializer,
        responses={404: error_response("Workflow, version, or stage not found.")},
        tags=["Stages"],
        auth=["Bearer"],
    )
    def get(self, request, workflow_id, version_id, stage_id):
        stage = self._get_stage(request, workflow_id, version_id, stage_id)
        return Response(StageSerializer(stage).data)

    @rm_swagger(
        summary="Update a stage's metadata",
        description="name/description/order only -- never `graph`.",
        request=UpdateStageMetadataSerializer,
        success=StageSerializer,
        responses={404: error_response("Workflow, version, or stage not found.")},
        tags=["Stages"],
        auth=["Bearer"],
    )
    def patch(self, request, workflow_id, version_id, stage_id):
        stage = self._get_stage(request, workflow_id, version_id, stage_id)
        serializer = UpdateStageMetadataSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        updated = StageService().update_metadata(stage, **serializer.validated_data)
        return Response(StageSerializer(updated).data)

    @rm_swagger(
        summary="Delete a stage",
        description="Soft-deletes the stage (§11).",
        success={"deleted": serializers.BooleanField()},
        responses={404: error_response("Workflow, version, or stage not found.")},
        tags=["Stages"],
        auth=["Bearer"],
    )
    def delete(self, request, workflow_id, version_id, stage_id):
        stage = self._get_stage(request, workflow_id, version_id, stage_id)
        StageService().delete_stage(stage)
        return Response({"deleted": True})


class StageGraphView(RMAPIView):
    """
    PUT /api/workflow/workflows/<workflow_id>/versions/<version_id>/stages/<stage_id>/graph

    The dedicated whole-document write path for a single stage's canvas
    (§10) -- saved independently of the stage's own metadata and of every
    other stage in the same version (§5.1).
    """

    permission_classes = [RequiresPermission("workflow", "edit")]

    @rm_swagger(
        summary="Replace a stage's graph",
        description=(
            "Whole-document replace of `{nodes, edges}` for this stage only. "
            "Validated for structural integrity (unique node/edge ids, every "
            "edge's source/target referencing a node present in this same "
            "document) and per-category node data (§8/§9) before it's saved."
        ),
        request=StageGraphSerializer,
        success=StageSerializer,
        responses={
            400: error_response("Invalid graph."),
            404: error_response("Workflow, version, or stage not found."),
        },
        tags=["Stages"],
        auth=["Bearer"],
    )
    def put(self, request, workflow_id, version_id, stage_id):
        workflow = _get_workflow_or_404(request, workflow_id)
        version = _get_version_or_404(request, workflow, version_id)
        stage = _get_stage_or_404(request, version, stage_id)

        serializer = StageGraphSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            updated = StageService().update_graph(
                stage, dict(serializer.validated_data)
            )
        except GraphValidationError as exc:
            raise ValidationError(str(exc))

        return Response(StageSerializer(updated).data)
