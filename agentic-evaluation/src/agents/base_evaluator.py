"""Base evaluation agent contract and tool factory.

Defines the BaseEvaluator abstract base class that all evaluation agents
must implement, and provides a factory function to wrap evaluators as
Strands-compatible callable tools using the @tool decorator pattern.
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from strands import tool

from models.data_models import EvaluationInput, EvaluationResult

logger = logging.getLogger(__name__)


class BaseEvaluator(ABC):
    """Abstract base class for all evaluation agents.

    Each evaluation agent must subclass BaseEvaluator and implement the
    `evaluate()` method. The agent is identified by its `dimension` (the
    aspect of a presentation it assesses) and its `agent_id` (a unique
    identifier for the specific agent implementation).

    Example:
        class DeliveryEvaluator(BaseEvaluator):
            @property
            def dimension(self) -> str:
                return "delivery"

            @property
            def agent_id(self) -> str:
                return "delivery-evaluator-v1"

            def evaluate(self, input: EvaluationInput) -> EvaluationResult:
                # Perform evaluation logic...
                ...
    """

    @property
    @abstractmethod
    def dimension(self) -> str:
        """Return the evaluation dimension name (e.g. 'delivery', 'structure')."""
        ...

    @property
    @abstractmethod
    def agent_id(self) -> str:
        """Return the unique agent identifier (e.g. 'delivery-evaluator-v1')."""
        ...

    @abstractmethod
    def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        """Evaluate a presentation for the agent's assigned dimension.

        Args:
            input: The standard evaluation input containing submission metadata
                and references to the presentation data.

        Returns:
            A structured EvaluationResult with findings, scores, strengths,
            and improvement suggestions.
        """
        ...


def create_evaluation_tool(evaluator: BaseEvaluator) -> Any:
    """Wrap an evaluator instance as a Strands-compatible callable tool.

    Creates a tool function using the Strands @tool decorator pattern that:
    - Accepts evaluation input as a JSON string parameter
    - Parses it into an EvaluationInput model
    - Calls the evaluator's evaluate() method
    - Returns the EvaluationResult serialized as JSON
    - Handles errors gracefully with proper logging

    Args:
        evaluator: An instance of a BaseEvaluator subclass.

    Returns:
        A Strands tool function that can be registered with a Strands Agent.

    Example:
        evaluator = DeliveryEvaluator()
        delivery_tool = create_evaluation_tool(evaluator)
        # delivery_tool can now be passed to a Strands Agent as a tool
    """

    @tool
    def evaluation_tool(evaluation_input_json: str) -> str:
        """Evaluate a presentation for the {dimension} dimension.

        Args:
            evaluation_input_json: JSON string representing an EvaluationInput
                with fields: submission_id, s3_bucket, s3_key, dimension, user_id.

        Returns:
            JSON string representing the EvaluationResult with dimension,
            score, findings, strengths, improvements, agent_id, and timestamp.
        """
        logger.info(
            "Evaluation tool invoked for dimension=%s, agent_id=%s",
            evaluator.dimension,
            evaluator.agent_id,
        )

        try:
            input_data = EvaluationInput.model_validate_json(evaluation_input_json)
        except Exception as exc:
            error_msg = (
                f"Failed to parse evaluation input for "
                f"agent={evaluator.agent_id}: {exc}"
            )
            logger.error(error_msg)
            return json.dumps({"error": error_msg})

        try:
            result = evaluator.evaluate(input_data)
        except Exception as exc:
            error_msg = (
                f"Evaluation failed for agent={evaluator.agent_id}, "
                f"dimension={evaluator.dimension}: {exc}"
            )
            logger.error(error_msg, exc_info=True)
            return json.dumps({"error": error_msg})

        result_json = result.model_dump_json()
        logger.info(
            "Evaluation completed for dimension=%s, agent_id=%s",
            evaluator.dimension,
            evaluator.agent_id,
        )
        return result_json

    # Set a descriptive name on the tool for registry/debugging purposes
    evaluation_tool.__name__ = f"{evaluator.dimension}_evaluator_tool"
    evaluation_tool.__doc__ = (
        f"Evaluate a presentation for the {evaluator.dimension} dimension. "
        f"Agent: {evaluator.agent_id}."
    )

    return evaluation_tool
