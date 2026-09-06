"""
Compiler._resolve_connection (§41.1 point 3) exercised in isolation, with
fake connections/connection_definitions services injected -- no node type
Sprint 1 actually seeds carries a `connectionId`, so there's no way to
reach this path through a real publish() yet (see compiler.py's own
`_compile_node` comment on why the hook exists early anyway). No DB
involved: Compiler(...) with services injected never touches
NodeTypeRepository either, since these tests call _resolve_connection()
directly.
"""

import pytest

from rm_workflow.compiler.compiler import Compiler, UnresolvedConnectionError


class _FakeConnection:
    def __init__(self, public_id, provider):
        self.public_id = public_id
        self.provider = provider


class _FakeConnectionService:
    def __init__(self, connection):
        self._connection = connection

    def get_connection(self, tenant_id, public_id):
        from rm_connection.services.connection_service import ConnectionServiceError

        if public_id != self._connection.public_id:
            raise ConnectionServiceError(f"No such connection '{public_id}'")
        return self._connection


class _FakeConnectionDefinitionService:
    def __init__(self, known_providers):
        self._known_providers = set(known_providers)

    def get_active(self, provider):
        from rm_connection.services.definition_service import (
            ConnectionDefinitionServiceError,
        )

        if provider not in self._known_providers:
            raise ConnectionDefinitionServiceError(
                f"No active connection definition for provider '{provider}'"
            )


def test_resolve_connection_returns_public_id_when_valid():
    connection = _FakeConnection(public_id="conn_abc123", provider="gmail")
    compiler = Compiler(
        connections=_FakeConnectionService(connection),
        connection_definitions=_FakeConnectionDefinitionService(["gmail"]),
    )

    resolved = compiler._resolve_connection("tenant-x", "conn_abc123")

    assert resolved == "conn_abc123"


def test_resolve_connection_raises_when_connection_not_found():
    connection = _FakeConnection(public_id="conn_abc123", provider="gmail")
    compiler = Compiler(
        connections=_FakeConnectionService(connection),
        connection_definitions=_FakeConnectionDefinitionService(["gmail"]),
    )

    with pytest.raises(UnresolvedConnectionError):
        compiler._resolve_connection("tenant-x", "conn_does_not_exist")


def test_resolve_connection_raises_when_provider_has_no_active_definition():
    # The connection exists, but its provider has no active
    # ConnectionDefinition -- e.g. deprecated/disabled provider. Sprint 1's
    # job here is confirming the connection *type* is valid, not the
    # credential (§41.1 point 3).
    connection = _FakeConnection(public_id="conn_abc123", provider="some_removed_provider")
    compiler = Compiler(
        connections=_FakeConnectionService(connection),
        connection_definitions=_FakeConnectionDefinitionService([]),
    )

    with pytest.raises(UnresolvedConnectionError):
        compiler._resolve_connection("tenant-x", "conn_abc123")
