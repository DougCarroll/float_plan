"""Authentik OIDC login for Float Plan."""
from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

from authlib.integrations.flask_client import OAuth
from flask import Flask, current_app, flash, redirect, request, session, url_for
from flask_login import current_user, login_user
from werkzeug.wrappers import Response

DEFAULT_GROUP_ADMINS = "boat-admins"
DEFAULT_GROUP_CREW = "boat-crew"
DEFAULT_GROUP_VIEWERS = "boat-viewers"
DEFAULT_GROUP_PENDING = "boat-pending"

oauth = OAuth()


@dataclass(frozen=True)
class OidcSettings:
    enabled: bool
    client_id: str
    client_secret: str
    issuer: str
    redirect_uri: str
    enrollment_url: str
    group_admins: str
    group_crew: str
    group_viewers: str
    group_pending: str
    break_glass_enabled: bool
    break_glass_username: str
    break_glass_password: str


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _load_yaml_config() -> dict[str, Any]:
    config_path = Path(__file__).resolve().parent / "config.yaml"
    if not config_path.is_file():
        return {}
    import yaml

    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


def load_oidc_settings(config: dict[str, Any] | None = None) -> OidcSettings:
    cfg = config if config is not None else _load_yaml_config()
    web = cfg.get("web") or {}
    public_base = str(
        web.get("public_base_url") or web.get("base_url") or ""
    ).strip().rstrip("/")
    redirect_uri = str(os.environ.get("OIDC_REDIRECT_URI") or "").strip()
    if not redirect_uri and public_base:
        redirect_uri = f"{public_base}/oidc/callback"
    issuer = str(os.environ.get("OIDC_ISSUER") or "").strip()
    if issuer and not issuer.endswith("/"):
        issuer += "/"
    enrollment = str(os.environ.get("OIDC_ENROLLMENT_URL") or "").strip()
    if not enrollment and issuer:
        parsed = urlparse(issuer.replace("/application/o/", "/if/user/"))
        enrollment = f"{parsed.scheme}://{parsed.netloc}/if/user/login/"
    return OidcSettings(
        enabled=_env_truthy("OIDC_ENABLED"),
        client_id=str(os.environ.get("OIDC_CLIENT_ID") or "").strip(),
        client_secret=str(os.environ.get("OIDC_CLIENT_SECRET") or "").strip(),
        issuer=issuer,
        redirect_uri=redirect_uri,
        enrollment_url=enrollment,
        group_admins=str(os.environ.get("OIDC_GROUP_ADMINS") or DEFAULT_GROUP_ADMINS).strip(),
        group_crew=str(os.environ.get("OIDC_GROUP_CREW") or DEFAULT_GROUP_CREW).strip(),
        group_viewers=str(os.environ.get("OIDC_GROUP_VIEWERS") or DEFAULT_GROUP_VIEWERS).strip(),
        group_pending=str(os.environ.get("OIDC_GROUP_PENDING") or DEFAULT_GROUP_PENDING).strip(),
        break_glass_enabled=_env_truthy("BREAK_GLASS_ENABLED"),
        break_glass_username=str(os.environ.get("BREAK_GLASS_USERNAME") or "breakglass").strip(),
        break_glass_password=str(os.environ.get("BREAK_GLASS_PASSWORD") or "").strip(),
    )


def _oidc_server_metadata(issuer: str) -> dict[str, Any]:
    """Load Authentik metadata and rewrite endpoints to match OIDC_ISSUER (offline mode)."""
    metadata_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        with urlopen(metadata_url, timeout=15) as resp:
            meta = json.load(resp)
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to load OIDC metadata from {metadata_url}") from exc

    parsed = urlparse(issuer)
    base = f"{parsed.scheme}://{parsed.netloc}"

    def _fix(url: str) -> str:
        part = urlparse(url)
        if not part.path:
            return url
        fixed = f"{base}{part.path}"
        if part.query:
            fixed = f"{fixed}?{part.query}"
        return fixed

    for key, val in list(meta.items()):
        if isinstance(val, str) and val.startswith(("http://", "https://")):
            meta[key] = _fix(val)
    meta["issuer"] = issuer if issuer.endswith("/") else f"{issuer}/"
    return meta


def init_oidc(app: Flask, settings: OidcSettings) -> None:
    if not settings.enabled:
        return
    if not all([settings.client_id, settings.client_secret, settings.issuer, settings.redirect_uri]):
        raise RuntimeError(
            "OIDC_ENABLED=1 requires OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, OIDC_ISSUER, "
            "and OIDC_REDIRECT_URI (or web.base_url / web.public_base_url in config.yaml)."
        )
    oauth.init_app(app)
    meta = _oidc_server_metadata(settings.issuer)
    oauth.register(
        name="authentik",
        client_id=settings.client_id,
        client_secret=settings.client_secret,
        authorize_url=meta["authorization_endpoint"],
        access_token_url=meta["token_endpoint"],
        userinfo_endpoint=meta.get("userinfo_endpoint"),
        jwks_uri=meta.get("jwks_uri"),
        client_kwargs={"scope": "openid profile email"},
    )


def _groups_from_claims(claims: dict[str, Any]) -> set[str]:
    raw = claims.get("groups") or claims.get("ak_groups") or []
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {str(item) for item in raw if item}
    return set()


def map_authentik_groups(settings: OidcSettings, group_names: set[str]) -> str:
    if settings.group_admins in group_names:
        return "admin"
    if settings.group_crew in group_names:
        return "crew"
    if settings.group_viewers in group_names:
        return "viewer"
    if settings.group_pending in group_names:
        return "pending"
    return "pending"


def _username_from_claims(claims: dict[str, Any]) -> str:
    for key in ("preferred_username", "nickname", "email", "sub"):
        value = str(claims.get(key) or "").strip()
        if value:
            if key == "email" and "@" in value:
                return value.split("@", 1)[0]
            return value[:80]
    return "user"


def _session_lifetime_for_group(group: str) -> timedelta:
    if group == "admin":
        return timedelta(days=1)
    return timedelta(days=7)


def upsert_user_from_oidc(settings: OidcSettings, claims: dict[str, Any]):
    from web_app import User, db

    sub = str(claims.get("sub") or "").strip()
    username = _username_from_claims(claims)
    groups = _groups_from_claims(claims)
    group = map_authentik_groups(settings, groups)

    user = None
    if sub:
        user = User.query.filter_by(authentik_sub=sub).first()
    if user is None:
        user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, group=group)
        user.set_password(secrets.token_urlsafe(32))
        db.session.add(user)
    else:
        user.username = username
        user.group = group
    if sub:
        user.authentik_sub = sub
    db.session.commit()
    return user


def _safe_next_url() -> str | None:
    nxt = (request.args.get("next") or session.pop("oidc_next", None) or "").strip()
    if nxt and nxt.startswith("/") and not nxt.startswith("//"):
        return nxt
    return None


def _login_flask_user(user, *, remember: bool = True) -> None:
    session.permanent = True
    current_app.permanent_session_lifetime = _session_lifetime_for_group(
        str(getattr(user, "group", "") or "crew")
    )
    login_user(user, remember=remember)


def register_oidc_routes(
    app: Flask,
    *,
    settings: OidcSettings,
    limit_login: str,
    limiter: Any,
) -> None:
    if not settings.enabled:
        return

    @app.route("/oidc/login")
    def oidc_login_start() -> Response:
        if current_user.is_authenticated:
            group = getattr(current_user, "group", None)
            if group == "pending":
                return redirect(url_for("pending_approval"))
            return redirect(url_for("index"))
        nxt = _safe_next_url()
        if nxt:
            session["oidc_next"] = nxt
        return oauth.authentik.authorize_redirect(settings.redirect_uri)

    @app.route("/oidc/callback")
    def oidc_callback() -> Response:
        try:
            token = oauth.authentik.authorize_access_token()
        except Exception:
            flash("Sign-in with Authentik failed.", "error")
            return redirect(url_for("login"))
        claims = token.get("userinfo") if isinstance(token, dict) else None
        if not isinstance(claims, dict):
            try:
                claims = oauth.authentik.parse_id_token(token, None)
            except Exception:
                claims = {}
        if not isinstance(claims, dict):
            flash("Authentik did not return user information.", "error")
            return redirect(url_for("login"))

        user = upsert_user_from_oidc(settings, claims)
        if user.group == "pending":
            flash(
                "Your account is waiting for admin approval in Authentik.",
                "info",
            )
            return redirect(url_for("pending_approval"))

        _login_flask_user(user)
        nxt = _safe_next_url()
        return redirect(nxt or url_for("index"))


def break_glass_login(settings: OidcSettings, username: str, password: str):
    from web_app import User, db

    if not settings.break_glass_enabled:
        return None
    if username != settings.break_glass_username:
        return None
    if not settings.break_glass_password or password != settings.break_glass_password:
        return None
    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, group="admin")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
    elif user.group != "admin":
        user.group = "admin"
        db.session.commit()
    return user


def oidc_logout_redirect(settings: OidcSettings, post_logout_url: str) -> str | None:
    if not settings.enabled or not settings.issuer:
        return None
    end_session = f"{settings.issuer}end-session/"
    query = urlencode({"post_logout_redirect_uri": post_logout_url})
    return f"{end_session}?{query}"


def authentik_admin_url(settings: OidcSettings) -> str:
    if not settings.issuer:
        return ""
    parsed = urlparse(settings.issuer)
    return f"{parsed.scheme}://{parsed.netloc}/if/admin/"


def authentik_user_url(settings: OidcSettings) -> str:
    """End-user portal (profile, password, MFA). Override with OIDC_USER_SETTINGS_URL if needed."""
    custom = str(os.environ.get("OIDC_USER_SETTINGS_URL") or "").strip()
    if custom:
        return custom
    if not settings.issuer:
        return ""
    parsed = urlparse(settings.issuer)
    return f"{parsed.scheme}://{parsed.netloc}/if/user/"


def user_manages_local_credentials(settings: OidcSettings, user) -> bool:
    """True when password/email are managed in the app (local or break-glass), not Authentik."""
    if not settings.enabled:
        return True
    return not getattr(user, "authentik_sub", None)
