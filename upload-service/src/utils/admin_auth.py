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

    # cognito:groups may come in several formats from API Gateway v2:
    # - A Python list: ["administrators"] (unlikely from APIGW, but handle it)
    # - A space-separated string: "administrators" or "administrators users"
    # - A bracketed string: "[administrators]" or "[administrators, users]"
    # - A JSON array string: '["administrators"]'
    groups_claim = claims.get("cognito:groups", "")

    if isinstance(groups_claim, list):
        groups = groups_claim
    elif isinstance(groups_claim, str):
        # Strip brackets if present (API Gateway v2 format)
        cleaned = groups_claim.strip()
        if cleaned.startswith("[") and cleaned.endswith("]"):
            cleaned = cleaned[1:-1]
        # Split by comma or space, strip whitespace from each
        if "," in cleaned:
            groups = [g.strip().strip('"').strip("'") for g in cleaned.split(",")]
        else:
            groups = cleaned.split() if cleaned else []
    else:
        groups = []

    if "administrators" not in groups:
        logger.info("User %s is not in administrators group", user_id)
        return (False, None)

    return (True, user_id)
