"""Property test for video processing decision.

Property 4: Video Processing Decision
Validates: Requirements 2.3, 2.4

For any file classification result and feature flag state, the processing
decision function SHALL: (a) proceed to embedding when the file is audio
regardless of flag state, (b) proceed to audio extraction when the file is
video and the flag is enabled, and (c) fail with a descriptive reason when
the file is video and the flag is disabled.
"""

import pytest
from hypothesis import given, settings
from hypothesis.strategies import sampled_from, booleans

from handlers.validate_format import make_processing_decision


@pytest.mark.property
@settings(max_examples=100, deadline=500)
@given(
    file_type=sampled_from(["audio", "video"]),
    video_processing_enabled=booleans(),
)
def test_video_processing_decision(
    file_type: str, video_processing_enabled: bool
) -> None:
    """**Validates: Requirements 2.3, 2.4**

    For any combination of file_type and video_processing_enabled flag,
    the processing decision SHALL be correct:
    - audio + any flag → decision="embed"
    - video + flag=True → decision="extract_audio"
    - video + flag=False → decision="fail" with reason containing "not currently enabled"
    """
    result = make_processing_decision(file_type, video_processing_enabled)

    assert "decision" in result
    assert "reason" in result

    if file_type == "audio":
        assert result["decision"] == "embed"
    elif file_type == "video" and video_processing_enabled:
        assert result["decision"] == "extract_audio"
    elif file_type == "video" and not video_processing_enabled:
        assert result["decision"] == "fail"
        assert "not currently enabled" in result["reason"]
