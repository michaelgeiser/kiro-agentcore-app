"""Admin authorization helper for verifying administrator group membership."""

import logging

logger = logging.getLogger(__name__)


def verify_admin(event: dict) -> tuple[bool, str | None]:
    """Extract and verify administrator group membership from JWT claims.

    Checks the cognito:groups claim in the API Gateway v2 JWT authorizer
    context for "administrators" group membership. This provides defense
    in depth on top of the API Gateway JWT authorizer.

    Non-admin access is unrecoverable — returns (False, None) immediately
    without retry.

    Args:
        event: API Gateway v2 event with requestContext.authorizer.jwt.claims

    Returns:
        (True, user_id) if the caller is an administrator.
        (False, None) if not an administrator or claims are missing/malformed.
    """
    try:
        claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    except (KeyError, TypeError):
        logger.warning("Missing or malformed JWT claims in event")
        return (False, None)

    # Extract user_id from sub claim
    user_id = claims.get("sub")
    if not user_id:
        logger.warning("JWT claims missing 'sub' claim")
        return (False, None)

    # cognito:groups may be a space-separated string or a list
    groups_claim = claims.get("cognito:groups", "")

    if isinstance(groups_claim, list):
        groups = groups_claim
    elif isinstance(groups_claim, str):
        groups = groups_claim.split() if groups_claim else []
    else:
        groups = []

    if "administrators" not in groups:
        logger.info("User %s is not in administrators group", user_id)
        return (False, None)

    return (True, user_id)
