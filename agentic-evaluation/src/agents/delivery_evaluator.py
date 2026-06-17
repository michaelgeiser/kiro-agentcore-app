"""Delivery Evaluation Agent.

Assesses vocal variety, pace, pauses, filler words, energy, and projection
to evaluate presentation delivery effectiveness.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

import boto3
from strands import Agent

from agents.base_evaluator import BaseEvaluator, create_evaluation_tool
from models.data_models import EvaluationInput, EvaluationResult, Finding

logger = logging.getLogger(__name__)

# Model used by evaluation agents — configurable via EVALUATION_MODEL_ID env var
EVALUATION_MODEL_ID = os.environ.get(
    "EVALUATION_MODEL_ID", "us.anthropic.claude-sonnet-4-6"
)

SYSTEM_PROMPT = """You are an expert presentation delivery evaluator. Your role is to assess
the delivery quality of a presentation by analyzing vocal characteristics and speaking style.

You evaluate the following aspects of delivery:
- **Vocal Variety**: Range of pitch, tone, and inflection used to maintain listener interest
- **Pace**: Speed of speech — whether it is too fast, too slow, or appropriately varied
- **Pauses**: Effective use of strategic pauses for emphasis and audience comprehension
- **Filler Words**: Frequency of filler words (um, uh, like, you know) that distract from the message
- **Energy**: Level of enthusiasm, passion, and dynamism conveyed through voice
- **Projection**: Clarity and volume of speech, ensuring the message reaches the audience

For each aspect, provide specific observations with evidence from the presentation content.
Rate the overall delivery on a scale of 0.0 to 10.0.
Identify concrete strengths and specific, actionable improvements.

Respond in the following JSON format:
{
    "score": <float 0.0-10.0>,
    "findings": [
        {
            "category": "<aspect evaluated>",
            "detail": "<specific observation>",
            "severity": "<low|medium|high>",
            "suggestion": "<actionable improvement>"
        }
    ],
    "strengths": ["<strength 1>", "<strength 2>"],
    "improvements": ["<improvement 1>", "<improvement 2>"]
}
"""


class DeliveryEvaluator(BaseEvaluator):
    """Evaluates presentation delivery effectiveness."""

    @property
    def dimension(self) -> str:
        """Return the evaluation dimension name."""
        return "delivery"

    @property
    def agent_id(self) -> str:
        """Return the unique agent identifier."""
        return "delivery-evaluator-v1"

    def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        """Evaluate a presentation's delivery quality.

        Retrieves presentation embeddings from the vector store, processes
        them through the LLM with the delivery-specific prompt, and returns
        structured findings.

        Args:
            input: The standard evaluation input with submission metadata.

        Returns:
            A structured EvaluationResult with delivery-specific findings.
        """
        logger.info(
            "Starting delivery evaluation for submission_id=%s",
            input.submission_id,
        )

        # Retrieve relevant content from the vector store
        content = self._retrieve_content(input)

        # Create a Strands Agent with the delivery-specific system prompt
        agent = Agent(system_prompt=SYSTEM_PROMPT, model=EVALUATION_MODEL_ID)

        # Invoke the agent with the retrieved content
        prompt = (
            f"Evaluate the delivery quality of this presentation.\n\n"
            f"Presentation Title: {input.dimension}\n"
            f"Submission ID: {input.submission_id}\n\n"
            f"Presentation Content:\n{content}"
        )

        response = agent(prompt)
        response_text = str(response)

        # Parse the LLM response into structured results
        return self._parse_response(response_text)

    def _retrieve_content(self, input: EvaluationInput) -> str:
        """Retrieve presentation content from the vector store.

        Args:
            input: The evaluation input containing S3 bucket and key references.

        Returns:
            The retrieved presentation content as a string.
        """
        try:
            client = boto3.client("bedrock-agent-runtime")
            response = client.retrieve(
                knowledgeBaseId=input.s3_key,
                retrievalQuery={"text": "presentation delivery vocal variety pace energy"},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": 10
                    }
                },
            )
            results = response.get("retrievalResults", [])
            content_parts = [
                r.get("content", {}).get("text", "") for r in results
            ]
            return "\n\n".join(content_parts)
        except Exception as exc:
            logger.warning(
                "Failed to retrieve content from vector store: %s. "
                "Falling back to empty content.",
                exc,
            )
            return ""

    def _parse_response(self, response_text: str) -> EvaluationResult:
        """Parse the LLM response into a structured EvaluationResult.

        Args:
            response_text: Raw text response from the LLM agent.

        Returns:
            A validated EvaluationResult instance.
        """
        try:
            # Try to extract JSON from the response
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # If JSON parsing fails, try to find JSON block in the response
            import re

            json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                # Return a default result if parsing completely fails
                logger.warning(
                    "Could not parse LLM response for delivery evaluation"
                )
                data = {
                    "score": 5.0,
                    "findings": [],
                    "strengths": ["Unable to parse detailed response"],
                    "improvements": ["Re-run evaluation for detailed feedback"],
                }

        findings = [
            Finding(
                category=f.get("category", "general"),
                detail=f.get("detail", "No detail provided"),
                severity=f.get("severity", "medium"),
                suggestion=f.get("suggestion", "No suggestion provided"),
            )
            for f in data.get("findings", [])
        ]

        return EvaluationResult(
            dimension=self.dimension,
            score=max(0.0, min(10.0, float(data.get("score", 5.0)))),
            findings=findings,
            strengths=data.get("strengths", []),
            improvements=data.get("improvements", []),
            agent_id=self.agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


def create_tool() -> Any:
    """Factory function to create the delivery evaluator tool.

    Instantiates the DeliveryEvaluator and wraps it using
    create_evaluation_tool() from base_evaluator.py.

    Returns:
        A Strands-compatible tool function for delivery evaluation.
    """
    evaluator = DeliveryEvaluator()
    return create_evaluation_tool(evaluator)
