"""Fill the USCG float plan PDF from vessel, crew, and itinerary data."""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter


def _str(v: str | bool | int | None) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else ""
    return str(v).strip()


def _checkbox(v: bool) -> str:
    """PDF checkboxes in this template use export value /Yes (not Yes)."""
    return "/Yes" if v else ""


def _gender(v: str | None) -> str:
    """Normalize to PDF choice option: 'M', 'F', or ' ' (blank)."""
    if not v:
        return " "
    s = str(v).strip().upper()
    if s in ("M", "MALE"):
        return "M"
    if s in ("F", "FEMALE"):
        return "F"
    if s:
        return "M" if s.startswith("M") else "F" if s.startswith("F") else " "
    return " "


def _normalize_phone(s: str | None) -> str:
    """Format phone for PDF: +1 (XXX) XXX-XXXX for 10-digit US numbers."""
    if not s:
        return ""
    digits = "".join(c for c in str(s).strip() if c.isdigit())
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    if len(digits) == 10:
        return f"+1 ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if len(digits) == 7:
        return f"+1 {digits[:3]}-{digits[3:]}"
    return str(s).strip()


def _normalize_phone_local(s: str | None) -> str:
    """Format phone for PDF Passenger/Crew home phone fields without leading +1.

    Expected format: (XXX) XXX-XXXX for 10-digit US numbers.
    """
    if not s:
        return ""
    digits = "".join(c for c in str(s).strip() if c.isdigit())
    # Strip US country code if provided
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if len(digits) == 7:
        return f"({digits[:3]}) {digits[3:]}"
    return str(s).strip()


def build_field_map(vessel: dict, crew: dict, itinerary: list[dict]) -> dict[str, str]:
    """Build PDF field name -> value map for the current template."""
    out: dict[str, str] = {}

    # ---- Vessel ID ----
    name = _str(vessel.get("id_vessel_name"))
    home_port = _str(vessel.get("id_home_port"))
    out["ID-VesselName"] = f"{name}, {home_port}" if home_port else name
    out["ID-DocRegNum"] = _str(vessel.get("id_doc_reg_num"))
    out["ID-HIN"] = _str(vessel.get("id_hin"))
    out["ID-YearMakeModel"] = _str(vessel.get("id_year_make_model"))
    out["ID-Length"] = _str(vessel.get("id_length"))
    out["ID-Type"] = _str(vessel.get("id_type"))
    out["ID-Draft"] = _str(vessel.get("id_draft"))
    out["ID-HullMat"] = _str(vessel.get("id_hull_mat"))
    out["ID-HullTrimColors"] = _str(vessel.get("id_hull_trim_colors"))
    out["ID-ProminentFeatures"] = _str(vessel.get("id_prominent_features"))

    # ---- Communications ----
    out["COM-RadioCallSign"] = _str(vessel.get("com_radio_call_sign"))
    out["COM-DSCNo"] = _str(vessel.get("com_dsc_no"))
    out["COM-Radio1Type"] = _str(vessel.get("com_radio1_type"))
    out["COM-Radio1FreqMon"] = _str(vessel.get("com_radio1_freq_mon"))
    out["COM-Radio2Type"] = _str(vessel.get("com_radio2_type"))
    out["COM-Radio2FreqMon"] = _str(vessel.get("com_radio2_freq_mon"))
    out["COM-CellSatPhone"] = _normalize_phone(vessel.get("com_cell_sat_phone"))
    out["COM-Email"] = _str(vessel.get("com_email"))

    # ---- Propulsion ----
    out["PRO-PrimEngType"] = _str(vessel.get("pro_prim_eng_type"))
    out["PRO-PrimNumEngines"] = _str(vessel.get("pro_prim_num_engines"))
    out["PRO-PrimFuelCapacity"] = _str(vessel.get("pro_prim_fuel_capacity"))
    out["PRO-AuxEngType"] = _str(vessel.get("pro_aux_eng_type"))
    out["PRO-AuxNumEng"] = _str(vessel.get("pro_aux_num_eng"))
    out["PRO-AuxFuelCapacity"] = _str(vessel.get("pro_aux_fuel_capacity"))

    # ---- Navigation (checkboxes / text) ----
    out["NAV-Maps"] = _checkbox(vessel.get("nav_maps") is True)
    out["NAV-Charts"] = _checkbox(vessel.get("nav_charts") is True)
    out["NAV-Compass"] = _checkbox(vessel.get("nav_compass") is True)
    out["NAV-GPS"] = _checkbox(vessel.get("nav_gps") is True)
    out["NAV-DepthSounder"] = _checkbox(vessel.get("nav_depth_sounder") is True)
    out["NAV-Radar"] = _checkbox(vessel.get("nav_radar") is True)
    out["NAV-OtherAvail"] = _checkbox(vessel.get("nav_other_avail") is True)
    out["NAV-UserDesc"] = _str(vessel.get("nav_user_desc"))

    # ---- Safety: VDS ----
    out["VDS-EDL"] = _checkbox(vessel.get("vds_edl") is True)
    out["VDS-Flag"] = _checkbox(vessel.get("vds_flag") is True)
    out["VDS-FlareAerial"] = _checkbox(vessel.get("vds_flare_aerial") is True)
    out["VDS-FlareHandheld"] = _checkbox(vessel.get("vds_flare_handheld") is True)
    out["VDS-SignalMirror"] = _checkbox(vessel.get("vds_signal_mirror") is True)
    out["VDS-Smoke"] = _checkbox(vessel.get("vds_smoke") is True)
    out["ADS-Bell"] = _checkbox(vessel.get("ads_bell") is True)
    out["ADS-Horn"] = _checkbox(vessel.get("ads_horn") is True)
    out["ADS-Whistle"] = _checkbox(vessel.get("ads_whistle") is True)
    out["EPIRB-UIN"] = _str(vessel.get("epirb_uin"))

    # ---- Safety: ADD ----
    out["ADD-Anchor"] = _checkbox(vessel.get("add_anchor") is True)
    out["ADD-AnchorLineLength"] = _str(vessel.get("add_anchor_line_length"))
    out["ADD-Raft"] = _checkbox(vessel.get("add_raft") is True)
    out["ADD-Flashlight"] = _checkbox(vessel.get("add_flashlight") is True)
    out["ADD-FireExtinguisher"] = _checkbox(vessel.get("add_fire_extinguisher") is True)
    out["ADD-ExposureSuit"] = _checkbox(vessel.get("add_exposure_suit") is True)
    out["ADD-Dewatering"] = _checkbox(vessel.get("add_dewatering") is True)
    out["ADD-Water"] = _checkbox(vessel.get("add_water") is True)
    out["ADD-WaterDays"] = _str(vessel.get("add_water_days"))
    out["ADD-FoodAvail"] = _checkbox(vessel.get("add_food_avail") is True)
    out["ADD-FoodDays"] = _str(vessel.get("add_food_days"))
    out["ADD-OtherAvail1"] = _checkbox(vessel.get("add_other_avail_1") is True)
    out["ADD-OtherDesc1"] = _str(vessel.get("add_other_desc_1"))
    out["ADD-OtherAvail2"] = _checkbox(vessel.get("add_other_avail_2") is True)
    out["ADD-OtherDesc2"] = _str(vessel.get("add_other_desc_2"))
    out["ADD-OtherAvail3"] = _checkbox(vessel.get("add_other_avail_3") is True)
    out["ADD-OtherDesc3"] = _str(vessel.get("add_other_desc_3"))
    out["ADD-OtherAvail4"] = _checkbox(vessel.get("add_other_avail_4") is True)
    out["ADD-OtherDesc4"] = _str(vessel.get("add_other_desc_4"))

    # ---- Contact 1 & 2 (plan / itinerary, not vessel) ----
    out["Contact1"] = _str(vessel.get("contact1"))
    out["Contact1-Phone"] = _normalize_phone(vessel.get("contact1_phone"))
    out["Contact2"] = _str(vessel.get("contact2"))
    out["Contact2-Phone"] = _normalize_phone(vessel.get("contact2_phone"))
    out["RescueAuthority"] = _str(vessel.get("rescue_authority"))
    out["RescueAuthority-Phone"] = _normalize_phone(vessel.get("rescue_authority_phone"))
    out["ProviderContactInfo"] = ""

    # ---- Operator (OPR) ----
    op = crew.get("operator") or {}
    out["OPR-Name"] = _str(op.get("name"))
    out["OPR-Address"] = _str(op.get("address"))
    out["OPR-City"] = _str(op.get("city"))
    out["OPR-State"] = _str(op.get("state"))
    out["OPR-ZipCode"] = _str(op.get("zip_code"))
    out["OPR-Age"] = _str(op.get("age"))
    out["OPR-Gender"] = _gender(op.get("gender"))
    out["OPR-Home Phone"] = _normalize_phone(op.get("home_phone"))
    out["OPR-Note"] = _str(op.get("note"))
    out["OPR-PFD"] = _checkbox(op.get("pfd") in (True, "yes", "Yes"))
    out["OPR-PLBUIN"] = _str(op.get("plb_uin"))
    out["OPR-VehicleYearMakeModel"] = _str(op.get("vehicle_year_make_model"))
    out["OPR-VehicleLicenseNum"] = _str(op.get("vehicle_license_num"))
    out["OPR-VehicleParkedAt"] = _str(op.get("vehicle_parked_at"))
    out["OPR-VesselTrailored"] = _str(op.get("vessel_trailored"))
    out["OPR-AreaExperience"] = _str(op.get("area_experience"))
    out["OPR-VesselExperience"] = _str(op.get("vessel_experience"))
    out["OPR-Float Plan Note"] = _str(op.get("float_plan_note"))

    # ---- Persons on board POB-01 .. POB-12 ----
    persons = list(crew.get("persons") or [])[:12]
    for i, p in enumerate(persons):
        n = f"{i+1:02d}"
        out[f"POB-{n}Name"] = _str(p.get("name"))
        out[f"POB-{n}Age"] = _str(p.get("age"))
        out[f"POB-{n}Gender"] = _gender(p.get("gender"))
        # Passengers/Crew home phone: omit "+1" for field fit
        out[f"POB-{n}HomePhone"] = _normalize_phone_local(p.get("home_phone"))
        out[f"POB-{n}Note"] = _str(p.get("note"))
        out[f"POB-{n}PFD"] = _checkbox(p.get("pfd") in (True, "yes", "Yes"))
        out[f"POB-{n}PLBnum"] = _str(p.get("plb_uin"))
    for i in range(len(persons), 12):
        n = f"{i+1:02d}"
        for suf in ["Name", "Age", "Gender", "HomePhone", "Note", "PFD", "PLBnum"]:
            out[f"POB-{n}{suf}"] = ""

    # ---- Itinerary: Row 01 = first leg depart; Row 02 = first leg arrive + second leg depart; etc. ----
    legs = list(itinerary)[:21]
    if legs:
        out["01DepartDate"] = _str(legs[0].get("depart_date"))
        out["01DepartTime"] = _str(legs[0].get("depart_time"))
        out["01DepartLocation"] = _str(legs[0].get("depart_location"))
        out["01DepartMode"] = _str(legs[0].get("depart_mode"))
    for prefix_num in range(2, 22):  # rows 02..21: arrive from leg[prefix-2], depart from leg[prefix-1]
        prefix = f"{prefix_num:02d}"
        if prefix_num - 2 < len(legs):
            leg_arr = legs[prefix_num - 2]
            out[f"{prefix}ArriveDate"] = _str(leg_arr.get("arrive_date"))
            out[f"{prefix}ArriveTime"] = _str(leg_arr.get("arrive_time"))
            out[f"{prefix}ArriveLocation"] = _str(leg_arr.get("arrive_location"))
            out[f"{prefix}ArriveReason"] = _str(leg_arr.get("arrive_reason"))
            out[f"{prefix}ArriveCheckinTime"] = _str(leg_arr.get("arrive_checkin_time"))
        if prefix_num - 1 < len(legs):
            leg_dep = legs[prefix_num - 1]
            out[f"{prefix}DepartDate"] = _str(leg_dep.get("depart_date"))
            out[f"{prefix}DepartTime"] = _str(leg_dep.get("depart_time"))
            out[f"{prefix}DepartMode"] = _str(leg_dep.get("depart_mode"))
    # Clear unused itinerary rows
    for prefix_num in range(1, 22):
        prefix = f"{prefix_num:02d}"
        if prefix_num == 1:
            if len(legs) == 0:
                for k in ["01DepartDate", "01DepartTime", "01DepartLocation", "01DepartMode"]:
                    out[k] = ""
        else:
            if prefix_num - 2 >= len(legs):
                for suf in ["ArriveDate", "ArriveTime", "ArriveLocation", "ArriveReason", "ArriveCheckinTime"]:
                    out[f"{prefix}{suf}"] = ""
            if prefix_num - 1 >= len(legs):
                for suf in ["DepartDate", "DepartTime", "DepartMode"]:
                    out[f"{prefix}{suf}"] = ""

    return out


def fill_float_plan(
    template_path: str | Path,
    output_path: str | Path,
    vessel: dict,
    crew: dict,
    itinerary: list[dict],
) -> None:
    """Fill the template PDF and write to output_path."""
    template_path = Path(template_path)
    output_path = Path(output_path)
    field_values = build_field_map(vessel, crew, itinerary)

    reader = PdfReader(template_path)
    writer = PdfWriter()
    # clone_reader_document_root copies the full document (including all pages and AcroForm)
    writer.clone_reader_document_root(reader)

    # auto_regenerate=True sets NeedAppearances so viewers redraw checkboxes/choices
    for page in writer.pages:
        writer.update_page_form_field_values(
            page,
            field_values,
            auto_regenerate=True,
        )

    with open(output_path, "wb") as f:
        writer.write(f)
