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


# ---------------------------------------------------------------------------
# Duplicate collapse logic (_collapse_duplicates)
# ---------------------------------------------------------------------------


class TestCollapseDuplicates:
    """Tests for the _collapse_duplicates() synthesis pass method.

    Requirements: 1.2, 1.3
    """

    def _make_supervisor(self) -> CoachingSupervisor:
        """Create a CoachingSupervisor with a mocked registry (no tools needed)."""
        registry = _mock_registry(["delivery", "structure", "pacing"])
        supervisor = CoachingSupervisor(registry=registry)
        return supervisor

    def _make_result_with_category(
        self, dimension: str, score: float, category: str
    ) -> EvaluationResult:
        """Create an EvaluationResult with a finding of the given category."""
        return EvaluationResult(
            dimension=dimension,
            score=score,
            findings=[
                Finding(
                    category=category,
                    detail=f"Issue observed in {dimension}",
                    severity="medium",
                    suggestion=f"Suggestion for {dimension}",
                )
            ],
            strengths=[f"Good {dimension}"],
            improvements=[f"Improve {dimension}"],
            agent_id=f"{dimension}-evaluator-v1",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_collapse_when_3_agents_same_category(self, mock_import):
        """Findings with same category from ≥3 dimensions collapse into one."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        results = [
            self._make_result_with_category("delivery", 6.0, "filler_words"),
            self._make_result_with_category("structure", 5.0, "filler_words"),
            self._make_result_with_category("pacing", 7.0, "filler_words"),
        ]

        synthesized = supervisor._collapse_duplicates(results)

        # Should collapse to exactly one finding for "filler_words"
        assert len(synthesized) == 1
        assert synthesized[0].cross_dimension_note is not None

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_no_collapse_when_fewer_than_3_agents(self, mock_import):
        """Findings from fewer than 3 dimensions are not collapsed."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        results = [
            self._make_result_with_category("delivery", 6.0, "filler_words"),
            self._make_result_with_category("structure", 5.0, "filler_words"),
        ]

        synthesized = supervisor._collapse_duplicates(results)

        # Should NOT collapse — two individual findings returned
        assert len(synthesized) == 2
        for finding in synthesized:
            assert finding.cross_dimension_note is None

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_collapsed_finding_attributed_to_lowest_score_dimension(self, mock_import):
        """Collapsed finding is attributed to the dimension with lowest score."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        # Structure has lowest score (3.0) — highest cost
        results = [
            self._make_result_with_category("delivery", 7.0, "filler_words"),
            self._make_result_with_category("structure", 3.0, "filler_words"),
            self._make_result_with_category("pacing", 8.0, "filler_words"),
        ]

        synthesized = supervisor._collapse_duplicates(results)

        assert len(synthesized) == 1
        # Projected impact = 10.0 - 3.0 = 7.0 (highest cost dimension)
        assert synthesized[0].projected_impact_score == 7.0

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_cross_dimension_note_max_120_chars(self, mock_import):
        """The cross_dimension_note field is at most 120 characters."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        results = [
            self._make_result_with_category("delivery", 6.0, "filler_words"),
            self._make_result_with_category("structure", 5.0, "filler_words"),
            self._make_result_with_category("pacing", 7.0, "filler_words"),
        ]

        synthesized = supervisor._collapse_duplicates(results)

        assert len(synthesized) == 1
        note = synthesized[0].cross_dimension_note
        assert note is not None
        assert len(note) <= 120

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_cross_dimension_note_lists_other_dimensions(self, mock_import):
        """The cross_dimension_note identifies which other dimensions are affected."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        # Structure is the primary (lowest score), so note should mention Delivery and Pacing
        results = [
            self._make_result_with_category("delivery", 7.0, "filler_words"),
            self._make_result_with_category("structure", 3.0, "filler_words"),
            self._make_result_with_category("pacing", 8.0, "filler_words"),
        ]

        synthesized = supervisor._collapse_duplicates(results)

        note = synthesized[0].cross_dimension_note
        assert "Delivery" in note
        assert "Pacing" in note

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_mixed_categories_only_collapse_qualifying(self, mock_import):
        """Only categories with ≥3 agents collapse; others pass through."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        results = [
            self._make_result_with_category("delivery", 6.0, "filler_words"),
            self._make_result_with_category("structure", 5.0, "filler_words"),
            self._make_result_with_category("pacing", 7.0, "filler_words"),
            # This one has a unique category — should not be collapsed
            self._make_result_with_category("delivery", 6.0, "eye_contact"),
        ]
        # Add a second finding to delivery's result
        results[0].findings.append(
            Finding(
                category="vocal_variety",
                detail="Monotone delivery",
                severity="low",
                suggestion="Vary pitch",
            )
        )

        synthesized = supervisor._collapse_duplicates(results)

        # "filler_words" collapsed into 1, "eye_contact" stays as 1,
        # "vocal_variety" stays as 1 => total 3
        assert len(synthesized) == 3
        collapsed = [f for f in synthesized if f.cross_dimension_note is not None]
        assert len(collapsed) == 1

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_empty_results_returns_empty_list(self, mock_import):
        """An empty results list returns an empty list of synthesized findings."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        synthesized = supervisor._collapse_duplicates([])
        assert synthesized == []

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_results_with_no_findings_returns_empty(self, mock_import):
        """Results without any findings return empty synthesized list."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        results = [
            EvaluationResult(
                dimension="delivery",
                score=8.0,
                findings=[],
                strengths=["Great delivery"],
                improvements=[],
                agent_id="delivery-evaluator-v1",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        ]

        synthesized = supervisor._collapse_duplicates(results)
        assert synthesized == []


# ---------------------------------------------------------------------------
# Swap Pair generation (_generate_swap_pairs)
# ---------------------------------------------------------------------------


class TestGenerateSwapPairs:
    """Tests for _generate_swap_pairs() method.

    Requirements: 1.8, 11.1, 11.2, 11.3, 11.4
    """

    def _make_supervisor(self) -> CoachingSupervisor:
        """Create a CoachingSupervisor with a mocked registry."""
        registry = _mock_registry(["delivery", "structure", "pacing"])
        supervisor = CoachingSupervisor(registry=registry)
        return supervisor

    def _make_finding(
        self,
        evidence_quote: str | None = None,
        impact: float = 5.0,
        severity: str = "medium",
        title: str = "Test finding",
        suggestion: str = "Test suggestion for improvement",
    ) -> "SynthesizedFinding":
        from models.synthesized_report import (
            EffortTag,
            ImpactTag,
            Severity,
            SynthesizedFinding,
        )

        severity_map = {"high": Severity.HIGH, "medium": Severity.MEDIUM, "low": Severity.LOW}
        return SynthesizedFinding(
            severity=severity_map[severity],
            title=title[:80],
            explanation="This is a test explanation for the finding.",
            suggestion=suggestion,
            effort_tag=EffortTag.MODERATE,
            impact_tag=ImpactTag.MEDIUM,
            evidence_quote=evidence_quote,
            evidence_timestamp_seconds=None,
            cross_dimension_note=None,
            projected_impact_score=impact,
        )

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_swap_pair_generated_for_dimension_with_evidence(self, mock_import):
        """A swap pair is generated when a finding has evidence_quote ≥ 10 chars."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(evidence_quote="This is a verbatim quote from the speaker", impact=7.0),
            ],
        }

        result = supervisor._generate_swap_pairs(findings_by_dim)

        assert result["delivery"] is not None
        assert len(result["delivery"].you_said) >= 10
        assert len(result["delivery"].you_said) <= 280
        assert len(result["delivery"].try_instead) <= 400

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_swap_pair_none_when_no_evidence(self, mock_import):
        """Swap pair is None when no finding has evidence_quote ≥ 10 chars."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(evidence_quote=None, impact=7.0),
                self._make_finding(evidence_quote="short", impact=5.0),
            ],
        }

        result = supervisor._generate_swap_pairs(findings_by_dim)

        assert result["delivery"] is None

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_swap_pair_uses_highest_impact_finding(self, mock_import):
        """When multiple findings have eligible evidence, the highest-impact one is used."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(evidence_quote="This is a low impact quote here", impact=3.0),
                self._make_finding(evidence_quote="This is the highest impact quote", impact=9.0),
                self._make_finding(evidence_quote="This is a medium impact quote", impact=5.0),
            ],
        }

        result = supervisor._generate_swap_pairs(findings_by_dim)

        assert result["delivery"] is not None
        assert result["delivery"].you_said == "This is the highest impact quote"

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_swap_pair_you_said_truncated_to_280(self, mock_import):
        """The you_said field is truncated to 280 characters."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        # Evidence quote longer than 200 chars won't pass model validation,
        # but our method handles truncation to 280.
        # The model field allows max_length=200, so let's test with up to 200.
        long_quote = "A" * 200
        findings_by_dim = {
            "delivery": [
                self._make_finding(evidence_quote=long_quote, impact=7.0),
            ],
        }

        result = supervisor._generate_swap_pairs(findings_by_dim)

        assert result["delivery"] is not None
        assert len(result["delivery"].you_said) <= 280

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_swap_pair_try_instead_not_empty(self, mock_import):
        """The try_instead field is a non-empty string."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(
                    evidence_quote="This is a quote from the speaker",
                    impact=6.0,
                    suggestion="Speak more slowly and pause between key points",
                ),
            ],
        }

        result = supervisor._generate_swap_pairs(findings_by_dim)

        assert result["delivery"] is not None
        assert len(result["delivery"].try_instead) > 0
        assert len(result["delivery"].try_instead) <= 400

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_swap_pair_none_for_evidence_under_10_chars(self, mock_import):
        """Swap pair is None when evidence_quote exists but is under 10 chars."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(evidence_quote="123456789", impact=7.0),  # 9 chars
            ],
        }

        result = supervisor._generate_swap_pairs(findings_by_dim)

        assert result["delivery"] is None

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_swap_pair_generated_for_exactly_10_char_evidence(self, mock_import):
        """Swap pair is generated when evidence_quote is exactly 10 characters."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(evidence_quote="1234567890", impact=7.0),  # 10 chars
            ],
        }

        result = supervisor._generate_swap_pairs(findings_by_dim)

        assert result["delivery"] is not None
        assert result["delivery"].you_said == "1234567890"

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_multiple_dimensions_independent(self, mock_import):
        """Each dimension is evaluated independently for swap pairs."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(evidence_quote="This has enough evidence", impact=7.0),
            ],
            "structure": [
                self._make_finding(evidence_quote=None, impact=8.0),
            ],
            "pacing": [
                self._make_finding(evidence_quote="Pacing evidence quote here", impact=6.0),
            ],
        }

        result = supervisor._generate_swap_pairs(findings_by_dim)

        assert result["delivery"] is not None
        assert result["structure"] is None
        assert result["pacing"] is not None


# ---------------------------------------------------------------------------
# Practice Drill generation (_generate_practice_drills)
# ---------------------------------------------------------------------------


class TestGeneratePracticeDrills:
    """Tests for _generate_practice_drills() method.

    Requirements: 1.9, 12.1, 12.2, 12.3, 12.4
    """

    def _make_supervisor(self) -> CoachingSupervisor:
        """Create a CoachingSupervisor with a mocked registry."""
        registry = _mock_registry(["delivery", "structure", "pacing"])
        supervisor = CoachingSupervisor(registry=registry)
        return supervisor

    def _make_finding(
        self,
        severity: str = "medium",
        impact: float = 5.0,
        title: str = "Test finding",
        suggestion: str = "Improve by practicing this specific technique daily",
    ) -> "SynthesizedFinding":
        from models.synthesized_report import (
            EffortTag,
            ImpactTag,
            Severity,
            SynthesizedFinding,
        )

        severity_map = {"high": Severity.HIGH, "medium": Severity.MEDIUM, "low": Severity.LOW}
        return SynthesizedFinding(
            severity=severity_map[severity],
            title=title[:80],
            explanation="This is a test explanation for the finding.",
            suggestion=suggestion,
            effort_tag=EffortTag.MODERATE,
            impact_tag=ImpactTag.MEDIUM,
            evidence_quote=None,
            evidence_timestamp_seconds=None,
            cross_dimension_note=None,
            projected_impact_score=impact,
        )

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_drill_generated_for_dimension_with_findings(self, mock_import):
        """A practice drill is generated for a dimension with findings."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(severity="medium", impact=6.0),
            ],
        }

        result = supervisor._generate_practice_drills(findings_by_dim)

        assert result["delivery"] is not None
        assert 2 <= result["delivery"].time_box_minutes <= 15
        assert 50 <= len(result["delivery"].instructions) <= 500

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_drill_none_for_empty_findings(self, mock_import):
        """Practice drill is None when a dimension has no findings."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [],
        }

        result = supervisor._generate_practice_drills(findings_by_dim)

        assert result["delivery"] is None

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_time_box_5_for_high_severity(self, mock_import):
        """High severity findings produce 5-minute time box."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(severity="high", impact=8.0),
            ],
        }

        result = supervisor._generate_practice_drills(findings_by_dim)

        assert result["delivery"] is not None
        assert result["delivery"].time_box_minutes == 5

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_time_box_10_for_medium_severity(self, mock_import):
        """Medium severity findings produce 10-minute time box."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(severity="medium", impact=5.0),
            ],
        }

        result = supervisor._generate_practice_drills(findings_by_dim)

        assert result["delivery"] is not None
        assert result["delivery"].time_box_minutes == 10

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_time_box_15_for_low_severity(self, mock_import):
        """Low severity findings produce 15-minute time box."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(severity="low", impact=3.0),
            ],
        }

        result = supervisor._generate_practice_drills(findings_by_dim)

        assert result["delivery"] is not None
        assert result["delivery"].time_box_minutes == 15

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_time_box_uses_highest_severity(self, mock_import):
        """When multiple severities present, highest determines time box."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(severity="low", impact=2.0),
                self._make_finding(severity="high", impact=8.0),
                self._make_finding(severity="medium", impact=5.0),
            ],
        }

        result = supervisor._generate_practice_drills(findings_by_dim)

        assert result["delivery"] is not None
        assert result["delivery"].time_box_minutes == 5  # high severity

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_instructions_reference_finding(self, mock_import):
        """Drill instructions reference at least one finding."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(
                    severity="medium",
                    impact=6.0,
                    title="Vocal monotony",
                    suggestion="Vary your pitch and tone",
                ),
            ],
        }

        result = supervisor._generate_practice_drills(findings_by_dim)

        assert result["delivery"] is not None
        instructions = result["delivery"].instructions
        # Should reference the finding title
        assert "Vocal monotony" in instructions

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_instructions_length_constraints(self, mock_import):
        """Instructions are between 50 and 500 characters."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(severity="medium", impact=6.0),
            ],
        }

        result = supervisor._generate_practice_drills(findings_by_dim)

        assert result["delivery"] is not None
        assert len(result["delivery"].instructions) >= 50
        assert len(result["delivery"].instructions) <= 500

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_multiple_dimensions_independent(self, mock_import):
        """Each dimension gets its own independent practice drill."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        findings_by_dim = {
            "delivery": [
                self._make_finding(severity="high", impact=8.0),
            ],
            "structure": [],
            "pacing": [
                self._make_finding(severity="low", impact=3.0),
            ],
        }

        result = supervisor._generate_practice_drills(findings_by_dim)

        assert result["delivery"] is not None
        assert result["delivery"].time_box_minutes == 5
        assert result["structure"] is None
        assert result["pacing"] is not None
        assert result["pacing"].time_box_minutes == 15


# ---------------------------------------------------------------------------
# synthesis_pass() orchestrator method
# ---------------------------------------------------------------------------


class TestSynthesisPass:
    """Tests for synthesis_pass() orchestrator method.

    Requirements: 1.1, 1.13
    """

    def _make_supervisor(self) -> CoachingSupervisor:
        """Create a CoachingSupervisor with a mocked registry."""
        registry = _mock_registry(["delivery", "structure", "pacing"])
        supervisor = CoachingSupervisor(registry=registry)
        return supervisor

    def _make_results(self, num_dims: int = 7) -> list[EvaluationResult]:
        """Create EvaluationResults for all 7 dimensions."""
        from agents.coaching_supervisor import ALL_DIMENSION_NAMES

        results = []
        for i, dim in enumerate(ALL_DIMENSION_NAMES[:num_dims]):
            results.append(
                EvaluationResult(
                    dimension=dim,
                    score=3.0 + i,  # Scores from 3.0 to 9.0
                    findings=[
                        Finding(
                            category=f"finding_{dim.lower().replace(' ', '_')}",
                            detail=f"Detail for {dim} finding that needs attention",
                            severity="medium",
                            suggestion=f"Suggestion for {dim} improvement here",
                        )
                    ],
                    strengths=[f"Good {dim} skills demonstrated"],
                    improvements=[f"Improve {dim} further"],
                    agent_id=f"{dim.lower().replace(' ', '-')}-evaluator-v1",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )
        return results

    def _make_transcript(self) -> "TranscriptData":
        """Create a minimal valid TranscriptData for testing."""
        from services.transcript_metrics import TranscriptData, WordTiming

        words = [
            WordTiming(word="Hello", start_seconds=0.0, end_seconds=0.5, confidence=0.95),
            WordTiming(word="world", start_seconds=0.6, end_seconds=1.0, confidence=0.92),
            WordTiming(word="this", start_seconds=1.1, end_seconds=1.4, confidence=0.90),
            WordTiming(word="is", start_seconds=1.5, end_seconds=1.7, confidence=0.88),
            WordTiming(word="a", start_seconds=1.8, end_seconds=1.9, confidence=0.99),
            WordTiming(word="test", start_seconds=2.0, end_seconds=2.5, confidence=0.93),
        ]
        return TranscriptData(words=words, close_start_seconds=2.0)

    def _make_metadata(self) -> "SubmissionMetadata":
        """Create a test SubmissionMetadata."""
        from agents.coaching_supervisor import SubmissionMetadata

        return SubmissionMetadata(
            user_name="Test User",
            presentation_title="Test Presentation",
            file_name="test_presentation.mp4",
            upload_date=datetime.now(timezone.utc).isoformat(),
            audio_duration_seconds=120.0,
            speaker_identified=False,
            user_id="user-123",
            submission_id="sub-456",
        )

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_synthesis_pass_produces_valid_report(self, mock_import):
        """synthesis_pass produces a valid SynthesizedReport with all 7 dimensions."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        results = self._make_results(7)
        transcript = self._make_transcript()
        metadata = self._make_metadata()

        report = supervisor.synthesis_pass(results, transcript, metadata)

        # Basic structure validation
        assert report is not None
        assert len(report.dimensions) == 7
        assert len(report.three_moves) == 3
        assert 0.0 <= report.overall_score <= 10.0
        assert report.user_name == "Test User"
        assert report.presentation_title == "Test Presentation"
        assert report.transcript_metrics is not None

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_synthesis_pass_raises_on_zero_results(self, mock_import):
        """synthesis_pass raises ValueError when zero agents returned results."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        transcript = self._make_transcript()
        metadata = self._make_metadata()

        import pytest

        with pytest.raises(ValueError, match="Zero agents returned results"):
            supervisor.synthesis_pass([], transcript, metadata)

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_synthesis_pass_handles_partial_results(self, mock_import):
        """synthesis_pass succeeds with partial results (≥1 agent returned)."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        # Only 3 of 7 agents returned results
        results = self._make_results(3)
        transcript = self._make_transcript()
        metadata = self._make_metadata()

        report = supervisor.synthesis_pass(results, transcript, metadata)

        # Should still produce a valid report with 7 dimensions
        assert report is not None
        assert len(report.dimensions) == 7

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_synthesis_pass_exactly_one_weakest(self, mock_import):
        """The report has exactly one dimension marked as weakest."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        results = self._make_results(7)
        transcript = self._make_transcript()
        metadata = self._make_metadata()

        report = supervisor.synthesis_pass(results, transcript, metadata)

        weakest_count = sum(1 for d in report.dimensions if d.is_weakest)
        assert weakest_count == 1

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_synthesis_pass_dimensions_sorted_weakest_first(self, mock_import):
        """Dimensions are sorted by score ascending (weakest first)."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        results = self._make_results(7)
        transcript = self._make_transcript()
        metadata = self._make_metadata()

        report = supervisor.synthesis_pass(results, transcript, metadata)

        scores = [d.score for d in report.dimensions]
        assert scores == sorted(scores)

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_synthesis_pass_no_user_name_in_coaching_prose(self, mock_import):
        """User name does not appear in coaching prose fields."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        results = self._make_results(7)
        transcript = self._make_transcript()
        metadata = self._make_metadata()

        report = supervisor.synthesis_pass(results, transcript, metadata)

        # Check that "Test User" does not appear in coaching prose
        prose_fields = [
            report.two_sentence_verdict,
            report.lede_paragraph,
            report.diagnosis_paragraph,
        ]
        for field in prose_fields:
            assert "Test User" not in field

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_synthesis_pass_second_person_voice(self, mock_import):
        """Coaching prose uses second-person voice (you/your)."""
        mock_import.return_value = MagicMock()
        supervisor = self._make_supervisor()

        results = self._make_results(7)
        transcript = self._make_transcript()
        metadata = self._make_metadata()

        report = supervisor.synthesis_pass(results, transcript, metadata)

        # At least one coaching prose field should contain "you" or "your"
        all_prose = (
            report.two_sentence_verdict
            + report.lede_paragraph
            + report.diagnosis_paragraph
        )
        assert "you" in all_prose.lower() or "your" in all_prose.lower()


# ---------------------------------------------------------------------------
# Voice consistency validation (_validate_voice_consistency, _strip_name_from_text)
# ---------------------------------------------------------------------------


class TestVoiceConsistencyValidation:
    """Tests for second-person voice enforcement and name stripping.

    Requirements: 15.1, 15.2, 15.3
    """

    def test_strip_name_replaces_standalone_name_with_you(self):
        """User name appearing in prose is replaced with 'you'."""
        text = "John delivered a solid opening."
        result = CoachingSupervisor._strip_name_from_text(text, "John")
        assert "John" not in result
        assert "you" in result

    def test_strip_name_replaces_possessive_with_your(self):
        """Possessive form of user name is replaced with 'your'."""
        text = "John's delivery was strong throughout."
        result = CoachingSupervisor._strip_name_from_text(text, "John")
        assert "John" not in result
        assert "your" in result

    def test_strip_name_case_insensitive(self):
        """Name stripping is case-insensitive."""
        text = "JOHN needs to work on pacing. john did well on structure."
        result = CoachingSupervisor._strip_name_from_text(text, "John")
        assert "JOHN" not in result
        assert "john" not in result

    def test_strip_name_ignores_short_names(self):
        """Names shorter than 2 characters are not stripped (avoids spurious matches)."""
        text = "I need to improve."
        result = CoachingSupervisor._strip_name_from_text(text, "I")
        assert result == text  # unchanged

    def test_strip_name_empty_name(self):
        """Empty user_name returns text unchanged."""
        text = "You should work on pacing."
        result = CoachingSupervisor._strip_name_from_text(text, "")
        assert result == text

    def test_strip_name_multiword_name(self):
        """Multi-word names (full names) are replaced correctly."""
        text = "Sarah Johnson demonstrated strong delivery."
        result = CoachingSupervisor._strip_name_from_text(text, "Sarah Johnson")
        assert "Sarah Johnson" not in result
        assert "you" in result

    def test_contains_second_person_detects_you(self):
        """_contains_second_person finds 'you' as a whole word."""
        assert CoachingSupervisor._contains_second_person("You should improve.") is True

    def test_contains_second_person_detects_your(self):
        """_contains_second_person finds 'your' as a whole word."""
        assert CoachingSupervisor._contains_second_person("Your delivery was strong.") is True

    def test_contains_second_person_rejects_substring(self):
        """_contains_second_person does not match 'you' inside other words like 'youth'."""
        # "youth" contains "you" as a substring but not as a whole word
        assert CoachingSupervisor._contains_second_person("The youth program is good.") is False

    def test_contains_second_person_empty_text(self):
        """_contains_second_person returns False for text without second-person."""
        assert CoachingSupervisor._contains_second_person("The speaker did well.") is False

    @patch("agents.coaching_supervisor.importlib.import_module")
    def test_validate_voice_strips_name_from_findings(self, mock_import):
        """Voice validation strips user_name from finding explanations and suggestions."""
        mock_import.return_value = MagicMock()
        registry = _mock_registry(["delivery"])
        supervisor = CoachingSupervisor(registry=registry)

        # Create a result where the user's name leaks into finding detail/suggestion
        finding = Finding(
            category="filler-words",
            detail="Alice used too many filler words throughout.",
            severity="high",
            suggestion="Alice should reduce filler words by pausing instead.",
        )
        results = [
            EvaluationResult(
                dimension="Delivery",
                score=5.0,
                findings=[finding],
                strengths=["Good energy"],
                improvements=["Reduce fillers"],
                agent_id="delivery-evaluator-v1",
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
        ]

        from services.transcript_metrics import TranscriptData, WordTiming

        transcript = TranscriptData(
            words=[
                WordTiming(word="hello", start_seconds=0.0, end_seconds=0.5, confidence=0.95),
                WordTiming(word="world", start_seconds=0.6, end_seconds=1.0, confidence=0.90),
            ],
            close_start_seconds=0.8,
        )

        from agents.coaching_supervisor import SubmissionMetadata

        metadata = SubmissionMetadata(
            user_name="Alice",
            presentation_title="Test Presentation",
            file_name="test.mp3",
            upload_date=datetime.now(timezone.utc).isoformat(),
            audio_duration_seconds=60.0,
        )

        report = supervisor.synthesis_pass(results, transcript, metadata)

        # The user_name "Alice" should not appear in any coaching prose
        for dim in report.dimensions:
            for f in dim.findings:
                assert "Alice" not in f.explanation, (
                    f"User name found in finding explanation: {f.explanation}"
                )
                assert "Alice" not in f.suggestion, (
                    f"User name found in finding suggestion: {f.suggestion}"
                )

        # user_name should still be in the metadata field
        assert report.user_name == "Alice"
