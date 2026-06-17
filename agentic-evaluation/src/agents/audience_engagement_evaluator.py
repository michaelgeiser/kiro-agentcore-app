"""Audience Engagement Evaluation Agent.

Assesses audience interaction, storytelling, rhetorical questions, eye contact
references, attention-holding strategies, and Q&A handling to evaluate
presentation audience engagement effectiveness.
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

SYSTEM_PROMPT = """You are an expert presentation audience engagement evaluator. Your role is to assess
how effectively a presenter engages and interacts with their audience throughout a presentation.

You evaluate the following aspects of audience engagement:
- **Audience Interaction**: Direct engagement with the audience, including questions posed, polls, and participatory elements
- **Storytelling**: Use of narratives, anecdotes, and relatable examples to connect with listeners
- **Rhetorical Questions**: Strategic use of rhetorical questions to provoke thought and maintain attention
- **Eye Contact References**: Indicators of visual connection with the audience and inclusive addressing
- **Attention-Holding Strategies**: Techniques used to maintain focus, such as humor, surprises, or varied delivery
- **Q&A Handling**: Effectiveness in addressing audience questions, managing discussion, and encouraging participation

For each aspect, provide specific observations with evidence from the presentation content.
Rate the overall audience engagement on a scale of 0.0 to 10.0.
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


class AudienceEngagementEvaluator(BaseEvaluator):
    """Evaluates presentation audience engagement effectiveness."""

    @property
    def dimension(self) -> str:
        """Return the evaluation dimension name."""
        return "audience_engagement"

    @property
    def agent_id(self) -> str:
        """Return the unique agent identifier."""
        return "audience-engagement-evaluator-v1"

    def evaluate(self, input: EvaluationInput) -> EvaluationResult:
        """Evaluate a presentation's audience engagement quality.

        Retrieves presentation embeddings from the vector store, processes
        them through the LLM with the audience engagement-specific prompt,
        and returns structured findings.

        Args:
            input: The standard evaluation input with submission metadata.

        Returns:
            A structured EvaluationResult with audience engagement-specific findings.
        """
        logger.info(
            "Starting audience engagement evaluation for submission_id=%s",
            input.submission_id,
        )

        # Retrieve relevant content from the vector store
        content = self._retrieve_content(input)

        # Create a Strands Agent with the audience engagement-specific system prompt
        agent = Agent(system_prompt=SYSTEM_PROMPT, model=EVALUATION_MODEL_ID)

        # Invoke the agent with the retrieved content
        prompt = (
            f"Evaluate the audience engagement quality of this presentation.\n\n"
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
                    "Could not parse LLM response for audience engagement evaluation"
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
    """Factory function to create the audience engagement evaluator tool.

    Instantiates the AudienceEngagementEvaluator and wraps it using
    create_evaluation_tool() from base_evaluator.py.

    Returns:
        A Strands-compatible tool function for audience engagement evaluation.
    """
    evaluator = AudienceEngagementEvaluator()
    return create_evaluation_tool(evaluator)
