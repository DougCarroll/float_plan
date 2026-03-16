# Security

## Overview

Float Plan web app is intended to run behind a **Cloudflare tunnel** (e.g. cloudflared). This document describes app-level security, mitigations, and a summary of the security review.

---

## Authentication and authorization

- **Flask-Login** — Session-based auth. **SECRET_KEY** can be set in a `.env` file (sourced by `run_web.sh` and `start-service.sh`), or left unset: the app creates `data/.flask_secret` on first run and reuses it.
- **Roles** — **admin** (manage users), **crew** (vessels, crew, PDF), **viewer** (read-only; data actions require crew or admin).
- **Public (no login required)**  
  - **`/`** — Plan page (anyone can fill form, save/open .floatplan, generate PDF, view summary).  
  - **`GET /api/vessels`**, **`GET /api/crew_members`** — Return empty lists when not logged in.  
  - **`GET /api/options`**, **`GET /api/rescue_authorities`** — Public (dropdown data).  
  - **`POST /api/pdf`**, **`POST /api/summary`** — Public (rate-limited by default limits).
- **Login required**  
  - **`/logout`**, **`/vessels`**, **`/crew`**, **`/admin/users`**, and all vessel/crew create/edit/delete (forms and APIs).
- **Admin only:** **`/admin/users`** (GET/POST).
- **Crew or admin:** **`/vessels`**, **`/crew`**, **`/api/vessels`** (POST), **`/api/crew_members`** (POST), and vessel/crew save/delete. Viewers cannot persist vessels/crew on the server.
- **Passwords** — Stored with **passlib** (pbkdf2_sha256). Not logged.

---

## CSRF and headers

- **CSRF** — Flask-WTF **CSRFProtect** is enabled. State-changing forms use `csrf_token()`. API calls from the plan page send **X-CSRFToken** from `<meta name="csrf-token">`.
- **Security headers** (all responses): `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection: 1; mode=block`, `Referrer-Policy: strict-origin-when-cross-origin`.
- **CORS** — `Access-Control-Allow-Origin` is set to a specific origin (e.g. `https://svburnttoast.com`). Change or remove if the app is served from another domain.

---

## Path and input safety

- **User data paths** — Vessel and crew JSON files live under `data/users/<username>/`. The username comes from the **session** (`current_user.username`), not from the request. Paths are resolved and checked to stay under `data/users/`; if a username would escape (e.g. `..`), the resolved path is forced to a safe placeholder (`_invalid`).
- **Username creation** — When an admin creates a user, the username is rejected if it contains `..`, `/`, or `\`, or if it exceeds 80 characters (matches DB and limits path length).
- **Login redirect** — The `next` parameter is used only if it is a relative path: starts with `/`, does not contain `//`, and contains no `\n` or `\r` (avoids open redirects and header injection).
- **Vessel/crew data** — Save and API handlers only accept keys that exist in **DEFAULT_VESSEL** or **DEFAULT_PERSON**; no mass assignment. Indices are integers and bounds-checked.
- **SQL** — SQLAlchemy ORM is used for user data; no raw SQL with user input.
- **Request size** — **MAX_CONTENT_LENGTH** is set (4 MB) to limit JSON body size for PDF/summary APIs. Oversized requests receive 413; API responses use JSON.

---

## Rate limiting

- **Default** — 200/day, 60/min per IP (Flask-Limiter).
- **Login** — 5 requests per minute per IP to reduce brute-force risk.

---

## Error handling

- **API 500 responses** — PDF and summary APIs log the real exception and return a generic message (`"PDF generation failed"` / `"Summary generation failed"`) so stack traces and paths are not leaked to clients.

---

## XSS

- **Templates** — Jinja2 auto-escapes `{{ }}`. Delete confirmation forms use `| e` for names in `data-name` / `data-username` attributes.
- **Client-side** — Plan page uses `escapeAttr` / `escapeHtml` when rendering itinerary and options into the DOM.

---

## Session cookies

- **SESSION_COOKIE_HTTPONLY** — True (script cannot read session cookie).
- **SESSION_COOKIE_SAMESITE** — Lax (reduces CSRF from cross-site requests).
- **SESSION_COOKIE_SECURE** — Set to True when **PREFER_HTTPS** env is `1`, `true`, or `yes` (cookie sent only over HTTPS). Enable in production when the app is behind HTTPS (e.g. Cloudflare tunnel).

---

## Secrets and config

- **SECRET_KEY** — Set via environment in production; do not commit. If unset or obviously default, the app may create/reuse `data/.flask_secret`.
- **Config** — `config.yaml` is in `.gitignore`; use `config.example.yaml` as a template if present.
- **Default user** — First run creates user `fp` (admin) with password from **FP_DEFAULT_PASSWORD** env or a default; change after first login if using the default.

---

## Cloudflare tunnel recommendations

1. **Restrict access** — Use [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/policies/access/) or similar so only allowed users can reach the app.
2. **Keep the tunnel URL private** if you do not use Access.
3. **HTTPS** — The tunnel provides HTTPS; the app does not need to handle TLS.

---

## Security review summary

- **Auth** — Session-based; roles enforced; public routes limited to plan page and read/PDF/summary APIs.
- **CSRF** — Enabled; token used for forms and API calls from the plan page.
- **Paths** — User data under `data/users/<username>/` with resolve/relative_to and safe username validation.
- **Redirects** — Login `next` restricted to relative path, no `//`, no CR/LF.
- **Input** — Vessel/crew keys restricted to schema; indices bounds-checked; no raw SQL.
- **Headers** — Nosniff, frame options, XSS filter, referrer policy; CORS set to a single origin.
- **Rate limiting** — Global and login-specific limits.
- **DoS** — MAX_CONTENT_LENGTH and 413 handler for APIs; exceptions not echoed in 500 responses.
- **XSS** — Escaping in templates and in client-side rendering.

---

## Security check (latest)

| Area | Status |
|------|--------|
| Auth & roles | Session-based; public routes: `/`, GET api/vessels, GET api/crew_members, api/options, api/rescue_authorities, POST api/pdf, POST api/summary. Rest require login and/or crew/admin. |
| CSRF | CSRFProtect on; forms and API use token. |
| Paths | `data/users/<username>/` with resolve/relative_to; username validated (no `..`, `/`, `\`, max 80 chars). |
| Login redirect | `next` allowed only relative path, no `//`, no `\n`/`\r`. |
| Input | Vessel/crew keys restricted to DEFAULT_*; indices bounds-checked; ORM only. |
| Headers | X-Content-Type-Options, X-Frame-Options, X-XSS-Protection, Referrer-Policy; CORS single origin. |
| Rate limit | 200/day, 60/min; login 5/min. |
| DoS | MAX_CONTENT_LENGTH 4 MB; 413 handler; 500 responses generic. |
| XSS | Jinja auto-escape; `\| e` in delete forms; client escapeAttr/escapeHtml. |
| Session | HttpOnly, SameSite=Lax; Secure when PREFER_HTTPS set. |
| Passwords | pbkdf2_sha256; not logged. |

---

## Optional hardening

- **Stricter SECRET_KEY** — Exit on startup if SECRET_KEY is default for production.
- **Password policy** — Enforce minimum length or complexity when creating users.
- **Audit logging** — Log admin actions (user create/delete/role change) and optionally vessel/crew changes.
- **pip-audit** — Run `pip audit` (e.g. in `run_web.sh`) to check dependencies for known vulnerabilities.
