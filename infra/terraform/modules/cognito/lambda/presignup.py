"""Cognito pre-sign-up trigger — pass-through allow-list gate (Stage 5.2).

Deployed ALLOW-ALL: with ALLOWLIST_EMAILS empty (the default), every sign-up is auto-confirmed. To close
signups later, set ALLOWLIST_EMAILS to a comma-separated list on THIS Lambda (no pool/app change needed) —
any email not on the list is rejected. Fires for both native and federated (Google) sign-ups
(triggerSource PreSignUp_SignUp / PreSignUp_ExternalProvider).
"""
import os


def handler(event, context):
    allow = [e.strip().lower() for e in os.environ.get("ALLOWLIST_EMAILS", "").split(",") if e.strip()]
    email = (event.get("request", {}).get("userAttributes", {}).get("email") or "").lower()
    if allow and email not in allow:
        raise Exception("Sign-up is restricted; this email is not on the allow-list.")
    # Auto-confirm so federated (Google) + any native sign-ups don't hang awaiting verification.
    event["response"]["autoConfirmUser"] = True
    event["response"]["autoVerifyEmail"] = True
    return event
