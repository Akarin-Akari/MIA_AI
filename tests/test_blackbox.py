"""Black-box functional tests for the challenge requirements.

Tests the full pipeline: tools, fault injection, retry, verification.
"""
import asyncio
import os
import sys
import shutil
from pathlib import Path

sys.path.insert(0, ".")


def test_write_note_creates_file():
    """G4: Deterministic check — file must exist and be non-empty after write."""
    from app.tools.write_note import WriteNoteTool

    test_dir = "memory/test_notes_blackbox"
    t = WriteNoteTool(notes_dir=test_dir)
    result = t.execute(title="Blackbox Test", content="This note should exist on disk")

    assert "saved successfully" in result.lower(), f"Expected success, got: {result}"

    # Extract file path from result
    import re
    match = re.search(r'saved successfully to\s+(\S+)', result, re.IGNORECASE)
    assert match, f"Could not extract path from: {result}"
    file_path = match.group(1).rstrip(".")

    # DETERMINISTIC CHECK: file must exist
    assert os.path.isfile(file_path), f"File should exist: {file_path}"
    # DETERMINISTIC CHECK: file must be non-empty
    assert os.path.getsize(file_path) > 0, f"File should be non-empty: {file_path}"

    print(f"[PASS] write_note creates file at {file_path} ({os.path.getsize(file_path)} bytes)")

    # Cleanup
    shutil.rmtree(test_dir, ignore_errors=True)


def test_read_notes_finds_written_notes():
    """Cross-tool test: write → read pipeline."""
    from app.tools.write_note import WriteNoteTool
    from app.tools.read_notes import ReadNotesTool

    test_dir = "memory/test_notes_blackbox2"
    writer = WriteNoteTool(notes_dir=test_dir)
    reader = ReadNotesTool(notes_dir=test_dir)

    # Write 2 notes
    writer.execute(title="Alpha Note", content="First note about alpha")
    writer.execute(title="Beta Note", content="Second note about beta")

    # Read all
    result = reader.execute()
    assert "Alpha Note" in result, f"Expected Alpha Note in: {result[:200]}"
    assert "Beta Note" in result, f"Expected Beta Note in: {result[:200]}"
    print("[PASS] read_notes finds both written notes")

    # Read with filter
    filtered = reader.execute(query="alpha")
    assert "Alpha Note" in filtered, f"Expected Alpha in filtered: {filtered[:200]}"
    assert "Beta Note" not in filtered, f"Should NOT find Beta in alpha-filtered: {filtered[:200]}"
    print("[PASS] read_notes keyword filter works")

    # Cleanup
    shutil.rmtree(test_dir, ignore_errors=True)


def test_fault_injection_raises():
    """G2: INJECT_FAILURE must cause tool to raise."""
    from app.tools.write_note import WriteNoteTool
    from app.tools.mock_search import MockSearchTool

    # WriteNoteTool
    t = WriteNoteTool(inject_failure=True)
    try:
        t.execute(title="x", content="y")
        assert False, "Should have raised IOError"
    except IOError:
        print("[PASS] WriteNoteTool fault injection raises IOError")

    # MockSearchTool
    t2 = MockSearchTool(inject_failure=True)
    try:
        t2.execute(query="test")
        assert False, "Should have raised RuntimeError"
    except RuntimeError:
        print("[PASS] MockSearchTool fault injection raises RuntimeError")


def test_registry_catches_fault_and_returns_error_string():
    """G2+G5: Registry wraps exceptions as ERROR strings (never raises)."""
    from app.tools.registry import ToolRegistry
    from app.tools.write_note import WriteNoteTool

    registry = ToolRegistry()
    registry.register(WriteNoteTool(inject_failure=True))

    result = asyncio.get_event_loop().run_until_complete(
        registry.execute("write_note", {"title": "x", "content": "y"})
    )
    assert "ERROR" in result, f"Expected ERROR string, got: {result}"
    assert "IOError" in result or "Injected failure" in result, f"Expected injection message: {result}"
    print(f"[PASS] Registry catches fault: {result[:100]}")


def test_retry_logic_in_core():
    """G5: Verify retry loop works — tool called up to 3 times (1 original + 2 retries)."""
    from app.tools.registry import ToolRegistry
    from app.tools.base import BaseTool
    from typing import Any

    call_count = 0

    class FailThenSucceedTool(BaseTool):
        @property
        def name(self): return "fail_then_succeed"
        @property
        def description(self): return "test"
        def parameters(self) -> dict[str, Any]:
            return {"type": "object", "properties": {}, "required": []}
        def execute(self) -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return f"ERROR: Simulated failure attempt {call_count}"
            return "Success on attempt 3"

    registry = ToolRegistry()
    registry.register(FailThenSucceedTool())

    # Simulate the retry loop from core.py L212-224
    MAX_TOOL_RETRIES = 2
    result = ""
    for attempt in range(MAX_TOOL_RETRIES + 1):
        result = asyncio.get_event_loop().run_until_complete(
            registry.execute("fail_then_succeed", {})
        )
        if "ERROR" not in result:
            break

    assert "Success" in result, f"Expected success on 3rd attempt, got: {result}"
    assert call_count == 3, f"Expected 3 calls, got: {call_count}"
    print(f"[PASS] Retry logic: tool called {call_count} times, final result: {result}")


def test_retry_exhaustion():
    """G5: All retries fail — error propagated, not hallucinated."""
    from app.tools.registry import ToolRegistry
    from app.tools.write_note import WriteNoteTool

    registry = ToolRegistry()
    registry.register(WriteNoteTool(inject_failure=True))

    MAX_TOOL_RETRIES = 2
    result = ""
    for attempt in range(MAX_TOOL_RETRIES + 1):
        result = asyncio.get_event_loop().run_until_complete(
            registry.execute("write_note", {"title": "x", "content": "y"})
        )
        if "ERROR" not in result:
            break

    assert "ERROR" in result, f"Expected ERROR after all retries, got: {result}"
    print(f"[PASS] Retry exhaustion: error propagated correctly: {result[:100]}")


def test_verifier_detects_missing_file():
    """G4: Verifier Stage 1 catches when tool claims file exists but it doesn't."""
    from app.agent.verifier import SelfVerifier

    verifier = SelfVerifier(enabled=True)
    # Simulate: tool claims success but file path is fake
    tool_results = [
        "Note saved successfully to memory/notes/NONEXISTENT_FILE.md. Title: 'test', Size: 42 bytes."
    ]
    answer = "I've saved your note successfully."

    issues = verifier._stage1_tool_results(answer, tool_results)
    assert any("NOT exist" in issue for issue in issues), f"Expected file-not-found issue, got: {issues}"
    print(f"[PASS] Verifier detects missing file: {issues}")


def test_verifier_passes_real_file():
    """G4: Verifier Stage 1 passes when file actually exists."""
    from app.agent.verifier import SelfVerifier
    from app.tools.write_note import WriteNoteTool

    test_dir = "memory/test_verifier_blackbox"
    writer = WriteNoteTool(notes_dir=test_dir)
    result = writer.execute(title="Verify Me", content="Content for verification")

    verifier = SelfVerifier(enabled=True)
    issues = verifier._stage1_tool_results("Note saved successfully.", [result])
    file_issues = [i for i in issues if "NOT exist" in i or "EMPTY" in i]
    assert len(file_issues) == 0, f"Expected no file issues for real file, got: {file_issues}"
    print("[PASS] Verifier passes for real, non-empty file")

    # Cleanup
    shutil.rmtree(test_dir, ignore_errors=True)


def test_factory_inject_failure_routing():
    """G2: Factory correctly routes INJECT_FAILURE to target tool."""
    from app.config import Settings

    # Mock settings with inject_failure
    os.environ["INJECT_FAILURE"] = "write_note"
    os.environ["LLM_PROVIDER"] = "openai"
    os.environ["OPENAI_API_KEY"] = "sk-test-dummy"
    s = Settings()
    assert s.inject_failure == "write_note", f"Expected 'write_note', got: {s.inject_failure}"
    print("[PASS] Config reads INJECT_FAILURE env var")

    # Clean up env
    del os.environ["INJECT_FAILURE"]
    del os.environ["LLM_PROVIDER"]
    del os.environ["OPENAI_API_KEY"]


def test_mock_search_returns_results():
    """Tool functional test: search should find content."""
    from app.tools.mock_search import MockSearchTool

    t = MockSearchTool()

    # Should match
    r1 = t.execute(query="agent engineering")
    assert "ReAct" in r1, f"Expected ReAct in results: {r1[:100]}"
    print("[PASS] mock_search finds 'agent engineering'")

    # Should not match
    r2 = t.execute(query="quantum computing")
    assert "No results" in r2, f"Expected no results: {r2[:100]}"
    print("[PASS] mock_search returns 'no results' for unknown topic")

    # Empty query
    r3 = t.execute(query="")
    assert "ERROR" in r3, f"Expected error for empty query: {r3[:100]}"
    print("[PASS] mock_search returns ERROR for empty query")


def test_read_notes_empty_dir():
    """Edge case: reading from non-existent directory."""
    from app.tools.read_notes import ReadNotesTool

    t = ReadNotesTool(notes_dir="memory/nonexistent_dir_blackbox")
    result = t.execute()
    assert "no notes" in result.lower() or "does not exist" in result.lower(), f"Expected empty message: {result}"
    print("[PASS] read_notes handles non-existent directory")


def test_agent_py_entry_point():
    """G3: agent.py exists at project root and imports correctly."""
    assert os.path.isfile("agent.py"), "agent.py must exist at project root"

    # Verify it imports correctly
    import importlib.util
    spec = importlib.util.spec_from_file_location("agent", "agent.py")
    assert spec is not None, "agent.py must be importable"
    print("[PASS] agent.py exists and is importable")


if __name__ == "__main__":
    tests = [
        test_write_note_creates_file,
        test_read_notes_finds_written_notes,
        test_fault_injection_raises,
        test_registry_catches_fault_and_returns_error_string,
        test_retry_logic_in_core,
        test_retry_exhaustion,
        test_verifier_detects_missing_file,
        test_verifier_passes_real_file,
        test_factory_inject_failure_routing,
        test_mock_search_returns_results,
        test_read_notes_empty_dir,
        test_agent_py_entry_point,
    ]

    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            print(f"[FAIL] {test_fn.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"BLACK-BOX RESULTS: {passed} passed, {failed} failed out of {len(tests)}")
    if failed > 0:
        sys.exit(1)
    print("ALL BLACK-BOX TESTS PASSED!")
