from pydantic import BaseModel


class SqsMessageBody(BaseModel):
    submission_id: str
    user_id: str
    s3_bucket: str
    s3_file_key: str
    original_file_name: str
    presentation_title: str
