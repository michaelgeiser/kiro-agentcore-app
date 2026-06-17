from enum import Enum
from typing import Optional

from pydantic import BaseModel


class ProcessingStatus(str, Enum):
    PENDING = "Pending"
    PROCESSING = "Processing"
    COMPLETED = "Completed"
    FAILED = "Failed"


class SubmissionRecord(BaseModel):
    submission_id: str
    user_id: str
    original_file_name: str
    presentation_title: str
    description: Optional[str] = None
    s3_file_key: str
    content_type: str
    file_size_bytes: int
    upload_date: str  # ISO 8601
    processing_status: ProcessingStatus = ProcessingStatus.PENDING
    completion_date: Optional[str] = None
    report_link: Optional[str] = None
    report_path: Optional[str] = None  # Written by agentic-evaluation module


class ErrorType(str, Enum):
    S3_WRITE_FAILURE = "S3_WRITE_FAILURE"
    DYNAMO_WRITE_FAILURE = "DYNAMO_WRITE_FAILURE"
    SQS_PUBLISH_FAILURE = "SQS_PUBLISH_FAILURE"
    S3_COMPENSATION_FAILURE = "S3_COMPENSATION_FAILURE"


class ErrorNotification(BaseModel):
    submission_id: Optional[str] = None
    error_type: ErrorType
    error_message: str
    timestamp: str  # ISO 8601
    service_component: str
    orphaned_s3_key: Optional[str] = None
