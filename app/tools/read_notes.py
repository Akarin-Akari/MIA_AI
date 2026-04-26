"""Read notes tool — retrieve saved notes from disk.

Scans the notes directory and returns all saved notes,
optionally filtered by a keyword query.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.base import BaseTool


class ReadNotesTool(BaseTool):
    """Reads all saved notes from disk.

    Scans {memory_dir}/notes/ directory and returns note titles and content.
    Supports optional keyword filtering.
    """

    def __init__(self, notes_dir: str = "memory/notes") -> None:
        """Initialize ReadNotesTool.

        Args:
            notes_dir: Directory where notes are stored.
        """
        self._notes_dir = Path(notes_dir)

    @property
    def name(self) -> str:
        return "read_notes"

    @property
    def description(self) -> str:
        return (
            "Read all saved notes from disk. Use this to review past notes, "
            "summarize what topics have been researched, or find specific information "
            "from previously saved notes. Optionally filter by keyword."
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional keyword to filter notes. Leave empty to return all notes.",
                },
            },
            "required": [],
        }

    def execute(self, query: str = "") -> str:
        """Read notes from the notes directory.

        This is intentionally SYNC to demonstrate asyncio.to_thread wrapping.

        Args:
            query: Optional keyword filter. Empty = return all.

        Returns:
            Formatted list of notes with titles and content summaries.
        """
        if not self._notes_dir.exists():
            return "No notes found. The notes directory does not exist yet."

        note_files = sorted(self._notes_dir.glob("*.md"), reverse=True)
        if not note_files:
            return "No notes found. Start by saving a note with write_note."

        results: list[str] = []
        query_lower = query.lower() if query else ""

        for note_path in note_files:
            try:
                content = note_path.read_text(encoding="utf-8")

                # Filter by keyword if provided
                if query_lower and query_lower not in content.lower():
                    continue

                # Extract title (first heading line)
                lines = content.strip().split("\n")
                title = lines[0].lstrip("# ").strip() if lines else note_path.stem
                # Get body (skip title and empty lines)
                body_lines = [l for l in lines[1:] if l.strip() and not l.startswith("---") and not l.startswith("_Saved")]
                body_preview = " ".join(body_lines)[:200]

                results.append(
                    f"[NOTE] **{title}**\n"
                    f"   File: {note_path.name}\n"
                    f"   Preview: {body_preview}..."
                )
            except Exception as e:
                results.append(f"[WARN] Error reading {note_path.name}: {e}")

        if not results:
            return f"No notes matching '{query}' found. Total notes on disk: {len(note_files)}"

        header = f"Found {len(results)} note(s)"
        if query:
            header += f" matching '{query}'"
        header += ":\n\n"

        return header + "\n\n".join(results)
