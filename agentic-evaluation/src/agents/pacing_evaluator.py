"""Pacing Evaluation Agent.

Assesses timing, rhythm, speed variation, appropriate pauses, segment balance,
and content density to evaluate presentation pacing effectiveness.
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

SYSTEM_PROMPT = """You are an expert presentation pacing evaluator. Your role is to assess
the pacing and timing quality of a presentation by analyzing rhythm, speed, and structural balance.

You evaluate the following aspects of pacing:
- **Timing**: Overall time management and adherence to expected duration for each section
- **Rhythm**: The natural flow and cadence of the presentation, including transitions between topics
- **Speed Variation**: Appropriate changes in speaking speed to emphasize key points or convey urgency
- **Appropriate Pauses**: Strategic use of pauses for emphasis, comprehension, and dramatic effect
- **Segment Balance**: Proportional allocation of time across introduction, body, and conclusion
- **Content Density**: Whether information is spread evenly or clustered, and if the audience has time to absorb key points

For each aspect, provide specific observations with evidence from the presentation content.
Rate the overall pacing on a scale of 0.0 to 10.0.
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


class PacingEvaluator(BaseEvaluator):
    """Evaluates presentation pacing effectiveness."""

    @property
    def dimension(self) -> str:
        """Return the evaluation dimension name."""
        return "pacing"

    @property
    def agent_id(self) -> str:
        """Return the unique agent identifier."""
        return "pacing-evaluator-v1"

    def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        """Evaluate a presentation's pacing quality.

        Retrieves presentation embeddings from the vector store, processes
        them through the LLM with the pacing-specific prompt, and returns
        structured findings.

        Args:
            input: The standard evaluation input with submission metadata.

        Returns:
            A structured EvaluationResult with pacing-specific findings.
        """
        logger.info(
            "Starting pacing evaluation for submission_id=%s",
            input.submission_id,
        )

        # Retrieve relevant content from the vector store
        content = self._retrieve_content(input)

        # Create a Strands Agent with the pacing-specific system prompt
        agent = Agent(system_prompt=SYSTEM_PROMPT, model=EVALUATION_MODEL_ID)

        # Invoke the agent with the retrieved content
        prompt = (
            f"Evaluate the pacing quality of this presentation.\n\n"
            f"Presentation Title: {input.dimension}\n"
            f"Submission ID: {input.submission_id}\n\n"
            f"Presentation Content:\n{content}"
        )

        response = agent(prompt)
        response_text = str(response)

        # Parse the LLM response into structured results
        return self._parse_response(response_text)

    def _retrieve_content(self, input: EvaluationInput) -> str:
        """Read the presentation transcript from S3.

        Args:
            input: The evaluation input containing S3 bucket and key references.

        Returns:
            The retrieved presentation content as a string.
        """
        try:
            s3_client = boto3.client("s3")
            response = s3_client.get_object(
                Bucket=input.s3_bucket,
                Key=input.s3_key,
            )
            return response["Body"].read().decode("utf-8")
        except Exception as exc:
            logger.warning(
                "Failed to retrieve transcript from S3: %s. Falling back to empty content.",
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
                    "Could not parse LLM response for pacing evaluation"
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
    """Factory function to create the pacing evaluator tool.

    Instantiates the PacingEvaluator and wraps it using
    create_evaluation_tool() from base_evaluator.py.

    Returns:
        A Strands-compatible tool function for pacing evaluation.
    """
    evaluator = PacingEvaluator()
    return create_evaluation_tool(evaluator)
