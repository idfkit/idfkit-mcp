"""Tests for error mapping, error logging, and change-log summaries in the tool middleware."""

from __future__ import annotations

import logging

import pytest
from fastmcp.exceptions import ToolError

from idfkit_mcp.models import BatchAddResult, GetChangeLogResult
from idfkit_mcp.state import ServerState
from tests.conftest import call_tool


class TestErrorText:
    async def test_unknown_object_type_is_not_quoted(self, client: object, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError) as raised:
            await call_tool(client, "describe_object_type", {"object_type": "Zone:Bogus"})
        message = str(raised.value)
        assert message.startswith("Unknown object type: 'Zone:Bogus'\n")
        assert "\\n" not in message

    async def test_duplicate_object_suggests_update(self, client: object, state_with_model: ServerState) -> None:
        with pytest.raises(ToolError, match="use update_object") as raised:
            await call_tool(client, "add_object", {"object_type": "Building", "name": "Building"})
        assert str(raised.value).startswith("Duplicate Building object with name 'Building'")

    async def test_batch_errors_use_the_same_text(self, client: object, state_with_model: ServerState) -> None:
        result = await call_tool(
            client,
            "batch_add_objects",
            {"objects": [{"object_type": "Building", "name": "Building"}, {"object_type": "Zone:Bogus"}]},
            BatchAddResult,
        )
        duplicate, unknown = (entry["error"] for entry in result.results)
        assert "use update_object" in duplicate
        assert unknown.startswith("Unknown object type: 'Zone:Bogus'\n")

    async def test_wrapped_runtime_error_is_unwrapped(self, client: object) -> None:
        with pytest.raises(ToolError, match=r"^No model loaded\. Use load_model or new_model first\.$"):
            await call_tool(client, "validate_model")


class TestErrorLogging:
    async def test_expected_tool_error_is_logged_without_traceback(
        self, client: object, state_with_model: ServerState, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="idfkit_mcp"), pytest.raises(ToolError):
            await call_tool(client, "describe_object_type", {"object_type": "Zone:Bogus"})
        failures = [r for r in caplog.records if r.getMessage().startswith("FAIL describe_object_type")]
        assert len(failures) == 1
        assert failures[0].exc_info is None
        assert "Unknown object type: 'Zone:Bogus'" in failures[0].getMessage()


class TestChangeLogSummary:
    async def test_mutations_record_a_summary(self, client: object, state_with_model: ServerState) -> None:
        await call_tool(client, "add_object", {"object_type": "Zone", "name": "Office"})
        await call_tool(client, "rename_object", {"object_type": "Zone", "old_name": "Office", "new_name": "Lab"})
        await call_tool(client, "batch_add_objects", {"objects": [{"object_type": "Zone", "name": "Hall"}]})

        log = await call_tool(client, "get_change_log", {"limit": 3}, GetChangeLogResult)
        summaries = [entry.summary for entry in log.entries]
        assert summaries == [
            "add_object: Zone name=Office",
            "rename_object: Zone new_name=Lab",
            "batch_add_objects: 1 succeeded, 0 failed",
        ]


class TestUnexpectedErrorLogging:
    async def test_defect_keeps_its_traceback(
        self,
        client: object,
        state_with_model: ServerState,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def broken(*_args: object, **_kwargs: object) -> None:
            raise AttributeError("simulated defect")

        monkeypatch.setattr("idfkit.validate_document", broken)
        with caplog.at_level(logging.WARNING, logger="idfkit_mcp"), pytest.raises(ToolError):
            await call_tool(client, "validate_model")
        failures = [r for r in caplog.records if r.getMessage().startswith("FAIL validate_model")]
        assert len(failures) == 1
        assert failures[0].exc_info is not None


class TestFastMCPDuplicateLog:
    async def test_fastmcp_does_not_log_the_failure_a_second_time(
        self, client: object, state_with_model: ServerState, caplog: pytest.LogCaptureFixture
    ) -> None:
        # FastMCP's loggers do not propagate to the root logger, so capture on it directly.
        fastmcp_logger = logging.getLogger("fastmcp.server.server")
        fastmcp_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.DEBUG), pytest.raises(ToolError):
                await call_tool(client, "describe_object_type", {"object_type": "Zone:Bogus"})
        finally:
            fastmcp_logger.removeHandler(caplog.handler)
        assert not [r for r in caplog.records if r.name == "fastmcp.server.server"]
        assert len([r for r in caplog.records if r.getMessage().startswith("FAIL describe_object_type")]) == 1

    async def test_resource_failure_is_logged_once_without_traceback(
        self, client: object, caplog: pytest.LogCaptureFixture
    ) -> None:
        fastmcp_logger = logging.getLogger("fastmcp.server.server")
        fastmcp_logger.addHandler(caplog.handler)
        try:
            with caplog.at_level(logging.DEBUG), pytest.raises(Exception, match="No model loaded"):
                await client.read_resource("idfkit://model/summary")  # type: ignore[attr-defined]
        finally:
            fastmcp_logger.removeHandler(caplog.handler)
        assert not [r for r in caplog.records if r.name == "fastmcp.server.server"]
        failures = [r for r in caplog.records if r.getMessage().startswith("FAIL resource idfkit://model/summary")]
        assert len(failures) == 1
        assert failures[0].exc_info is None
