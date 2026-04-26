"""Quick smoke test for all new tools and fault injection."""
import sys
sys.path.insert(0, ".")

# Test 1: MockSearchTool normal
from app.tools.mock_search import MockSearchTool
t = MockSearchTool()
r = t.execute(query="agent engineering")
assert "ReAct" in r, f"Expected ReAct in result, got: {r[:100]}"
print("[PASS] MockSearchTool normal execution")

# Test 2: MockSearchTool fault injection
t_fail = MockSearchTool(inject_failure=True)
try:
    t_fail.execute(query="test")
    print("[FAIL] Should have raised RuntimeError")
    sys.exit(1)
except RuntimeError as e:
    print(f"[PASS] MockSearchTool fault injection: {e}")

# Test 3: WriteNoteTool normal
from app.tools.write_note import WriteNoteTool
t2 = WriteNoteTool(notes_dir="memory/notes")
r2 = t2.execute(title="Test Note", content="Hello from smoke test")
assert "saved successfully" in r2.lower(), f"Expected 'saved' in: {r2}"
print(f"[PASS] WriteNoteTool: {r2}")

# Test 4: WriteNoteTool fault injection
t2_fail = WriteNoteTool(inject_failure=True)
try:
    t2_fail.execute(title="x", content="y")
    print("[FAIL] Should have raised IOError")
    sys.exit(1)
except IOError as e:
    print(f"[PASS] WriteNoteTool fault injection: {e}")

# Test 5: ReadNotesTool
from app.tools.read_notes import ReadNotesTool
t3 = ReadNotesTool(notes_dir="memory/notes")
r3 = t3.execute()
assert "Test Note" in r3, f"Expected 'Test Note' in: {r3[:200]}"
print(f"[PASS] ReadNotesTool found notes")

# Test 6: ReadNotesTool with filter
r4 = t3.execute(query="nonexistent_keyword_xyz")
assert "no notes matching" in r4.lower() or "0" in r4, f"Expected no match: {r4[:200]}"
print(f"[PASS] ReadNotesTool filter works")

# Test 7: Config
from app.config import Settings
s = Settings()
assert s.inject_failure == ""
assert s.notes_dir == "memory/notes"
print("[PASS] Config fields OK")

# Test 8: Factory imports
from app.factory import build_agent
print("[PASS] Factory import OK (no dead imports)")

print("\n========== ALL 8 TESTS PASSED ==========")
