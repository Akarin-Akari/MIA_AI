"""Write note tool — persist notes to disk.

Saves user notes as individual markdown files in memory/notes/.
Each note gets a timestamped filename for uniqueness.

Supports fault injection via INJECT_FAILURE env var for demonstrating
error recovery during evaluation.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.tools.base import BaseTool


class WriteNoteTool(BaseTool):
    """Saves a note to disk as a markdown file.

    Notes are stored in {memory_dir}/notes/ with timestamped filenames.
    Supports fault injection for evaluation of retry/recovery flow.
    """

    def __init__(self, notes_dir: str = "memory/notes", inject_failure: bool = False) -> None:
        """Initialize WriteNoteTool.

        Args:
            notes_dir: Directory to store note files.
            inject_failure: If True, tool will raise IOError on execute.
        """
        self._notes_dir = Path(notes_dir)
        self._inject_failure = inject_failure

    @property
    def name(self) -> str:
        return "write_note"

    @property
    def description(self) -> str:
        return (
            "Save a note to disk. Use this when the user wants to remember something, "
            "save a summary, or persist information for later retrieval. "
            "Each note is saved as a separate file."
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short descriptive title for the note",
                },
                "content": {
                    "type": "string",
                    "description": "The full content/body of the note to save",
                },
            },
            "required": ["title", "content"],
        }

    def execute(self, title: str = "", content: str = "") -> str:
        """Save a note to disk.

        This is intentionally SYNC to demonstrate asyncio.to_thread wrapping.

        Args:
            title: Note title.
            content: Note content body.

        Returns:
            Success message with file path, or error message.

        Raises:
            IOError: If fault injection is enabled.
        """
        if self._inject_failure:
            raise IOError(
                f"Injected failure for write_note "
                f"(INJECT_FAILURE={os.environ.get('INJECT_FAILURE', '')})"
            )

        if not title or not content:
            return "ERROR: Both 'title' and 'content' are required."

        # Ensure notes directory exists
        self._notes_dir.mkdir(parents=True, exist_ok=True)

        # Generate timestamped filename
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        safe_title = "".join(c if c.isalnum() or c in "-_ " else "" for c in title).strip()
        safe_title = safe_title.replace(" ", "_")[:50]
        filename = f"{timestamp}_{safe_title}.md"
        filepath = self._notes_dir / filename

        # Write note content
        note_content = f"# {title}\n\n{content}\n\n---\n_Saved at: {datetime.now(timezone.utc).isoformat()}_\n"
        filepath.write_text(note_content, encoding="utf-8")

        file_size = filepath.stat().st_size
        return (
            f"Note saved successfully to {filepath}. "
            f"Title: '{title}', Size: {file_size} bytes."
        )
