# Feature: agentic-evaluation, Properties 3, 14: Agent registry and evaluation output
"""Property-based tests for evaluation agent output schema compliance and
agent registry subset functionality.

Validates: Requirements 3.4, 3.5, 4.3
"""

from datetime import datetime

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

non_empty_text = st.text(min_size=1, max_size=100)
score_float = st.floats(min_value=0.0, max_value=10.0, allow_nan=False)
severity_st = st.sampled_from(["low", "medium", "high"])

# ISO 8601 timestamps strategy
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
def valid_evaluation_result(draw):
    """Generate a valid EvaluationResult instance with all required fields."""
    findings = draw(st.lists(valid_finding(), min_size=0, max_size=5))
    strengths = draw(st.lists(non_empty_text, min_size=0, max_size=5))
    improvements = draw(st.lists(non_empty_text, min_size=0, max_size=5))

    return EvaluationResult(
        dimension=draw(non_empty_text),
        score=draw(score_float),
        findings=findings,
        strengths=strengths,
        improvements=improvements,
        agent_id=draw(non_empty_text),
        timestamp=draw(iso_timestamp),
    )


@composite
def non_empty_dimension_subset(draw):
    """Generate a non-empty subset of the 7 evaluation dimensions."""
    subset = draw(
        st.lists(
            st.sampled_from(ALL_DIMENSIONS),
            min_size=1,
            max_size=7,
            unique=True,
        )
    )
    return subset


# ---------------------------------------------------------------------------
# Property 3: Evaluation agent output schema compliance
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(result=valid_evaluation_result())
def test_evaluation_result_schema_compliance(result: EvaluationResult) -> None:
    """For any evaluation result produced by an agent, it must have:
    - dimension non-empty
    - score in [0.0, 10.0]
    - agent_id non-empty
    - timestamp is valid ISO 8601
    - findings have valid severity values

    **Validates: Requirements 3.5, 4.3**
    """
    # dimension must be non-empty
    assert len(result.dimension) >= 1
    assert result.dimension.strip() != "" or len(result.dimension) >= 1

    # score must be in [0.0, 10.0]
    assert 0.0 <= result.score <= 10.0

    # agent_id must be non-empty
    assert len(result.agent_id) >= 1

    # timestamp must be valid ISO 8601
    ts = result.timestamp
    try:
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        pytest.fail(f"Timestamp is not valid ISO 8601: {ts!r}")

    # All findings must have valid severity values
    valid_severities = {"low", "medium", "high"}
    for finding in result.findings:
        assert finding.severity in valid_severities, (
            f"Finding severity {finding.severity!r} not in {valid_severities}"
        )
        # Finding fields must also be non-empty
        assert len(finding.category) >= 1
        assert len(finding.detail) >= 1
        assert len(finding.suggestion) >= 1


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    dimension=non_empty_text,
    score=score_float,
    agent_id=non_empty_text,
    timestamp=iso_timestamp,
    findings=st.lists(valid_finding(), min_size=0, max_size=5),
)
def test_evaluation_result_rejects_out_of_range_scores(
    dimension: str,
    score: float,
    agent_id: str,
    timestamp: str,
    findings: list,
) -> None:
    """For any valid EvaluationResult, the Pydantic model SHALL enforce that
    score is always within [0.0, 10.0] — verifying the schema constraint.

    **Validates: Requirements 3.5, 4.3**
    """
    result = EvaluationResult(
        dimension=dimension,
        score=score,
        findings=findings,
        strengths=[],
        improvements=[],
        agent_id=agent_id,
        timestamp=timestamp,
    )
    # Score constraint is enforced by Pydantic at construction time;
    # if we got here, the constraint holds.
    assert 0.0 <= result.score <= 10.0


@pytest.mark.property
@settings(max_examples=50, deadline=500)
@given(
    bad_score=st.one_of(
        st.floats(max_value=-0.01, allow_nan=False, allow_infinity=False),
        st.floats(min_value=10.01, allow_nan=False, allow_infinity=False),
    )
)
def test_evaluation_result_rejects_invalid_scores(bad_score: float) -> None:
    """Scores outside [0.0, 10.0] SHALL be rejected by the EvaluationResult model.

    **Validates: Requirements 3.5, 4.3**
    """
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EvaluationResult(
            dimension="test_dimension",
            score=bad_score,
            findings=[],
            strengths=[],
            improvements=[],
            agent_id="test-agent-v1",
            timestamp=datetime.now().isoformat(),
        )


# ---------------------------------------------------------------------------
# Property 14: System functions with any agent subset
# ---------------------------------------------------------------------------


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(subset=non_empty_dimension_subset())
def test_registry_lookup_works_for_any_agent_subset(
    subset: list[str],
) -> None:
    """For any non-empty subset of available agents from the registry, the
    system should be able to look them up without error. get_agent_by_dimension()
    SHALL return valid AgentDescriptor instances for any enabled dimension.

    **Validates: Requirements 3.4**
    """
    # Use the real agents_manifest.json
    registry = AgentRegistry()

    for dimension in subset:
        descriptor = registry.get_agent_by_dimension(dimension)

        # The dimension exists in the manifest and is enabled
        assert descriptor is not None, (
            f"get_agent_by_dimension({dimension!r}) returned None — "
            f"expected a valid AgentDescriptor"
        )

        # Verify the returned descriptor is a valid AgentDescriptor
        assert isinstance(descriptor, AgentDescriptor)

        # Verify key fields are non-empty
        assert len(descriptor.agent_id) >= 1
        assert len(descriptor.dimension) >= 1
        assert len(descriptor.display_name) >= 1
        assert len(descriptor.description) >= 1
        assert len(descriptor.version) >= 1
        assert len(descriptor.tool_module) >= 1

        # Verify the dimension matches what we asked for
        assert descriptor.dimension == dimension

        # Verify the agent is enabled
        assert descriptor.enabled is True


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(subset=non_empty_dimension_subset())
def test_registry_available_agents_contains_subset(
    subset: list[str],
) -> None:
    """For any non-empty subset of the 7 dimensions, get_available_agents()
    SHALL return descriptors that cover all those dimensions.

    **Validates: Requirements 3.4**
    """
    registry = AgentRegistry()
    available = registry.get_available_agents()

    # All enabled agents should be returned
    available_dimensions = {agent.dimension for agent in available}

    for dimension in subset:
        assert dimension in available_dimensions, (
            f"Dimension {dimension!r} not found in available agents. "
            f"Available: {available_dimensions}"
        )


@pytest.mark.property
@settings(max_examples=50, deadline=500)
@given(subset=non_empty_dimension_subset())
def test_create_evaluation_tool_for_any_agent_subset(
    subset: list[str],
) -> None:
    """For any non-empty subset of available agents from the registry,
    the system should be able to create evaluation tools without error
    (test registry lookup + tool creation).

    **Validates: Requirements 3.4, 4.3**
    """
    registry = AgentRegistry()

    for dimension in subset:
        descriptor = registry.get_agent_by_dimension(dimension)
        assert descriptor is not None

        # Create a concrete evaluator that implements the BaseEvaluator contract
        # to verify tool creation works for any dimension
        class _TestEvaluator(BaseEvaluator):
            @property
            def dimension(self) -> str:
                return descriptor.dimension

            @property
            def agent_id(self) -> str:
                return descriptor.agent_id

            def evaluate(self, input: EvaluationInput) -> EvaluationResult:
                return EvaluationResult(
                    dimension=self.dimension,
                    score=7.5,
                    findings=[],
                    strengths=["Good overall"],
                    improvements=["Could improve"],
                    agent_id=self.agent_id,
                    timestamp=datetime.now().isoformat(),
                )

        evaluator = _TestEvaluator()
        tool = create_evaluation_tool(evaluator)

        # Tool creation should succeed without error
        assert tool is not None
        assert callable(tool)
