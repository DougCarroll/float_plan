# Security

## Overview

Float Plan web app is intended to run behind a **Cloudflare tunnel** (like [anchor_watch](../anchor_watch)). This document describes app-level security, mitigations, and recommendations.

---

## Authentication and authorization

- **Flask-Login** — Session-based auth. **SECRET_KEY** can be set once in a `.env` file (sourced by `run_web.sh` and `start-service.sh`), or left unset: the app will then create `data/.flask_secret` on first run and reuse it so you never have to set it. For production you may still prefer an explicit `SECRET_KEY` in `.env`.
- **Roles** — **admin** (manage users), **crew** (vessels, crew, itinerary, PDF), **viewer** (not used for data; all data actions require crew or admin).
- **Protected routes**
  - **Login required:** `/`, `/vessels`, `/crew`, `/admin/users`, `/logout`, and all `/api/*` that read/write data.
  - **Admin only:** `/admin/users` (GET/POST).
  - **Crew or admin:** `/vessels`, `/crew`, `/api/vessels`, `/api/crew_members`, `POST /api/pdf`, and vessel/crew save/delete.
- **Passwords** — Stored with **passlib** (pbkdf2_sha256). Not logged.

---

## CSRF and headers

- **CSRF** — Flask-WTF **CSRFProtect** is enabled. All state-changing forms include `csrf_token()`. API calls from the main page (PDF generate, add vessel, add crew) send **X-CSRFToken** from the `<meta name="csrf-token">` value in the base template.
- **Security headers** (all responses): `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection: 1; mode=block`, `Referrer-Policy: strict-origin-when-cross-origin`.

---

## Path and input safety

- **User data paths** — Vessel and crew JSON files live under `data/users/<username>/`. The username comes from the **session** (`current_user.username`), not from the request. Paths are resolved and checked to stay under `data/users/`; if a username would escape (e.g. `..`), the resolved path is forced to a safe placeholder so no read/write occurs outside the users directory.
- **Username creation** — When an admin creates a user, the username is rejected if it contains `..`, `/`, or `\`.
- **Login redirect** — The `next` parameter is used only if it starts with `/` and **not** with `//`, avoiding open redirects to other hosts.
- **Vessel/crew data** — Save and API handlers only accept keys that exist in **DEFAULT_VESSEL** or **DEFAULT_PERSON**; no mass assignment of arbitrary keys. Indices are integers and bounds-checked.
- **SQL** — SQLAlchemy ORM is used for user and session data; no raw SQL with user input.

---

## Rate limiting

- **Default** — 200/day, 60/min per IP (Flask-Limiter).
- **Login** — 5 requests per minute per IP to reduce brute-force risk.

---

## XSS

- **Templates** — Jinja2 auto-escapes `{{ }}`. Delete confirmation forms use `| e` for names in `data-name` attributes.

---

## Secrets and config

- **SECRET_KEY** — Set via environment in production; do not commit. App logs a warning if default or unset.
- **Config** — `config.yaml` is in `.gitignore`; use `config.example.yaml` as a template.
- **Default user** — First run creates user `fp` (admin) with password from **FP_DEFAULT_PASSWORD** env or a default; change after first login if using the default.

---

## Cloudflare tunnel recommendations

1. **Restrict access** — Use [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/policies/access/) or similar so only allowed users can reach the app.
2. **Keep the tunnel URL private** if you do not use Access.
3. **HTTPS** — The tunnel provides HTTPS; the app does not need to handle TLS.

---

## Optional hardening

- **Stricter SECRET_KEY** — Exit on startup if SECRET_KEY is default (like anchor_watch) for production deployments.
- **Password policy** — Enforce minimum length or complexity when creating users.
- **Audit logging** — Log admin actions (user create/delete/role change) and optionally vessel/crew changes.
- **pip-audit** — Run `pip audit` (e.g. in `run_web.sh`) to check dependencies for known vulnerabilities.
