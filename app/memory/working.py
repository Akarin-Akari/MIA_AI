"""Working memory — Tier 1: in-process conversation buffer.

Stores recent messages per conversation_id using bounded deques.
NEVER uses a global _messages list — strict conv_id isolation.
"""

from __future__ import annotations

import logging
from collections import deque

from app.llm.base import CanonicalMessage

logger = logging.getLogger(__name__)


class WorkingMemory:
    """Per-conversation in-memory message buffer.

    Uses dict[str, deque[CanonicalMessage]] for strict conv_id isolation.
    Each deque has a configurable maxlen to prevent unbounded growth.

    Attributes:
        _conversations: Map of conv_id → bounded deque of messages.
        _maxlen: Maximum messages per conversation.
    """

    def __init__(self, maxlen: int = 50) -> None:
        self._conversations: dict[str, deque[CanonicalMessage]] = {}
        self._maxlen = maxlen

    def append(self, conv_id: str, msg: CanonicalMessage) -> None:
        """Add a message to a conversation's buffer.

        Creates the deque on first access.

        Args:
            conv_id: Conversation identifier.
            msg: Message to append.
        """
        if conv_id not in self._conversations:
            self._conversations[conv_id] = deque(maxlen=self._maxlen)
        self._conversations[conv_id].append(msg)

    def get_messages(self, conv_id: str) -> list[CanonicalMessage]:
        """Get all messages for a conversation.

        Args:
            conv_id: Conversation identifier.

        Returns:
            List of messages (copy), empty if conv_id not found.
        """
        if conv_id not in self._conversations:
            return []
        return list(self._conversations[conv_id])

    def clear(self, conv_id: str | None = None) -> None:
        """Clear messages for a specific conversation or all.

        Args:
            conv_id: If provided, clear only that conversation.
                     If None, clear all conversations.
        """
        if conv_id is None:
            self._conversations.clear()
            logger.info("Cleared all working memory")
        elif conv_id in self._conversations:
            del self._conversations[conv_id]
            logger.info("Cleared working memory for conv_id=%s", conv_id)
