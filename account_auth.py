"""Sign-in boundary for the hosted fantasy advisor."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from typing import Any

import streamlit as st


def _development_login_allowed() -> bool:
    return (
        os.getenv("APP_ENV", "production").strip().lower() == "development"
        and os.getenv("ALLOW_SINGLE_USER_DEV", "0").strip() == "1"
    )


def _auth_settings() -> dict[str, Any]:
    try:
        value = st.secrets.get("auth", {})
    except Exception:
        return {}
    return value if isinstance(value, Mapping) else {}


def _provider_settings(auth: dict[str, Any]) -> list[dict[str, Any]]:
    providers = []
    if auth.get("client_id") and auth.get("client_secret") and auth.get("server_metadata_url"):
        providers.append(auth)
    for value in auth.values():
        if isinstance(value, Mapping) and value.get("client_id") and value.get("client_secret") and value.get("server_metadata_url"):
            providers.append(value)
    return providers


def oidc_is_configured() -> bool:
    auth = _auth_settings()
    return bool(auth.get("redirect_uri") and auth.get("cookie_secret") and _provider_settings(auth))


def require_user_id() -> str:
    """Require an OIDC identity, except for explicitly enabled localhost development."""
    if _development_login_allowed():
        return hashlib.sha256(b"fantasy-advisor-local-development").hexdigest()

    user = getattr(st, "user", None)
    is_logged_in = bool(getattr(user, "is_logged_in", False))
    if not is_logged_in:
        if oidc_is_configured():
            st.button("Sign in", on_click=st.login)
        else:
            st.error(
                "Sign-in is not configured. Add an OpenID Connect provider to Streamlit secrets before enabling user accounts."
            )
        st.stop()

    try:
        claims = user.to_dict()
    except AttributeError:
        claims = dict(user)
    subject = claims.get("sub")
    issuer = claims.get("iss")
    if not issuer:
        providers = _provider_settings(_auth_settings())
        issuer = providers[0].get("server_metadata_url") if len(providers) == 1 else None
    if not issuer or not subject:
        raise RuntimeError("The sign-in provider must return stable issuer and subject claims.")

    identity = f"{issuer}\0{subject}".encode("utf-8")
    return hashlib.sha256(identity).hexdigest()
