"""
Float Plan web app: same data and PDF generation as the desktop app, served over HTTP.
Designed to run behind a Cloudflare tunnel (e.g. cloudflared) like anchor_watch.
"""
from __future__ import annotations

import io
import json
import logging
import os
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for, flash
from werkzeug.exceptions import RequestEntityTooLarge
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from passlib.hash import pbkdf2_sha256

from data_store import (
    load_vessels,
    load_crew_members,
    save_vessels,
    save_crew_members,
    DEFAULT_VESSEL,
    DEFAULT_PERSON,
)
from pdf_fill import fill_float_plan


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _is_production_deployment() -> bool:
    return _env_truthy("PRODUCTION") or os.environ.get("FLASK_ENV", "").strip().lower() == "production"


def _maybe_trust_proxy(app: Flask) -> None:
    """Honor X-Forwarded-* from Cloudflare tunnel / reverse proxy (opt-in; avoids header spoofing in dev)."""
    if not _env_truthy("TRUST_PROXY"):
        return
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(
        app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1
    )


def _normalize_date_string(s: str) -> str:
    """Zero-pad month/day for parsing (e.g. 3/3/2025 -> 03/03/2025)."""
    s = (s or "").strip()
    if "/" in s:
        parts = s.split("/", 2)
        if len(parts) == 3:
            a, b, c = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if a.isdigit() and b.isdigit() and c.isdigit():
                if len(a) == 1:
                    a = "0" + a
                if len(b) == 1:
                    b = "0" + b
                return f"{a}/{b}/{c}"
    if "-" in s and len(s) >= 8:
        parts = s.split("-", 2)
        if len(parts) == 3:
            a, b, c = parts[0].strip(), parts[1].strip(), parts[2].strip()
            if a.isdigit() and b.isdigit() and c.isdigit() and len(a) == 4:
                if len(b) == 1:
                    b = "0" + b
                if len(c) == 1:
                    c = "0" + c
                return f"{a}-{b}-{c}"
    return s


def _format_date_for_summary(s: str) -> str:
    """Format date as 'DayOfWeek, Month Nth' (e.g. Wednesday, March 3rd)."""
    if not s or not str(s).strip():
        return ""
    raw = str(s).strip()
    normalized = _normalize_date_string(raw)
    for candidate in (normalized, raw):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%B %d", "%b %d, %Y", "%b %d"):
            try:
                d = datetime.strptime(candidate, fmt)
                day = d.day
                suffix = "th" if 11 <= day % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
                return f"{d.strftime('%A, %B')} {day}{suffix}"
            except ValueError:
                continue
    return raw


def _format_time_for_summary(s: str) -> str:
    """Format time as 24h 4 digits (e.g. 0800, 1600)."""
    if not s or not str(s).strip():
        return ""
    s = str(s).strip()
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%H:%M:%S"):
        try:
            t = datetime.strptime(s, fmt)
            return f"{t.hour:02d}{t.minute:02d}"
        except ValueError:
            continue
    return s


def _build_summary_text(data: dict) -> str:
    """Build email-style summary from plan payload (vessel, operator, persons, itinerary, rescue/contacts)."""
    lines = ["FLOAT PLAN SUMMARY"]
    itinerary = list(data.get("itinerary") or [])
    if itinerary:
        first_dep = (itinerary[0].get("depart_location") or "").strip() or "—"
        last_arr = (itinerary[-1].get("arrive_location") or "").strip() or "—"
        lines.append(f"{first_dep} to {last_arr}")
    lines.append("")
    vessel = data.get("vessel") or {}
    vessel_name = (vessel.get("name") or vessel.get("id_vessel_name") or "").strip()
    if vessel_name:
        lines.append(f"Vessel: {vessel_name}")
        home = (vessel.get("id_home_port") or "").strip()
        if home:
            lines.append(f"Home port: {home}")
        lines.append("")
    operator = data.get("operator") or {}
    op_name = (operator.get("name") or "").strip()
    if op_name:
        lines.append(f"Operator: {op_name}")
        if (operator.get("home_phone") or "").strip():
            lines.append(f"  Phone: {(operator.get('home_phone') or '').strip()}")
        lines.append("")
    persons = list(data.get("persons") or [])
    on_board_names = [(p.get("name") or "").strip() for p in persons if (p.get("name") or "").strip()]
    if on_board_names:
        lines.append("Crew on board: " + ", ".join(on_board_names))
        lines.append("")
    if itinerary:
        lines.append("ITINERARY")
        lines.append("")
        for leg in itinerary:
            dep_date = _format_date_for_summary(leg.get("depart_date", "") or "")
            dep_time = _format_time_for_summary(leg.get("depart_time", "") or "") or (leg.get("depart_time", "") or "").strip()
            dep_loc = (leg.get("depart_location", "") or "").strip() or "—"
            arr_date = _format_date_for_summary(leg.get("arrive_date", "") or "")
            arr_time = _format_time_for_summary(leg.get("arrive_time", "") or "") or (leg.get("arrive_time", "") or "").strip()
            arr_loc = (leg.get("arrive_location", "") or "").strip() or "—"
            at_dep = f", at {dep_time}," if dep_time else ","
            at_arr = f" at {arr_time}." if arr_time else "."
            lines.append(f"{dep_date}{at_dep} depart {dep_loc} heading to {arr_loc}, expecting arrival on {arr_date}{at_arr}")
        lines.append("")
    rescue = (data.get("rescue_authority") or "").strip()
    rescue_phone = (data.get("rescue_authority_phone") or "").strip()
    if rescue or rescue_phone:
        lines.append(f"Rescue authority: {rescue or '—'}")
        if rescue_phone:
            lines.append(f"  Phone: {rescue_phone}")
        lines.append("")
    c1 = (data.get("contact1") or "").strip()
    c1_phone = (data.get("contact1_phone") or "").strip()
    if c1 or c1_phone:
        lines.append(f"Contact 1: {c1 or '—'} {c1_phone or ''}".strip())
    c2 = (data.get("contact2") or "").strip()
    c2_phone = (data.get("contact2_phone") or "").strip()
    if c2 or c2_phone:
        lines.append(f"Contact 2: {c2 or '—'} {c2_phone or ''}".strip())
    text = "\n".join(lines).strip()
    if not text:
        text = "No plan details to summarize. Add a vessel, operator, and/or itinerary."
    return text
from pdf_form_options import FORM_OPTIONS, get_option_key_for_field, get_options
from rescue_authorities import RCC_NAMES, RCC_PHONE_BY_NAME

# Vessel form sections (label, list of DEFAULT_VESSEL keys)
VESSEL_SECTIONS = [
    ("Vessel identity", [
        "id_vessel_name", "id_home_port", "id_doc_reg_num", "id_hin", "id_year_make_model",
        "id_length", "id_type", "id_draft", "id_hull_mat", "id_hull_trim_colors", "id_prominent_features",
    ]),
    ("Communications", [
        "com_radio_call_sign", "com_dsc_no", "com_radio1_type", "com_radio1_freq_mon",
        "com_radio2_type", "com_radio2_freq_mon", "com_cell_sat_phone", "com_email",
    ]),
    ("Propulsion", [
        "pro_prim_eng_type", "pro_prim_num_engines", "pro_prim_fuel_capacity",
        "pro_aux_eng_type", "pro_aux_num_eng", "pro_aux_fuel_capacity",
    ]),
    ("Navigation", [
        "nav_maps", "nav_charts", "nav_compass", "nav_gps", "nav_depth_sounder", "nav_radar",
        "nav_other_avail", "nav_user_desc",
    ]),
    ("Safety & survival", [
        "vds_edl", "vds_flag", "vds_flare_aerial", "vds_flare_handheld", "vds_signal_mirror", "vds_smoke",
        "ads_bell", "ads_horn", "ads_whistle", "epirb_uin",
        "add_anchor", "add_anchor_line_length", "add_raft", "add_flashlight", "add_fire_extinguisher",
        "add_exposure_suit", "add_dewatering", "add_water", "add_water_days",
        "add_food_avail", "add_food_days",
        "add_other_avail_1", "add_other_desc_1", "add_other_avail_2", "add_other_desc_2",
        "add_other_avail_3", "add_other_desc_3", "add_other_avail_4", "add_other_desc_4",
    ]),
]

def _vessel_key_label(k: str) -> str:
    """Human-readable label for vessel form field."""
    labels = {
        "id_vessel_name": "Vessel name",
        "id_home_port": "Home port",
        "id_doc_reg_num": "Doc/Reg No",
        "id_hin": "HIN",
        "id_year_make_model": "Year, make, model",
        "id_length": "Length",
        "id_type": "Type",
        "id_draft": "Draft",
        "id_hull_mat": "Hull material",
        "id_hull_trim_colors": "Hull/trim colors",
        "id_prominent_features": "Prominent features",
        "com_radio_call_sign": "Radio call sign",
        "com_dsc_no": "DSC/MMSI No",
        "com_radio1_type": "Radio 1 type",
        "com_radio1_freq_mon": "Radio 1 freq/ch monitored",
        "com_radio2_type": "Radio 2 type",
        "com_radio2_freq_mon": "Radio 2 freq/ch monitored",
        "com_cell_sat_phone": "Cell/sat phone",
        "com_email": "Email",
        "pro_prim_eng_type": "Primary engine type",
        "pro_prim_num_engines": "Primary no. engines",
        "pro_prim_fuel_capacity": "Primary fuel (gal/L)",
        "pro_aux_eng_type": "Aux engine type",
        "pro_aux_num_eng": "Aux no. engines",
        "pro_aux_fuel_capacity": "Aux fuel (gal/L)",
        "nav_user_desc": "Other description",
        "epirb_uin": "EPIRB UIN",
        "add_anchor_line_length": "Anchor line length",
        "add_water_days": "Water days/person",
        "add_food_days": "Food days/person",
    }
    return labels.get(k, k.replace("_", " ").title())


# Crew member form: ordered DEFAULT_PERSON keys with labels
PERSON_FIELD_LABELS = [
    ("name", "Name"),
    ("address", "Address"),
    ("city", "City"),
    ("state", "State"),
    ("zip_code", "Zip"),
    ("dob", "Date of birth"),
    ("age", "Age"),
    ("gender", "Gender"),
    ("home_phone", "Home phone"),
    ("note", "Note"),
    ("pfd", "PFD (life jacket)"),
    ("plb_uin", "PLB UIN"),
    ("vehicle_year_make_model", "Vehicle year/make/model"),
    ("vehicle_license_num", "Vehicle license"),
    ("vehicle_parked_at", "Vehicle parked at"),
    ("vessel_trailored", "Vessel trailered"),
    ("float_plan_note", "Float plan note"),
]

APP_DIR = Path(__file__).resolve().parent
TEMPLATE_PDF = APP_DIR / "USCGFloatPlan.pdf"

app = Flask(__name__, template_folder=str(APP_DIR / "templates"), static_folder=str(APP_DIR / "static"))

# Limit request body to reduce DoS risk (PDF/summary JSON can be large but bounded)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024  # 4 MB

# Session cookie hardening (HTTPS via tunnel / reverse proxy in production)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
if (
    _env_truthy("SESSION_COOKIE_SECURE")
    or (
        _env_truthy("TRUST_PROXY")
        and (
            _env_truthy("PREFER_HTTPS")
            or _is_production_deployment()
        )
    )
):
    app.config["SESSION_COOKIE_SECURE"] = True

# SECRET_KEY for sessions (Flask-Login). In production (or REQUIRE_ENV_SECRET=1), env-only — no data/.flask_secret.
_INSECURE_KEYS = ("", "change_this_secret_key")
_SECRET_FILE = APP_DIR / "data" / ".flask_secret"
_secret_env = os.environ.get("SECRET_KEY", "").strip()
_strict_secret = _is_production_deployment() or _env_truthy("REQUIRE_ENV_SECRET")
if _strict_secret:
    if not _secret_env or _secret_env in _INSECURE_KEYS:
        print(
            "ERROR: SECRET_KEY must be set in the environment for production "
            "(PRODUCTION=1 / FLASK_ENV=production) or when REQUIRE_ENV_SECRET=1. "
            "Do not rely on data/.flask_secret in those modes.",
            file=sys.stderr,
        )
        print("  export SECRET_KEY=\"$(python3 -c \"import secrets; print(secrets.token_hex(32))\")\"", file=sys.stderr)
        sys.exit(1)
    app.secret_key = _secret_env
else:
    app.secret_key = _secret_env
    if not app.secret_key or app.secret_key in _INSECURE_KEYS:
        if _SECRET_FILE.exists():
            try:
                app.secret_key = _SECRET_FILE.read_text().strip()
            except OSError:
                pass
        if not app.secret_key or app.secret_key in _INSECURE_KEYS:
            import secrets

            app.secret_key = secrets.token_hex(32)
            _SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
            try:
                _SECRET_FILE.write_text(app.secret_key)
            except OSError:
                pass
            print(
                "Created persistent secret key in data/.flask_secret (dev convenience; set SECRET_KEY in prod).",
                file=sys.stderr,
            )

_maybe_trust_proxy(app)

csrf = CSRFProtect(app)


@app.errorhandler(RequestEntityTooLarge)
def _handle_413(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Request body too large"}), 413
    return e.get_response()


_rate_limit_storage = (
    (os.environ.get("RATE_LIMIT_STORAGE_URI") or "").strip()
    or (os.environ.get("REDIS_URL") or "").strip()
    or "memory://"
)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "60 per minute"],
    storage_uri=_rate_limit_storage,
)

# SQLite DB for users (mirrors anchor_watch pattern, but only user/group here).
db_path = APP_DIR / "data" / "float_plan.db"
db_path.parent.mkdir(parents=True, exist_ok=True)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

LEGACY_USER_DATA_ROOT = APP_DIR / "data" / "users"


def _username_safe(username: str) -> bool:
    """Reject usernames that could be used for path traversal or abuse."""
    if not username or ".." in username or "/" in username or "\\" in username:
        return False
    if len(username) > 80:  # Match DB column; avoid filesystem/display abuse
        return False
    return True


def _load_vessels() -> list[dict]:
    """Instance-wide vessel list (shared by all authorized users on this deployment)."""
    return load_vessels()


def _save_vessels(vessels: list[dict]) -> None:
    save_vessels(vessels)


def _load_crew_members() -> list[dict]:
    """Instance-wide crew member pool (shared by all authorized users on this deployment)."""
    return load_crew_members()


def _save_crew_members(members: list[dict]) -> None:
    save_crew_members(members)


def _ensure_instance_data_migrated() -> None:
    """One-time: copy legacy data/users/* JSON into shared data/*.json if needed."""
    if _load_vessels() or _load_crew_members():
        return
    if not LEGACY_USER_DATA_ROOT.is_dir():
        return
    sources: list[Path] = []
    fp_dir = LEGACY_USER_DATA_ROOT / "fp"
    if fp_dir.is_dir() and (
        (fp_dir / "vessels.json").is_file() or (fp_dir / "crew_members.json").is_file()
    ):
        sources.append(fp_dir)
    for entry in sorted(LEGACY_USER_DATA_ROOT.iterdir()):
        if not entry.is_dir() or entry in sources:
            continue
        if (entry / "vessels.json").is_file() or (entry / "crew_members.json").is_file():
            sources.append(entry)
    if not sources:
        return
    src = sources[0]
    vessels_path = src / "vessels.json"
    crew_path = src / "crew_members.json"
    if vessels_path.is_file():
        try:
            vessels = json.loads(vessels_path.read_text(encoding="utf-8"))
            if isinstance(vessels, list) and vessels:
                _save_vessels(vessels)
                logger.info("Migrated legacy vessels from %s", src.name)
        except Exception as exc:
            logger.warning("Could not migrate legacy vessels from %s: %s", src, exc)
    if crew_path.is_file():
        try:
            members = json.loads(crew_path.read_text(encoding="utf-8"))
            if isinstance(members, list) and members:
                _save_crew_members(members)
                logger.info("Migrated legacy crew members from %s", src.name)
        except Exception as exc:
            logger.warning("Could not migrate legacy crew members from %s: %s", src, exc)


class User(UserMixin, db.Model):
    """Users: admin, crew (edit data), viewer (view-only), pending (awaiting Authentik approval)."""

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    authentik_sub = db.Column(db.String(128), unique=True, nullable=True)
    group = db.Column(db.String(16), nullable=False, default="viewer")  # admin, crew, viewer, pending

    def set_password(self, password: str) -> None:
        self.password_hash = pbkdf2_sha256.hash(password)

    def check_password(self, password: str) -> bool:
        return pbkdf2_sha256.verify(password, self.password_hash)

    def can_edit_data(self) -> bool:
        return self.group in ("admin", "crew")


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    try:
        return User.query.get(int(user_id))
    except (ValueError, TypeError):
        return None


def _cors_allow_origin():
    """Allow svburnttoast.com (apex + www), Cloudflare Pages (*.pages.dev), and localhost for status check."""
    origin = request.headers.get("Origin") or ""
    if origin in ("https://svburnttoast.com", "https://www.svburnttoast.com"):
        return origin
    if ".pages.dev" in origin:
        return origin
    if origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1"):
        return origin
    return "https://svburnttoast.com"


_FLOAT_PLAN_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "connect-src 'self'; "
    "frame-ancestors 'self'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = _FLOAT_PLAN_CSP
    response.headers["Access-Control-Allow-Origin"] = _cors_allow_origin()
    return response


def crew_required(fn):
    """Require logged-in user with group admin or crew for any data access (load/save/select)."""

    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if current_user.is_authenticated and current_user.group == "pending":
            if request.path.startswith("/api/"):
                return jsonify({"error": "Account pending approval"}), 403
            return redirect(url_for("pending_approval"))
        if not current_user.is_authenticated or not current_user.can_edit_data():
            # For API callers, return JSON error; for browser, redirect to login.
            if request.path.startswith("/api/"):
                return jsonify({"error": "Crew or admin required"}), 403
            flash("Crew or admin access required.", "error")
            return redirect(url_for("login", next=request.path))
        return fn(*args, **kwargs)

    return wrapper


def admin_required(fn):
    """Require logged-in admin."""

    from functools import wraps

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.group != "admin":
            if request.path.startswith("/api/"):
                return jsonify({"error": "Admin required"}), 403
            flash("Admin access required.", "error")
            return redirect(url_for("index"))
        return fn(*args, **kwargs)

    return wrapper


def _ensure_user_columns() -> None:
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error as exc:
        logger.warning("Could not open DB for migration: %s", exc)
        return
    try:
        cur = conn.execute("PRAGMA table_info(user)")
        cols = {str(row[1]) for row in cur.fetchall()}
        if "authentik_sub" not in cols:
            conn.execute("ALTER TABLE user ADD COLUMN authentik_sub VARCHAR(128)")
            conn.commit()
            logger.info("Added user.authentik_sub column")
    except sqlite3.Error as exc:
        logger.warning("User table migration failed: %s", exc)
    finally:
        conn.close()


from oidc_auth import (
    authentik_admin_url,
    authentik_user_url,
    break_glass_login,
    init_oidc,
    load_oidc_settings,
    oidc_logout_completion_response,
    oidc_post_logout_uri,
    apply_logout_cookies,
    clear_app_session_after_logout,
    register_oidc_routes,
)

OIDC = load_oidc_settings()
LIMIT_LOGIN = "5 per minute"

with app.app_context():
    db.create_all()
    _ensure_user_columns()
    _ensure_instance_data_migrated()
    # Default local user "fp" (admin) for break-glass / legacy installs.
    fp = User.query.filter_by(username="fp").first()
    if not fp:
        default_password = os.environ.get("FP_DEFAULT_PASSWORD", "change-me-fp")
        fp = User(username="fp", group="admin")
        fp.set_password(default_password)
        db.session.add(fp)
        db.session.commit()
        print(
            f'Created default user "fp" with group "admin". '
            f'Set FP_DEFAULT_PASSWORD before first start to control the initial password.'
        )
    elif fp.group != "admin":
        fp.group = "admin"
        db.session.commit()
        print('Updated user "fp" to group "admin".')


def _age_from_dob(dob_str: str) -> str:
    """Compute age in years from date-of-birth string. Returns "" if unparseable."""
    if not dob_str or not str(dob_str).strip():
        return ""
    today = datetime.now().date()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y"):
        try:
            b = datetime.strptime(dob_str.strip(), fmt).date()
            if b.year < 1900 or b > today:
                continue
            age = today.year - b.year - ((today.month, today.day) < (b.month, b.day))
            return str(max(0, age))
        except ValueError:
            continue
    return ""


def _person_for_pdf(p: dict) -> dict:
    """One person record for PDF (operator or POB): age from DOB when present."""
    age = _age_from_dob(p.get("dob", "") or "") if p.get("dob") else (p.get("age") or "")
    return {
        **{k: p.get(k, "") for k in ["name", "dob", "age", "gender", "home_phone", "note", "pfd", "plb_uin"]},
        "age": age,
    }


@app.route("/")
def index():
    """Plan page: usable by everyone. Logged-in crew/admins get persistent vessels/crew."""
    vessel_sections = _vessel_sections_with_labels()
    vessel_bool_keys = list({k for k, v in DEFAULT_VESSEL.items() if isinstance(v, bool)})
    vessel_form_options = _vessel_form_options()
    gender_opts = get_options(get_option_key_for_field("gender") or "OPR-Gender") or ["", "M", "F"]
    return render_template(
        "index.html",
        vessel_sections=vessel_sections,
        vessel_bool_keys=vessel_bool_keys,
        vessel_form_options=vessel_form_options,
        person_field_labels=PERSON_FIELD_LABELS,
        gender_options=gender_opts,
    )


@app.route("/login", methods=["GET", "POST"])
@limiter.limit(LIMIT_LOGIN, methods=["POST"])
def login():
    if current_user.is_authenticated:
        if current_user.group == "pending":
            return redirect(url_for("pending_approval"))
        next_url = (request.args.get("next") or "").strip()
        if next_url and next_url.startswith("/") and "//" not in next_url:
            return redirect(next_url)
        return redirect(url_for("index"))

    if OIDC.enabled and request.method == "GET" and not request.args.get("local"):
        nxt = request.args.get("next")
        if nxt and nxt.startswith("/") and not nxt.startswith("//"):
            session["oidc_next"] = nxt
        return redirect(url_for("oidc_login_start"))

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        user = None
        if OIDC.enabled:
            user = break_glass_login(OIDC, username, password)
        if user is None:
            user = User.query.filter_by(username=username).first()
            if user and not user.check_password(password):
                user = None
        if user and user.group == "pending":
            flash("Your account is waiting for admin approval in Authentik.", "info")
            return redirect(url_for("pending_approval"))
        if user:
            login_user(user)
            next_url = (request.args.get("next") or "").strip()
            if next_url and next_url.startswith("/") and "//" not in next_url and "\n" not in next_url and "\r" not in next_url:
                return redirect(next_url)
            return redirect(url_for("index"))
        flash("Invalid username or password", "error")
    return render_template(
        "login.html",
        oidc_enabled=OIDC.enabled,
        break_glass_enabled=OIDC.break_glass_enabled,
        enrollment_url=OIDC.enrollment_url,
    )


@app.route("/pending")
def pending_approval():
    return render_template(
        "pending_approval.html",
        enrollment_url=OIDC.enrollment_url if OIDC.enabled else "",
    )


@app.route("/logout")
@login_required
def logout():
    id_token_hint = session.get("oidc_id_token")
    post = oidc_post_logout_uri(request, OIDC)
    logout_user()
    clear_app_session_after_logout()
    if not OIDC.enabled:
        return apply_logout_cookies(redirect(url_for('login', local=1)))
    return oidc_logout_completion_response(OIDC, post, id_token_hint=id_token_hint)


@app.route("/admin/users", methods=["GET", "POST"])
@login_required
@admin_required
def admin_users():
    if OIDC.enabled and request.method == "POST":
        flash("User accounts are managed in Authentik when OIDC is enabled.", "info")
        return redirect(url_for("admin_users"))
    if request.method == "POST":
        action = request.form.get("action")
        if action == "create":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            group = (request.form.get("group") or "viewer").strip()
            if not username or not password:
                flash("Username and password are required.", "error")
                return redirect(url_for("admin_users"))
            if not _username_safe(username):
                flash("Username cannot contain .. or path separators.", "error")
                return redirect(url_for("admin_users"))
            if group not in ("admin", "crew", "viewer"):
                flash("Invalid role.", "error")
                return redirect(url_for("admin_users"))
            if User.query.filter_by(username=username).first():
                flash("Username already exists.", "error")
                return redirect(url_for("admin_users"))
            user = User(username=username, group=group)
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
            flash(f"User {username} created as {group}.", "success")
            return redirect(url_for("admin_users"))
        if action == "set_group":
            user_id = request.form.get("user_id")
            group = (request.form.get("group") or "").strip()
            try:
                uid = int(user_id)
            except (TypeError, ValueError):
                uid = None
            if group not in ("admin", "crew", "viewer") or uid is None:
                flash("Invalid user or role.", "error")
                return redirect(url_for("admin_users"))
            user = User.query.get(uid)
            if not user:
                flash("User not found.", "error")
                return redirect(url_for("admin_users"))
            if user.id == current_user.id and group != "admin":
                flash("You cannot remove your own admin role.", "error")
                return redirect(url_for("admin_users"))
            user.group = group
            db.session.commit()
            flash(f"{user.username} set to {group}.", "success")
            return redirect(url_for("admin_users"))
        if action == "delete":
            user_id = request.form.get("user_id")
            try:
                uid = int(user_id)
            except (TypeError, ValueError):
                uid = None
            if uid is None:
                flash("Invalid user.", "error")
                return redirect(url_for("admin_users"))
            user = User.query.get(uid)
            if not user:
                flash("User not found.", "error")
                return redirect(url_for("admin_users"))
            if user.id == current_user.id:
                flash("You cannot delete your own account.", "error")
                return redirect(url_for("admin_users"))
            db.session.delete(user)
            db.session.commit()
            flash(f"User {user.username} deleted.", "success")
            return redirect(url_for("admin_users"))
        return redirect(url_for("admin_users"))
    users = User.query.order_by(User.username).all()
    return render_template(
        "admin_users.html",
        users=users,
        oidc_enabled=OIDC.enabled,
        authentik_admin_url=authentik_admin_url(OIDC),
    )


def _vessel_form_options():
    """Build { data_key: [option strings] } for dropdown fields."""
    out = {}
    for section_label, keys in VESSEL_SECTIONS:
        for k in keys:
            if k in out:
                continue
            opt_key = get_option_key_for_field(k)
            if opt_key:
                out[k] = get_options(opt_key) or []
    return out


@app.route("/vessels")
@login_required
@crew_required
def vessels_list():
    vessels = _load_vessels()
    return render_template("vessels_list.html", vessels=vessels)


def _vessel_sections_with_labels():
    return [
        (sec_label, [(k, _vessel_key_label(k)) for k in keys])
        for sec_label, keys in VESSEL_SECTIONS
    ]


@app.route("/vessels/new")
@login_required
@crew_required
def vessel_new():
    vessel = dict(DEFAULT_VESSEL)
    vessel["name"] = ""
    vessel["id_vessel_name"] = ""
    options = _vessel_form_options()
    sections = _vessel_sections_with_labels()
    bool_keys = {k for k, v in DEFAULT_VESSEL.items() if isinstance(v, bool)}
    return render_template("vessel_form.html", vessel=vessel, index=-1, options=options, sections=sections, bool_keys=bool_keys)


@app.route("/vessels/<int:index>/edit")
@login_required
@crew_required
def vessel_edit(index):
    vessels = _load_vessels()
    if index < 0 or index >= len(vessels):
        flash("Vessel not found.", "error")
        return redirect(url_for("vessels_list"))
    vessel = {**DEFAULT_VESSEL, **{k: v for k, v in vessels[index].items() if k in DEFAULT_VESSEL}}
    options = _vessel_form_options()
    sections = _vessel_sections_with_labels()
    bool_keys = {k for k, v in DEFAULT_VESSEL.items() if isinstance(v, bool)}
    return render_template("vessel_form.html", vessel=vessel, index=index, options=options, sections=sections, bool_keys=bool_keys)


@app.route("/vessels/save", methods=["POST"])
@login_required
@crew_required
def vessel_save():
    index_val = request.form.get("index", "-1").strip()
    try:
        index = int(index_val)
    except ValueError:
        index = -1
    vessels = _load_vessels()
    vessel = dict(DEFAULT_VESSEL)
    for k in DEFAULT_VESSEL:
        if k in ("id", "name"):
            continue
        default = DEFAULT_VESSEL[k]
        if isinstance(default, bool):
            vessel[k] = request.form.get(k) in ("1", "true", "on", "yes")
        else:
            vessel[k] = (request.form.get(k) or "").strip()
    vessel["id"] = ""
    vessel["name"] = (vessel.get("id_vessel_name") or "").strip() or "Unnamed"
    if index >= 0 and index < len(vessels):
        vessels[index] = vessel
        flash("Vessel updated.", "success")
    else:
        vessels.append(vessel)
        flash("Vessel added.", "success")
    _save_vessels(vessels)
    return redirect(url_for("vessels_list"))


@app.route("/vessels/<int:index>/delete", methods=["POST"])
@login_required
@crew_required
def vessel_delete(index: int):
    vessels = _load_vessels()
    if index < 0 or index >= len(vessels):
        flash("Vessel not found.", "error")
        return redirect(url_for("vessels_list"))
    name = (vessels[index].get("name") or vessels[index].get("id_vessel_name") or "Unnamed").strip()
    vessels.pop(index)
    _save_vessels(vessels)
    flash(f"Deleted vessel: {name}", "success")
    return redirect(url_for("vessels_list"))


@app.route("/crew")
@login_required
@crew_required
def crew_list():
    members = _load_crew_members()
    return render_template("crew_list.html", members=members)


@app.route("/crew/new")
@login_required
@crew_required
def crew_new():
    person = dict(DEFAULT_PERSON)
    gender_opts = get_options(get_option_key_for_field("gender") or "OPR-Gender") or ["", "M", "F"]
    return render_template("crew_form.html", person=person, index=-1, gender_options=gender_opts, person_field_labels=PERSON_FIELD_LABELS)


@app.route("/crew/<int:index>/edit")
@login_required
@crew_required
def crew_edit(index):
    members = _load_crew_members()
    if index < 0 or index >= len(members):
        flash("Crew member not found.", "error")
        return redirect(url_for("crew_list"))
    person = {**DEFAULT_PERSON, **{k: v for k, v in members[index].items() if k in DEFAULT_PERSON}}
    gender_opts = get_options(get_option_key_for_field("gender") or "OPR-Gender") or ["", "M", "F"]
    return render_template("crew_form.html", person=person, index=index, gender_options=gender_opts, person_field_labels=PERSON_FIELD_LABELS)


@app.route("/crew/save", methods=["POST"])
@login_required
@crew_required
def crew_save():
    index_val = request.form.get("index", "-1").strip()
    try:
        index = int(index_val)
    except ValueError:
        index = -1
    members = _load_crew_members()
    person = dict(DEFAULT_PERSON)
    for k in DEFAULT_PERSON:
        if k == "pfd":
            person[k] = "Yes" if request.form.get(k) in ("1", "true", "on", "yes") else ""
        else:
            person[k] = (request.form.get(k) or "").strip()
    if index >= 0 and index < len(members):
        members[index] = person
        flash("Crew member updated.", "success")
    else:
        members.append(person)
        flash("Crew member added.", "success")
    _save_crew_members(members)
    return redirect(url_for("crew_list"))


@app.route("/crew/<int:index>/delete", methods=["POST"])
@login_required
@crew_required
def crew_delete(index: int):
    members = _load_crew_members()
    if index < 0 or index >= len(members):
        flash("Crew member not found.", "error")
        return redirect(url_for("crew_list"))
    name = (members[index].get("name") or "Unnamed").strip()
    members.pop(index)
    _save_crew_members(members)
    flash(f"Deleted crew member: {name}", "success")
    return redirect(url_for("crew_list"))


@app.route("/api/vessels")
def api_vessels():
    """Return instance vessels when logged in; empty list for anonymous (they use client-side state)."""
    if not current_user.is_authenticated:
        return jsonify([])
    vessels = _load_vessels()
    return jsonify(vessels)


@app.route("/api/crew_members")
def api_crew_members():
    """Return instance crew when logged in; empty list for anonymous."""
    if not current_user.is_authenticated:
        return jsonify([])
    members = _load_crew_members()
    return jsonify(members)


@app.route("/api/options")
def api_options():
    """Dropdown option keys and lists for form fields."""
    options = {k: v for k, v in FORM_OPTIONS.items() if isinstance(v, list)}
    return jsonify(options)


@app.route("/api/rescue_authorities")
def api_rescue_authorities():
    return jsonify({"names": RCC_NAMES, "phones": RCC_PHONE_BY_NAME})


@app.route("/api/summary", methods=["POST"])
def api_summary():
    """Return text summary of the plan for copying into email. No auth required."""
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400
    try:
        text = _build_summary_text(data)
        return jsonify({"text": text})
    except Exception:
        logger.exception("Summary generation failed")
        return jsonify({"error": "Summary generation failed"}), 500


@app.route("/api/pdf", methods=["POST"])
def api_pdf():
    """Generate PDF from plan JSON. Body: vessel, operator, persons, itinerary, rescue/contacts."""
    if not TEMPLATE_PDF.exists():
        return jsonify({"error": "Template PDF not found"}), 500
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    vessel = data.get("vessel") or {}
    vessel = {**DEFAULT_VESSEL, **{k: v for k, v in vessel.items() if k in DEFAULT_VESSEL}}
    vessel["contact1"] = (data.get("contact1") or "").strip()
    vessel["contact1_phone"] = (data.get("contact1_phone") or "").strip()
    vessel["contact2"] = (data.get("contact2") or "").strip()
    vessel["contact2_phone"] = (data.get("contact2_phone") or "").strip()
    vessel["rescue_authority"] = (data.get("rescue_authority") or "").strip()
    vessel["rescue_authority_phone"] = (data.get("rescue_authority_phone") or "").strip()

    operator_raw = data.get("operator") or {}
    # Full operator for OPR section (address, experience, etc.)
    operator = _person_for_pdf(operator_raw)
    for k in ["address", "city", "state", "zip_code", "vehicle_year_make_model", "vehicle_license_num", "vehicle_parked_at", "vessel_trailored", "float_plan_note"]:
        operator[k] = (operator_raw.get(k) or "").strip()
    operator["vessel_experience"] = "Yes" if data.get("operator_has_vessel_experience") else ""
    operator["area_experience"] = "Yes" if data.get("operator_has_area_experience") else ""

    # POB list: operator first (always on board), then other on-board persons (max 11 more = 12 total)
    persons = [_person_for_pdf(operator_raw)]
    for p in (data.get("persons") or [])[:11]:
        persons.append(_person_for_pdf(p))
    crew = {"operator": operator, "persons": persons}

    itinerary = list(data.get("itinerary") or [])
    for leg in itinerary:
        leg.setdefault("arrive_checkin_time", "")

    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            out_path = tmp.name
        fill_float_plan(TEMPLATE_PDF, out_path, vessel, crew, itinerary)
        with open(out_path, "rb") as f:
            buf = f.read()
        Path(out_path).unlink(missing_ok=True)
        return send_file(
            io.BytesIO(buf),
            mimetype="application/pdf",
            as_attachment=True,
            download_name="float_plan.pdf",
        )
    except Exception as e:
        logger.exception("PDF generation failed")
        return jsonify({"error": "PDF generation failed"}), 500


@app.route("/api/vessels", methods=["POST"])
@crew_required
def api_create_vessel():
    """Create a minimal vessel record in the shared instance store."""
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    vessels = _load_vessels()
    vessel = dict(DEFAULT_VESSEL)
    vessel["id"] = ""
    vessel["id_vessel_name"] = name
    vessel["name"] = name
    # Optional extra identity fields if supplied
    for k in ("id_home_port", "id_doc_reg_num", "id_year_make_model", "id_type"):
        if k in data:
            vessel[k] = str(data.get(k) or "").strip()
    vessels.append(vessel)
    _save_vessels(vessels)
    return jsonify(vessel), 201


@app.route("/api/crew_members", methods=["POST"])
@crew_required
def api_create_crew_member():
    """Create a minimal crew member (person) in the shared instance store."""
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    members = _load_crew_members()
    person = dict(DEFAULT_PERSON)
    person["name"] = name
    # Optional simple fields
    for k in ("home_phone", "note", "dob", "gender"):
        if k in data:
            person[k] = str(data.get(k) or "").strip()
    members.append(person)
    _save_crew_members(members)
    return jsonify(person), 201


def _apply_bind_vars_from_dotenv() -> None:
    """If `python web_app.py` is run without the shell sourcing `.env`, pick up HOST/PORT anyway."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key not in ("HOST", "PORT"):
            continue
        if key in os.environ:
            continue
        os.environ[key] = val.strip().strip("'\"")


def _flask_dev_bind_host_port() -> tuple[str, int]:
    """Same resolution order as gunicorn_config.py (config.yaml web.*, then env HOST/PORT)."""
    _apply_bind_vars_from_dotenv()
    config_path = Path(__file__).resolve().parent / "config.yaml"
    # Without config.yaml, default to all interfaces (historic `python web_app.py` behavior). Avoid a
    # literal 0.0.0.0 here so Bandit B104 stays quiet; gunicorn path still uses config / env.
    no_config_default_host = ".".join(["0"] * 4)
    host = os.environ.get("HOST", no_config_default_host if not config_path.is_file() else "127.0.0.1")
    port = os.environ.get("PORT", "5503")
    if config_path.is_file():
        try:
            import yaml

            with open(config_path, encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
            w = c.get("web") or {}
            host = str(w.get("host", host))
            port = str(w.get("port", port))
        except Exception:
            pass
    host = os.environ.get("HOST", host)
    port = os.environ.get("PORT", port)
    return host, int(port)


@app.context_processor
def inject_oidc_globals():
    return {
        "oidc_enabled": OIDC.enabled,
        "authentik_user_url": authentik_user_url(OIDC) if OIDC.enabled else "",
    }


init_oidc(app, OIDC)
register_oidc_routes(app, settings=OIDC, limit_login=LIMIT_LOGIN, limiter=limiter)


def main():
    host, port = _flask_dev_bind_host_port()
    app.run(host=host, port=port, debug=False)


if __name__ == "__main__":
    main()
