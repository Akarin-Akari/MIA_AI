"""Self-verification with 3-stage pipeline.

Stage 1: Hard rules — tool_results consistency (deterministic, no LLM)
Stage 2: Profile schema validation (deterministic, no LLM)
Stage 3: LLM soft fallback (Structured Outputs + sampling)

CRITICAL: verify() MUST be awaited (blocking) in the main response chain.
          It must NOT be asyncio.create_task'd — that loses revised_answer.

Stage 3 uses FORCED TOOL USE (tool_choice) for structured output:
- Anthropic: tool_choice={"type": "tool", "name": "submit_verification"}
- OpenAI: tool_choice={"type": "function", "function": {"name": ...}}
This is NOT just a hopeful chat — it's a contract-enforced structured output.
"""

from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from typing import Any

from app.llm.base import LLMClient, ToolSpec

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Result of self-verification.

    Attributes:
        is_valid: Whether the answer passed all checks.
        confidence: Confidence level (0.0-1.0).
        issues: List of detected issues.
        revised_answer: If not None, replaces the original answer.
    """

    is_valid: bool
    confidence: float
    issues: list[str] = field(default_factory=list)
    revised_answer: str | None = None


# Success semantic words for Stage 1 contradiction detection
_SUCCESS_WORDS = {
    "successfully", "completed", "done", "finished", "succeeded",
    "已完成", "成功", "好了", "搞定", "完成了",
}

# High-risk indicators for Stage 3 proactive sampling
_HIGH_RISK_PATTERNS = [
    re.compile(r"\d+"),  # Contains numbers
    re.compile(r"(将会|保证|一定|definitely|guaranteed|always|never)", re.IGNORECASE),
]
_HIGH_RISK_LENGTH_THRESHOLD = 200


class SelfVerifier:
    """Three-stage answer verification pipeline.

    Stage 1: tool_results hard rules (deterministic)
    Stage 2: profile.json structured validation (deterministic)
    Stage 3: LLM forced tool use (tool_choice + sampling)

    MUST be awaited in main response chain — NOT fire-and-forget.
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        sampling_rate: float = 0.1,
        soft_fallback: bool = True,
        enabled: bool = True,
    ) -> None:
        self._llm_client = llm_client
        self._sampling_rate = sampling_rate
        self._soft_fallback = soft_fallback
        self._enabled = enabled

    async def verify(
        self,
        question: str,
        answer: str,
        tool_results: list[str] | None = None,
        profile: dict[str, Any] | None = None,
    ) -> VerificationResult:
        """Run 3-stage verification pipeline.

        MUST be awaited (blocking) in main chain. Speed comes from
        Stage 1/2 short-circuits and Stage 3 sampling, NOT from
        making this async/fire-and-forget.

        Args:
            question: User's original question.
            answer: Agent's draft answer.
            tool_results: List of tool result strings from this turn.
            profile: Current user profile dict.

        Returns:
            VerificationResult with potential revised_answer.
        """
        if not self._enabled:
            return VerificationResult(is_valid=True, confidence=1.0)

        all_issues: list[str] = []

        # ── Stage 1: Tool Results Hard Rules ─────────────────────────
        stage1_issues = self._stage1_tool_results(answer, tool_results or [])
        if stage1_issues:
            all_issues.extend(stage1_issues)
            logger.info("Stage 1 found %d issues", len(stage1_issues))
            # Short-circuit: if hard contradiction, go to Stage 3 for revision
            if self._soft_fallback and self._llm_client:
                return await self._stage3_llm_fallback(
                    question, answer, tool_results or [], all_issues, profile or {},
                )
            return VerificationResult(
                is_valid=False, confidence=0.3, issues=all_issues,
            )

        # ── Stage 2: Profile Schema Validation ──────────────────────
        stage2_issues = self._stage2_profile_check(answer, profile or {})
        if stage2_issues:
            all_issues.extend(stage2_issues)
            logger.info("Stage 2 found %d issues", len(stage2_issues))
            if self._soft_fallback and self._llm_client:
                return await self._stage3_llm_fallback(
                    question, answer, tool_results or [], all_issues, profile or {},
                )
            return VerificationResult(
                is_valid=False, confidence=0.5, issues=all_issues,
            )

        # ── Stage 3: Proactive Sampling (independent of Stage 1/2) ──
        if self._should_sample(answer) and self._llm_client:
            logger.info("Stage 3 proactive sampling triggered")
            return await self._stage3_llm_fallback(
                question, answer, tool_results or [], all_issues, profile or {},
            )

        return VerificationResult(is_valid=True, confidence=0.9)

    # ── Stage 1 Implementation ───────────────────────────────────────

    def _stage1_tool_results(
        self, answer: str, tool_results: list[str],
    ) -> list[str]:
        """Check for contradictions between tool results and answer.

        Detects:
        1. Tool returned ERROR but answer claims success
        2. Tool claims file written but file doesn't exist or is empty
        """
        import os

        issues: list[str] = []
        answer_lower = answer.lower()

        for i, result in enumerate(tool_results):
            if "ERROR" in result:
                # Check if answer claims success despite error
                has_success_word = any(w in answer_lower for w in _SUCCESS_WORDS)
                # Check for negation prefixes (未, 没, not, etc.)
                has_negation = any(neg in answer_lower for neg in ["未", "没", "not ", "didn't", "failed"])

                if has_success_word and not has_negation:
                    issues.append(
                        f"Tool result #{i+1} contains ERROR but answer claims success. "
                        f"Tool result: {result[:100]}"
                    )

            # Deterministic file existence check:
            # If tool result mentions "saved to <path>" or "written to <path>",
            # verify the file actually exists and is non-empty.
            result_lower = result.lower()
            if "saved" in result_lower or "written" in result_lower:
                import re as _re
                # Match file paths like: memory/notes/xxx.md, /some/path/file.txt
                path_patterns = _re.findall(
                    r'(?:saved(?:\s+successfully)?\s+to|written\s+to)\s+([^\s,]+)',
                    result, _re.IGNORECASE,
                )
                for file_path in path_patterns:
                    file_path = file_path.rstrip(".")
                    if not os.path.isfile(file_path):
                        issues.append(
                            f"Tool result #{i+1} claims file saved to '{file_path}' "
                            f"but file does NOT exist on disk."
                        )
                    elif os.path.getsize(file_path) == 0:
                        issues.append(
                            f"Tool result #{i+1} claims file saved to '{file_path}' "
                            f"but file is EMPTY (0 bytes)."
                        )

        return issues

    # ── Stage 2 Implementation ───────────────────────────────────────

    def _stage2_profile_check(
        self, answer: str, profile: dict[str, Any],
    ) -> list[str]:
        """Validate answer against profile.json with typed checks.

        Uses metadata schema (type, tolerance, values) for strong validation.
        Does NOT use fragile string-contains checks.
        """
        issues: list[str] = []

        for key, meta in profile.items():
            if not isinstance(meta, dict) or "value" not in meta or "type" not in meta:
                continue  # Skip non-metadata entries

            field_type = meta["type"]
            field_value = meta["value"]

            if field_type == "number":
                # Extract numbers from answer, compare with tolerance
                tolerance = meta.get("tolerance", 0)
                numbers_in_answer = re.findall(r"[-+]?\d*\.?\d+", answer)
                if numbers_in_answer and str(key).lower() in answer.lower():
                    for num_str in numbers_in_answer:
                        try:
                            num = float(num_str)
                            if abs(num - float(field_value)) > tolerance:
                                issues.append(
                                    f"Profile '{key}' = {field_value} (tolerance={tolerance}), "
                                    f"but answer contains {num}"
                                )
                        except (ValueError, TypeError):
                            continue

            elif field_type == "enum":
                # Check if answer mentions the field but uses wrong value
                allowed_values = meta.get("values", [])
                if str(key).lower() in answer.lower() and allowed_values:
                    mentioned_any = any(str(v).lower() in answer.lower() for v in allowed_values)
                    mentioned_correct = str(field_value).lower() in answer.lower()
                    if mentioned_any and not mentioned_correct:
                        issues.append(
                            f"Profile '{key}' = '{field_value}', "
                            f"but answer mentions a different value from {allowed_values}"
                        )

            elif field_type == "text":
                # Free text: skip Stage 2, defer to Stage 3
                pass

        return issues

    # ── Stage 3 Implementation ───────────────────────────────────────

    def _should_sample(self, answer: str) -> bool:
        """Determine if answer should be proactively sampled by Stage 3.

        High-risk answers: contain numbers, commitment verbs, or are very long.
        Sampling is probabilistic based on verifier_sampling_rate.
        """
        is_high_risk = (
            len(answer) > _HIGH_RISK_LENGTH_THRESHOLD
            or any(p.search(answer) for p in _HIGH_RISK_PATTERNS)
        )
        if is_high_risk:
            return random.random() < self._sampling_rate
        return False

    async def _stage3_llm_fallback(
        self,
        question: str,
        answer: str,
        tool_results: list[str],
        issues: list[str],
        profile: dict[str, Any],
    ) -> VerificationResult:
        """LLM-based verification with Structured Outputs.

        Uses SDK native Structured Outputs capability:
        - OpenAI: response_format with json_schema
        - Anthropic: forced Tool Use with submit_verification tool

        Falls back gracefully on parse failure.
        """
        if not self._llm_client:
            return VerificationResult(
                is_valid=False, confidence=0.5, issues=issues,
            )

        # Build verification prompt
        verification_prompt = self._build_verification_prompt(
            question, answer, tool_results, issues, profile,
        )

        try:
            from app.llm.base import CanonicalMessage, ToolSpec as TS

            # Use forced Tool Use for structured output
            verification_tool = TS(
                name="submit_verification",
                description="Submit your verification result as structured JSON",
                parameters={
                    "type": "object",
                    "properties": {
                        "is_valid": {"type": "boolean", "description": "Is the answer correct?"},
                        "confidence": {"type": "number", "description": "Confidence 0.0-1.0"},
                        "issues": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of issues found",
                        },
                        "revised_answer": {
                            "type": ["string", "null"],
                            "description": "Corrected answer if invalid, null if valid",
                        },
                    },
                    "required": ["is_valid", "confidence", "issues"],
                },
            )

            msgs = [CanonicalMessage(role="user", content=verification_prompt)]
            # CRITICAL: Use forced tool_choice — NOT hopeful chat
            response = await self._llm_client.chat(
                messages=msgs,
                tools=[verification_tool],
                system="You are a verification assistant. Check the answer and use submit_verification tool.",
                tool_choice="submit_verification",
            )

            # Parse tool call result
            if response.tool_calls:
                tc = response.tool_calls[0]
                if tc.name == "submit_verification":
                    data = tc.input
                    return VerificationResult(
                        is_valid=data.get("is_valid", False),
                        confidence=data.get("confidence", 0.5),
                        issues=data.get("issues", issues),
                        revised_answer=data.get("revised_answer"),
                    )

            # Fallback: try parsing content as JSON
            if response.content:
                try:
                    # Handle code-fenced JSON
                    content = response.content.strip()
                    if content.startswith("```"):
                        # Safe extraction: handle both ```json\n{...}``` and ```{...}```
                        import re
                        match = re.search(r'\{.*\}', content, re.DOTALL)
                        if match:
                            content = match.group(0)
                    data = json.loads(content)
                    return VerificationResult(
                        is_valid=data.get("is_valid", False),
                        confidence=data.get("confidence", 0.5),
                        issues=data.get("issues", issues),
                        revised_answer=data.get("revised_answer"),
                    )
                except (json.JSONDecodeError, KeyError, IndexError):
                    pass

        except Exception as e:
            logger.error("Stage 3 LLM verification failed: %s", e)

        # Ultimate fallback
        return VerificationResult(
            is_valid=False,
            confidence=0.5,
            issues=issues or ["Stage 3 LLM verification inconclusive"],
            revised_answer=None,
        )

    @staticmethod
    def _build_verification_prompt(
        question: str,
        answer: str,
        tool_results: list[str],
        issues: list[str],
        profile: dict[str, Any],
    ) -> str:
        """Build the verification prompt for Stage 3 LLM."""
        parts = [
            f"## Question\n{question}",
            f"## Answer to verify\n{answer}",
        ]

        if tool_results:
            tr_text = "\n".join(f"- Result {i+1}: {r[:200]}" for i, r in enumerate(tool_results))
            parts.append(f"## Tool Results\n{tr_text}")

        if issues:
            issues_text = "\n".join(f"- {issue}" for issue in issues)
            parts.append(f"## Issues found by earlier stages\n{issues_text}")

        if profile:
            profile_text = json.dumps(profile, ensure_ascii=False, indent=2)
            parts.append(f"## User Profile\n```json\n{profile_text}\n```")

        parts.append(
            "## Task\n"
            "Verify the answer against the tool results and profile. "
            "Use the submit_verification tool to report your findings."
        )

        return "\n\n".join(parts)
