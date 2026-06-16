# Feature: agentic-evaluation, Property 4: Agent failure resilience
"""Property-based tests for Coaching Supervisor resilience.

Property 4: Agent failure resilience — For any subset of agents that fail,
the supervisor still returns results from the remaining successful agents
without crashing.

Validates: Requirements 4.4
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite

from agents.coaching_supervisor import CoachingSupervisor
from agents.registry import AgentRegistry
from models.data_models import (
    AgentDescriptor,
    EvaluationInput,
    EvaluationResult,
    Finding,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALL_DIMENSIONS = [
    "delivery",
    "structure",
    "executive_presence",
    "technical_communication",
    "audience_engagement",
    "pacing",
    "persuasion",
]

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

non_empty_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=50,
)


@composite
def failing_and_succeeding_dimensions(draw):
    """Generate random subsets of the 7 dimensions split into failing and succeeding.

    Ensures at least one dimension is in one of the sets (non-empty total).
    The test asserts resilience, so we need at least one failing dimension
    and at least one succeeding dimension to verify partial failure behavior.
    """
    # Draw a random subset that will fail (at least 1)
    all_dims = list(ALL_DIMENSIONS)
    # Draw which dimensions fail (at least 1, at most 6 so at least 1 succeeds)
    num_failing = draw(st.integers(min_value=1, max_value=len(all_dims) - 1))
    failing = draw(
        st.lists(
            st.sampled_from(all_dims),
            min_size=num_failing,
            max_size=num_failing,
            unique=True,
        )
    )
    succeeding = [d for d in all_dims if d not in failing]
    return failing, succeeding


@composite
def valid_evaluation_input(draw):
    """Generate a valid EvaluationInput instance."""
    return EvaluationInput(
        submission_id=draw(non_empty_text),
        s3_bucket=draw(non_empty_text),
        s3_key=draw(non_empty_text),
        dimension=draw(st.sampled_from(ALL_DIMENSIONS)),
        user_id=draw(non_empty_text),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evaluation_result(dimension: str) -> EvaluationResult:
    """Create a valid EvaluationResult for a given dimension."""
    return EvaluationResult(
        dimension=dimension,
        score=7.5,
        findings=[
            Finding(
                category="test_category",
                detail="Test observation for " + dimension,
                severity="medium",
                suggestion="Test suggestion",
            )
        ],
        strengths=["Good " + dimension],
        improvements=["Improve " + dimension],
        agent_id=f"{dimension}-evaluator-v1",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _create_manifest_with_all_enabled() -> Path:
    """Create a temporary manifest with all 7 agents enabled."""
    agents_data = []
    for dim in ALL_DIMENSIONS:
        agents_data.append(
            {
                "agent_id": f"{dim}-evaluator-v1",
                "dimension": dim,
                "display_name": f"{dim.replace('_', ' ').title()} Evaluator",
                "description": f"Evaluates {dim}.",
                "version": "1.0.0",
                "enabled": True,
                "tool_module": f"agents.{dim}_evaluator",
            }
        )

    manifest = {"agents": agents_data}
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(manifest, tmp, indent=2)
    tmp.close()
    return Path(tmp.name)


# ---------------------------------------------------------------------------
# Property 4: Agent failure resilience
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=5000)
@given(
    dim_split=failing_and_succeeding_dimensions(),
    eval_input=valid_evaluation_input(),
)
def test_agent_failure_resilience(
    dim_split: tuple[list[str], list[str]],
    eval_input: EvaluationInput,
) -> None:
    """For any subset of agents that fail, the supervisor still returns
    results from the remaining successful agents without crashing.

    1. Generates random subsets of 7 dimensions where some are "failing"
       and some are "succeeding".
    2. Mocks _invoke_single_tool so that "failing" dimensions raise
       exceptions while "succeeding" ones return valid EvaluationResult.
    3. Asserts that the supervisor returns results for all successful
       dimensions and does not crash.
    4. Asserts that the count of successful results equals the number
       of non-failing dimensions.

    **Validates: Requirements 4.4**
    """
    failing_dims, succeeding_dims = dim_split

    # Create a registry with all agents enabled
    manifest_path = _create_manifest_with_all_enabled()

    try:
        registry = AgentRegistry(manifest_path=manifest_path)

        # Create a mock agent that we'll pass to avoid actual Strands Agent creation
        mock_strands_agent = MagicMock()
        # Make the agent call raise so the supervisor falls back to _direct_invoke_tools
        mock_strands_agent.side_effect = RuntimeError(
            "Simulated agent orchestration failure"
        )

        supervisor = CoachingSupervisor(registry=registry, agent=mock_strands_agent)

        # Mock _invoke_single_tool to control which dimensions succeed/fail
        def mock_invoke_single_tool(input: EvaluationInput, dimension: str):
            if dimension in failing_dims:
                raise RuntimeError(f"Simulated failure for {dimension}")
            return _make_evaluation_result(dimension)

        # Patch _invoke_single_tool on the supervisor instance
        supervisor._invoke_single_tool = mock_invoke_single_tool  # type: ignore[assignment]

        # All dimensions requested
        all_requested = failing_dims + succeeding_dims

        # Call evaluate — it should NOT crash
        results = supervisor.evaluate(input=eval_input, dimensions=all_requested)

        # Assert: results only contain successful dimensions
        result_dimensions = {r.dimension for r in results}
        expected_dimensions = set(succeeding_dims)

        assert result_dimensions == expected_dimensions, (
            f"Expected results for dimensions {expected_dimensions}, "
            f"got {result_dimensions}. "
            f"Failing: {failing_dims}, Succeeding: {succeeding_dims}"
        )

        # Assert: count of results equals number of succeeding dimensions
        assert len(results) == len(succeeding_dims), (
            f"Expected {len(succeeding_dims)} results, got {len(results)}"
        )

        # Assert: each result is a valid EvaluationResult
        for result in results:
            assert isinstance(result, EvaluationResult)
            assert result.dimension in succeeding_dims
            assert 0.0 <= result.score <= 10.0
            assert len(result.agent_id) >= 1

    finally:
        manifest_path.unlink(missing_ok=True)
