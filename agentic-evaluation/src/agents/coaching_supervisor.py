"""Coaching Supervisor Agent.

Orchestrates evaluation agents based on presentation context using the
Strands Agents SDK "Agents as Tools" pattern. The Coaching Supervisor
dynamically selects evaluators, invokes them, reviews results, and
decides whether additional evaluation is warranted.
"""

import importlib
import json
import logging
from typing import Any

from strands import Agent

from agents.registry import AgentRegistry
from models.data_models import AgentFailure, EvaluationInput, EvaluationResult

logger = logging.getLogger(__name__)

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
        model_id: str = "anthropic.claude-sonnet-4-6",
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
        """Invoke the Strands agent and collect evaluation results.

        Uses the agent's tool-calling capabilities to invoke evaluation
        tools for each dimension. Parses tool call results into
        EvaluationResult objects.

        This method supports iterative invocation — the agent may decide
        to call additional tools based on earlier findings.

        On agent orchestration failure, falls back to direct tool invocation
        while tracking any individual agent failures.

        Args:
            input: The evaluation input.
            dimensions: The dimensions being evaluated.
            prompt: The orchestration prompt for the agent.

        Returns:
            A list of parsed EvaluationResult objects from tool invocations.
        """
        results: list[EvaluationResult] = []

        try:
            response = self._agent(prompt)
            # Extract tool results from the agent's response
            results = self._extract_results_from_response(response)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Agent orchestration failed for submission_id=%s: %s. "
                "Falling back to direct tool invocation.",
                input.submission_id,
                exc,
            )
            # Fall back to direct tool invocation for each dimension
            results = self._direct_invoke_tools(input, dimensions)

        return results

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
        import re

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
