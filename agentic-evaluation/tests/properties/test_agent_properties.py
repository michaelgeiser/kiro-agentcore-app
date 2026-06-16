# Feature: agentic-evaluation, Properties 3, 14: Agent registry and evaluation output
"""Property-based tests for evaluation agent output schema compliance and
agent registry filtering with arbitrary agent subsets.

Property 3: Evaluation agent output schema compliance — For any valid
EvaluationInput, the output of any evaluator must conform to EvaluationResult
schema (score 0-10, valid dimension, non-empty agent_id, valid ISO timestamp).

Property 14: System functions with any agent subset — Given any subset of
agents enabled/disabled in the registry, the system correctly returns only
enabled agents.

Validates: Requirements 3.4, 3.5, 4.3
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.strategies import composite

from agents.base_evaluator import BaseEvaluator, create_evaluation_tool
from agents.registry import AgentRegistry
from models.data_models import (
    AgentDescriptor,
    EvaluationInput,
    EvaluationResult,
    Finding,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

non_empty_text = st.text(min_size=1, max_size=80)
score_float = st.floats(min_value=0.0, max_value=10.0, allow_nan=False)
severity_st = st.sampled_from(["low", "medium", "high"])
iso_timestamp = st.datetimes().map(lambda dt: dt.isoformat())

# The 7 evaluation dimensions from the manifest
ALL_DIMENSIONS = [
    "delivery",
    "structure",
    "executive_presence",
    "technical_communication",
    "audience_engagement",
    "pacing",
    "persuasion",
]


@composite
def valid_finding(draw):
    """Generate a valid Finding instance."""
    return Finding(
        category=draw(non_empty_text),
        detail=draw(non_empty_text),
        severity=draw(severity_st),
        suggestion=draw(non_empty_text),
    )


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


@composite
def agent_enabled_flags(draw):
    """Generate a mapping of dimension -> enabled flag.

    Ensures at least one agent is enabled so the subset is non-empty.
    """
    flags = {}
    for dim in ALL_DIMENSIONS:
        flags[dim] = draw(st.booleans())

    # Ensure at least one agent is enabled
    if not any(flags.values()):
        # Enable a random one
        dim_to_enable = draw(st.sampled_from(ALL_DIMENSIONS))
        flags[dim_to_enable] = True

    return flags


# ---------------------------------------------------------------------------
# Mock Evaluator for Property 3
# ---------------------------------------------------------------------------


class MockEvaluator(BaseEvaluator):
    """A mock evaluator that produces valid EvaluationResult objects.

    Used to verify that any evaluator following the BaseEvaluator contract
    produces schema-compliant output.
    """

    def __init__(
        self,
        dim: str,
        agent_identifier: str,
        mock_score: float,
        mock_findings: list[Finding],
        mock_strengths: list[str],
        mock_improvements: list[str],
    ):
        self._dimension = dim
        self._agent_id = agent_identifier
        self._mock_score = mock_score
        self._mock_findings = mock_findings
        self._mock_strengths = mock_strengths
        self._mock_improvements = mock_improvements

    @property
    def dimension(self) -> str:
        return self._dimension

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        return EvaluationResult(
            dimension=self._dimension,
            score=self._mock_score,
            findings=self._mock_findings,
            strengths=self._mock_strengths,
            improvements=self._mock_improvements,
            agent_id=self._agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# ---------------------------------------------------------------------------
# Property 3: Evaluation agent output schema compliance
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    eval_input=valid_evaluation_input(),
    mock_score=score_float,
    mock_findings=st.lists(valid_finding(), min_size=0, max_size=5),
    mock_strengths=st.lists(non_empty_text, min_size=0, max_size=3),
    mock_improvements=st.lists(non_empty_text, min_size=0, max_size=3),
)
def test_mock_evaluator_output_schema_compliance(
    eval_input: EvaluationInput,
    mock_score: float,
    mock_findings: list[Finding],
    mock_strengths: list[str],
    mock_improvements: list[str],
) -> None:
    """For any valid EvaluationInput, the output of any evaluator must conform
    to EvaluationResult schema: score 0-10, valid dimension, non-empty agent_id,
    valid ISO timestamp.

    Creates a mock evaluator with random valid parameters and invokes it,
    then verifies the output conforms to the schema contract.

    **Validates: Requirements 3.5, 4.3**
    """
    evaluator = MockEvaluator(
        dim=eval_input.dimension,
        agent_identifier=f"{eval_input.dimension}-evaluator-v1",
        mock_score=mock_score,
        mock_findings=mock_findings,
        mock_strengths=mock_strengths,
        mock_improvements=mock_improvements,
    )

    # Invoke the evaluator
    result = evaluator.evaluate(eval_input)

    # Verify schema compliance
    assert isinstance(result, EvaluationResult)

    # Score must be in [0.0, 10.0]
    assert 0.0 <= result.score <= 10.0

    # Dimension must be non-empty and match the evaluator's dimension
    assert len(result.dimension) >= 1
    assert result.dimension == eval_input.dimension

    # Agent_id must be non-empty
    assert len(result.agent_id) >= 1

    # Timestamp must be valid ISO 8601
    try:
        datetime.fromisoformat(result.timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        pytest.fail(f"Timestamp is not valid ISO 8601: {result.timestamp!r}")

    # All findings must have valid severity values
    valid_severities = {"low", "medium", "high"}
    for finding in result.findings:
        assert finding.severity in valid_severities


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    eval_input=valid_evaluation_input(),
    mock_score=score_float,
    mock_findings=st.lists(valid_finding(), min_size=0, max_size=3),
)
def test_evaluation_tool_output_schema_compliance(
    eval_input: EvaluationInput,
    mock_score: float,
    mock_findings: list[Finding],
) -> None:
    """For any valid EvaluationInput, the tool wrapper around an evaluator
    SHALL produce a JSON string that deserializes to a valid EvaluationResult
    with score 0-10, valid dimension, non-empty agent_id, valid ISO timestamp.

    This tests the create_evaluation_tool() wrapper end-to-end.

    **Validates: Requirements 3.5, 4.3**
    """
    evaluator = MockEvaluator(
        dim=eval_input.dimension,
        agent_identifier=f"{eval_input.dimension}-evaluator-v1",
        mock_score=mock_score,
        mock_findings=mock_findings,
        mock_strengths=["Strong point"],
        mock_improvements=["Area to improve"],
    )

    tool_fn = create_evaluation_tool(evaluator)
    assert tool_fn is not None

    # Invoke the tool with JSON input
    input_json = eval_input.model_dump_json()
    result_json = tool_fn(evaluation_input_json=input_json)

    # The result should be parseable JSON
    result_data = json.loads(result_json)

    # Should not be an error response
    assert "error" not in result_data, f"Tool returned error: {result_data}"

    # Validate as EvaluationResult
    result = EvaluationResult.model_validate(result_data)

    # Score must be in [0.0, 10.0]
    assert 0.0 <= result.score <= 10.0

    # Dimension must be non-empty
    assert len(result.dimension) >= 1

    # Agent_id must be non-empty
    assert len(result.agent_id) >= 1

    # Timestamp must be valid ISO 8601
    try:
        datetime.fromisoformat(result.timestamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        pytest.fail(f"Timestamp is not valid ISO 8601: {result.timestamp!r}")


# ---------------------------------------------------------------------------
# Property 14: System functions with any agent subset
# ---------------------------------------------------------------------------


def _create_temp_manifest(enabled_flags: dict[str, bool]) -> Path:
    """Create a temporary agents_manifest.json with specified enabled flags.

    Args:
        enabled_flags: Mapping of dimension name to enabled boolean.

    Returns:
        Path to the temporary manifest file.
    """
    # Base agent data matching the real manifest structure
    agents_data = {
        "delivery": {
            "agent_id": "delivery-evaluator-v1",
            "display_name": "Delivery Evaluator",
            "description": "Assesses delivery effectiveness.",
            "version": "1.0.0",
            "tool_module": "src.agents.delivery_evaluator",
        },
        "structure": {
            "agent_id": "structure-evaluator-v1",
            "display_name": "Structure Evaluator",
            "description": "Evaluates structure and flow.",
            "version": "1.0.0",
            "tool_module": "src.agents.structure_evaluator",
        },
        "executive_presence": {
            "agent_id": "executive-presence-evaluator-v1",
            "display_name": "Executive Presence Evaluator",
            "description": "Assesses executive presence.",
            "version": "1.0.0",
            "tool_module": "src.agents.executive_presence_evaluator",
        },
        "technical_communication": {
            "agent_id": "technical-communication-evaluator-v1",
            "display_name": "Technical Communication Evaluator",
            "description": "Evaluates technical communication.",
            "version": "1.0.0",
            "tool_module": "src.agents.technical_communication_evaluator",
        },
        "audience_engagement": {
            "agent_id": "audience-engagement-evaluator-v1",
            "display_name": "Audience Engagement Evaluator",
            "description": "Assesses audience engagement.",
            "version": "1.0.0",
            "tool_module": "src.agents.audience_engagement_evaluator",
        },
        "pacing": {
            "agent_id": "pacing-evaluator-v1",
            "display_name": "Pacing Evaluator",
            "description": "Evaluates pacing and timing.",
            "version": "1.0.0",
            "tool_module": "src.agents.pacing_evaluator",
        },
        "persuasion": {
            "agent_id": "persuasion-evaluator-v1",
            "display_name": "Persuasion Evaluator",
            "description": "Assesses persuasive impact.",
            "version": "1.0.0",
            "tool_module": "src.agents.persuasion_evaluator",
        },
    }

    manifest = {"agents": []}
    for dim, data in agents_data.items():
        entry = {
            "agent_id": data["agent_id"],
            "dimension": dim,
            "display_name": data["display_name"],
            "description": data["description"],
            "version": data["version"],
            "enabled": enabled_flags.get(dim, True),
            "tool_module": data["tool_module"],
        }
        manifest["agents"].append(entry)

    # Write to a temp file
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(manifest, tmp, indent=2)
    tmp.close()
    return Path(tmp.name)


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(enabled_flags=agent_enabled_flags())
def test_registry_returns_only_enabled_agents(
    enabled_flags: dict[str, bool],
) -> None:
    """Given any subset of agents enabled/disabled in the registry, the system
    correctly returns only enabled agents via get_available_agents().

    Creates a temporary manifest with random enabled/disabled flags and verifies
    the registry filters correctly.

    **Validates: Requirements 3.4**
    """
    manifest_path = _create_temp_manifest(enabled_flags)

    try:
        registry = AgentRegistry(manifest_path=manifest_path)
        available = registry.get_available_agents()

        # Compute expected enabled dimensions
        expected_enabled = {dim for dim, flag in enabled_flags.items() if flag}
        expected_disabled = {dim for dim, flag in enabled_flags.items() if not flag}

        # Available agents should exactly match the enabled set
        available_dimensions = {agent.dimension for agent in available}
        assert available_dimensions == expected_enabled, (
            f"Expected enabled: {expected_enabled}, got: {available_dimensions}"
        )

        # No disabled dimensions should appear
        for dim in expected_disabled:
            assert dim not in available_dimensions, (
                f"Disabled dimension {dim!r} should not be in available agents"
            )

        # All returned agents should be valid AgentDescriptors
        for agent in available:
            assert isinstance(agent, AgentDescriptor)
            assert agent.enabled is True
            assert len(agent.agent_id) >= 1
            assert len(agent.dimension) >= 1
            assert len(agent.display_name) >= 1
    finally:
        manifest_path.unlink(missing_ok=True)


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(enabled_flags=agent_enabled_flags())
def test_registry_get_agent_by_dimension_respects_enabled_flag(
    enabled_flags: dict[str, bool],
) -> None:
    """Given any subset of agents enabled/disabled, get_agent_by_dimension()
    SHALL return the agent only if it is enabled, and None if disabled.

    **Validates: Requirements 3.4**
    """
    manifest_path = _create_temp_manifest(enabled_flags)

    try:
        registry = AgentRegistry(manifest_path=manifest_path)

        for dim, is_enabled in enabled_flags.items():
            result = registry.get_agent_by_dimension(dim)

            if is_enabled:
                assert result is not None, (
                    f"Enabled dimension {dim!r} returned None"
                )
                assert result.dimension == dim
                assert result.enabled is True
            else:
                assert result is None, (
                    f"Disabled dimension {dim!r} should return None, "
                    f"got {result!r}"
                )
    finally:
        manifest_path.unlink(missing_ok=True)


@pytest.mark.property
@settings(max_examples=50, deadline=500)
@given(enabled_flags=agent_enabled_flags())
def test_registry_agent_count_matches_enabled_count(
    enabled_flags: dict[str, bool],
) -> None:
    """The number of agents returned by get_available_agents() SHALL equal
    the number of dimensions set to enabled=True in the manifest.

    **Validates: Requirements 3.4**
    """
    manifest_path = _create_temp_manifest(enabled_flags)

    try:
        registry = AgentRegistry(manifest_path=manifest_path)
        available = registry.get_available_agents()

        expected_count = sum(1 for flag in enabled_flags.values() if flag)
        assert len(available) == expected_count, (
            f"Expected {expected_count} enabled agents, "
            f"got {len(available)}"
        )
    finally:
        manifest_path.unlink(missing_ok=True)
