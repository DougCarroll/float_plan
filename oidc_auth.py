"""Authentik OIDC login for Float Plan."""
from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

import requests

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


def _oidc_metadata_url(issuer: str) -> str:
    """Prefer local Authentik for discovery when the boat runs with public issuer URLs."""
    issuer_path = urlparse(issuer).path.rstrip("/")
    internal = str(os.environ.get("AUTHENTIK_INTERNAL_URL") or "").strip().rstrip("/")
    if internal and issuer_path:
        return f"{internal}{issuer_path}/.well-known/openid-configuration"
    return f"{issuer.rstrip('/')}/.well-known/openid-configuration"


def _load_oidc_metadata_json(metadata_url: str) -> dict[str, Any]:
    parsed = urlparse(metadata_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError(f"Invalid OIDC metadata URL: {metadata_url}")
    try:
        resp = requests.get(metadata_url, timeout=15)
        resp.raise_for_status()
        meta = resp.json()
    except (requests.RequestException, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Failed to load OIDC metadata from {metadata_url}") from exc
    if not isinstance(meta, dict):
        raise RuntimeError(f"OIDC metadata from {metadata_url} is not a JSON object")
    return meta


def _oidc_server_metadata(issuer: str) -> dict[str, Any]:
    """Load Authentik metadata and rewrite endpoints to match OIDC_ISSUER."""
    metadata_url = _oidc_metadata_url(issuer)
    meta = _load_oidc_metadata_json(metadata_url)

    parsed = urlparse(issuer)
    public_base = f"{parsed.scheme}://{parsed.netloc}"

    def _to_public(url: str) -> str:
        part = urlparse(url)
        if not part.path:
            return url
        fixed = f"{public_base}{part.path}"
        if part.query:
            fixed = f"{fixed}?{part.query}"
        return fixed

    meta["issuer"] = issuer if issuer.endswith("/") else f"{issuer}/"
    for key, val in list(meta.items()):
        if isinstance(val, str) and val.startswith(("http://", "https://")):
            meta[key] = _to_public(val)
    return meta


def _login_after_oidc_failure() -> Response:
    """Break /login → /oidc/login loops when the OAuth callback fails."""
    return redirect(url_for("login", local=1))


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


def _login_flask_user(user, *, remember: bool = False) -> None:
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
            return _login_after_oidc_failure()
        claims = token.get("userinfo") if isinstance(token, dict) else None
        if not isinstance(claims, dict):
            try:
                claims = oauth.authentik.parse_id_token(token, None)
            except Exception:
                claims = {}
        if not isinstance(claims, dict):
            flash("Authentik did not return user information.", "error")
            return _login_after_oidc_failure()

        user = upsert_user_from_oidc(settings, claims)
        if user.group == "pending":
            flash(
                "Your account is waiting for admin approval in Authentik.",
                "info",
            )
            return redirect(url_for("pending_approval"))

        _login_flask_user(user)
        stash_oidc_id_token(token, settings)
        nxt = _safe_next_url()
        return redirect(nxt or url_for("index"))
    @app.route("/oidc/logout/done")
    def oidc_logout_done() -> Response:
        return redirect(url_for("login", local=1))



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



def _b64url_json(segment: str) -> dict[str, Any]:
    padding = "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(segment + padding))


def id_token_hint_usable(id_token: str | None, settings: OidcSettings | None = None) -> bool:
    """Authentik end-session only accepts signed JWTs, not encrypted JWE (5 segments)."""
    token = str(id_token or "").strip()
    if not token:
        return False
    parts = token.split(".")
    if len(parts) != 3:
        return False
    try:
        header = _b64url_json(parts[0])
        if header.get("enc"):
            return False
    except (ValueError, json.JSONDecodeError, TypeError):
        return False
    return True


def stash_oidc_id_token(token: dict[str, Any] | None, settings: OidcSettings) -> None:
    if not isinstance(token, dict):
        return
    id_token = str(token.get("id_token") or "").strip()
    if id_token and id_token_hint_usable(id_token, settings):
        session["oidc_id_token"] = id_token
        session.modified = True


def oidc_logout_params(
    settings: OidcSettings,
    post_logout_url: str,
    *,
    id_token_hint: str | None = None,
) -> dict[str, str] | None:
    if not settings.enabled or not settings.issuer:
        return None
    params: dict[str, str] = {}
    if settings.client_id:
        params["client_id"] = settings.client_id
    if id_token_hint and id_token_hint_usable(id_token_hint, settings):
        params["id_token_hint"] = id_token_hint
        params["post_logout_redirect_uri"] = post_logout_url
    return params or None


def oidc_logout_redirect(
    settings: OidcSettings,
    post_logout_url: str,
    *,
    id_token_hint: str | None = None,
) -> str | None:
    params = oidc_logout_params(settings, post_logout_url, id_token_hint=id_token_hint)
    if not params:
        return None
    end_session = f"{settings.issuer.rstrip('/')}/end-session/"
    return f"{end_session}?{urlencode(params)}"


_MAX_LOGOUT_GET_URL_LEN = 1800
_MAX_LOGOUT_GET_ID_TOKEN_LEN = 400


def _app_display_name() -> str:
    doc = (__doc__ or "").strip()
    prefix = "Authentik OIDC login for "
    if doc.startswith(prefix):
        return doc[len(prefix) :].rstrip(".")
    return "application"


def oidc_logout_completion_response(
    settings: OidcSettings,
    post_logout_url: str,
    *,
    id_token_hint: str | None = None,
) -> Response:
    import html

    params = oidc_logout_params(settings, post_logout_url, id_token_hint=id_token_hint)
    if not settings.issuer or not params:
        return redirect(post_logout_url or url_for("index"))
    end_session = f"{settings.issuer.rstrip('/')}/end-session/"
    login_url = html.escape(_app_login_url(settings), quote=True)
    app_name = html.escape(_app_display_name())
    inputs = "".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">'
        for k, v in params.items()
    )
    action = html.escape(end_session, quote=True)
    body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Signing out…</title></head>
<body>
  <p>Signing out…</p>
  <form id="logout" method="get" action="{action}">{inputs}</form>
  <p><a href="{login_url}">Return to {app_name}</a></p>
  <script>document.getElementById("logout").submit();</script>
</body>
</html>"""
    from flask import make_response

    return apply_logout_cookies(make_response(body))


def apply_logout_cookies(response: Response) -> Response:
    """Clear remember-me on the logout response (must run after logout_user())."""
    current_app.login_manager._clear_cookie(response)
    return response


def clear_app_session_after_logout() -> None:
    """Remove OIDC/app keys without undoing Flask-Login's remember-me clear marker."""
    for key in ("oidc_id_token", "oidc_next"):
        session.pop(key, None)


def _app_home_from_redirect(settings: OidcSettings) -> str:
    parsed = urlparse(settings.redirect_uri)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/"
    return url_for("index", _external=True)


def _app_login_url(settings: OidcSettings) -> str:
    parsed = urlparse(settings.redirect_uri)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/login?local=1"
    return url_for("login", local=1, _external=True)


def oidc_post_logout_url(settings: OidcSettings) -> str:
    """App home URL registered with Authentik (derived from OIDC redirect_uri)."""
    return _app_home_from_redirect(settings)


def oidc_post_logout_uri(request, settings: OidcSettings) -> str:
    """Post-logout redirect registered with Authentik (/oidc/logout/done on request host)."""
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or ""
    ).strip()
    if not host:
        return f"{_app_home_from_redirect(settings).rstrip('/')}/oidc/logout/done"

    redirect_parsed = urlparse(settings.redirect_uri)
    redirect_host = (redirect_parsed.netloc or "").lower()
    host_only = host.split(":")[0].lower()
    if redirect_host:
        allowed = {redirect_host, redirect_host.split(":")[0]}
        if host.lower() not in allowed and host_only not in allowed:
            return f"{_app_home_from_redirect(settings).rstrip('/')}/oidc/logout/done"

    proto = (
        request.headers.get("x-forwarded-proto") or redirect_parsed.scheme or "https"
    ).split(",")[0].strip()
    return f"{proto}://{host}/oidc/logout/done"


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
