"""
Node category validation (§8/§9). Categories are fixed JSON strings for now
-- a category registry (pluggable, tenant-defined categories) was
deliberately deferred (workflow-store-design.md, "Node categories" decision)
in favor of shipping something concrete first.
"""


class GraphValidationError(Exception):
    """Raised for any structural or category-level problem with a stage's
    graph JSON. Caught at the API boundary (api/views.py) and turned into a
    400 response -- never allowed to surface as a 500."""


NODE_CATEGORIES = frozenset(
    {
        "input",
        "process",
        "output",
        "decision",
        "action",
        "condition",
        "custom",
    }
)


def validate_category(category: str) -> None:
    if category not in NODE_CATEGORIES:
        raise GraphValidationError(
            f"Unknown node category '{category}'. Must be one of: "
            f"{sorted(NODE_CATEGORIES)}"
        )


# Per-category JSON-schema validation of a node's `data` payload (§8/§9).
# The exact field shapes for each category are frontend-owned and not
# finalized in the design doc -- this dict is the intended extension point:
# register a schema per category as the frontend's node `data` shapes
# stabilize (see validate_node_data below). A category with no schema
# registered here still gets its category-name checked by
# validate_category(), it just isn't shape-checked yet.
CATEGORY_SCHEMAS: dict[str, dict] = {}


def validate_node_data(category: str, data: dict) -> None:
    validate_category(category)
    schema = CATEGORY_SCHEMAS.get(category)
    if schema is None:
        return

    import jsonschema

    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as exc:
        raise GraphValidationError(
            f"Invalid data for node category '{category}': {exc.message}"
        ) from exc
