"""Coaching Supervisor Agent.

Orchestrates evaluation agents based on presentation context using the
Strands Agents SDK "Agents as Tools" pattern. The Coaching Supervisor
dynamically selects evaluators, invokes them, reviews results, and
decides whether additional evaluation is warranted.
"""

import importlib
import json
import logging
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from strands import Agent

from agents.registry import AgentRegistry
from models.data_models import AgentFailure, EvaluationInput, EvaluationResult, Finding
from models.synthesized_report import (
    DimensionEntry,
    EffortTag,
    ImpactTag,
    PracticeDrill,
    Provenance,
    ScoreBand,
    Severity,
    SeverityCounts,
    SwapPair,
    SynthesizedFinding,
    SynthesizedReport,
    TalkTimeline,
    ThreeMove,
    TimelinePin,
    TranscriptMetrics,
)
from services.score_utils import classify_score_band, compute_distance_to_next_band
from services.synthesis_utils import apply_findings_cap
from services.transcript_metrics import TranscriptData, compute_metrics

logger = logging.getLogger(__name__)

EXPECTED_AGENT_COUNT = 7

ALL_DIMENSION_NAMES = [
    "Delivery",
    "Structure",
    "Executive Presence",
    "Technical Communication",
    "Audience Engagement",
    "Pacing",
    "Persuasion",
]


@dataclass(frozen=True)
class SubmissionMetadata:
    """Metadata about the submission for inclusion in the SynthesizedReport.

    Attributes:
        user_name: Display name of the user.
        presentation_title: Title of the presentation.
        file_name: Original uploaded file name.
        upload_date: ISO 8601 UTC timestamp of when the file was uploaded.
        audio_duration_seconds: Duration of the audio in seconds.
        speaker_identified: Whether the audio speaker was identified.
        user_id: User identifier for provenance.
        submission_id: Submission identifier for provenance.
    """

    user_name: str
    presentation_title: str
    file_name: str = ""
    upload_date: str = ""
    audio_duration_seconds: float = 0.0
    speaker_identified: bool = False
    user_id: str = ""
    submission_id: str = ""


# System prompt that guides the Coaching Supervisor's reasoning
SUPERVISOR_SYSTEM_PROMPT = """You are the Coaching Supervisor for a presentation evaluation platform.
Your role is to orchestrate evaluation agents to assess presentations through multiple lenses.

You have access to evaluation tools — one per dimension (e.g., delivery, structure, pacing).
When asked to evaluate a presentation:

1. Analyze the requested dimensions and the presentation context.
2. Invoke the appropriate evaluation tool for each requested dimension.
3. After receiving results from each tool, review the findings.
4. Determine if additional evaluators should be invoked based on initial findings.
   For example, if delivery findings suggest pacing issues, invoke the pacing evaluator if
   it was not already requested.
5. Once all warranted evaluations are complete, signal completion.

Always invoke at least the explicitly requested dimensions. You may add additional dimensions
if your analysis of the results indicates they would provide valuable coaching feedback.

For each tool invocation, pass the evaluation input as a JSON string with these fields:
- submission_id: The unique submission identifier
- s3_bucket: The S3 bucket for presentation data
- s3_key: The S3 key for presentation data
- dimension: The evaluation dimension name
- user_id: The user identifier
"""


class CoachingSupervisor:
    """Orchestrates evaluation agents based on presentation context.

    Uses the Strands Agents SDK "Agents as Tools" pattern to invoke
    evaluation agents for requested dimensions. Supports iterative
    invocation when initial findings suggest additional evaluation
    is warranted.

    Args:
        registry: The AgentRegistry for discovering available evaluation agents.
        agent: Optional pre-configured Strands Agent for orchestration.
            If not provided, one is created with registered evaluation tools.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        agent: Agent | None = None,
        model_id: str = "us.anthropic.claude-sonnet-4-6",
    ) -> None:
        self._registry = registry
        self._model_id = model_id
        self._tools = self._load_tools()
        self._agent = agent or self._create_agent()
        self._failures: list[AgentFailure] = []

    def _load_tools(self) -> list[Any]:
        """Load evaluation tools from the agent registry.

        Discovers available agents, imports their tool modules, and calls
        the `create_tool()` factory function to get Strands-compatible tools.

        Returns:
            A list of Strands tool functions for evaluation agents.
        """
        tools: list[Any] = []
        available_agents = self._registry.get_available_agents()

        for descriptor in available_agents:
            try:
                module = importlib.import_module(descriptor.tool_module)
                tool_factory = getattr(module, "create_tool", None)
                if tool_factory is None:
                    logger.warning(
                        "Module %s does not have a create_tool() function. "
                        "Skipping agent %s.",
                        descriptor.tool_module,
                        descriptor.agent_id,
                    )
                    continue

                tool_fn = tool_factory()
                tools.append(tool_fn)
                logger.info(
                    "Loaded evaluation tool for dimension=%s, agent_id=%s",
                    descriptor.dimension,
                    descriptor.agent_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Failed to load tool for agent %s (module=%s): %s",
                    descriptor.agent_id,
                    descriptor.tool_module,
                    exc,
                )

        logger.info("Loaded %d evaluation tool(s) total.", len(tools))
        return tools

    def _create_agent(self) -> Agent:
        """Create a Strands Agent configured with evaluation tools.

        Returns:
            A Strands Agent instance with the supervisor system prompt
            and all discovered evaluation tools registered.
        """
        return Agent(
            system_prompt=SUPERVISOR_SYSTEM_PROMPT,
            tools=self._tools,
            model=self._model_id,
        )

    def evaluate(
        self,
        input: EvaluationInput,
        dimensions: list[str],
    ) -> list[EvaluationResult]:
        """Run the full evaluation orchestration for requested dimensions.

        Analyzes the presentation context, selects appropriate evaluators,
        invokes them via the Strands agent, collects results, and supports
        iterative invocation if findings warrant additional evaluation.

        Agent failures are tracked internally and can be retrieved via
        `get_last_failures()` after this method returns.

        Args:
            input: The standard evaluation input with submission metadata.
            dimensions: List of evaluation dimension names to assess
                (e.g., ["delivery", "structure", "pacing"]).

        Returns:
            A list of EvaluationResult objects, one per dimension evaluated.
            May include more dimensions than originally requested if the
            supervisor determined additional evaluation was warranted.
        """
        # Reset failure tracking for each evaluation session
        self._failures = []

        logger.info(
            "Starting coaching evaluation for submission_id=%s, "
            "requested_dimensions=%s",
            input.submission_id,
            dimensions,
        )

        # Filter dimensions to only those with available agents
        available_dimensions = self._get_available_dimensions(dimensions)
        if not available_dimensions:
            logger.warning(
                "No available agents for requested dimensions: %s",
                dimensions,
            )
            return []

        # Build the orchestration prompt for the Strands agent
        prompt = self._build_evaluation_prompt(input, available_dimensions)

        # Invoke the Strands agent to orchestrate evaluation
        results = self._invoke_agent(input, available_dimensions, prompt)

        logger.info(
            "Coaching evaluation completed for submission_id=%s. "
            "Collected %d result(s), %d failure(s).",
            input.submission_id,
            len(results),
            len(self._failures),
        )
        return results

    def get_last_failures(self) -> list[AgentFailure]:
        """Return the failures from the most recent evaluate() call.

        Each entry contains the dimension, agent_id, and error message
        for an agent that failed during the last evaluation session.

        Returns:
            A list of AgentFailure instances. Empty if no failures occurred
            or if evaluate() has not yet been called.
        """
        return list(self._failures)

    def _get_available_dimensions(self, dimensions: list[str]) -> list[str]:
        """Filter requested dimensions to only those with available agents.

        Args:
            dimensions: The originally requested dimension names.

        Returns:
            A list of dimensions that have enabled agents in the registry.
        """
        available = []
        for dim in dimensions:
            descriptor = self._registry.get_agent_by_dimension(dim)
            if descriptor is not None:
                available.append(dim)
            else:
                logger.warning(
                    "No enabled agent found for dimension=%s. Skipping.", dim
                )
        return available

    def _build_evaluation_prompt(
        self,
        input: EvaluationInput,
        dimensions: list[str],
    ) -> str:
        """Build the orchestration prompt for the Strands agent.

        Constructs a prompt that instructs the supervisor to invoke
        each requested evaluation tool and review results.

        Args:
            input: The evaluation input with submission context.
            dimensions: The dimensions to evaluate.

        Returns:
            A formatted prompt string for the Strands agent.
        """
        input_json = input.model_dump_json()

        dimension_list = ", ".join(dimensions)
        prompt = (
            f"Evaluate this presentation across the following dimensions: "
            f"{dimension_list}.\n\n"
            f"Presentation Context:\n"
            f"- Submission ID: {input.submission_id}\n"
            f"- Dimension: {input.dimension}\n"
            f"- User ID: {input.user_id}\n\n"
            f"For each dimension, invoke the corresponding evaluation tool "
            f"with this input:\n{input_json}\n\n"
            f"After receiving results, review the findings and determine if "
            f"additional dimensions should be evaluated based on what was "
            f"discovered. If so, invoke those additional tools as well.\n\n"
            f"Return all evaluation results."
        )
        return prompt

    def _invoke_agent(
        self,
        input: EvaluationInput,
        dimensions: list[str],
        prompt: str,
    ) -> list[EvaluationResult]:
        """Invoke evaluation tools directly for each requested dimension.

        Uses direct tool invocation rather than Strands Agent orchestration
        for deterministic, reliable results. Each dimension's tool is called
        sequentially, with iterative invocation support (findings from one
        agent can trigger additional dimensions).

        Args:
            input: The evaluation input.
            dimensions: The dimensions being evaluated.
            prompt: Unused (kept for interface compatibility).

        Returns:
            A list of parsed EvaluationResult objects from tool invocations.
        """
        return self._direct_invoke_tools(input, dimensions)

    def _extract_results_from_response(
        self, response: Any
    ) -> list[EvaluationResult]:
        """Extract EvaluationResult objects from the agent's response.

        Parses the agent response to find tool call results that contain
        valid EvaluationResult JSON.

        Args:
            response: The raw response from the Strands agent.

        Returns:
            A list of successfully parsed EvaluationResult objects.
        """
        results: list[EvaluationResult] = []

        # The Strands agent response may contain tool results in its
        # message history. Try to extract structured results.
        response_text = str(response)

        # Attempt to find JSON-encoded EvaluationResult objects in the response
        self._parse_results_from_text(response_text, results)

        # Also check if the agent has tool_results in its state
        if hasattr(response, "tool_results"):
            for tool_result in response.tool_results:
                self._parse_single_result(str(tool_result), results)

        return results

    def _parse_results_from_text(
        self, text: str, results: list[EvaluationResult]
    ) -> None:
        """Parse EvaluationResult JSON objects from text.

        Searches for JSON objects in the text that can be parsed
        as EvaluationResult instances.

        Args:
            text: The text to search for JSON results.
            results: List to append parsed results to (modified in place).
        """
        # Try to find JSON objects that look like EvaluationResults
        # Look for JSON objects containing "dimension" field
        json_pattern = re.compile(r"\{[^{}]*\"dimension\"[^{}]*\}", re.DOTALL)
        matches = json_pattern.findall(text)

        for match in matches:
            self._parse_single_result(match, results)

    def _parse_single_result(
        self, text: str, results: list[EvaluationResult]
    ) -> None:
        """Try to parse a single text fragment as an EvaluationResult.

        Args:
            text: A text fragment that may contain a JSON EvaluationResult.
            results: List to append the parsed result to (modified in place).
        """
        try:
            data = json.loads(text)
            if "error" in data:
                logger.warning(
                    "Tool returned an error: %s", data["error"]
                )
                return
            result = EvaluationResult.model_validate(data)
            # Avoid duplicate results for the same dimension
            existing_dims = {r.dimension for r in results}
            if result.dimension not in existing_dims:
                results.append(result)
        except (json.JSONDecodeError, Exception):  # noqa: BLE001
            pass

    def _direct_invoke_tools(
        self,
        input: EvaluationInput,
        dimensions: list[str],
    ) -> list[EvaluationResult]:
        """Directly invoke evaluation tools as a fallback.

        When the agent-based orchestration fails, fall back to directly
        calling each evaluation tool for the requested dimensions.

        This supports the iterative invocation pattern by checking
        results and potentially invoking additional tools.

        Args:
            input: The evaluation input.
            dimensions: The dimensions to evaluate.

        Returns:
            A list of EvaluationResult objects from direct invocations.
        """
        results: list[EvaluationResult] = []
        evaluated_dimensions: set[str] = set()
        pending_dimensions = list(dimensions)

        while pending_dimensions:
            dimension = pending_dimensions.pop(0)

            if dimension in evaluated_dimensions:
                continue

            try:
                result = self._invoke_single_tool(input, dimension)
            except Exception as exc:  # noqa: BLE001
                # Catch unexpected exceptions not handled within _invoke_single_tool
                descriptor = self._registry.get_agent_by_dimension(dimension)
                agent_id = descriptor.agent_id if descriptor else f"unknown-{dimension}"
                error_msg = f"{type(exc).__name__}: {exc}"
                logger.error(
                    "Agent %s (dimension=%s) raised an unhandled exception for "
                    "submission_id=%s: %s",
                    agent_id,
                    dimension,
                    input.submission_id,
                    error_msg,
                )
                self._failures.append(
                    AgentFailure(
                        dimension=dimension,
                        agent_id=agent_id,
                        error=error_msg,
                    )
                )
                evaluated_dimensions.add(dimension)
                continue

            if result is not None:
                results.append(result)
                evaluated_dimensions.add(dimension)

                # Iterative pattern: check if findings suggest
                # additional dimensions should be evaluated
                additional = self._determine_additional_dimensions(
                    result, evaluated_dimensions
                )
                for dim in additional:
                    if dim not in evaluated_dimensions and dim not in pending_dimensions:
                        logger.info(
                            "Adding additional dimension=%s based on "
                            "findings from dimension=%s",
                            dim,
                            dimension,
                        )
                        pending_dimensions.append(dim)
            else:
                evaluated_dimensions.add(dimension)

        return results

    def _invoke_single_tool(
        self,
        input: EvaluationInput,
        dimension: str,
    ) -> EvaluationResult | None:
        """Invoke a single evaluation tool for the given dimension.

        Finds the appropriate tool function and calls it with the
        evaluation input. On failure, records the failure with agent
        identifier and error details for partial failure reporting.

        Args:
            input: The evaluation input.
            dimension: The dimension to evaluate.

        Returns:
            An EvaluationResult if successful, or None if the tool
            could not be found or invocation failed.
        """
        descriptor = self._registry.get_agent_by_dimension(dimension)
        if descriptor is None:
            logger.warning(
                "No agent descriptor found for dimension=%s", dimension
            )
            return None

        # Find the matching tool by name
        tool_name = f"{dimension}_evaluator_tool"
        tool_fn = None
        for t in self._tools:
            if getattr(t, "__name__", "") == tool_name:
                tool_fn = t
                break

        if tool_fn is None:
            logger.warning(
                "No loaded tool found with name=%s for dimension=%s",
                tool_name,
                dimension,
            )
            return None

        # Prepare input with the specific dimension
        dim_input = EvaluationInput(
            submission_id=input.submission_id,
            s3_bucket=input.s3_bucket,
            s3_key=input.s3_key,
            dimension=dimension,
            user_id=input.user_id,
        )
        input_json = dim_input.model_dump_json()

        try:
            result_json = tool_fn(evaluation_input_json=input_json)
            if isinstance(result_json, str):
                data = json.loads(result_json)
                if "error" in data:
                    error_msg = str(data["error"])
                    logger.error(
                        "Agent %s (dimension=%s) returned an error for "
                        "submission_id=%s: %s",
                        descriptor.agent_id,
                        dimension,
                        input.submission_id,
                        error_msg,
                    )
                    self._failures.append(
                        AgentFailure(
                            dimension=dimension,
                            agent_id=descriptor.agent_id,
                            error=error_msg,
                        )
                    )
                    return None
                return EvaluationResult.model_validate(data)
            return None
        except Exception as exc:  # noqa: BLE001
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error(
                "Agent %s (dimension=%s) failed during invocation for "
                "submission_id=%s: %s",
                descriptor.agent_id,
                dimension,
                input.submission_id,
                error_msg,
            )
            self._failures.append(
                AgentFailure(
                    dimension=dimension,
                    agent_id=descriptor.agent_id,
                    error=error_msg,
                )
            )
            return None

    def _determine_additional_dimensions(
        self,
        result: EvaluationResult,
        already_evaluated: set[str],
    ) -> list[str]:
        """Determine if additional dimensions should be evaluated.

        Analyzes findings from a completed evaluation to identify
        dimensions that may warrant additional assessment. This
        implements the iterative invocation pattern.

        Args:
            result: The evaluation result to analyze.
            already_evaluated: Set of dimensions already evaluated or pending.

        Returns:
            A list of additional dimension names to evaluate.
        """
        additional: list[str] = []

        # Mapping of keywords in findings to related dimensions
        dimension_triggers: dict[str, list[str]] = {
            "pacing": ["pacing"],
            "pace": ["pacing"],
            "timing": ["pacing"],
            "too fast": ["pacing"],
            "too slow": ["pacing"],
            "structure": ["structure"],
            "organization": ["structure"],
            "flow": ["structure"],
            "transition": ["structure"],
            "engagement": ["audience_engagement"],
            "audience": ["audience_engagement"],
            "interaction": ["audience_engagement"],
            "persuasion": ["persuasion"],
            "convincing": ["persuasion"],
            "argument": ["persuasion"],
            "evidence": ["persuasion"],
            "technical": ["technical_communication"],
            "jargon": ["technical_communication"],
            "complexity": ["technical_communication"],
            "confidence": ["executive_presence"],
            "authority": ["executive_presence"],
            "presence": ["executive_presence"],
            "delivery": ["delivery"],
            "vocal": ["delivery"],
            "energy": ["delivery"],
        }

        # Scan findings for trigger keywords
        all_text = " ".join(
            f.detail.lower() + " " + f.suggestion.lower()
            for f in result.findings
        )

        for keyword, related_dims in dimension_triggers.items():
            if keyword in all_text:
                for dim in related_dims:
                    if dim not in already_evaluated and dim not in additional:
                        # Only add if there's an available agent
                        if self._registry.get_agent_by_dimension(dim) is not None:
                            additional.append(dim)

        return additional

    def synthesis_pass(
        self,
        results: list[EvaluationResult],
        transcript: TranscriptData,
        metadata: SubmissionMetadata,
    ) -> SynthesizedReport:
        """Collapse duplicates, rank globally, generate coaching artifacts.

        Orchestrates the full synthesis pipeline:
        1. Validate that at least one agent returned results
        2. Log missing agents if partial results
        3. Collapse duplicate findings (≥3 agents same category/behavior)
        4. Compute Projected_Impact_Score for each surviving finding
        5. Rank findings globally descending by impact
        6. Cap findings (5/dim), strengths (3/dim)
        7. Derive Three_Move_Plan from top 3 findings
        8. Generate Swap_Pairs (1/dim where evidence exists)
        9. Generate Practice_Drills (1/dim where findings exist)
        10. Compute transcript metrics
        11. Assemble and return a fully validated SynthesizedReport

        Args:
            results: List of EvaluationResult objects from specialist agents.
                Must contain at least 1 result.
            transcript: Word-level transcript data for metrics computation.
            metadata: Submission metadata for the report header.

        Returns:
            A fully validated SynthesizedReport.

        Raises:
            ValueError: If zero agents returned results.
        """
        # --- Step 1: Validate that at least one agent returned results ---
        if not results:
            raise ValueError(
                "Zero agents returned results. Cannot produce a "
                "SynthesizedReport without at least one EvaluationResult."
            )

        # --- Step 2: Log missing agents if partial results ---
        returned_agent_ids = {r.agent_id for r in results}
        returned_dimensions = {r.dimension for r in results}
        if len(results) < EXPECTED_AGENT_COUNT:
            missing_dims = [
                dim for dim in ALL_DIMENSION_NAMES
                if dim not in returned_dimensions
            ]
            logger.warning(
                "Partial results: received %d of %d expected agent results. "
                "Missing dimensions: %s. Missing agent IDs cannot be "
                "determined for dimensions without results.",
                len(results),
                EXPECTED_AGENT_COUNT,
                missing_dims,
            )

        # --- Step 3: Collapse duplicate findings ---
        synthesized_findings = self._collapse_duplicates(results)

        # --- Step 4: Compute Projected_Impact_Score ---
        # Already computed during _collapse_duplicates and _finding_to_synthesized
        # (projected_impact_score = 10.0 - dimension_score, clamped to [0.0, 10.0])

        # --- Step 5: Rank findings globally descending by impact ---
        ranked_findings = self._rank_findings(synthesized_findings)

        # --- Step 6: Group findings by dimension, apply caps ---
        findings_by_dim = self._group_findings_by_dimension(results, ranked_findings)
        capped_findings_by_dim = self._apply_caps(findings_by_dim)

        # --- Step 7: Derive Three_Move_Plan from top 3 findings ---
        three_moves = self._derive_three_moves(ranked_findings)

        # Ensure we always have exactly 3 moves (pad if fewer findings available)
        three_moves = self._ensure_three_moves(three_moves, ranked_findings)

        # Generate supporting narrative artifacts
        strengths_to_protect = self._generate_strengths_to_protect(results)
        diagnosis_paragraph = self._generate_diagnosis_paragraph(three_moves)

        # --- Step 8: Generate Swap_Pairs and Practice_Drills ---
        swap_pairs = self._generate_swap_pairs(capped_findings_by_dim)
        practice_drills = self._generate_practice_drills(capped_findings_by_dim)

        # --- Step 9: Compute transcript metrics ---
        transcript_metrics = compute_metrics(transcript)

        # --- Step 10: Assemble DimensionEntry list ---
        dimensions = self._assemble_dimensions(
            results, capped_findings_by_dim, swap_pairs, practice_drills
        )

        # --- Step 11: Compute overall score and assemble report ---
        overall_score = self._compute_overall_score(results)
        score_band = classify_score_band(overall_score)
        distance_to_next = compute_distance_to_next_band(overall_score)

        # Build talk timeline
        talk_timeline = self._build_talk_timeline(
            transcript, capped_findings_by_dim
        )

        # Build provenance
        provenance = self._build_provenance(metadata)

        # Build narrative fields (second-person, no speaker name)
        two_sentence_verdict = self._generate_two_sentence_verdict(
            overall_score, score_band, dimensions
        )
        lede_paragraph = self._generate_lede_paragraph(
            overall_score, score_band, three_moves
        )

        report = SynthesizedReport(
            user_name=metadata.user_name[:100],
            presentation_title=metadata.presentation_title[:200],
            file_name=metadata.file_name[:255],
            upload_date=metadata.upload_date or datetime.now(timezone.utc).isoformat(),
            audio_duration_seconds=metadata.audio_duration_seconds,
            report_id=str(uuid.uuid4()),
            speaker_identified=metadata.speaker_identified,
            overall_score=overall_score,
            score_band=score_band,
            distance_to_next_band=distance_to_next,
            two_sentence_verdict=two_sentence_verdict,
            lede_paragraph=lede_paragraph,
            dimensions=dimensions,
            three_moves=three_moves,
            strengths_to_protect=strengths_to_protect,
            diagnosis_paragraph=diagnosis_paragraph,
            transcript_metrics=transcript_metrics,
            talk_timeline=talk_timeline,
            provenance=provenance,
        )

        # --- Step 12: Validate and enforce voice consistency ---
        report = self._validate_voice_consistency(report)

        logger.info(
            "Synthesis pass completed. Report ID: %s, overall_score=%.1f, "
            "band=%s, dimensions=%d",
            report.report_id,
            overall_score,
            score_band.value,
            len(dimensions),
        )

        return report

    def _group_findings_by_dimension(
        self,
        results: list[EvaluationResult],
        ranked_findings: list[SynthesizedFinding],
    ) -> dict[str, list[SynthesizedFinding]]:
        """Group ranked findings by their source dimension.

        Since _collapse_duplicates attributes findings based on dimension
        scores, we re-derive the grouping by matching findings back to
        dimensions via their projected_impact_score (which is 10 - score).

        For simplicity, we rebuild per-dimension finding lists from the
        raw evaluation results, applying the collapse logic per dimension.

        Args:
            results: Original evaluation results.
            ranked_findings: The globally-ranked findings list.

        Returns:
            Dictionary mapping dimension names to their findings.
        """
        # Re-derive findings per dimension from the original results
        # by running collapse logic and tracking dimension attribution
        category_groups: dict[str, list[tuple[str, float, Finding]]] = defaultdict(list)

        for eval_result in results:
            for finding in eval_result.findings:
                category_groups[finding.category].append(
                    (eval_result.dimension, eval_result.score, finding)
                )

        findings_by_dim: dict[str, list[SynthesizedFinding]] = defaultdict(list)

        for category, entries in category_groups.items():
            unique_dimensions = {dim for dim, _, _ in entries}

            if len(unique_dimensions) >= 3:
                # Collapsed finding — attribute to lowest-score dimension
                entries_sorted = sorted(entries, key=lambda e: e[1])
                primary_dimension = entries_sorted[0][0]
                collapsed_finding = self._build_collapsed_finding(category, entries)
                findings_by_dim[primary_dimension].append(collapsed_finding)
            else:
                # Non-collapsed — each finding stays in its own dimension
                for dimension, score, finding in entries:
                    synthesized = self._finding_to_synthesized(finding, score)
                    findings_by_dim[dimension].append(synthesized)

        # Ensure all dimensions that returned results have an entry
        for result in results:
            if result.dimension not in findings_by_dim:
                findings_by_dim[result.dimension] = []

        # Sort each dimension's findings by projected_impact_score descending
        for dim in findings_by_dim:
            findings_by_dim[dim] = sorted(
                findings_by_dim[dim],
                key=lambda f: f.projected_impact_score,
                reverse=True,
            )

        return dict(findings_by_dim)

    def _ensure_three_moves(
        self,
        three_moves: list[ThreeMove],
        ranked_findings: list[SynthesizedFinding],
    ) -> list[ThreeMove]:
        """Ensure exactly 3 ThreeMove objects exist.

        If fewer than 3 findings were available, generates placeholder
        moves to fill the requirement.

        Args:
            three_moves: The derived moves (may be fewer than 3).
            ranked_findings: All ranked findings for context.

        Returns:
            A list of exactly 3 ThreeMove objects.
        """
        while len(three_moves) < 3:
            idx = len(three_moves) + 1
            three_moves.append(
                ThreeMove(
                    title=f"Continue developing your presentation skills",
                    coaching_advice=(
                        "Focus on building consistency across all dimensions. "
                        "Record yourself practicing and review the playback to "
                        "identify areas where you can refine your approach."
                    ),
                    projected_impact_score=1.0,
                    dimensions_lifted=["Delivery"],
                )
            )
        return three_moves[:3]

    def _assemble_dimensions(
        self,
        results: list[EvaluationResult],
        capped_findings_by_dim: dict[str, list[SynthesizedFinding]],
        swap_pairs: dict[str, SwapPair | None],
        practice_drills: dict[str, PracticeDrill | None],
    ) -> list[DimensionEntry]:
        """Assemble the list of 7 DimensionEntry objects for the report.

        Sorts dimensions by score ascending (weakest first) and assigns
        ranks. Ensures exactly 7 entries, filling in defaults for missing
        dimensions.

        Args:
            results: Original evaluation results.
            capped_findings_by_dim: Capped findings per dimension.
            swap_pairs: Swap pairs per dimension.
            practice_drills: Practice drills per dimension.

        Returns:
            A list of exactly 7 DimensionEntry objects.
        """
        # Build dimension data from results
        dim_data: dict[str, dict] = {}
        for result in results:
            dim_data[result.dimension] = {
                "score": result.score,
                "strengths": result.strengths[:3],
            }

        # Sort dimensions by score ascending for ranking
        sorted_dims = sorted(dim_data.items(), key=lambda x: (x[1]["score"], x[0]))

        # Assign ranks (1 = weakest)
        dim_ranks: dict[str, int] = {}
        for rank, (dim, _) in enumerate(sorted_dims, start=1):
            dim_ranks[dim] = rank

        # Find the weakest dimension (lowest score)
        weakest_dim = sorted_dims[0][0] if sorted_dims else None

        # Build DimensionEntry for each known dimension
        dimension_entries: list[DimensionEntry] = []
        for dim_name in ALL_DIMENSION_NAMES:
            if dim_name in dim_data:
                data = dim_data[dim_name]
                score = data["score"]
                strengths = data["strengths"]
            else:
                # Default for missing dimensions
                score = 5.0
                strengths = []

            findings = capped_findings_by_dim.get(dim_name, [])
            swap_pair = swap_pairs.get(dim_name)
            practice_drill = practice_drills.get(dim_name)
            rank = dim_ranks.get(dim_name, 4)  # middle rank for missing dims

            # Compute severity counts
            severity_counts = SeverityCounts(
                high=sum(1 for f in findings if f.severity == Severity.HIGH),
                medium=sum(1 for f in findings if f.severity == Severity.MEDIUM),
                low=sum(1 for f in findings if f.severity == Severity.LOW),
                strength=len(strengths),
            )

            # Generate one-sentence verdict (max 25 words)
            verdict = self._generate_one_sentence_verdict(
                dim_name, score, findings
            )

            is_weakest = dim_name == weakest_dim

            dimension_entries.append(
                DimensionEntry(
                    dimension_name=dim_name,
                    score=score,
                    score_band=classify_score_band(score),
                    rank=rank,
                    one_sentence_verdict=verdict,
                    severity_counts=severity_counts,
                    findings=findings,
                    strengths=strengths[:3],
                    swap_pair=swap_pair,
                    practice_drill=practice_drill,
                    is_weakest=is_weakest,
                )
            )

        # Ensure exactly 7 dimensions
        if len(dimension_entries) < 7:
            # Fill missing dimensions with defaults
            existing_names = {d.dimension_name for d in dimension_entries}
            for dim_name in ALL_DIMENSION_NAMES:
                if dim_name not in existing_names:
                    dimension_entries.append(
                        DimensionEntry(
                            dimension_name=dim_name,
                            score=5.0,
                            score_band=classify_score_band(5.0),
                            rank=4,
                            one_sentence_verdict="No evaluation data available for this dimension.",
                            severity_counts=SeverityCounts(
                                high=0, medium=0, low=0, strength=0
                            ),
                            findings=[],
                            strengths=[],
                            swap_pair=None,
                            practice_drill=None,
                            is_weakest=False,
                        )
                    )

        # Sort by score ascending (weakest first) for display order
        dimension_entries.sort(key=lambda d: (d.score, d.dimension_name))

        # Re-assign ranks after final sort
        for i, entry in enumerate(dimension_entries):
            # Use model_copy to update the rank since DimensionEntry is a BaseModel
            dimension_entries[i] = entry.model_copy(update={"rank": i + 1})

        # Ensure exactly one weakest: mark only the first (lowest score)
        for i, entry in enumerate(dimension_entries):
            dimension_entries[i] = entry.model_copy(
                update={"is_weakest": i == 0}
            )

        return dimension_entries[:7]

    def _generate_one_sentence_verdict(
        self,
        dimension: str,
        score: float,
        findings: list[SynthesizedFinding],
    ) -> str:
        """Generate a one-sentence verdict for a dimension (max 25 words).

        Uses second-person voice, no speaker name.

        Args:
            dimension: The dimension name.
            score: The dimension score.
            findings: The dimension's findings.

        Returns:
            A verdict string of at most 25 words.
        """
        band = classify_score_band(score)
        high_count = sum(1 for f in findings if f.severity == Severity.HIGH)

        if band == ScoreBand.EXCEPTIONAL:
            verdict = f"Your {dimension.lower()} is exceptional with no major issues to address."
        elif band == ScoreBand.EFFECTIVE:
            verdict = f"Your {dimension.lower()} is effective with minor refinements possible."
        elif band == ScoreBand.COMPETENT:
            if high_count > 0:
                verdict = f"Your {dimension.lower()} is competent but has {high_count} high-priority area{'s' if high_count > 1 else ''} to strengthen."
            else:
                verdict = f"Your {dimension.lower()} is competent with room to grow."
        else:
            verdict = f"Your {dimension.lower()} needs focused attention to reach competency."

        # Enforce 25-word limit
        words = verdict.split()
        if len(words) > 25:
            verdict = " ".join(words[:25])

        return verdict

    def _compute_overall_score(self, results: list[EvaluationResult]) -> float:
        """Compute overall score as the mean of dimension scores.

        Args:
            results: The evaluation results.

        Returns:
            A float in [0.0, 10.0] representing the average score.
        """
        if not results:
            return 0.0
        total = sum(r.score for r in results)
        return round(total / len(results), 1)

    def _build_talk_timeline(
        self,
        transcript: TranscriptData,
        findings_by_dim: dict[str, list[SynthesizedFinding]],
    ) -> TalkTimeline:
        """Build the TalkTimeline from transcript data and findings.

        Computes open/body/close percentages from the transcript's
        close_start_seconds and builds timeline pins from findings
        with timestamps.

        Args:
            transcript: The transcript data with close_start_seconds.
            findings_by_dim: Capped findings per dimension.

        Returns:
            A TalkTimeline object with percentages and pins.
        """
        words = transcript.words
        if len(words) < 2:
            return TalkTimeline(
                total_duration_seconds=0.0,
                open_percent=33.33,
                body_percent=33.34,
                close_percent=33.33,
                timeline_pins=[],
            )

        total_duration = words[-1].end_seconds - words[0].start_seconds
        if total_duration <= 0:
            return TalkTimeline(
                total_duration_seconds=0.0,
                open_percent=33.33,
                body_percent=33.34,
                close_percent=33.33,
                timeline_pins=[],
            )

        close_start = transcript.close_start_seconds
        # Assume open is ~10% and body fills the rest before close
        # This is a simplification; real implementation would use
        # Talk_Timeline segmentation from the evaluation agents
        close_duration = total_duration - (close_start - words[0].start_seconds)
        close_duration = max(0.0, close_duration)
        close_percent = (close_duration / total_duration) * 100.0

        # Simple heuristic: open is 10% of non-close duration
        non_close_duration = total_duration - close_duration
        open_percent = min(15.0, (non_close_duration * 0.15 / total_duration) * 100.0)
        if open_percent < 0:
            open_percent = 0.0

        body_percent = 100.0 - open_percent - close_percent

        # Clamp values to valid ranges
        if body_percent < 0:
            body_percent = 0.0
            open_percent = 100.0 - close_percent

        # Round to 2 decimals and fix rounding
        open_percent = round(open_percent, 2)
        close_percent = round(close_percent, 2)
        body_percent = round(100.0 - open_percent - close_percent, 2)

        # Safety: ensure all are non-negative
        if body_percent < 0:
            body_percent = 0.0
            close_percent = round(100.0 - open_percent, 2)

        # Build timeline pins from findings with timestamps
        pins: list[TimelinePin] = []
        for dim, findings in findings_by_dim.items():
            for finding in findings:
                if finding.evidence_timestamp_seconds is not None:
                    pins.append(
                        TimelinePin(
                            timestamp_seconds=finding.evidence_timestamp_seconds,
                            label=finding.title[:60],
                            severity=finding.severity,
                            dimension=dim,
                        )
                    )

        return TalkTimeline(
            total_duration_seconds=total_duration,
            open_percent=open_percent,
            body_percent=body_percent,
            close_percent=close_percent,
            timeline_pins=pins,
        )

    def _build_provenance(self, metadata: SubmissionMetadata) -> Provenance:
        """Build the Provenance object for the report.

        Args:
            metadata: Submission metadata containing user/submission IDs.

        Returns:
            A Provenance object with current run details.
        """
        return Provenance(
            report_id=str(uuid.uuid4()),
            evaluator_release="2.0.0",
            rubric_version="1.0.0",
            prompt_set_version="1.0.0",
            model_id=self._model_id,
            model_temperature=0.0,
            transcription_service="aws-transcribe",
            evaluation_window="PT30M",
            run_completed_timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _generate_two_sentence_verdict(
        self,
        overall_score: float,
        score_band: ScoreBand,
        dimensions: list[DimensionEntry],
    ) -> str:
        """Generate a two-sentence verdict for the report (max 80 words).

        Uses second-person voice, no speaker name.

        Args:
            overall_score: The overall score.
            score_band: The classified score band.
            dimensions: The dimension entries (sorted weakest-first).

        Returns:
            A two-sentence verdict string.
        """
        weakest = dimensions[0].dimension_name if dimensions else "overall delivery"
        strongest = dimensions[-1].dimension_name if dimensions else "general skills"

        if score_band == ScoreBand.EXCEPTIONAL:
            verdict = (
                f"Your presentation demonstrates exceptional command across "
                f"all dimensions. Continue refining your {weakest.lower()} "
                f"to maintain this level."
            )
        elif score_band == ScoreBand.EFFECTIVE:
            verdict = (
                f"Your presentation is effective with clear strengths in "
                f"{strongest.lower()}. Focused work on your "
                f"{weakest.lower()} will push you toward exceptional."
            )
        elif score_band == ScoreBand.COMPETENT:
            verdict = (
                f"Your presentation is competent with a solid foundation. "
                f"Prioritizing improvements in {weakest.lower()} will "
                f"yield the greatest score gains."
            )
        else:
            verdict = (
                f"Your presentation has room for significant growth. "
                f"Start with your {weakest.lower()} where focused practice "
                f"will make the most visible difference."
            )

        # Enforce 80-word limit
        words = verdict.split()
        if len(words) > 80:
            verdict = " ".join(words[:80])

        return verdict

    def _generate_lede_paragraph(
        self,
        overall_score: float,
        score_band: ScoreBand,
        three_moves: list[ThreeMove],
    ) -> str:
        """Generate the lede paragraph for the scorecard page (max 120 words).

        Uses second-person voice, no speaker name.

        Args:
            overall_score: The overall score.
            score_band: The classified score band.
            three_moves: The three move plan.

        Returns:
            A lede paragraph string.
        """
        move_titles = [m.title for m in three_moves[:3]]

        lede = (
            f"You scored {overall_score:.1f} out of 10, placing you in the "
            f"{score_band.value} band. "
        )

        if move_titles:
            lede += (
                f"Your three highest-leverage improvements are: "
                f"{move_titles[0]}"
            )
            if len(move_titles) > 1:
                lede += f", {move_titles[1]}"
            if len(move_titles) > 2:
                lede += f", and {move_titles[2]}"
            lede += ". "

        lede += (
            "Addressing these will create measurable progress toward "
            "the next performance band."
        )

        # Enforce 120-word limit
        words = lede.split()
        if len(words) > 120:
            lede = " ".join(words[:120])

        return lede

    def _rank_findings(
        self, findings: list[SynthesizedFinding]
    ) -> list[SynthesizedFinding]:
        """Sort findings by Projected_Impact_Score descending (non-increasing).

        Args:
            findings: List of synthesized findings to rank.

        Returns:
            A new list sorted by projected_impact_score in descending order.
        """
        return sorted(
            findings,
            key=lambda f: f.projected_impact_score,
            reverse=True,
        )

    def _apply_caps(
        self, findings_by_dim: dict[str, list[SynthesizedFinding]]
    ) -> dict[str, list[SynthesizedFinding]]:
        """Enforce 5-finding cap per dimension.

        Drop order: findings without evidence first (lowest impact first),
        then lowest-impact findings with evidence.

        Also enforces 3-strength cap per dimension (handled separately
        at the DimensionEntry level by taking the first 3 strengths).

        Args:
            findings_by_dim: Dictionary mapping dimension names to their
                lists of synthesized findings.

        Returns:
            A new dictionary with each dimension's findings capped at 5.
        """
        capped: dict[str, list[SynthesizedFinding]] = {}
        for dim, findings in findings_by_dim.items():
            capped[dim] = apply_findings_cap(findings, cap=5)
        return capped

    def _collapse_duplicates(
        self, results: list[EvaluationResult]
    ) -> list[SynthesizedFinding]:
        """Collapse findings raised by ≥3 agents for same behavior.

        Groups findings by their category field across all EvaluationResults.
        When 3 or more dimensions raise findings with the same category,
        the findings are collapsed into one SynthesizedFinding attributed
        to the dimension where the issue costs the most points (lowest score).

        Non-collapsed findings are converted to SynthesizedFinding and
        returned alongside collapsed ones.

        Args:
            results: The list of EvaluationResult objects from specialist agents.

        Returns:
            A list of SynthesizedFinding objects containing both collapsed
            and non-collapsed findings.
        """
        # Build a mapping of category -> list of (dimension, score, finding)
        category_groups: dict[str, list[tuple[str, float, Finding]]] = defaultdict(list)

        for eval_result in results:
            for finding in eval_result.findings:
                category_groups[finding.category].append(
                    (eval_result.dimension, eval_result.score, finding)
                )

        synthesized: list[SynthesizedFinding] = []
        collapsed_categories: set[str] = set()

        for category, entries in category_groups.items():
            # Count unique dimensions that raised this category
            unique_dimensions = {dim for dim, _, _ in entries}

            if len(unique_dimensions) >= 3:
                # Collapse: attribute to the dimension with the lowest score
                collapsed_categories.add(category)
                collapsed_finding = self._build_collapsed_finding(
                    category, entries
                )
                synthesized.append(collapsed_finding)
            else:
                # No collapse: convert each finding individually
                for dimension, score, finding in entries:
                    synthesized.append(
                        self._finding_to_synthesized(finding, score)
                    )

        return synthesized

    def _build_collapsed_finding(
        self,
        category: str,
        entries: list[tuple[str, float, Finding]],
    ) -> SynthesizedFinding:
        """Build a single collapsed SynthesizedFinding from multiple dimension entries.

        Attributes the finding to the dimension with the lowest score
        (highest cost) and generates a cross_dimension_note listing
        other affected dimensions.

        Args:
            category: The shared category being collapsed.
            entries: Tuples of (dimension, score, finding) for this category.

        Returns:
            A SynthesizedFinding attributed to the highest-cost dimension.
        """
        # Find the entry with the lowest score (highest cost)
        entries_sorted = sorted(entries, key=lambda e: e[1])
        primary_dimension, primary_score, primary_finding = entries_sorted[0]

        # Collect other affected dimensions (excluding the primary)
        other_dimensions = sorted(
            {dim for dim, _, _ in entries if dim != primary_dimension}
        )

        # Build cross_dimension_note (max 120 chars)
        cross_dimension_note = self._build_cross_dimension_note(other_dimensions)

        # Map severity from the Finding to the SynthesizedFinding Severity enum
        severity = self._map_severity(primary_finding.severity)

        # Compute a projected impact score based on how much the score deviates
        # from a perfect 10 — lower scores mean higher impact
        projected_impact = round(10.0 - primary_score, 1)
        projected_impact = max(0.0, min(10.0, projected_impact))

        return SynthesizedFinding(
            severity=severity,
            title=primary_finding.category[:80],
            explanation=primary_finding.detail[:500],  # validator enforces 100 words
            suggestion=primary_finding.suggestion[:400],  # validator enforces 80 words
            effort_tag=EffortTag.MODERATE,
            impact_tag=self._severity_to_impact(severity),
            evidence_quote=None,
            evidence_timestamp_seconds=None,
            cross_dimension_note=cross_dimension_note,
            projected_impact_score=projected_impact,
        )

    def _build_cross_dimension_note(self, other_dimensions: list[str]) -> str:
        """Build a cross-dimension impact note of max 120 characters.

        Formats dimension names in title case and truncates if necessary.

        Args:
            other_dimensions: Sorted list of other affected dimension names.

        Returns:
            A string like "Also impacts: Structure, Pacing" (max 120 chars).
        """
        prefix = "Also impacts: "
        formatted_dims = [
            dim.replace("_", " ").title() for dim in other_dimensions
        ]

        note = prefix + ", ".join(formatted_dims)

        # Truncate to 120 chars if needed
        if len(note) > 120:
            # Progressively remove dimensions from the end until it fits
            while formatted_dims and len(note) > 120:
                formatted_dims.pop()
                if formatted_dims:
                    note = prefix + ", ".join(formatted_dims) + ", ..."
                else:
                    note = prefix + "multiple dimensions"

        return note[:120]

    def _finding_to_synthesized(
        self, finding: Finding, score: float
    ) -> SynthesizedFinding:
        """Convert a single Finding to a SynthesizedFinding without collapse.

        Args:
            finding: The original Finding from an evaluation agent.
            score: The dimension score for projected impact calculation.

        Returns:
            A SynthesizedFinding with no cross_dimension_note.
        """
        severity = self._map_severity(finding.severity)
        projected_impact = round(10.0 - score, 1)
        projected_impact = max(0.0, min(10.0, projected_impact))

        return SynthesizedFinding(
            severity=severity,
            title=finding.category[:80],
            explanation=finding.detail[:500],
            suggestion=finding.suggestion[:400],
            effort_tag=EffortTag.MODERATE,
            impact_tag=self._severity_to_impact(severity),
            evidence_quote=None,
            evidence_timestamp_seconds=None,
            cross_dimension_note=None,
            projected_impact_score=projected_impact,
        )

    @staticmethod
    def _map_severity(severity_str: str) -> Severity:
        """Map a severity string to the Severity enum.

        Args:
            severity_str: One of "low", "medium", "high".

        Returns:
            The corresponding Severity enum value.
        """
        mapping = {
            "high": Severity.HIGH,
            "medium": Severity.MEDIUM,
            "low": Severity.LOW,
        }
        return mapping.get(severity_str.lower(), Severity.MEDIUM)

    @staticmethod
    def _severity_to_impact(severity: Severity) -> ImpactTag:
        """Map a Severity to an ImpactTag.

        Args:
            severity: The Severity enum value.

        Returns:
            The corresponding ImpactTag.
        """
        mapping = {
            Severity.HIGH: ImpactTag.HIGH,
            Severity.MEDIUM: ImpactTag.MEDIUM,
            Severity.LOW: ImpactTag.LOW,
        }
        return mapping.get(severity, ImpactTag.MEDIUM)

    def _derive_three_moves(
        self, ranked_findings: list[SynthesizedFinding]
    ) -> list[ThreeMove]:
        """Extract top 3 findings as the Three_Move_Plan.

        Takes the globally-ranked findings list (already sorted descending
        by projected_impact_score) and creates exactly 3 ThreeMove objects
        from the top 3 findings.

        Each ThreeMove includes:
        - title (max 60 chars): derived from the finding's title
        - coaching_advice (max 150 words): actionable advice from finding's
          suggestion and explanation
        - projected_impact_score (0.0-10.0): the finding's impact score
        - dimensions_lifted (1-7 dimension names): dimensions that benefit
          from addressing this finding

        Args:
            ranked_findings: Findings sorted descending by projected_impact_score.

        Returns:
            A list of exactly 3 ThreeMove objects.
        """
        # All 7 dimension names used in the system
        all_dimensions = [
            "Delivery",
            "Structure",
            "Executive Presence",
            "Technical Communication",
            "Audience Engagement",
            "Pacing",
            "Persuasion",
        ]

        three_moves: list[ThreeMove] = []
        top_findings = ranked_findings[:3]

        for finding in top_findings:
            # Title: truncate to 60 chars
            title = finding.title[:60]

            # Coaching advice: combine suggestion and explanation into
            # actionable second-person advice (max 150 words)
            coaching_advice = self._build_coaching_advice(finding)

            # Projected impact score: use the finding's score directly
            projected_impact_score = finding.projected_impact_score

            # Dimensions lifted: identify which dimensions benefit
            dimensions_lifted = self._identify_dimensions_lifted(
                finding, all_dimensions
            )

            three_moves.append(
                ThreeMove(
                    title=title,
                    coaching_advice=coaching_advice,
                    projected_impact_score=projected_impact_score,
                    dimensions_lifted=dimensions_lifted,
                )
            )

        return three_moves

    def _build_coaching_advice(self, finding: SynthesizedFinding) -> str:
        """Build actionable coaching advice text from a finding.

        Combines the finding's suggestion and explanation into a
        second-person coaching paragraph. Caps at 150 words.

        Args:
            finding: The synthesized finding to derive coaching advice from.

        Returns:
            A coaching advice string (max 150 words).
        """
        # Start with the suggestion as the primary advice
        suggestion = finding.suggestion.strip()
        explanation = finding.explanation.strip()

        # Build advice prioritizing the suggestion, adding context from explanation
        if suggestion and explanation:
            advice = f"{suggestion} {explanation}"
        elif suggestion:
            advice = suggestion
        else:
            advice = explanation

        # Enforce 150 word limit by truncating at word boundary
        words = advice.split()
        if len(words) > 150:
            advice = " ".join(words[:150])

        return advice

    def _identify_dimensions_lifted(
        self,
        finding: SynthesizedFinding,
        all_dimensions: list[str],
    ) -> list[str]:
        """Identify which dimensions would benefit from addressing a finding.

        At minimum, includes the dimension the finding is attributed to
        (inferred from cross_dimension_note or title). Also includes
        dimensions mentioned in the cross_dimension_note.

        Args:
            finding: The synthesized finding.
            all_dimensions: List of all valid dimension names.

        Returns:
            A list of 1-7 dimension names that would benefit.
        """
        lifted: list[str] = []

        # If there's a cross_dimension_note, parse affected dimensions from it
        if finding.cross_dimension_note:
            note_lower = finding.cross_dimension_note.lower()
            for dim in all_dimensions:
                if dim.lower() in note_lower:
                    lifted.append(dim)

        # Try to infer the primary dimension from the finding title
        title_lower = finding.title.lower()
        for dim in all_dimensions:
            if dim.lower() in title_lower and dim not in lifted:
                lifted.append(dim)

        # If we still haven't identified any dimensions, use impact-based heuristic:
        # high impact findings likely affect the weakest areas
        if not lifted:
            # Default: attribute to the first dimension as a fallback.
            # In practice, the finding's context would identify the dimension.
            # Use severity as a heuristic for breadth of impact.
            if finding.severity == Severity.HIGH:
                # High severity findings often cut across multiple dimensions
                lifted.append(all_dimensions[0])  # Delivery as primary
            else:
                lifted.append(all_dimensions[0])

        # Ensure at most 7
        return lifted[:7]

    def _generate_strengths_to_protect(
        self, results: list[EvaluationResult]
    ) -> list[str]:
        """Produce a list of up to 4 strengths to protect.

        Extracts strength statements from evaluation results, selecting
        the top items that represent the speaker's strongest qualities.
        Each strength is a single sentence of max 30 words.

        Args:
            results: The list of EvaluationResult objects from specialist agents.

        Returns:
            A list of 1-4 strength strings (single sentences, max 30 words each).
        """
        all_strengths: list[str] = []

        # Collect strengths from all evaluation results, prioritizing
        # higher-scoring dimensions (their strengths are more notable)
        results_by_score = sorted(results, key=lambda r: r.score, reverse=True)

        for result in results_by_score:
            for strength in result.strengths:
                # Ensure single sentence and max 30 words
                sentence = strength.strip().rstrip(".")
                words = sentence.split()
                if len(words) > 30:
                    sentence = " ".join(words[:30])
                # Add period if not present
                if not sentence.endswith("."):
                    sentence += "."
                all_strengths.append(sentence)

        # Deduplicate by keeping unique strengths (case-insensitive)
        seen: set[str] = set()
        unique_strengths: list[str] = []
        for s in all_strengths:
            key = s.lower()
            if key not in seen:
                seen.add(key)
                unique_strengths.append(s)

        # Return at most 4, at least 1
        result_list = unique_strengths[:4]
        if not result_list:
            result_list = ["You have a foundation to build on."]

        return result_list

    def _generate_diagnosis_paragraph(self, three_moves: list[ThreeMove]) -> str:
        """Produce a paragraph explaining why the three moves matter together.

        Constructs a second-person narrative explaining the interrelationship
        between the top three coaching recommendations. Max 150 words.

        Args:
            three_moves: The list of exactly 3 ThreeMove objects.

        Returns:
            A diagnosis paragraph string (max 150 words).
        """
        if not three_moves:
            return (
                "Your presentation shows potential. Focus on building "
                "consistency across all dimensions to move to the next level."
            )

        move_titles = [move.title for move in three_moves]

        # Build a connecting narrative about why these three things matter together
        paragraph = (
            f"Your three highest-leverage improvements are interconnected. "
            f"Addressing {move_titles[0]} will create a foundation for the "
            f"other changes."
        )

        if len(move_titles) > 1:
            paragraph += (
                f" Working on {move_titles[1]} reinforces that foundation "
                f"and amplifies your impact."
            )

        if len(move_titles) > 2:
            paragraph += (
                f" Finally, improving {move_titles[2]} ties everything together, "
                f"helping you deliver a more cohesive and compelling presentation."
            )

        # Enforce 150 word limit
        words = paragraph.split()
        if len(words) > 150:
            paragraph = " ".join(words[:150])

        return paragraph

    def _generate_swap_pairs(
        self, findings_by_dim: dict[str, list[SynthesizedFinding]]
    ) -> dict[str, SwapPair | None]:
        """Generate one swap pair per dimension where evidence ≥10 chars.

        For each dimension, selects the highest-impact finding whose
        evidence_quote is at least 10 characters. Constructs a SwapPair
        with the verbatim quote as 'you_said' and a rewritten version
        demonstrating the coaching improvement as 'try_instead'.

        If no finding in the dimension has an evidence_quote of at least
        10 characters, the swap pair for that dimension is None.

        Field constraints:
        - you_said: 10-280 characters (verbatim quote)
        - try_instead: max 400 characters (rewritten version)

        Args:
            findings_by_dim: Dictionary mapping dimension names to their
                lists of synthesized findings.

        Returns:
            A dictionary mapping dimension names to SwapPair or None.
        """
        swap_pairs: dict[str, SwapPair | None] = {}

        for dim, findings in findings_by_dim.items():
            # Filter findings that have evidence_quote of at least 10 chars
            eligible = [
                f
                for f in findings
                if f.evidence_quote is not None and len(f.evidence_quote) >= 10
            ]

            if not eligible:
                swap_pairs[dim] = None
                continue

            # Select the highest-impact finding among eligible ones
            best = max(eligible, key=lambda f: f.projected_impact_score)

            # Extract the verbatim quote, truncating to 280 chars
            you_said = best.evidence_quote[:280] if best.evidence_quote else ""

            # Ensure minimum length (should always be ≥10 given the filter above)
            if len(you_said) < 10:
                swap_pairs[dim] = None
                continue

            # Build 'try_instead' from the finding's suggestion
            try_instead = self._build_try_instead(best, dim)

            swap_pairs[dim] = SwapPair(
                you_said=you_said,
                try_instead=try_instead,
            )

        return swap_pairs

    def _build_try_instead(
        self, finding: SynthesizedFinding, dimension: str
    ) -> str:
        """Build a 'try instead' rewrite from a finding's suggestion.

        Constructs a coaching-oriented rewrite that preserves the speaker's
        original intent while demonstrating the improvement. Uses the
        finding's suggestion as the basis for the rewrite.

        Args:
            finding: The synthesized finding with the coaching suggestion.
            dimension: The dimension name for context.

        Returns:
            A rewrite string of max 400 characters.
        """
        suggestion = finding.suggestion.strip()
        dim_display = dimension.replace("_", " ").title()

        # Build a rewrite that frames the improvement as a coaching example
        if suggestion:
            rewrite = (
                f"Try this instead: {suggestion} "
                f"This adjustment improves your {dim_display}."
            )
        else:
            rewrite = (
                f"Consider rephrasing to strengthen your {dim_display}. "
                f"Focus on clarity and directness to make your point land."
            )

        # Enforce max 400 characters
        if len(rewrite) > 400:
            rewrite = rewrite[:397] + "..."

        return rewrite

    def _generate_practice_drills(
        self, findings_by_dim: dict[str, list[SynthesizedFinding]]
    ) -> dict[str, PracticeDrill | None]:
        """Generate one practice drill per dimension with findings.

        For each dimension that has at least one finding, produces a
        PracticeDrill with:
        - time_box_minutes: derived from the highest-severity finding
          (high=5min, medium=10min, low=15min)
        - instructions: 50-500 chars of specific rehearsal exercise
          referencing at least one finding from that dimension

        If a dimension has zero findings, the practice drill is None.

        Args:
            findings_by_dim: Dictionary mapping dimension names to their
                lists of synthesized findings.

        Returns:
            A dictionary mapping dimension names to PracticeDrill or None.
        """
        drills: dict[str, PracticeDrill | None] = {}

        for dim, findings in findings_by_dim.items():
            if not findings:
                drills[dim] = None
                continue

            # Determine time_box_minutes from the highest-severity finding
            time_box = self._derive_time_box(findings)

            # Build instructions referencing the highest-impact finding
            instructions = self._build_drill_instructions(findings, dim)

            drills[dim] = PracticeDrill(
                time_box_minutes=time_box,
                instructions=instructions,
            )

        return drills

    def _derive_time_box(self, findings: list[SynthesizedFinding]) -> int:
        """Derive practice drill time box from finding severity.

        Uses the highest severity present among findings to set the
        time commitment:
        - HIGH severity → 5 minutes (focused, intense practice)
        - MEDIUM severity → 10 minutes (moderate practice)
        - LOW severity → 15 minutes (extended, exploratory practice)

        The logic is that high-severity issues need quick, focused drills
        while low-severity polishing benefits from longer exploration.

        Args:
            findings: List of findings for a dimension.

        Returns:
            Integer time_box_minutes in range [2, 15].
        """
        severity_to_time = {
            Severity.HIGH: 5,
            Severity.MEDIUM: 10,
            Severity.LOW: 15,
        }

        # Find the highest severity present
        severities = [f.severity for f in findings]

        if Severity.HIGH in severities:
            return severity_to_time[Severity.HIGH]
        elif Severity.MEDIUM in severities:
            return severity_to_time[Severity.MEDIUM]
        else:
            return severity_to_time[Severity.LOW]

    def _build_drill_instructions(
        self, findings: list[SynthesizedFinding], dimension: str
    ) -> str:
        """Build specific rehearsal instructions referencing findings.

        Constructs actionable drill text from the highest-impact finding
        in the dimension. The instructions describe a concrete action
        the speaker can perform to practice the improvement.

        Enforces 50-500 character constraint.

        Args:
            findings: List of findings for the dimension.
            dimension: The dimension name for context.

        Returns:
            Instruction string between 50 and 500 characters.
        """
        dim_display = dimension.replace("_", " ").title()

        # Select the highest-impact finding for the drill
        best = max(findings, key=lambda f: f.projected_impact_score)

        # Build instructions referencing the finding
        title = best.title.strip()
        suggestion = best.suggestion.strip()

        if suggestion:
            instructions = (
                f"Practice drill for {dim_display}: Record yourself for "
                f"the allotted time focusing on '{title}'. {suggestion} "
                f"Play back the recording and note improvements."
            )
        else:
            instructions = (
                f"Practice drill for {dim_display}: Record yourself for "
                f"the allotted time focusing on '{title}'. "
                f"Pay attention to how you can improve in this area. "
                f"Play back the recording and note improvements."
            )

        # Enforce 50-500 character constraint
        if len(instructions) > 500:
            instructions = instructions[:497] + "..."

        # Pad if under 50 characters (unlikely given the template above)
        if len(instructions) < 50:
            instructions = instructions.rstrip(".")
            instructions += (
                ". Repeat this exercise until you feel confident."
            )
            # If still too short, add more context
            if len(instructions) < 50:
                instructions += " Focus on consistent improvement."

        return instructions

    def _validate_voice_consistency(
        self, report: SynthesizedReport
    ) -> SynthesizedReport:
        """Validate and enforce second-person voice in all coaching prose.

        Ensures that:
        1. Coaching prose contains at least one second-person pronoun
           ("you" or "your") in aggregate across all prose fields.
        2. The user_name does NOT appear in any coaching prose field.
           If found, replaces occurrences with "you" or "your" as appropriate.

        Speaker identity (user_name) belongs only in submission metadata fields
        (user_name, presentation_title, file_name), not in coaching prose.

        Coaching prose fields checked:
        - two_sentence_verdict
        - lede_paragraph
        - diagnosis_paragraph
        - All finding explanations and suggestions (across all dimensions)
        - All swap pair try_instead fields
        - All drill instructions

        Args:
            report: The assembled SynthesizedReport to validate.

        Returns:
            A (possibly modified) SynthesizedReport with voice consistency
            enforced. If user_name was found in prose, it is replaced with
            second-person references.
        """
        user_name = report.user_name.strip()

        # Collect all coaching prose for aggregate second-person check
        # and strip user_name if found

        # --- Top-level narrative fields ---
        two_sentence_verdict = self._strip_name_from_text(
            report.two_sentence_verdict, user_name
        )
        lede_paragraph = self._strip_name_from_text(
            report.lede_paragraph, user_name
        )
        diagnosis_paragraph = self._strip_name_from_text(
            report.diagnosis_paragraph, user_name
        )

        # --- Dimension-level prose fields ---
        updated_dimensions: list[DimensionEntry] = []
        for dim_entry in report.dimensions:
            # Process findings
            updated_findings: list[SynthesizedFinding] = []
            for finding in dim_entry.findings:
                new_explanation = self._strip_name_from_text(
                    finding.explanation, user_name
                )
                new_suggestion = self._strip_name_from_text(
                    finding.suggestion, user_name
                )
                if (
                    new_explanation != finding.explanation
                    or new_suggestion != finding.suggestion
                ):
                    updated_findings.append(
                        finding.model_copy(
                            update={
                                "explanation": new_explanation,
                                "suggestion": new_suggestion,
                            }
                        )
                    )
                else:
                    updated_findings.append(finding)

            # Process swap pair
            updated_swap_pair = dim_entry.swap_pair
            if dim_entry.swap_pair is not None:
                new_try_instead = self._strip_name_from_text(
                    dim_entry.swap_pair.try_instead, user_name
                )
                if new_try_instead != dim_entry.swap_pair.try_instead:
                    updated_swap_pair = dim_entry.swap_pair.model_copy(
                        update={"try_instead": new_try_instead}
                    )

            # Process practice drill
            updated_drill = dim_entry.practice_drill
            if dim_entry.practice_drill is not None:
                new_instructions = self._strip_name_from_text(
                    dim_entry.practice_drill.instructions, user_name
                )
                if new_instructions != dim_entry.practice_drill.instructions:
                    updated_drill = dim_entry.practice_drill.model_copy(
                        update={"instructions": new_instructions}
                    )

            # Rebuild dimension entry if anything changed
            if (
                updated_findings != dim_entry.findings
                or updated_swap_pair != dim_entry.swap_pair
                or updated_drill != dim_entry.practice_drill
            ):
                updated_dimensions.append(
                    dim_entry.model_copy(
                        update={
                            "findings": updated_findings,
                            "swap_pair": updated_swap_pair,
                            "practice_drill": updated_drill,
                        }
                    )
                )
            else:
                updated_dimensions.append(dim_entry)

        # --- Aggregate second-person pronoun check ---
        all_prose = " ".join([
            two_sentence_verdict,
            lede_paragraph,
            diagnosis_paragraph,
        ])
        for dim_entry in updated_dimensions:
            for finding in dim_entry.findings:
                all_prose += " " + finding.explanation
                all_prose += " " + finding.suggestion
            if dim_entry.swap_pair is not None:
                all_prose += " " + dim_entry.swap_pair.try_instead
            if dim_entry.practice_drill is not None:
                all_prose += " " + dim_entry.practice_drill.instructions

        has_second_person = self._contains_second_person(all_prose)

        if not has_second_person:
            # Inject second-person reference into the two_sentence_verdict
            # to guarantee at least one occurrence in aggregate
            logger.warning(
                "No second-person pronouns found in coaching prose for "
                "report_id=%s. Injecting second-person reference.",
                report.report_id,
            )
            if not two_sentence_verdict.strip().endswith("."):
                two_sentence_verdict += "."
            two_sentence_verdict = (
                "Your presentation was evaluated. " + two_sentence_verdict
            )
            # Re-enforce 80-word limit
            words = two_sentence_verdict.split()
            if len(words) > 80:
                two_sentence_verdict = " ".join(words[:80])

        # --- Rebuild report if any changes were made ---
        report = report.model_copy(
            update={
                "two_sentence_verdict": two_sentence_verdict,
                "lede_paragraph": lede_paragraph,
                "diagnosis_paragraph": diagnosis_paragraph,
                "dimensions": updated_dimensions,
            }
        )

        return report

    @staticmethod
    def _strip_name_from_text(text: str, user_name: str) -> str:
        """Remove or replace user_name occurrences in text with second-person.

        Performs case-insensitive replacement of the user_name with "you"
        or "your" depending on context. If user_name appears as a
        possessive (e.g., "John's"), replaces with "your". Otherwise
        replaces with "you".

        Only performs replacement if user_name is non-empty and at least
        2 characters long (to avoid spurious single-character replacements).

        Args:
            text: The text to process.
            user_name: The speaker name to strip from the text.

        Returns:
            The text with user_name replaced by second-person references.
        """
        if not user_name or len(user_name.strip()) < 2:
            return text

        name = user_name.strip()

        # Replace possessive form first (e.g., "John's" -> "your")
        possessive_pattern = re.compile(
            re.escape(name) + r"['\u2019]s\b", re.IGNORECASE
        )
        text = possessive_pattern.sub("your", text)

        # Replace standalone name with "you"
        name_pattern = re.compile(
            r"\b" + re.escape(name) + r"\b", re.IGNORECASE
        )
        text = name_pattern.sub("you", text)

        return text

    @staticmethod
    def _contains_second_person(text: str) -> bool:
        """Check if text contains at least one second-person pronoun.

        Looks for word-boundary-delimited "you" or "your" (case-insensitive).

        Args:
            text: The text to check.

        Returns:
            True if "you" or "your" appears as a whole word in the text.
        """
        return bool(re.search(r"\b(you|your)\b", text, re.IGNORECASE))
