"""Dropdown options for PDF form fields. Loaded from dropdown_options.json when present."""
from __future__ import annotations

import json
from pathlib import Path

OPTIONS_FILE = Path(__file__).resolve().parent / "dropdown_options.json"

# Maps app/data field names to option keys (which list to use). Loaded from _dropdown_fields in JSON.
DROPDOWN_FIELDS: dict[str, str] = {}

# Built-in fallback if dropdown_options.json is missing or invalid
_DEFAULT_OPTIONS = {
    "ID-Type": ["", "Power", "Sail", "Paddle", "Personal Watercraft", "Canoe/Kayak", "Other"],
    "ID-HullMat": ["", "Aluminum", "Composite", "Concrete", "Fabric", "Fiberglass", "Plastic", "Steel", "Wood"],
    "PRO-PrimEngType": ["", "Diesel IB", "Diesel IO", "Diesel OB", "Electric IB", "Electric IO", "Electric OB", "Fan Gas IB", "Gas IO", "Gas OB", "Oar", "Paddle", "Wind"],
    "COM-RadioType": ["", "None", "CB", "HF", "MF", "VHF-FM"],
    "01DepartMode": ["", "Power", "Sail", "Paddle", "Other"],
    "OPR-Gender": ["", "M", "F"],
}


def _load_form_options() -> dict:
    """Load options from dropdown_options.json, or use built-in defaults."""
    global DROPDOWN_FIELDS
    if OPTIONS_FILE.exists():
        try:
            with open(OPTIONS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            # Load which fields use dropdowns (app field name -> option key)
            df = data.get("_dropdown_fields")
            if isinstance(df, dict):
                DROPDOWN_FIELDS = {str(k): str(v) for k, v in df.items()}
            else:
                DROPDOWN_FIELDS = {"id_type": "ID-Type", "id_hull_mat": "ID-HullMat", "pro_prim_eng_type": "PRO-PrimEngType", "pro_aux_eng_type": "PRO-AuxEngType", "com_radio1_type": "COM-RadioType", "com_radio2_type": "COM-RadioType", "gender": "OPR-Gender", "depart_mode": "01DepartMode"}
            # Option lists: strip keys that are comments/metadata
            opts = {
                k: v for k, v in data.items()
                if not k.startswith("_") and isinstance(v, list)
            }
            if opts:
                result = dict(opts)
                # Aliases: same list for Mode and Gender
                if "01DepartMode" in result:
                    result["02DepartMode"] = result["01DepartMode"]
                    result["03ArriveMode"] = result["01DepartMode"]
                if "OPR-Gender" in result:
                    result["POB-Gender"] = result["OPR-Gender"]
                if "PRO-PrimEngType" in result:
                    result["PRO-AuxEngType"] = result["PRO-PrimEngType"]
                return result
        except (json.JSONDecodeError, TypeError):
            pass
    result = dict(_DEFAULT_OPTIONS)
    result["02DepartMode"] = result["01DepartMode"]
    result["03ArriveMode"] = result["01DepartMode"]
    result["POB-Gender"] = result["OPR-Gender"]
    if "PRO-PrimEngType" in result:
        result["PRO-AuxEngType"] = result["PRO-PrimEngType"]
    if not DROPDOWN_FIELDS:
        DROPDOWN_FIELDS = {"id_type": "ID-Type", "id_hull_mat": "ID-HullMat", "pro_prim_eng_type": "PRO-PrimEngType", "pro_aux_eng_type": "PRO-AuxEngType", "com_radio1_type": "COM-RadioType", "com_radio2_type": "COM-RadioType", "gender": "OPR-Gender", "depart_mode": "01DepartMode"}
    return result


FORM_OPTIONS = _load_form_options()


def _opt_strings(opt):
    """Turn PDF /Opt array into list of strings."""
    if opt is None:
        return None
    out = []
    for item in opt:
        try:
            if hasattr(item, "get_object"):
                item = item.get_object()
            if hasattr(item, "get_object"):
                item = item.get_object()
            if isinstance(item, bytes):
                out.append(item.decode("utf-8", errors="replace"))
            else:
                out.append(str(item))
        except Exception:
            pass
    return out if out else None


def get_options_from_pdf(pdf_path: Path | None = None) -> dict[str, list[str]]:
    """Read choice/dropdown options from the template PDF. Returns field_name -> [options]."""
    if pdf_path is None:
        pdf_path = Path(__file__).resolve().parent / "USCGFloatPlan.pdf"
    if not pdf_path.exists():
        return {}
    result = {}
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        fields = reader.get_fields() or {}
        for name, field in fields.items():
            try:
                obj = field.get_object() if hasattr(field, "get_object") else field
                if obj is None:
                    continue
                opt = obj.get("/Opt")
                if opt is None and "/Kids" in obj:
                    for kid in obj["/Kids"]:
                        k = kid.get_object() if hasattr(kid, "get_object") else kid
                        opt = k.get("/Opt") if k else None
                        if opt is not None:
                            break
                opts = _opt_strings(opt)
                if opts:
                    result[name] = opts
            except Exception:
                continue
    except Exception:
        pass
    return result


def get_option_key_for_field(data_key: str) -> str | None:
    """Return the option key for an app/data field if it uses a dropdown, else None."""
    return DROPDOWN_FIELDS.get(data_key)


def get_options(field_name: str, pdf_path: Path | None = None) -> list[str]:
    """Return dropdown options for a PDF form field. Uses template PDF if readable, else FORM_OPTIONS."""
    opts = get_options_from_pdf(pdf_path)
    if field_name in opts:
        return opts[field_name]
    if field_name in FORM_OPTIONS:
        return FORM_OPTIONS[field_name]
    if field_name in ("01DepartMode", "02DepartMode", "03ArriveMode"):
        return FORM_OPTIONS["01DepartMode"]
    return []
