"""Session Supervisor Agent.

Top-level orchestrator for the evaluation session lifecycle. Consumes
messages from the SQS FIFO handoff queue, manages DynamoDB status
transitions, delegates evaluation to the Coaching Supervisor, stores
results in S3, and triggers report generation.

Supports concurrent message processing (across different MessageGroupIds)
with configurable idle timeout for ECS Fargate Spot deployments and
graceful SIGTERM handling for Spot reclamation.
"""

import json
import logging
import os
import signal
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import boto3
from pydantic import ValidationError

from agents.coaching_supervisor import CoachingSupervisor, SubmissionMetadata as SynthesisMetadata
from agents.registry import AgentRegistry
from models.data_models import (
    EvaluationInput,
    EvaluationResult,
    HandoffMessage,
    ProcessingStatus,
    RetryConfig,
    SessionResult,
    get_evaluation_result_path,
)
from services.error_notifier import ErrorNotifier
from services.report_generator import ReportGenerator, ReportGeneratorV2, SubmissionMetadata
from services.retry import _compute_delay
from services.sqs_consumer import SQSConsumer
from services.status_manager import StatusManager
from services.transcript_loader import load_transcript_from_s3

logger = logging.getLogger(__name__)

# Default configuration for ECS Fargate Spot deployment
DEFAULT_IDLE_TIMEOUT_MINUTES = 30
DEFAULT_MAX_CONCURRENT_EVALUATIONS = 5


class SessionSupervisor:
    """Top-level orchestrator for the evaluation session lifecycle.

    Wires together SQSConsumer, StatusManager, CoachingSupervisor,
    ReportGenerator, and ErrorNotifier to process handoff messages
    through the full evaluation pipeline.

    Args:
        sqs_consumer: Consumer for the SQS FIFO handoff queue.
        status_manager: Manager for DynamoDB status transitions.
        coaching_supervisor: Orchestrator for evaluation agents.
        report_generator: Generator for PDF coaching reports.
        error_notifier: Best-effort SNS error notification publisher.
        s3_client: Boto3 S3 client for storing evaluation results.
        bucket_name: Name of the S3 bucket for evaluation results.
        registry: Agent registry for determining available dimensions.
    """

    def __init__(
        self,
        sqs_consumer: SQSConsumer,
        status_manager: StatusManager,
        coaching_supervisor: CoachingSupervisor,
        report_generator: ReportGenerator,
        error_notifier: ErrorNotifier,
        s3_client: Any,
        bucket_name: str,
        registry: AgentRegistry | None = None,
        retry_config: RetryConfig | None = None,
        report_generator_v2: ReportGeneratorV2 | None = None,
    ) -> None:
        self._sqs_consumer = sqs_consumer
        self._status_manager = status_manager
        self._coaching_supervisor = coaching_supervisor
        self._report_generator = report_generator
        self._report_generator_v2 = report_generator_v2
        self._error_notifier = error_notifier
        self._s3_client = s3_client
        self._bucket_name = bucket_name
        self._registry = registry
        self._retry_config = retry_config or RetryConfig()
        self._use_report_v2 = os.environ.get("USE_REPORT_V2", "").lower() == "true"

    def handle_message(self, raw_message: dict) -> SessionResult:
        """Process a single handoff message through the full evaluation pipeline.

        Lifecycle:
        1. Parse and validate as HandoffMessage (Pydantic validation)
        2. Acknowledge the SQS message
        3. Update status to Evaluating
        4. Determine dimensions (all enabled agents from the registry)
        5. Build EvaluationInput and delegate to CoachingSupervisor.evaluate()
        6. Store each EvaluationResult as JSON in S3
        7. Update status to Report_Generating
        8. Generate report via ReportGenerator.generate()
        9. Update status to Completed with report_path
        10. Return SessionResult

        Args:
            raw_message: The raw message dict from SQS (includes _receipt_handle).

        Returns:
            A SessionResult summarizing the evaluation session outcome.
        """
        start_time = time.time()
        receipt_handle = raw_message.get("_receipt_handle")

        # Step 1: Parse and validate as HandoffMessage
        logger.info("Parsing handoff message")
        try:
            # Remove internal SQS metadata keys before validation
            message_data = {
                k: v for k, v in raw_message.items() if not k.startswith("_")
            }
            handoff = HandoffMessage.model_validate(message_data)
        except ValidationError as exc:
            logger.error("Message validation failed: %s", exc)
            # Route invalid message to DLQ
            self._handle_validation_failure(raw_message, receipt_handle, str(exc))
            duration = time.time() - start_time
            submission_id = raw_message.get("submission_id") or "unknown"
            return SessionResult(
                submission_id=submission_id,
                status=ProcessingStatus.FAILED,
                failure_reason=f"Validation error: {exc}",
            )

        submission_id = handoff.submission_id
        logger.info(
            "Processing submission_id=%s, title=%s",
            submission_id,
            handoff.presentation_title,
        )

        # Step 2: Acknowledge the SQS message
        try:
            if receipt_handle:
                self._sqs_consumer.acknowledge(receipt_handle)
                logger.info(
                    "Acknowledged SQS message for submission_id=%s",
                    submission_id,
                )
        except Exception as exc:
            logger.error(
                "Failed to acknowledge message for submission_id=%s: %s",
                submission_id,
                exc,
            )
            # Continue processing even if acknowledge fails

        # Step 3: Update status to Evaluating
        try:
            self._status_manager.update_status(
                submission_id=submission_id,
                status=ProcessingStatus.EVALUATING,
            )
        except Exception as exc:
            logger.error(
                "Failed to update status to Evaluating for submission_id=%s: %s",
                submission_id,
                exc,
            )
            # Continue processing — status update is best-effort at this stage

        # Step 4: Determine dimensions (all enabled agents from registry)
        dimensions = self._get_all_dimensions()
        logger.info(
            "Evaluating %d dimension(s) for submission_id=%s: %s",
            len(dimensions),
            submission_id,
            dimensions,
        )

        # Step 5: Build EvaluationInput and delegate to CoachingSupervisor
        evaluation_input = EvaluationInput(
            submission_id=submission_id,
            s3_bucket=self._bucket_name,
            s3_key=handoff.transcript_s3_key,
            dimension="all",
            user_id=handoff.user_id,
        )

        try:
            evaluation_results = self._coaching_supervisor.evaluate(
                input=evaluation_input,
                dimensions=dimensions,
            )
        except Exception as exc:
            logger.error(
                "CoachingSupervisor evaluation failed for submission_id=%s: %s",
                submission_id,
                exc,
            )
            return self._handle_failure(
                submission_id=submission_id,
                failure_reason=f"Evaluation failed: {exc}",
                start_time=start_time,
                evaluation_results=[],
            )

        # Collect agent failures for partial failure reporting
        agent_failures = self._coaching_supervisor.get_last_failures()

        # Step 6: Store each EvaluationResult as JSON in S3
        stored_results = self._store_evaluation_results(
            submission_id, evaluation_results
        )

        # Partial failure handling:
        # - If NO results were obtained AND there were agent failures (all
        #   agents that were invoked failed): mark as Failed, do NOT generate
        #   a report.
        # - If SOME results obtained but some agents failed: still generate
        #   the report from whatever data we have.
        # - If no results and no failures (e.g., no agents invoked): proceed
        #   normally — report generation will handle zero-result case.
        if not stored_results and agent_failures:
            # All agents failed — cannot generate a report
            failed_dims = [f.dimension for f in agent_failures]
            failure_reason = (
                "All evaluation agents failed — no results obtained. "
                f"Failed dimensions: {failed_dims}. "
                f"Agent failure details: "
                + "; ".join(
                    f"{f.agent_id} ({f.dimension}): {f.error}"
                    for f in agent_failures
                )
            )
            return self._handle_failure(
                submission_id=submission_id,
                failure_reason=failure_reason,
                start_time=start_time,
                evaluation_results=[],
                agent_failures=agent_failures,
            )

        # Step 7: Update status to Report_Generating
        try:
            self._status_manager.update_status(
                submission_id=submission_id,
                status=ProcessingStatus.REPORT_GENERATING,
            )
        except Exception as exc:
            logger.error(
                "Failed to update status to Report_Generating for "
                "submission_id=%s: %s",
                submission_id,
                exc,
            )

        # Step 8: Generate report via ReportGenerator
        # Build submission metadata for the report header
        report_metadata = self._build_report_metadata(
            submission_id=submission_id,
            user_id=handoff.user_id,
            presentation_title=handoff.presentation_title,
        )

        try:
            report_path = self._generate_report(
                submission_id=submission_id,
                user_id=handoff.user_id,
                stored_results=stored_results,
                report_metadata=report_metadata,
                transcript_s3_key=handoff.transcript_s3_key,
            )
        except Exception as exc:
            logger.error(
                "Report generation failed for submission_id=%s: %s",
                submission_id,
                exc,
            )
            return self._handle_failure(
                submission_id=submission_id,
                failure_reason=f"Report generation failed: {exc}",
                start_time=start_time,
                evaluation_results=stored_results,
                agent_failures=agent_failures,
                results_already_stored=True,
            )

        # Step 9: Update status to Completed with report_path
        try:
            self._status_manager.update_status(
                submission_id=submission_id,
                status=ProcessingStatus.COMPLETED,
                report_path=report_path,
            )
        except Exception as exc:
            logger.error(
                "Failed to update status to Completed for submission_id=%s: %s",
                submission_id,
                exc,
            )

        # Log partial failure info if some agents failed but report was
        # still generated (results were available)
        if agent_failures:
            logger.warning(
                "Evaluation session for submission_id=%s completed with "
                "partial failures. Report generated from %d result(s). "
                "Failed agents: %s",
                submission_id,
                len(stored_results),
                [
                    f"{f.agent_id} ({f.dimension})" for f in agent_failures
                ],
            )

        # Step 10: Return SessionResult
        duration = time.time() - start_time
        logger.info(
            "Evaluation session completed for submission_id=%s in %.2fs. "
            "Report stored at: %s",
            submission_id,
            duration,
            report_path,
        )

        return SessionResult(
            submission_id=submission_id,
            status=ProcessingStatus.COMPLETED,
            evaluation_results=stored_results,
            report_path=report_path,
            agent_failures=agent_failures,
        )

    def consume_queue(
        self,
        idle_timeout_minutes: int = DEFAULT_IDLE_TIMEOUT_MINUTES,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT_EVALUATIONS,
    ) -> None:
        """Continuously poll the SQS FIFO queue and process messages concurrently.

        Supports concurrent processing of messages from different MessageGroupIds
        (each submission_id is its own group), idle timeout for ECS Fargate Spot
        cost optimization, and graceful SIGTERM handling for Spot reclamation.

        FIFO Ordering Guarantee:
            Sequential ordering within a single MessageGroupId is preserved
            naturally because each submission_id uses its own MessageGroupId.
            Messages from different groups are processed concurrently in
            separate threads.

        Idle Timeout:
            If no messages are received for ``idle_timeout_minutes`` consecutive
            minutes, the consumer exits gracefully. This allows ECS Fargate Spot
            tasks to shut down when there is no work, minimizing cost.

        SIGTERM Handling (Spot Reclamation):
            When a SIGTERM signal is received (e.g., ECS Spot 2-minute warning),
            the consumer stops accepting new messages, waits for in-progress
            evaluations to complete, then exits cleanly.

        Args:
            idle_timeout_minutes: Minutes of inactivity before graceful exit.
                Defaults to DEFAULT_IDLE_TIMEOUT_MINUTES (30).
            max_concurrent: Maximum number of messages to process simultaneously.
                Defaults to DEFAULT_MAX_CONCURRENT_EVALUATIONS (5).
        """
        idle_timeout_seconds = idle_timeout_minutes * 60
        last_message_time = time.time()
        shutting_down = False

        logger.info(
            "Starting queue consumption loop: idle_timeout=%d min, "
            "max_concurrent=%d",
            idle_timeout_minutes,
            max_concurrent,
        )

        # --- SIGTERM handler for Spot reclamation ---
        def _sigterm_handler(signum: int, frame: Any) -> None:
            nonlocal shutting_down
            shutting_down = True
            logger.warning(
                "SIGTERM received — initiating graceful shutdown. "
                "No new messages will be accepted. Waiting for %d "
                "in-progress evaluation(s) to complete...",
                len(futures),
            )

        signal.signal(signal.SIGTERM, _sigterm_handler)

        executor = ThreadPoolExecutor(
            max_workers=max_concurrent,
            thread_name_prefix="eval-worker",
        )
        futures: dict = {}  # future -> submission_id

        try:
            while not shutting_down:
                # Check idle timeout
                idle_elapsed = time.time() - last_message_time
                if idle_elapsed >= idle_timeout_seconds:
                    logger.info(
                        "Idle timeout reached (%.1f min with no messages). "
                        "Exiting gracefully.",
                        idle_elapsed / 60,
                    )
                    break

                # Clean up completed futures
                done_futures = [f for f in futures if f.done()]
                for f in done_futures:
                    sub_id = futures.pop(f)
                    try:
                        f.result()  # Re-raise any exception for logging
                    except Exception as exc:
                        logger.exception(
                            "Unhandled error in worker for submission_id=%s: %s",
                            sub_id,
                            exc,
                        )

                # If all slots are full, wait briefly before checking again
                if len(futures) >= max_concurrent:
                    time.sleep(1)
                    continue

                # Poll for a new message
                try:
                    raw_message = self._sqs_consumer.receive_message()
                except Exception as exc:
                    logger.error("Error receiving message from SQS: %s", exc)
                    time.sleep(5)
                    continue

                if raw_message is None:
                    logger.debug(
                        "No messages received (idle %.0fs / %ds timeout), "
                        "continuing to poll. Active workers: %d/%d",
                        idle_elapsed,
                        idle_timeout_seconds,
                        len(futures),
                        max_concurrent,
                    )
                    continue

                # Reset idle timer on message receipt
                last_message_time = time.time()
                submission_id = raw_message.get("submission_id", "unknown")

                logger.info(
                    "Dispatching message for submission_id=%s to worker "
                    "(slot %d/%d)",
                    submission_id,
                    len(futures) + 1,
                    max_concurrent,
                )

                future = executor.submit(self._process_message_safe, raw_message)
                futures[future] = submission_id

        finally:
            # Wait for in-progress evaluations to finish
            if futures:
                logger.info(
                    "Waiting for %d in-progress evaluation(s) to complete "
                    "before exit...",
                    len(futures),
                )
                for f in as_completed(futures):
                    sub_id = futures[f]
                    try:
                        f.result()
                    except Exception as exc:
                        logger.exception(
                            "Worker error during shutdown for submission_id=%s: %s",
                            sub_id,
                            exc,
                        )

            executor.shutdown(wait=False)
            logger.info("Queue consumption loop exited. Goodbye.")

    def _process_message_safe(self, raw_message: dict) -> None:
        """Process a single message, catching and reporting any unhandled errors.

        This wrapper is used by the thread pool to ensure exceptions
        don't crash the worker thread silently.

        Args:
            raw_message: The raw SQS message dict.
        """
        try:
            self.handle_message(raw_message)
        except Exception as exc:
            submission_id = raw_message.get("submission_id", "unknown")
            logger.exception(
                "Unhandled error processing message for "
                "submission_id=%s: %s",
                submission_id,
                exc,
            )
            self._error_notifier.notify(
                submission_id=submission_id,
                component_name="SessionSupervisor",
                error_type="UnhandledError",
                error_message=str(exc),
                retry_count_exhausted=0,
            )

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _get_all_dimensions(self) -> list[str]:
        """Get all enabled evaluation dimension names from the registry.

        Returns:
            A list of dimension strings. Returns a default set of 7 dimensions
            if no registry is configured.
        """
        if self._registry is not None:
            available = self._registry.get_available_agents()
            return [agent.dimension for agent in available]

        # Default set of all 7 dimensions if no registry is available
        return [
            "delivery",
            "structure",
            "executive_presence",
            "technical_communication",
            "audience_engagement",
            "pacing",
            "persuasion",
        ]

    def _build_report_metadata(
        self,
        submission_id: str,
        user_id: str,
        presentation_title: str,
    ) -> SubmissionMetadata | None:
        """Build submission metadata for the coaching report header.

        Queries DynamoDB for the full submission record to get description,
        file name, and upload date. Attempts to look up the user's display
        name from Cognito; falls back to user_id if unavailable.

        Args:
            submission_id: The submission identifier.
            user_id: The Cognito user sub (UUID).
            presentation_title: Title from the handoff message.

        Returns:
            SubmissionMetadata instance, or None if metadata cannot be built.
        """
        try:
            # Query DynamoDB for the full submission record
            table = self._status_manager._table
            response = table.get_item(Key={"submission_id": submission_id})
            item = response.get("Item", {})

            description = item.get("description")
            file_name = item.get("original_file_name")
            upload_date = item.get("upload_date")

            # Attempt to get user display name from Cognito
            user_name = self._get_user_display_name(user_id)

            return SubmissionMetadata(
                user_name=user_name,
                presentation_title=presentation_title,
                description=description,
                file_name=file_name,
                upload_date=upload_date,
            )
        except Exception as exc:
            logger.warning(
                "Failed to build report metadata for submission_id=%s: %s. "
                "Report will use fallback header.",
                submission_id,
                exc,
            )
            return None

    def _generate_report(
        self,
        submission_id: str,
        user_id: str,
        stored_results: list[EvaluationResult],
        report_metadata: SubmissionMetadata | None,
        transcript_s3_key: str,
    ) -> str:
        """Generate a coaching report using v1 or v2 pipeline.

        When USE_REPORT_V2=true and a ReportGeneratorV2 is configured,
        runs the synthesis pass to produce a SynthesizedReport and renders
        it via WeasyPrint. Otherwise falls back to the existing ReportLab
        pipeline.

        Args:
            submission_id: Unique identifier for the submission.
            user_id: Unique identifier for the user.
            stored_results: EvaluationResult objects from specialist agents.
            report_metadata: Submission metadata for the report header.
            transcript_s3_key: S3 key for the transcript JSON file.

        Returns:
            The S3 key path where the report was stored.
        """
        if self._use_report_v2 and self._report_generator_v2 is not None:
            return self._generate_report_v2(
                submission_id=submission_id,
                user_id=user_id,
                stored_results=stored_results,
                report_metadata=report_metadata,
                transcript_s3_key=transcript_s3_key,
            )

        # Fall back to v1 ReportLab pipeline
        return self._report_generator.generate(
            submission_id=submission_id,
            user_id=user_id,
            results=stored_results,
            metadata=report_metadata,
        )

    def _generate_report_v2(
        self,
        submission_id: str,
        user_id: str,
        stored_results: list[EvaluationResult],
        report_metadata: SubmissionMetadata | None,
        transcript_s3_key: str,
    ) -> str:
        """Generate a coaching report using the v2 WeasyPrint pipeline.

        Runs the Coaching Supervisor synthesis pass to produce a
        SynthesizedReport, then renders it to PDF via ReportGeneratorV2.

        Steps:
        1. Load transcript data from S3 (word-level timings)
        2. Build SynthesisMetadata from report_metadata
        3. Call synthesis_pass() with evaluation results + transcript + metadata
        4. Pass the SynthesizedReport to ReportGeneratorV2.generate()

        Args:
            submission_id: Unique identifier for the submission.
            user_id: Unique identifier for the user.
            stored_results: EvaluationResult objects from specialist agents.
            report_metadata: Submission metadata for the report header.
            transcript_s3_key: S3 key for the transcript JSON file.

        Returns:
            The S3 key path where the report was stored
                (reports/{user_id}/{submission_id}/coaching_report.pdf).
        """
        logger.info(
            "Using Report v2 pipeline for submission_id=%s", submission_id
        )

        # Step 1: Load transcript data from S3
        transcript_data = load_transcript_from_s3(
            s3_client=self._s3_client,
            bucket_name=self._bucket_name,
            transcript_s3_key=transcript_s3_key,
        )

        # Step 2: Build SynthesisMetadata from report_metadata
        synthesis_metadata = self._build_synthesis_metadata(
            submission_id=submission_id,
            user_id=user_id,
            report_metadata=report_metadata,
        )

        # Step 3: Call synthesis_pass() to produce SynthesizedReport
        synthesized_report = self._coaching_supervisor.synthesis_pass(
            results=stored_results,
            transcript=transcript_data,
            metadata=synthesis_metadata,
        )

        logger.info(
            "Synthesis pass completed for submission_id=%s, report_id=%s, "
            "overall_score=%.1f, score_band=%s",
            submission_id,
            synthesized_report.report_id,
            synthesized_report.overall_score,
            synthesized_report.score_band.value,
        )

        # Step 4: Generate PDF via ReportGeneratorV2
        s3_key = self._report_generator_v2.generate(
            report=synthesized_report,
            user_id=user_id,
            submission_id=submission_id,
        )

        logger.info(
            "Report v2 generated for submission_id=%s at s3://%s/%s",
            submission_id,
            self._bucket_name,
            s3_key,
        )

        return s3_key

    def _build_synthesis_metadata(
        self,
        submission_id: str,
        user_id: str,
        report_metadata: SubmissionMetadata | None,
    ) -> SynthesisMetadata:
        """Build SynthesisMetadata for the synthesis pass from report metadata.

        Converts the ReportGenerator's SubmissionMetadata (used for the v1
        pipeline) into the CoachingSupervisor's SubmissionMetadata dataclass
        required by synthesis_pass().

        Args:
            submission_id: Unique identifier for the submission.
            user_id: Unique identifier for the user.
            report_metadata: Optional metadata from DynamoDB/Cognito lookup.

        Returns:
            SynthesisMetadata instance for the synthesis pass.
        """
        if report_metadata is not None:
            return SynthesisMetadata(
                user_name=report_metadata.user_name or user_id,
                presentation_title=report_metadata.presentation_title or "Untitled",
                file_name=report_metadata.file_name or "",
                upload_date=report_metadata.upload_date or "",
                audio_duration_seconds=0.0,
                speaker_identified=False,
                user_id=user_id,
                submission_id=submission_id,
            )

        # Fallback when metadata is unavailable
        return SynthesisMetadata(
            user_name=user_id,
            presentation_title="Untitled",
            file_name="",
            upload_date="",
            audio_duration_seconds=0.0,
            speaker_identified=False,
            user_id=user_id,
            submission_id=submission_id,
        )

    def _get_user_display_name(self, user_id: str) -> str:
        """Look up the user's display name and email from Cognito.

        Retrieves the user's name and email attributes from Cognito and
        formats them as "Name (email)". Falls back to user_id if the
        lookup fails.

        Name resolution order:
        1. "name" attribute (full name)
        2. "given_name" + "family_name" (first + last)
        3. "given_name" only
        4. "email" only
        5. user_id (fallback)

        Args:
            user_id: The Cognito user sub (UUID).

        Returns:
            Formatted string like "Michael Geiser (mgeiser@mgeiser.net)",
            or user_id as fallback.
        """
        try:
            import os

            user_pool_id = os.environ.get("COGNITO_USER_POOL_ID", "")
            user_pool_name = os.environ.get("COGNITO_USER_POOL_NAME", "")

            if not user_pool_id and not user_pool_name:
                logger.warning(
                    "Neither COGNITO_USER_POOL_ID nor COGNITO_USER_POOL_NAME is set. "
                    "Cannot look up user display name for user_id=%s",
                    user_id,
                )
                return user_id

            cognito_client = boto3.client("cognito-idp")

            # If we only have the pool name, look up the pool ID
            if not user_pool_id and user_pool_name:
                user_pool_id = self._resolve_user_pool_id(
                    cognito_client, user_pool_name
                )
                if not user_pool_id:
                    logger.warning(
                        "Could not resolve Cognito user pool ID from name '%s'",
                        user_pool_name,
                    )
                    return user_id

            response = cognito_client.admin_get_user(
                UserPoolId=user_pool_id,
                Username=user_id,
            )

            # Extract user attributes
            attributes = {
                attr["Name"]: attr["Value"]
                for attr in response.get("UserAttributes", [])
            }

            # Resolve display name: name > given_name+family_name > given_name
            name = attributes.get("name")
            if not name:
                given_name = attributes.get("given_name", "")
                family_name = attributes.get("family_name", "")
                if given_name and family_name:
                    name = f"{given_name} {family_name}"
                elif given_name:
                    name = given_name

            email = attributes.get("email")

            # Format as "Name (email)"
            if name and email:
                return f"{name} ({email})"
            elif name:
                return name
            elif email:
                return email
            else:
                return user_id
        except Exception as exc:
            logger.warning(
                "Cognito user lookup failed for user_id=%s: %s. "
                "Using user_id as display name.",
                user_id,
                exc,
            )
            return user_id

    def _resolve_user_pool_id(
        self, cognito_client: Any, pool_name: str
    ) -> str | None:
        """Resolve a Cognito user pool ID from its name.

        Lists user pools and finds the one matching the given name.

        Args:
            cognito_client: Boto3 Cognito IDP client.
            pool_name: The user pool name to search for.

        Returns:
            The user pool ID if found, None otherwise.
        """
        try:
            paginator = cognito_client.get_paginator("list_user_pools")
            for page in paginator.paginate(MaxResults=60):
                for pool in page.get("UserPools", []):
                    if pool.get("Name") == pool_name:
                        return pool["Id"]
            return None
        except Exception as exc:
            logger.warning(
                "Failed to list Cognito user pools: %s", exc
            )
            return None

    def _store_evaluation_results(
        self,
        submission_id: str,
        results: list[EvaluationResult],
    ) -> list[EvaluationResult]:
        """Store each evaluation result as JSON in S3 with retry logic.

        Uses exponential backoff with jitter for transient S3 write failures.
        On permanent failure (retries exhausted), notifies via SNS and
        continues with remaining results.

        Args:
            submission_id: The submission identifier.
            results: List of evaluation results to store.

        Returns:
            The list of results that were successfully stored.
        """
        stored: list[EvaluationResult] = []

        for result in results:
            s3_key = get_evaluation_result_path(submission_id, result.dimension)
            success = self._put_object_with_retry(
                submission_id=submission_id,
                s3_key=s3_key,
                body=result.model_dump_json(),
                dimension=result.dimension,
            )
            if success:
                stored.append(result)
                logger.info(
                    "Stored evaluation result for submission_id=%s, "
                    "dimension=%s at s3://%s/%s",
                    submission_id,
                    result.dimension,
                    self._bucket_name,
                    s3_key,
                )
            else:
                # Failure after retries exhausted — already notified via SNS
                # Continue with remaining results per Requirement 5.5
                logger.warning(
                    "Skipping dimension=%s for submission_id=%s after "
                    "S3 write failure (retries exhausted)",
                    result.dimension,
                    submission_id,
                )

        return stored

    def _put_object_with_retry(
        self,
        submission_id: str,
        s3_key: str,
        body: str,
        dimension: str,
    ) -> bool:
        """Write an object to S3 with exponential backoff and jitter.

        Args:
            submission_id: The submission identifier (for error reporting).
            s3_key: The S3 key to write to.
            body: The body content to store.
            dimension: The evaluation dimension (for error reporting).

        Returns:
            True if the write succeeded, False if all retries were exhausted.
        """
        config = self._retry_config
        last_exception: Exception | None = None

        for attempt in range(1, config.max_attempts + 1):
            try:
                self._s3_client.put_object(
                    Bucket=self._bucket_name,
                    Key=s3_key,
                    Body=body,
                    ContentType="application/json",
                )
                return True
            except Exception as exc:
                last_exception = exc

                if attempt >= config.max_attempts:
                    logger.error(
                        "Failed to store evaluation result for "
                        "submission_id=%s, dimension=%s after %d attempts: %s",
                        submission_id,
                        dimension,
                        config.max_attempts,
                        exc,
                    )
                    # Notify via SNS on final failure
                    self._error_notifier.notify(
                        submission_id=submission_id,
                        component_name=f"S3Storage-{dimension}",
                        error_type="S3WriteError",
                        error_message=str(exc),
                        retry_count_exhausted=config.max_attempts,
                    )
                    return False

                delay = _compute_delay(attempt, config)
                logger.warning(
                    "S3 write failed for submission_id=%s, dimension=%s "
                    "on attempt %d/%d (%s). Retrying in %.2fs...",
                    submission_id,
                    dimension,
                    attempt,
                    config.max_attempts,
                    exc,
                    delay,
                )
                time.sleep(delay)

        # Should not be reached, but satisfies type checkers
        return False  # pragma: no cover

    def verify_completeness(
        self,
        submission_id: str,
        expected_dimensions: list[str],
    ) -> bool:
        """Verify that all expected evaluation result files exist in S3.

        Checks that every expected dimension has a corresponding result
        file present in S3 at the correct path. Used before proceeding
        to report generation to ensure data completeness.

        Args:
            submission_id: The submission identifier.
            expected_dimensions: List of dimension names that should have
                corresponding result files in S3.

        Returns:
            True if all expected dimension files are present, False otherwise.
        """
        if not expected_dimensions:
            return True

        for dimension in expected_dimensions:
            s3_key = get_evaluation_result_path(submission_id, dimension)
            try:
                self._s3_client.head_object(
                    Bucket=self._bucket_name,
                    Key=s3_key,
                )
            except Exception:
                logger.warning(
                    "Completeness check failed: missing result for "
                    "submission_id=%s, dimension=%s (expected at s3://%s/%s)",
                    submission_id,
                    dimension,
                    self._bucket_name,
                    s3_key,
                )
                return False

        logger.info(
            "Completeness verification passed for submission_id=%s: "
            "all %d expected dimensions present",
            submission_id,
            len(expected_dimensions),
        )
        return True

    def _handle_validation_failure(
        self,
        raw_message: dict,
        receipt_handle: str | None,
        error_message: str,
    ) -> None:
        """Handle a message that fails validation.

        Routes the message to the DLQ and sends an error notification.

        Args:
            raw_message: The raw message that failed validation.
            receipt_handle: The SQS receipt handle for acknowledgment.
            error_message: Description of the validation failure.
        """
        submission_id = raw_message.get("submission_id", "unknown")

        # Route to DLQ
        try:
            message_body = json.dumps(raw_message, default=str)
            self._sqs_consumer.send_to_dlq(message_body, error_message)
        except Exception as exc:
            logger.error(
                "Failed to route invalid message to DLQ: %s", exc
            )

        # Acknowledge the original message to remove it from the queue
        try:
            if receipt_handle:
                self._sqs_consumer.acknowledge(receipt_handle)
        except Exception as exc:
            logger.error(
                "Failed to acknowledge invalid message: %s", exc
            )

        # Send error notification
        self._error_notifier.notify(
            submission_id=submission_id,
            component_name="SessionSupervisor",
            error_type="ValidationError",
            error_message=error_message,
            retry_count_exhausted=0,
        )

    def _handle_failure(
        self,
        submission_id: str,
        failure_reason: str,
        start_time: float,
        evaluation_results: list[EvaluationResult],
        agent_failures: list | None = None,
        results_already_stored: bool = False,
    ) -> SessionResult:
        """Handle an unrecoverable failure during the evaluation session.

        Updates DynamoDB status to Failed (always with a non-empty
        failure_reason), stores any successfully obtained results to S3,
        and publishes a detailed SNS notification including which agents
        completed and which failed.

        Does NOT generate a report from incomplete data.

        Args:
            submission_id: The submission identifier.
            failure_reason: Human-readable description of the failure.
            start_time: The time the session started (for duration calc).
            evaluation_results: Any results successfully obtained.
            agent_failures: List of agent failures for partial failure info.
            results_already_stored: If True, skip storing results (already in S3).

        Returns:
            A SessionResult with Failed status.
        """
        failures = agent_failures or []

        # Store whatever results were successfully obtained (partial results)
        # Skip if results were already stored earlier in the pipeline
        if evaluation_results and not results_already_stored:
            self._store_evaluation_results(submission_id, evaluation_results)

        # Build detailed failure reason including which agents completed/failed
        completed_dimensions = [r.dimension for r in evaluation_results]
        failed_dimensions = [f.dimension for f in failures]

        detailed_reason = failure_reason
        if failures or evaluation_results:
            parts = [failure_reason]
            if completed_dimensions:
                parts.append(
                    f"Completed dimensions: {completed_dimensions}"
                )
            if failed_dimensions:
                parts.append(
                    f"Failed dimensions: {failed_dimensions}"
                )
            for f in failures:
                parts.append(f"  - {f.agent_id} ({f.dimension}): {f.error}")
            detailed_reason = ". ".join(
                p for p in parts if not p.startswith("  -")
            )
            if failures:
                detailed_reason += ". Agent failure details: " + "; ".join(
                    f"{f.agent_id} ({f.dimension}): {f.error}"
                    for f in failures
                )

        # Ensure failure_reason is always non-empty
        if not detailed_reason:
            detailed_reason = "Unknown failure during evaluation session"

        # Update status to Failed with non-empty failure_reason
        try:
            self._status_manager.update_status(
                submission_id=submission_id,
                status=ProcessingStatus.FAILED,
                failure_reason=detailed_reason,
            )
        except Exception as exc:
            logger.error(
                "Failed to update status to Failed for submission_id=%s: %s",
                submission_id,
                exc,
            )

        # Build detailed SNS notification with partial failure info
        notification_message = self._build_failure_notification_message(
            failure_reason=failure_reason,
            completed_dimensions=completed_dimensions,
            failed_dimensions=failed_dimensions,
            agent_failures=failures,
        )

        self._error_notifier.notify(
            submission_id=submission_id,
            component_name="SessionSupervisor",
            error_type="EvaluationSessionFailed",
            error_message=notification_message,
            retry_count_exhausted=0,
        )

        duration = time.time() - start_time
        logger.error(
            "Evaluation session FAILED for submission_id=%s after %.2fs. "
            "Reason: %s",
            submission_id,
            duration,
            detailed_reason,
        )

        return SessionResult(
            submission_id=submission_id,
            status=ProcessingStatus.FAILED,
            evaluation_results=evaluation_results,
            failure_reason=detailed_reason,
            agent_failures=failures,
        )

    def _build_failure_notification_message(
        self,
        failure_reason: str,
        completed_dimensions: list[str],
        failed_dimensions: list[str],
        agent_failures: list,
    ) -> str:
        """Build a detailed error notification message for SNS.

        Includes which dimensions were successfully evaluated and which
        failed, along with agent-level failure details.

        Args:
            failure_reason: The primary failure reason.
            completed_dimensions: List of dimensions that completed.
            failed_dimensions: List of dimensions that failed.
            agent_failures: List of AgentFailure objects with details.

        Returns:
            A detailed error message string for the SNS notification.
        """
        parts = [failure_reason]

        if completed_dimensions:
            parts.append(
                f"Dimensions evaluated successfully: {completed_dimensions}"
            )
        if failed_dimensions:
            parts.append(
                f"Dimensions that failed: {failed_dimensions}"
            )
        if agent_failures:
            failure_details = "; ".join(
                f"{f.agent_id} ({f.dimension}): {f.error}"
                for f in agent_failures
            )
            parts.append(f"Agent failure details: {failure_details}")

        return " | ".join(parts)
