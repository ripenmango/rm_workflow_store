"""
Aggregator module so Django admin's autodiscovery (which only looks for
admin.py at each app's top level, not its sub-packages) picks up
registrations that live in rm_workflow/node_types/admin.py -- same
aggregator convention as models.py in this package.

No other rm_workflow model is registered here today -- Workspace/Workflow/
Stage/etc. have no Django admin presence; this file exists specifically for
NodeType/TenantNodeTypeSetting (see node_types/admin.py's module docstring
for why those two are deliberately admin-managed rather than API-managed).
"""

from rm_workflow.node_types.admin import (  # noqa: F401
    NodeTypeAdmin,
    TenantNodeTypeSettingAdmin,
)
