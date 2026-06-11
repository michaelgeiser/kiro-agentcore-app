"""S3 service for presigned URL generation and object management."""

import os

import boto3


class S3Service:
    """Service for interacting with S3 bucket operations."""

    def __init__(self) -> None:
        self._client = boto3.client("s3")
        self._bucket_name = os.environ["S3_BUCKET_NAME"]

    def generate_presigned_upload_url(
        self, file_key: str, content_type: str, expires_in_seconds: int = 3600
    ) -> str:
        """Generate a presigned PUT URL for client-side upload.

        Args:
            file_key: The S3 object key for the upload.
            content_type: The MIME type of the file being uploaded.
            expires_in_seconds: URL expiration time in seconds (default: 3600).

        Returns:
            A presigned URL string for uploading the file via HTTP PUT.
        """
        url: str = self._client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": self._bucket_name,
                "Key": file_key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_in_seconds,
        )
        return url

    def delete_object(self, file_key: str) -> None:
        """Delete an object from S3 (compensating action).

        Args:
            file_key: The S3 object key to delete.
        """
        self._client.delete_object(
            Bucket=self._bucket_name,
            Key=file_key,
        )
