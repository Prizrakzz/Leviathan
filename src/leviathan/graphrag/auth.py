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


def _verified_claims(token: str) -> dict:
    """Verify a Cognito ID/access JWT -> its claims dict. Raises ValueError on ANY failure — malformed
    token, bad signature, wrong issuer/audience, expiry, or JWKS-fetch error — so the caller maps every
    failure to a clean 401 (never a 500). Imports PyJWT lazily so the dependency is import-free when auth
    is off."""
    try:
        import jwt  # PyJWT
        from jwt import PyJWKClient
        region = os.environ["COGNITO_REGION"]
        pool = os.environ["COGNITO_USER_POOL_ID"]
        aud = os.environ.get("COGNITO_APP_CLIENT_ID")
        iss = f"https://cognito-idp.{region}.amazonaws.com/{pool}"
        signing_key = PyJWKClient(f"{iss}/.well-known/jwks.json").get_signing_key_from_jwt(token).key
        return jwt.decode(token, signing_key, algorithms=["RS256"], issuer=iss,
                          audience=aud, options={"verify_aud": aud is not None})
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001 — any verification failure is a 401 (fail-closed)
        raise ValueError(f"invalid token: {type(e).__name__}")


def _claims_subject(claims: dict) -> str:
    return claims.get("sub") or claims.get("username") or LOCAL_USER


def verify_token(token: str) -> str:
    """Verify a Cognito ID/access JWT -> subject (unchanged contract; see `_verified_claims`)."""
    return _claims_subject(_verified_claims(token))


def user_from_header(authorization: Optional[str]) -> str:
    """Resolve the request's user id. Auth OFF -> LOCAL_USER (no token). Auth ON -> verified subject, or
    ValueError (missing/malformed/invalid token) which the route maps to HTTP 401. Routes through
    `verify_token` (the seam tests stub)."""
    if not auth_on():
        return LOCAL_USER
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ValueError("missing bearer token")
    return verify_token(authorization.split(" ", 1)[1].strip())


def identity_from_header(authorization: Optional[str]) -> dict:
    """Resolve the request's identity: {sub} plus whichever of email/name/picture the ID token carries
    (name claims flow only after the Cognito Google-IdP attribute_mapping ships AND the user's next
    sign-in). Auth OFF -> {sub: LOCAL_USER}. Raises ValueError like `user_from_header`."""
    if not auth_on():
        return {"sub": LOCAL_USER}
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ValueError("missing bearer token")
    claims = _verified_claims(authorization.split(" ", 1)[1].strip())
    ident = {"sub": _claims_subject(claims)}
    for k in ("email", "name", "given_name", "picture"):
        if claims.get(k):
            ident[k] = claims[k]
    return ident
