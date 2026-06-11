"""Test configuration for the Preparation Workflow.

Configures Hypothesis settings profiles and shared pytest fixtures.
"""

import os

from hypothesis import HealthCheck, settings

# Register Hypothesis settings profiles
settings.register_profile(
    "default",
    max_examples=100,
    deadline=500,
)

settings.register_profile(
    "ci",
    max_examples=200,
    deadline=1000,
    suppress_health_check=[HealthCheck.too_slow],
)

settings.register_profile(
    "dev",
    max_examples=10,
    deadline=None,
)

# Load the appropriate profile based on environment variable
settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "default"))

# Set dummy AWS credentials for moto
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SECURITY_TOKEN", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
