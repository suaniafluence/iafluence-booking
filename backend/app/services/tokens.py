import secrets


def new_token() -> str:
    """256-bit random, URL-safe, unpredictable booking token (§22)."""
    return secrets.token_urlsafe(32)
