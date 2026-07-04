"""Cognito JWT auth for the terminal API (build-plan P1.7) — BUILT, default-OFF.

`user_from_header` is the resolver the FastAPI dependency wraps: when `GRAPHRAG_AUTH` is off (default) it
returns a fixed local user, so dev/tests never need a token; when on, it verifies a Cognito-issued JWT
(RS256; iss/aud/exp) against the pool's JWKS and returns the subject. Turning it on + provisioning the
Cognito user pool is a Phase-4 deploy step — nothing in serving requires a token until then."""
from __future__ import annotations

import os
from typing import Optional

LOCAL_USER = "local"


def auth_on() -> bool:
    return os.environ.get("GRAPHRAG_AUTH", "off").lower() not in ("", "off", "0", "false", "no")


def verify_token(token: str) -> str:
    """Verify a Cognito access/ID JWT -> subject. Raises on any failure (caller maps to 401). Imports PyJWT
    lazily so the dependency is import-free when auth is off (the default)."""
    import jwt                                                       # PyJWT
    from jwt import PyJWKClient
    region = os.environ["COGNITO_REGION"]
    pool = os.environ["COGNITO_USER_POOL_ID"]
    aud = os.environ.get("COGNITO_APP_CLIENT_ID")
    iss = f"https://cognito-idp.{region}.amazonaws.com/{pool}"
    signing_key = PyJWKClient(f"{iss}/.well-known/jwks.json").get_signing_key_from_jwt(token).key
    claims = jwt.decode(token, signing_key, algorithms=["RS256"], issuer=iss,
                        audience=aud, options={"verify_aud": aud is not None})
    return claims.get("sub") or claims.get("username") or LOCAL_USER


def user_from_header(authorization: Optional[str]) -> str:
    """Resolve the request's user id. Auth OFF -> LOCAL_USER (no token). Auth ON -> verified subject, or
    ValueError (missing/malformed/invalid token) which the route maps to HTTP 401."""
    if not auth_on():
        return LOCAL_USER
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ValueError("missing bearer token")
    return verify_token(authorization.split(" ", 1)[1].strip())
