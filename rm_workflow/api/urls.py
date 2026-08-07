from django.urls import path
from rest_framework.routers import SimpleRouter

from rm_workflow.api.views import (
    PublishWorkflowView,
    StageDetailView,
    StageGraphView,
    StageListCreateView,
    WorkflowCollaboratorDetailView,
    WorkflowCollaboratorsView,
    WorkflowVersionListView,
    WorkflowViewSet,
    WorkspaceViewSet,
)

# trailing_slash=False to match rm_auth_tenant's own convention.
router = SimpleRouter(trailing_slash=False)
router.register("workspaces", WorkspaceViewSet, basename="rm_workflow_workspace")
router.register("workflows", WorkflowViewSet, basename="rm_workflow_workflow")

urlpatterns = [
    *router.urls,
    path(
        "workflows/<str:workflow_id>/publish",
        PublishWorkflowView.as_view(),
        name="rm_workflow_publish",
    ),
    path(
        "workflows/<str:workflow_id>/versions",
        WorkflowVersionListView.as_view(),
        name="rm_workflow_version_list",
    ),
    path(
        "workflows/<str:workflow_id>/versions/<str:version_id>/stages",
        StageListCreateView.as_view(),
        name="rm_workflow_stage_list",
    ),
    path(
        "workflows/<str:workflow_id>/versions/<str:version_id>/stages/<str:stage_id>",
        StageDetailView.as_view(),
        name="rm_workflow_stage_detail",
    ),
    path(
        "workflows/<str:workflow_id>/versions/<str:version_id>/stages/<str:stage_id>/graph",
        StageGraphView.as_view(),
        name="rm_workflow_stage_graph",
    ),
    path(
        "workflows/<str:workflow_id>/collaborators",
        WorkflowCollaboratorsView.as_view(),
        name="rm_workflow_collaborators",
    ),
    path(
        "workflows/<str:workflow_id>/collaborators/<str:user_id>",
        WorkflowCollaboratorDetailView.as_view(),
        name="rm_workflow_collaborator_detail",
    ),
]
