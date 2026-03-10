"""JSON file storage for vessels and crews."""
from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
VESSELS_FILE = DATA_DIR / "vessels.json"
CREWS_FILE = DATA_DIR / "crews.json"
CREW_MEMBERS_FILE = DATA_DIR / "crew_members.json"

# Default vessel schema (matches PDF: ID, COM, PRO, NAV, safety; Contact 1/2 are plan-level, not vessel)
DEFAULT_VESSEL = {
    "id": "",
    "name": "",
    "id_vessel_name": "",
    "id_home_port": "",
    "id_doc_reg_num": "",
    "id_hin": "",
    "id_year_make_model": "",
    "id_length": "",
    "id_type": "",
    "id_draft": "",
    "id_hull_mat": "",
    "id_hull_trim_colors": "",
    "id_prominent_features": "",
    "com_radio_call_sign": "",
    "com_dsc_no": "",
    "com_radio1_type": "",
    "com_radio1_freq_mon": "",
    "com_radio2_type": "",
    "com_radio2_freq_mon": "",
    "com_cell_sat_phone": "",
    "com_email": "",
    "pro_prim_eng_type": "",
    "pro_prim_num_engines": "",
    "pro_prim_fuel_capacity": "",
    "pro_aux_eng_type": "",
    "pro_aux_num_eng": "",
    "pro_aux_fuel_capacity": "",
    "nav_maps": False,
    "nav_charts": False,
    "nav_compass": False,
    "nav_gps": False,
    "nav_depth_sounder": False,
    "nav_radar": False,
    "nav_other_avail": False,
    "nav_user_desc": "",
    "vds_edl": False,
    "vds_flag": False,
    "vds_flare_aerial": False,
    "vds_flare_handheld": False,
    "vds_signal_mirror": False,
    "vds_smoke": False,
    "ads_bell": False,
    "ads_horn": False,
    "ads_whistle": False,
    "epirb_uin": "",
    "add_anchor": False,
    "add_anchor_line_length": "",
    "add_raft": False,
    "add_flashlight": False,
    "add_fire_extinguisher": False,
    "add_exposure_suit": False,
    "add_dewatering": False,
    "add_water": False,
    "add_water_days": "",
    "add_food_avail": False,
    "add_food_days": "",
    "add_other_avail_1": False,
    "add_other_desc_1": "",
    "add_other_avail_2": False,
    "add_other_desc_2": "",
    "add_other_avail_3": False,
    "add_other_desc_3": "",
    "add_other_avail_4": False,
    "add_other_desc_4": "",
}

# Operator + up to 12 POB (POB-01..POB-12 in PDF; OPR is operator)
DEFAULT_PERSON = {
    "name": "",
    "address": "",
    "city": "",
    "state": "",
    "zip_code": "",
    "dob": "",
    "age": "",
    "gender": "",
    "home_phone": "",
    "note": "",
    "pfd": "",
    "plb_uin": "",
    "vehicle_year_make_model": "",
    "vehicle_license_num": "",
    "vehicle_parked_at": "",
    "vessel_trailered": "",
    "float_plan_note": "",
}

DEFAULT_CREW = {
    "id": "",
    "name": "",
    "operator": {**DEFAULT_PERSON},
    "persons": [],  # list of person dicts (same shape, fewer keys used for POB-01..)
}


def _ensure_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_vessels() -> list[dict]:
    _ensure_dir()
    if not VESSELS_FILE.exists():
        return []
    with open(VESSELS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_vessels(vessels: list[dict]) -> None:
    _ensure_dir()
    with open(VESSELS_FILE, "w", encoding="utf-8") as f:
        json.dump(vessels, f, indent=2)


def load_crews() -> list[dict]:
    _ensure_dir()
    if not CREWS_FILE.exists():
        return []
    with open(CREWS_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_crews(crews: list[dict]) -> None:
    _ensure_dir()
    with open(CREWS_FILE, "w", encoding="utf-8") as f:
        json.dump(crews, f, indent=2)


def load_crew_members() -> list[dict]:
    """Load the pool of crew members (people). Each item has DEFAULT_PERSON keys."""
    _ensure_dir()
    if CREW_MEMBERS_FILE.exists():
        with open(CREW_MEMBERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    # One-time migration from old crews.json: add each operator and each POB as a crew member
    if CREWS_FILE.exists():
        crews = load_crews()
        seen: set[str] = set()
        members: list[dict] = []
        for c in crews:
            op = c.get("operator") or {}
            if op and op.get("name"):
                key = (op.get("name") or "").strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    members.append({**DEFAULT_PERSON, **{k: op.get(k, "") for k in DEFAULT_PERSON}})
            for p in c.get("persons") or []:
                name = (p.get("name") or "").strip()
                if name:
                    key = name.lower()
                    if key not in seen:
                        seen.add(key)
                        members.append({**DEFAULT_PERSON, **{k: p.get(k, "") for k in ["name", "dob", "age", "gender", "home_phone", "note", "pfd", "plb_uin"]}})
        if members:
            save_crew_members(members)
            return members
    return []


def save_crew_members(members: list[dict]) -> None:
    _ensure_dir()
    with open(CREW_MEMBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(members, f, indent=2)
