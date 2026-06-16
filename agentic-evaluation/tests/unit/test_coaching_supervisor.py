"""Unit tests for the Coaching Supervisor Agent.

Tests orchestration of evaluation agents, partial failure handling,
iterative invocation based on findings, and completion signaling.

Requirements: 2.1, 2.3, 2.5, 4.4
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from agents.coaching_supervisor import CoachingSupervisor
from models.data_models import (
    AgentDescriptor,
    EvaluationInput,
    EvaluationResult,
    Finding,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_descriptor(dimension: str, enabled: bool = True) -> AgentDescriptor:
    """Create a test AgentDescriptor for a given dimension."""
    return AgentDescriptor(
        agent_id=f"{dimension}-evaluator-v1",
        dimension=dimension,
        display_name=f"{dimension.replace('_', ' ').title()} Evaluator",
        description=f"Evaluates {dimension}",
        version="1.0.0",
        enabled=enabled,
        tool_module=f"agents.{dimension}_evaluator",
    )


def _make_evaluation_result(
    dimension: str, findings: list[Finding] | None = None
) -> EvaluationResult:
    """Create a test EvaluationResult for a given dimension."""
    return EvaluationResult(
        dimension=dimension,
        score=7.5,
        findings=findings or [],
        strengths=[f"Good {dimension}"],
        improvements=[f"Improve {dimension}"],
        agent_id=f"{dimension}-evaluator-v1",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def _make_evaluation_input() -> EvaluationInput:
    """Create a standard test EvaluationInput."""
    return EvaluationInput(
        submission_id="sub-12345",
        s3_bucket="test-bucket",
        s3_key="presentations/sub-12345/data.json",
        dimension="delivery",
        user_id="user-abc",
    )


def _mock_registry(dimensions: list[str]) -> MagicMock:
    """Create a mock AgentRegistry returning descriptors for the given dimensions."""
    registry = MagicMock()
    descriptors = [_make_descriptor(dim) for dim in dimensions]
    registry.get_available_agents.return_value = descriptors

    def get_by_dim(dim: str):
        for d in descriptors:
            if d.dimension == dim:
                return d
        return None

    registry.get_agent_by_dimension.side_effect = get_by_dim
    return registry


# ---------------------------------------------------------------------------
# Successful orchestration with all agents
# ---------------------------------------------------------------------------


class TestCoachingSupervisorSuccessfulOrchestration:
    """Tests that all agents successfully produce evaluation results.

    Requirements: 2.1, 2.3
    """

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_all_agents_succeed_returns_all_results(self, mock_import):
        """When all agents succeed, evaluate() returns results for every dimension."""
        dimensions = ["delivery", "structure", "pacing"]
        registry = _mock_registry(dimensions)

        # Mock tool loading - each module returns a create_tool factory
        def fake_import(module_name):
            dim = module_name.replace("agents.", "").replace("_evaluator", "")
            mock_module = MagicMock()
            tool_fn = MagicMock()
            tool_fn.__name__ = f"{dim}_evaluator_tool"
            mock_module.create_tool.return_value = tool_fn
            return mock_module

        mock_import.side_effect = fake_import

        supervisor = CoachingSupervisor(registry=registry)

        # Mock _invoke_single_tool to return controlled results
        results_map = {dim: _make_evaluation_result(dim) for dim in dimensions}

        def mock_invoke(input_arg, dim):
            return results_map.get(dim)

        # Bypass the Strands agent by making _invoke_agent delegate to _direct_invoke_tools
        def fake_invoke_agent(inp, dims, prompt):
            return supervisor._direct_invoke_tools(inp, dims)

        with patch.object(supervisor, "_invoke_single_tool", side_effect=mock_invoke):
            with patch.object(supervisor, "_invoke_agent", side_effect=fake_invoke_agent):
                eval_input = _make_evaluation_input()
                results = supervisor.evaluate(eval_input, dimensions)

        assert len(results) == 3
        result_dims = {r.dimension for r in results}
        assert result_dims == {"delivery", "structure", "pacing"}

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_all_results_are_evaluation_result_instances(self, mock_import):
        """Each returned result is a valid EvaluationResult instance."""
        dimensions = ["delivery", "structure"]
        registry = _mock_registry(dimensions)

        def fake_import(module_name):
            dim = module_name.replace("agents.", "").replace("_evaluator", "")
            mock_module = MagicMock()
            tool_fn = MagicMock()
            tool_fn.__name__ = f"{dim}_evaluator_tool"
            mock_module.create_tool.return_value = tool_fn
            return mock_module

        mock_import.side_effect = fake_import

        supervisor = CoachingSupervisor(registry=registry)

        results_map = {dim: _make_evaluation_result(dim) for dim in dimensions}

        def mock_invoke(input_arg, dim):
            return results_map.get(dim)

        def fake_invoke_agent(inp, dims, prompt):
            return supervisor._direct_invoke_tools(inp, dims)

        with patch.object(supervisor, "_invoke_single_tool", side_effect=mock_invoke):
            with patch.object(supervisor, "_invoke_agent", side_effect=fake_invoke_agent):
                eval_input = _make_evaluation_input()
                results = supervisor.evaluate(eval_input, dimensions)

        for result in results:
            assert isinstance(result, EvaluationResult)
            assert result.score >= 0.0
            assert result.score <= 10.0


# ---------------------------------------------------------------------------
# Partial failure (some agents succeed, some fail)
# ---------------------------------------------------------------------------


class TestCoachingSupervisorPartialFailure:
    """Tests that the supervisor handles individual agent failures gracefully.

    Requirements: 4.4
    """

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_one_agent_fails_returns_partial_results(self, mock_import):
        """When one agent fails, results from successful agents are still returned."""
        dimensions = ["delivery", "structure", "pacing"]
        registry = _mock_registry(dimensions)

        def fake_import(module_name):
            dim = module_name.replace("agents.", "").replace("_evaluator", "")
            mock_module = MagicMock()
            tool_fn = MagicMock()
            tool_fn.__name__ = f"{dim}_evaluator_tool"
            mock_module.create_tool.return_value = tool_fn
            return mock_module

        mock_import.side_effect = fake_import

        supervisor = CoachingSupervisor(registry=registry)

        # Structure agent fails (returns None), others succeed
        def mock_invoke(input_arg, dim):
            if dim == "structure":
                return None  # Simulate failure
            return _make_evaluation_result(dim)

        def fake_invoke_agent(inp, dims, prompt):
            return supervisor._direct_invoke_tools(inp, dims)

        with patch.object(supervisor, "_invoke_single_tool", side_effect=mock_invoke):
            with patch.object(supervisor, "_invoke_agent", side_effect=fake_invoke_agent):
                eval_input = _make_evaluation_input()
                results = supervisor.evaluate(eval_input, dimensions)

        assert len(results) == 2
        result_dims = {r.dimension for r in results}
        assert "delivery" in result_dims
        assert "pacing" in result_dims
        assert "structure" not in result_dims

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_all_agents_fail_returns_empty_list(self, mock_import):
        """When all agents fail, evaluate() returns an empty list."""
        dimensions = ["delivery", "structure"]
        registry = _mock_registry(dimensions)

        def fake_import(module_name):
            dim = module_name.replace("agents.", "").replace("_evaluator", "")
            mock_module = MagicMock()
            tool_fn = MagicMock()
            tool_fn.__name__ = f"{dim}_evaluator_tool"
            mock_module.create_tool.return_value = tool_fn
            return mock_module

        mock_import.side_effect = fake_import

        supervisor = CoachingSupervisor(registry=registry)

        def mock_invoke(input_arg, dim):
            return None  # All fail

        def fake_invoke_agent(inp, dims, prompt):
            return supervisor._direct_invoke_tools(inp, dims)

        with patch.object(supervisor, "_invoke_single_tool", side_effect=mock_invoke):
            with patch.object(supervisor, "_invoke_agent", side_effect=fake_invoke_agent):
                eval_input = _make_evaluation_input()
                results = supervisor.evaluate(eval_input, dimensions)

        assert results == []


# ---------------------------------------------------------------------------
# Iterative invocation (additional agent triggered by findings)
# ---------------------------------------------------------------------------


class TestCoachingSupervisorIterativeInvocation:
    """Tests that findings from one agent can trigger additional dimension evaluation.

    Requirements: 2.3, 2.5
    """

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_findings_trigger_additional_dimension(self, mock_import):
        """Findings mentioning pacing issues trigger the pacing evaluator."""
        # Start with delivery only, but pacing is available in the registry
        all_dims = ["delivery", "pacing"]
        registry = _mock_registry(all_dims)

        def fake_import(module_name):
            dim = module_name.replace("agents.", "").replace("_evaluator", "")
            mock_module = MagicMock()
            tool_fn = MagicMock()
            tool_fn.__name__ = f"{dim}_evaluator_tool"
            mock_module.create_tool.return_value = tool_fn
            return mock_module

        mock_import.side_effect = fake_import

        supervisor = CoachingSupervisor(registry=registry)

        # Delivery result has findings that mention pacing
        delivery_findings = [
            Finding(
                category="vocal_variety",
                detail="Speaker talks too fast in several sections",
                severity="high",
                suggestion="Slow down pacing in key transitions",
            )
        ]
        delivery_result = _make_evaluation_result("delivery", findings=delivery_findings)
        pacing_result = _make_evaluation_result("pacing")

        call_count = {"delivery": 0, "pacing": 0}

        def mock_invoke(input_arg, dim):
            call_count[dim] = call_count.get(dim, 0) + 1
            if dim == "delivery":
                return delivery_result
            elif dim == "pacing":
                return pacing_result
            return None

        def fake_invoke_agent(inp, dims, prompt):
            return supervisor._direct_invoke_tools(inp, dims)

        with patch.object(supervisor, "_invoke_single_tool", side_effect=mock_invoke):
            with patch.object(supervisor, "_invoke_agent", side_effect=fake_invoke_agent):
                eval_input = _make_evaluation_input()
                # Request only delivery - pacing should be triggered by findings
                results = supervisor.evaluate(eval_input, ["delivery"])

        result_dims = {r.dimension for r in results}
        assert "delivery" in result_dims
        assert "pacing" in result_dims
        assert len(results) == 2

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_no_additional_dimensions_when_no_trigger_keywords(self, mock_import):
        """When findings don't contain trigger keywords, no extra agents are invoked."""
        all_dims = ["delivery", "pacing"]
        registry = _mock_registry(all_dims)

        def fake_import(module_name):
            dim = module_name.replace("agents.", "").replace("_evaluator", "")
            mock_module = MagicMock()
            tool_fn = MagicMock()
            tool_fn.__name__ = f"{dim}_evaluator_tool"
            mock_module.create_tool.return_value = tool_fn
            return mock_module

        mock_import.side_effect = fake_import

        supervisor = CoachingSupervisor(registry=registry)

        # Findings that do NOT mention other dimension keywords
        delivery_findings = [
            Finding(
                category="volume",
                detail="Good volume control throughout.",
                severity="low",
                suggestion="Keep maintaining consistent volume.",
            )
        ]
        delivery_result = _make_evaluation_result("delivery", findings=delivery_findings)

        def mock_invoke(input_arg, dim):
            if dim == "delivery":
                return delivery_result
            return _make_evaluation_result(dim)

        def fake_invoke_agent(inp, dims, prompt):
            return supervisor._direct_invoke_tools(inp, dims)

        with patch.object(supervisor, "_invoke_single_tool", side_effect=mock_invoke):
            with patch.object(supervisor, "_invoke_agent", side_effect=fake_invoke_agent):
                eval_input = _make_evaluation_input()
                results = supervisor.evaluate(eval_input, ["delivery"])

        result_dims = {r.dimension for r in results}
        assert result_dims == {"delivery"}
        assert len(results) == 1

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_already_evaluated_dimension_not_repeated(self, mock_import):
        """A dimension already being evaluated is not invoked again by triggers."""
        all_dims = ["delivery", "pacing"]
        registry = _mock_registry(all_dims)

        def fake_import(module_name):
            dim = module_name.replace("agents.", "").replace("_evaluator", "")
            mock_module = MagicMock()
            tool_fn = MagicMock()
            tool_fn.__name__ = f"{dim}_evaluator_tool"
            mock_module.create_tool.return_value = tool_fn
            return mock_module

        mock_import.side_effect = fake_import

        supervisor = CoachingSupervisor(registry=registry)

        # Pacing result mentions pacing (self-reference) - should NOT cause re-invoke
        pacing_findings = [
            Finding(
                category="tempo",
                detail="Pacing needs improvement in the introduction.",
                severity="medium",
                suggestion="Adjust pacing for the intro section.",
            )
        ]
        pacing_result = _make_evaluation_result("pacing", findings=pacing_findings)

        invocation_counts: dict[str, int] = {}

        def mock_invoke(input_arg, dim):
            invocation_counts[dim] = invocation_counts.get(dim, 0) + 1
            if dim == "pacing":
                return pacing_result
            return _make_evaluation_result(dim)

        def fake_invoke_agent(inp, dims, prompt):
            return supervisor._direct_invoke_tools(inp, dims)

        with patch.object(supervisor, "_invoke_single_tool", side_effect=mock_invoke):
            with patch.object(supervisor, "_invoke_agent", side_effect=fake_invoke_agent):
                eval_input = _make_evaluation_input()
                results = supervisor.evaluate(eval_input, ["pacing"])

        # Pacing should only be invoked once
        assert invocation_counts.get("pacing", 0) == 1
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Completion signaling
# ---------------------------------------------------------------------------


class TestCoachingSupervisorCompletion:
    """Tests that the supervisor properly signals completion.

    Requirements: 2.5
    """

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_empty_dimensions_returns_empty_list(self, mock_import):
        """Requesting evaluation with an empty dimensions list returns empty results."""
        registry = _mock_registry(["delivery", "structure"])

        def fake_import(module_name):
            mock_module = MagicMock()
            tool_fn = MagicMock()
            tool_fn.__name__ = "some_tool"
            mock_module.create_tool.return_value = tool_fn
            return mock_module

        mock_import.side_effect = fake_import

        supervisor = CoachingSupervisor(registry=registry)
        eval_input = _make_evaluation_input()
        results = supervisor.evaluate(eval_input, [])

        assert results == []

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_unavailable_dimensions_returns_empty_list(self, mock_import):
        """Requesting dimensions that have no registered agents returns empty."""
        # Registry only has delivery
        registry = _mock_registry(["delivery"])

        def fake_import(module_name):
            mock_module = MagicMock()
            tool_fn = MagicMock()
            tool_fn.__name__ = "delivery_evaluator_tool"
            mock_module.create_tool.return_value = tool_fn
            return mock_module

        mock_import.side_effect = fake_import

        supervisor = CoachingSupervisor(registry=registry)
        eval_input = _make_evaluation_input()
        # Request dimensions not in registry
        results = supervisor.evaluate(eval_input, ["nonexistent_dimension"])

        assert results == []

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_evaluate_returns_list_type(self, mock_import):
        """evaluate() always returns a list regardless of outcome."""
        registry = _mock_registry(["delivery"])

        def fake_import(module_name):
            mock_module = MagicMock()
            tool_fn = MagicMock()
            tool_fn.__name__ = "delivery_evaluator_tool"
            mock_module.create_tool.return_value = tool_fn
            return mock_module

        mock_import.side_effect = fake_import

        supervisor = CoachingSupervisor(registry=registry)

        def mock_invoke(input_arg, dim):
            return _make_evaluation_result(dim)

        def fake_invoke_agent(inp, dims, prompt):
            return supervisor._direct_invoke_tools(inp, dims)

        with patch.object(supervisor, "_invoke_single_tool", side_effect=mock_invoke):
            with patch.object(supervisor, "_invoke_agent", side_effect=fake_invoke_agent):
                eval_input = _make_evaluation_input()
                results = supervisor.evaluate(eval_input, ["delivery"])

        assert isinstance(results, list)
