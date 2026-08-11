"""
Aggregator module so Django's app registry (and anything doing
`from rm_workflow.models import X`) sees a flat, single-app model surface,
even though the actual model classes are organized into sub-packages by
domain concept (tenants/, workspaces/, workflows/, stages/) -- same
convention as rm_auth_tenant/models.py.
"""

from rm_workflow.tenants.models import Tenant
from rm_workflow.workspaces.models import Workspace
from rm_workflow.workflows.models import Workflow, WorkflowVersion
from rm_workflow.stages.models import Stage
from rm_workflow.node_types.models import NodeType, TenantNodeTypeSetting

__all__ = [
    "Tenant",
    "Workspace",
    "Workflow",
    "WorkflowVersion",
    "Stage",
    "NodeType",
    "TenantNodeTypeSetting",
]
