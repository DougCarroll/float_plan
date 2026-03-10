#!/usr/bin/env python3
"""Float Plan GUI: configure vessel, crew, itinerary, and generate PDF."""
from __future__ import annotations

import json
import tkinter as tk
from datetime import datetime
from tkinter import ttk, filedialog
from pathlib import Path

from data_store import (
    load_vessels,
    save_vessels,
    load_crew_members,
    save_crew_members,
    DEFAULT_VESSEL,
    DEFAULT_PERSON,
)
from pdf_fill import fill_float_plan
from pdf_form_options import get_options, get_option_key_for_field
from rescue_authorities import RCC_NAMES, RCC_PHONE_BY_NAME

DATA_DIR = Path(__file__).resolve().parent
TEMPLATE_PDF = DATA_DIR / "USCGFloatPlan.pdf"


def _tk_alert(root: tk.Tk | tk.Toplevel, title: str, message: str) -> None:
    """Show a modal message dialog without using messagebox (avoids macOS NSAlert autorelease crash)."""
    top = tk.Toplevel(root)
    top.title(title)
    top.transient(root)
    top.grab_set()
    f = ttk.Frame(top, padding=15)
    f.pack(fill=tk.BOTH, expand=True)
    ttk.Label(f, text=message, wraplength=400).pack(pady=(0, 12))
    ttk.Button(f, text="OK", command=top.destroy).pack()
    top.protocol("WM_DELETE_WINDOW", top.destroy)
    top.wait_window()


# US country code used as default for phone formatting
DEFAULT_PHONE_COUNTRY = "+1"


def _format_phone(s: str) -> str:
    """Format a phone string with US country code by default: +1 (XXX) XXX-XXXX for 10 digits."""
    if not s:
        return ""
    digits = "".join(c for c in str(s).strip() if c.isdigit())
    # Strip leading 1 if 11 digits (US country code)
    if len(digits) == 11 and digits[0] == "1":
        digits = digits[1:]
    if len(digits) == 10:
        return f"{DEFAULT_PHONE_COUNTRY} ({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if len(digits) == 7:
        return f"{DEFAULT_PHONE_COUNTRY} {digits[:3]}-{digits[3:]}"
    return s.strip()


def _format_phone_entry(entry: tk.Entry) -> None:
    """Format the content of a phone entry in place (e.g. on FocusOut). Empty -> +1 (US default)."""
    s = entry.get().strip()
    if not s:
        entry.delete(0, tk.END)
        entry.insert(0, DEFAULT_PHONE_COUNTRY + " ")
        return
    formatted = _format_phone(s)
    if formatted != s:
        entry.delete(0, tk.END)
        entry.insert(0, formatted)


def _age_from_dob(dob_str: str) -> str:
    """Compute age in years from date-of-birth string. Returns "" if unparseable."""
    if not dob_str or not dob_str.strip():
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


def _copy_vessel_for_edit(v: dict) -> dict:
    """Return a mutable copy with all default keys."""
    out = {**DEFAULT_VESSEL, **{k: v for k, v in v.items() if k in DEFAULT_VESSEL}}
    out.setdefault("id", "")
    out.setdefault("name", "")
    return out


def _copy_person_for_edit(p: dict) -> dict:
    """Return a full person dict suitable for editing (operator-style fields)."""
    return {**DEFAULT_PERSON, **{k: (p.get(k) or "") for k in DEFAULT_PERSON}}


class FloatPlanApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Float Plan")
        self.root.minsize(500, 400)
        self.vessels = load_vessels()
        self.crew_members: list[dict] = load_crew_members()
        self.vessel: dict = _copy_vessel_for_edit(DEFAULT_VESSEL)
        self.vessel["name"] = "(No vessel selected)"
        self.selected_operator_index: int | None = None
        self.on_board_indices: set[int] = set()
        self._on_board_vars: dict[int, tk.BooleanVar] = {}
        self.itinerary: list[dict] = []
        # Rescue authority is per itinerary (where you are), not per vessel
        self.rescue_authority = ""
        self.rescue_authority_phone = ""
        self.contact1 = ""
        self.contact1_phone = ""
        self.contact2 = ""
        self.contact2_phone = ""
        # Operator experience (per plan) – does the operator have experience with this vessel and these areas?
        self.operator_has_vessel_experience = False
        self.operator_has_area_experience = False
        self._build_ui()
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(1000, lambda: self.root.attributes("-topmost", False))

    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # Vessel
        ttk.Label(main, text="Vessel").grid(row=0, column=0, sticky=tk.W)
        self.vessel_var = tk.StringVar()
        self.vessel_combo = ttk.Combobox(main, textvariable=self.vessel_var, width=35, state="readonly")
        self.vessel_combo.grid(row=0, column=1, sticky=tk.EW, padx=(8, 4))
        self._refresh_vessel_combo()
        ttk.Button(main, text="New vessel", command=self._new_vessel).grid(row=0, column=2, padx=2)
        ttk.Button(main, text="Edit vessel", command=self._edit_vessel).grid(row=0, column=3, padx=2)
        self.vessel_combo.bind("<<ComboboxSelected>>", self._on_vessel_selected)

        # Crew members (pool) + operator and on-board for this plan
        ttk.Label(main, text="Crew members").grid(row=1, column=0, sticky=tk.NW, pady=(4, 0))
        crew_list_frame = ttk.Frame(main)
        crew_list_frame.grid(row=2, column=0, columnspan=4, sticky=tk.EW, pady=2)
        self.crew_members_listbox = tk.Listbox(crew_list_frame, height=3, width=40)
        self.crew_members_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        crew_btns = ttk.Frame(crew_list_frame)
        crew_btns.pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(crew_btns, text="Add crew member", command=self._add_crew_member).pack(fill=tk.X, pady=2)
        ttk.Button(crew_btns, text="Edit crew member", command=self._edit_crew_member).pack(fill=tk.X, pady=2)

        ttk.Label(main, text="Operator (for this plan)").grid(row=3, column=0, sticky=tk.W, pady=(6, 2))
        self.operator_var = tk.StringVar()
        self.operator_combo = ttk.Combobox(main, textvariable=self.operator_var, width=35, state="readonly")
        self.operator_combo.grid(row=3, column=1, sticky=tk.EW, padx=(8, 4), pady=(6, 2))
        self.operator_combo.bind("<<ComboboxSelected>>", self._on_operator_selected)

        ttk.Label(main, text="On board for this plan").grid(row=4, column=0, sticky=tk.NW, pady=(4, 2))
        self.on_board_frame = ttk.Frame(main)
        self.on_board_frame.grid(row=5, column=0, columnspan=4, sticky=tk.EW, pady=2)

        self._refresh_crew_members_list()

        # Itinerary
        ttk.Label(main, text="Itinerary").grid(row=6, column=0, sticky=tk.NW, pady=(8, 0))
        it_frame = ttk.Frame(main)
        it_frame.grid(row=7, column=0, columnspan=4, sticky=tk.EW, pady=4)
        self.itinerary_list = tk.Listbox(it_frame, height=6, width=60)
        self.itinerary_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        it_btns = ttk.Frame(it_frame)
        it_btns.pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(it_btns, text="Add leg", command=self._add_leg).pack(fill=tk.X, pady=2)
        ttk.Button(it_btns, text="Remove leg", command=self._remove_leg).pack(fill=tk.X, pady=2)
        self._refresh_itinerary_display()

        # Rescue authority (on itinerary page)
        ttk.Label(main, text="Rescue authority").grid(row=8, column=0, sticky=tk.W, pady=(8, 2))
        self.rescue_combo = ttk.Combobox(main, width=33, values=RCC_NAMES, state="readonly")
        self.rescue_combo.grid(row=8, column=1, sticky=tk.EW, padx=(8, 4), pady=(8, 2))
        self.rescue_combo.bind("<<ComboboxSelected>>", self._on_rescue_selected)
        ttk.Label(main, text="Rescue authority phone").grid(row=9, column=0, sticky=tk.W, pady=2)
        self.rescue_phone_e = ttk.Entry(main, width=35)
        self.rescue_phone_e.grid(row=9, column=1, sticky=tk.EW, padx=(8, 4), pady=2)
        self.rescue_phone_e.bind("<FocusOut>", self._on_rescue_phone_focusout)
        self._refresh_rescue_ui()

        # Contact 1 & 2 (on itinerary / plan)
        ttk.Label(main, text="Contact 1").grid(row=10, column=0, sticky=tk.W, pady=(8, 2))
        self.contact1_e = ttk.Entry(main, width=35)
        self.contact1_e.grid(row=10, column=1, sticky=tk.EW, padx=(8, 4), pady=(8, 2))
        ttk.Label(main, text="Contact 1 phone").grid(row=11, column=0, sticky=tk.W, pady=2)
        self.contact1_phone_e = ttk.Entry(main, width=35)
        self.contact1_phone_e.grid(row=11, column=1, sticky=tk.EW, padx=(8, 4), pady=2)
        ttk.Label(main, text="Contact 2").grid(row=12, column=0, sticky=tk.W, pady=2)
        self.contact2_e = ttk.Entry(main, width=35)
        self.contact2_e.grid(row=12, column=1, sticky=tk.EW, padx=(8, 4), pady=2)
        ttk.Label(main, text="Contact 2 phone").grid(row=13, column=0, sticky=tk.W, pady=2)
        self.contact2_phone_e = ttk.Entry(main, width=35)
        self.contact2_phone_e.grid(row=13, column=1, sticky=tk.EW, padx=(8, 4), pady=2)
        self.contact1_e.bind("<FocusOut>", self._on_contact_changed)
        self.contact1_phone_e.bind("<FocusOut>", self._on_contact_phone_focusout)
        self.contact2_e.bind("<FocusOut>", self._on_contact_changed)
        self.contact2_phone_e.bind("<FocusOut>", self._on_contact_phone_focusout)
        self._refresh_contact_ui()

        # Operator experience (on itinerary page)
        ttk.Label(main, text="Does the operator have experience with:").grid(row=14, column=0, columnspan=2, sticky=tk.W, pady=(8, 2))
        self.op_has_vessel_exp_var = tk.BooleanVar(value=self.operator_has_vessel_experience)
        self.op_has_area_exp_var = tk.BooleanVar(value=self.operator_has_area_experience)
        ttk.Checkbutton(main, text="This vessel", variable=self.op_has_vessel_exp_var, command=self._on_operator_experience_changed).grid(row=15, column=0, columnspan=2, sticky=tk.W, padx=(8, 0))
        ttk.Checkbutton(main, text="These boating areas", variable=self.op_has_area_exp_var, command=self._on_operator_experience_changed).grid(row=16, column=0, columnspan=2, sticky=tk.W, padx=(8, 0))

        # Save / Open plan & Generate PDF
        btn_row = ttk.Frame(main)
        btn_row.grid(row=17, column=0, columnspan=4, pady=16)
        ttk.Button(btn_row, text="Save plan…", command=self._save_plan).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Open plan…", command=self._open_plan).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Generate PDF…", command=self._generate_pdf).pack(side=tk.LEFT)

        main.columnconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

    def _refresh_vessel_combo(self):
        names = [v.get("name") or v.get("id_vessel_name") or "Unnamed" for v in self.vessels]
        self.vessel_combo["values"] = names
        if names and (not self.vessel.get("name") or self.vessel.get("name") == "(No vessel selected)"):
            self.vessel_combo.current(0)
            self._on_vessel_selected(None)
        elif not names:
            self.vessel_combo.set("")

    def _refresh_crew_members_list(self):
        self.crew_members_listbox.delete(0, tk.END)
        for m in self.crew_members:
            self.crew_members_listbox.insert(tk.END, m.get("name") or "Unnamed")
        names = [m.get("name") or "Unnamed" for m in self.crew_members]
        self.operator_combo["values"] = names
        if names and self.selected_operator_index is None:
            self.selected_operator_index = 0
            self.operator_combo.current(0)
        if names and self.selected_operator_index is not None and self.selected_operator_index < len(names):
            self.operator_combo.current(self.selected_operator_index)
        elif not names:
            self.selected_operator_index = None
            self.operator_combo.set("")
        self._refresh_on_board_checkboxes()

    def _refresh_on_board_checkboxes(self):
        for w in self.on_board_frame.winfo_children():
            w.destroy()
        self._on_board_vars.clear()
        for i, m in enumerate(self.crew_members):
            name = m.get("name") or "Unnamed"
            v = tk.BooleanVar(value=i in self.on_board_indices)
            self._on_board_vars[i] = v
            cb = ttk.Checkbutton(self.on_board_frame, text=name, variable=v, command=lambda idx=i: self._on_on_board_toggled(idx))
            cb.pack(anchor=tk.W)

    def _on_on_board_toggled(self, index: int):
        if self._on_board_vars[index].get():
            self.on_board_indices.add(index)
        else:
            self.on_board_indices.discard(index)

    def _on_operator_selected(self, ev=None):
        i = self.operator_combo.current()
        if i is not None and 0 <= i < len(self.crew_members):
            self.selected_operator_index = i
            self.on_board_indices.add(i)
            if i in self._on_board_vars:
                self._on_board_vars[i].set(True)

    def _on_vessel_selected(self, ev):
        i = self.vessel_combo.current()
        if i is not None and 0 <= i < len(self.vessels):
            self.vessel = _copy_vessel_for_edit(self.vessels[i])

    def _refresh_rescue_ui(self):
        """Sync rescue authority widgets from plan state (itinerary), not vessel."""
        self.rescue_combo.set(self.rescue_authority or "")
        self.rescue_phone_e.delete(0, tk.END)
        self.rescue_phone_e.insert(0, _format_phone(self.rescue_authority_phone or "") or self.rescue_authority_phone or "")

    def _on_rescue_selected(self, ev=None):
        name = self.rescue_combo.get().strip()
        raw = RCC_PHONE_BY_NAME.get(name, "")
        self.rescue_phone_e.delete(0, tk.END)
        self.rescue_phone_e.insert(0, _format_phone(raw) or raw)
        self.rescue_authority = name
        self.rescue_authority_phone = self.rescue_phone_e.get().strip()

    def _on_rescue_phone_focusout(self, ev=None):
        _format_phone_entry(self.rescue_phone_e)
        self.rescue_authority_phone = self.rescue_phone_e.get().strip()

    def _refresh_contact_ui(self):
        self.contact1_e.delete(0, tk.END)
        self.contact1_e.insert(0, self.contact1 or "")
        self.contact1_phone_e.delete(0, tk.END)
        self.contact1_phone_e.insert(0, _format_phone(self.contact1_phone or "") or self.contact1_phone or "")
        self.contact2_e.delete(0, tk.END)
        self.contact2_e.insert(0, self.contact2 or "")
        self.contact2_phone_e.delete(0, tk.END)
        self.contact2_phone_e.insert(0, _format_phone(self.contact2_phone or "") or self.contact2_phone or "")

    def _on_contact_phone_focusout(self, ev=None):
        _format_phone_entry(self.contact1_phone_e)
        _format_phone_entry(self.contact2_phone_e)
        self._on_contact_changed()

    def _on_contact_changed(self, ev=None):
        self.contact1 = self.contact1_e.get().strip()
        self.contact1_phone = self.contact1_phone_e.get().strip()
        self.contact2 = self.contact2_e.get().strip()
        self.contact2_phone = self.contact2_phone_e.get().strip()

    def _on_operator_experience_changed(self):
        self.operator_has_vessel_experience = self.op_has_vessel_exp_var.get()
        self.operator_has_area_experience = self.op_has_area_exp_var.get()

    def _new_vessel(self):
        self._open_vessel_editor(_copy_vessel_for_edit(DEFAULT_VESSEL), is_new=True)

    def _edit_vessel(self):
        if not self.vessels:
            _tk_alert(self.root, "Edit vessel", "No vessel selected. Create one with 'New vessel'.")
            return
        i = self.vessel_combo.current()
        if i is None or i < 0:
            i = 0
        self._open_vessel_editor(_copy_vessel_for_edit(self.vessels[i]), index=i)

    def _open_vessel_editor(self, vessel: dict, is_new: bool = False, index: int | None = None):
        win = tk.Toplevel(self.root)
        win.title("New vessel" if is_new else "Edit vessel")
        win.transient(self.root)
        win.grab_set()
        f = ttk.Frame(win, padding=10)
        f.pack(fill=tk.BOTH, expand=True)
        nb = ttk.Notebook(f)
        nb.pack(fill=tk.BOTH, expand=True)

        # Identity
        id_f = ttk.Frame(nb, padding=5)
        nb.add(id_f, text="Vessel identity")
        rows = [
            ("Vessel name", "id_vessel_name"),
            ("Home port", "id_home_port"),
            ("Doc/Reg No", "id_doc_reg_num"),
            ("HIN", "id_hin"),
            ("Year, make, model", "id_year_make_model"),
            ("Length", "id_length"),
            ("Type", "id_type"),
            ("Draft", "id_draft"),
            ("Hull material", "id_hull_mat"),
            ("Hull/trim colors", "id_hull_trim_colors"),
            ("Prominent features", "id_prominent_features"),
        ]
        for r, (label, key) in enumerate(rows):
            ttk.Label(id_f, text=label).grid(row=r, column=0, sticky=tk.W, pady=2)
            val = str(vessel.get(key, ""))
            options_key = get_option_key_for_field(key)
            if options_key:
                opts = get_options(options_key)
                e = ttk.Combobox(id_f, width=37, values=opts, state="readonly")
                if val:
                    e.set(val)
            else:
                e = ttk.Entry(id_f, width=40)
                e.insert(0, val)
            e.grid(row=r, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
            vessel["_e_" + key] = e
        id_f.columnconfigure(1, weight=1)

        # Communications
        com_f = ttk.Frame(nb, padding=5)
        nb.add(com_f, text="Communications")
        rows = [
            ("Radio call sign", "com_radio_call_sign"),
            ("DSC/MMSI No", "com_dsc_no"),
            ("Radio 1 type", "com_radio1_type"),
            ("Radio 1 freq/ch monitored", "com_radio1_freq_mon"),
            ("Radio 2 type", "com_radio2_type"),
            ("Radio 2 freq/ch monitored", "com_radio2_freq_mon"),
            ("Cell/sat phone", "com_cell_sat_phone"),
            ("Email", "com_email"),
        ]
        for r, (label, key) in enumerate(rows):
            ttk.Label(com_f, text=label).grid(row=r, column=0, sticky=tk.W, pady=2)
            val = str(vessel.get(key, ""))
            # Radio 1 type and Radio 2 type use COM-RadioType dropdown (None, CB, HF, MF, VHF-FM)
            options_key = get_option_key_for_field(key) or ("COM-RadioType" if key in ("com_radio1_type", "com_radio2_type") else None)
            if options_key:
                opts = get_options(options_key)
                e = ttk.Combobox(com_f, width=37, values=opts, state="readonly")
                if val:
                    e.set(val)
            else:
                e = ttk.Entry(com_f, width=40)
                e.insert(0, val)
            e.grid(row=r, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
            vessel["_e_" + key] = e
        com_f.columnconfigure(1, weight=1)

        # Propulsion
        pro_f = ttk.Frame(nb, padding=5)
        nb.add(pro_f, text="Propulsion")
        rows = [
            ("Primary type", "pro_prim_eng_type"),
            ("Primary no. engines", "pro_prim_num_engines"),
            ("Primary fuel (gal/L)", "pro_prim_fuel_capacity"),
            ("Aux type", "pro_aux_eng_type"),
            ("Aux no. engines", "pro_aux_num_eng"),
            ("Aux fuel (gal/L)", "pro_aux_fuel_capacity"),
        ]
        for r, (label, key) in enumerate(rows):
            ttk.Label(pro_f, text=label).grid(row=r, column=0, sticky=tk.W, pady=2)
            val = str(vessel.get(key, ""))
            options_key = get_option_key_for_field(key)
            if options_key:
                opts = get_options(options_key)
                e = ttk.Combobox(pro_f, width=37, values=opts, state="readonly")
                if val:
                    e.set(val)
            else:
                e = ttk.Entry(pro_f, width=40)
                e.insert(0, val)
            e.grid(row=r, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
            vessel["_e_" + key] = e
        pro_f.columnconfigure(1, weight=1)

        # Navigation
        nav_f = ttk.Frame(nb, padding=5)
        nb.add(nav_f, text="Navigation")
        checks = [
            ("Maps", "nav_maps"),
            ("Charts", "nav_charts"),
            ("Compass", "nav_compass"),
            ("GPS/DGPS", "nav_gps"),
            ("Depth sounder", "nav_depth_sounder"),
            ("Radar", "nav_radar"),
            ("Other", "nav_other_avail"),
        ]
        for r, (label, key) in enumerate(checks):
            v = tk.BooleanVar(value=bool(vessel.get(key)))
            ttk.Checkbutton(nav_f, text=label, variable=v).grid(row=r, column=0, columnspan=2, sticky=tk.W, pady=2)
            vessel["_v_" + key] = v
        ttk.Label(nav_f, text="Other description").grid(row=len(checks), column=0, sticky=tk.W, pady=2)
        e = ttk.Entry(nav_f, width=40)
        e.grid(row=len(checks), column=1, sticky=tk.EW, padx=(8, 0), pady=2)
        e.insert(0, str(vessel.get("nav_user_desc", "")))
        vessel["_e_nav_user_desc"] = e
        nav_f.columnconfigure(1, weight=1)

        # Safety & Survival
        safe_f = ttk.Frame(nb, padding=5)
        nb.add(safe_f, text="Safety & survival")
        row = 0
        ttk.Label(safe_f, text="Visual Distress Signals", font=("", 10, "bold")).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(0, 4))
        row += 1
        for label, key in [
            ("Electric Distress Light (night only)", "vds_edl"),
            ("Flag (day only)", "vds_flag"),
            ("Flare, Aerial (day & night)", "vds_flare_aerial"),
            ("Flare, Handheld (day & night)", "vds_flare_handheld"),
            ("Signal Mirror (day only)", "vds_signal_mirror"),
            ("Smoke (day only)", "vds_smoke"),
        ]:
            v = tk.BooleanVar(value=bool(vessel.get(key)))
            ttk.Checkbutton(safe_f, text=label, variable=v).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=1)
            vessel["_v_" + key] = v
            row += 1
        ttk.Label(safe_f, text="Audible Distress Signals", font=("", 10, "bold")).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(8, 4))
        row += 1
        for label, key in [
            ("Bell", "ads_bell"),
            ("Horn", "ads_horn"),
            ("Whistle", "ads_whistle"),
        ]:
            v = tk.BooleanVar(value=bool(vessel.get(key)))
            ttk.Checkbutton(safe_f, text=label, variable=v).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=1)
            vessel["_v_" + key] = v
            row += 1
        ttk.Label(safe_f, text="EPIRB UIN").grid(row=row, column=0, sticky=tk.W, pady=2)
        e = ttk.Entry(safe_f, width=25)
        e.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
        e.insert(0, str(vessel.get("epirb_uin", "")))
        vessel["_e_epirb_uin"] = e
        row += 1
        # Anchor: checkbox and anchor line length on same line
        v = tk.BooleanVar(value=bool(vessel.get("add_anchor")))
        ttk.Checkbutton(safe_f, text="Anchor", variable=v).grid(row=row, column=0, sticky=tk.W, pady=2)
        vessel["_v_add_anchor"] = v
        anchor_f = ttk.Frame(safe_f)
        anchor_f.grid(row=row, column=1, sticky=tk.W, padx=(8, 0), pady=2)
        ttk.Label(anchor_f, text="Anchor line length").pack(side=tk.LEFT, padx=(0, 4))
        e = ttk.Entry(anchor_f, width=12)
        e.pack(side=tk.LEFT)
        e.insert(0, str(vessel.get("add_anchor_line_length", "")))
        vessel["_e_add_anchor_line_length"] = e
        row += 1
        # Checkboxes only: Dewatering, Exposure suits, Fire extinguisher, Flashlight, Raft/Dinghy
        for label, key in [
            ("Dewatering Device", "add_dewatering"),
            ("Exposure suits", "add_exposure_suit"),
            ("Fire extinguisher", "add_fire_extinguisher"),
            ("Flashlight/Search light", "add_flashlight"),
            ("Raft/Dinghy", "add_raft"),
        ]:
            v = tk.BooleanVar(value=bool(vessel.get(key)))
            ttk.Checkbutton(safe_f, text=label, variable=v).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=1)
            vessel["_v_" + key] = v
            row += 1
        # Food: checkbox and Days/Person on same line
        v = tk.BooleanVar(value=bool(vessel.get("add_food_avail")))
        ttk.Checkbutton(safe_f, text="Food", variable=v).grid(row=row, column=0, sticky=tk.W, pady=2)
        vessel["_v_add_food_avail"] = v
        food_f = ttk.Frame(safe_f)
        food_f.grid(row=row, column=1, sticky=tk.W, padx=(8, 0), pady=2)
        ttk.Label(food_f, text="Days / Person").pack(side=tk.LEFT, padx=(0, 4))
        e = ttk.Entry(food_f, width=8)
        e.pack(side=tk.LEFT)
        e.insert(0, str(vessel.get("add_food_days", "")))
        vessel["_e_add_food_days"] = e
        row += 1
        # Water: checkbox and Days/Person on same line
        v = tk.BooleanVar(value=bool(vessel.get("add_water")))
        ttk.Checkbutton(safe_f, text="Water", variable=v).grid(row=row, column=0, sticky=tk.W, pady=2)
        vessel["_v_add_water"] = v
        water_f = ttk.Frame(safe_f)
        water_f.grid(row=row, column=1, sticky=tk.W, padx=(8, 0), pady=2)
        ttk.Label(water_f, text="Days / Person").pack(side=tk.LEFT, padx=(0, 4))
        e = ttk.Entry(water_f, width=8)
        e.pack(side=tk.LEFT)
        e.insert(0, str(vessel.get("add_water_days", "")))
        vessel["_e_add_water_days"] = e
        row += 1
        for i in range(1, 5):
            v = tk.BooleanVar(value=bool(vessel.get(f"add_other_avail_{i}")))
            ttk.Checkbutton(safe_f, text=f"Other {i}", variable=v).grid(row=row, column=0, sticky=tk.W, pady=1)
            vessel["_v_add_other_avail_" + str(i)] = v
            e = ttk.Entry(safe_f, width=25)
            e.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=1)
            e.insert(0, str(vessel.get(f"add_other_desc_{i}", "")))
            vessel["_e_add_other_desc_" + str(i)] = e
            row += 1
        safe_f.columnconfigure(1, weight=1)

        def save_vessel_from_editor():
            for key in list(DEFAULT_VESSEL.keys()):
                if key in ("id", "name"):
                    continue
                if "_e_" + key in vessel:
                    vessel[key] = vessel["_e_" + key].get().strip()
                if "_v_" + key in vessel:
                    vessel[key] = vessel["_v_" + key].get()
            for i in range(1, 5):
                if "_v_add_other_avail_" + str(i) in vessel:
                    vessel["add_other_avail_" + str(i)] = vessel["_v_add_other_avail_" + str(i)].get()
                if "_e_add_other_desc_" + str(i) in vessel:
                    vessel["add_other_desc_" + str(i)] = vessel["_e_add_other_desc_" + str(i)].get().strip()
            vessel["name"] = vessel.get("id_vessel_name") or vessel.get("name") or "Unnamed"
            # Save a clean copy without UI refs
            clean = {k: v for k, v in vessel.items() if not k.startswith("_") and k in DEFAULT_VESSEL}
            clean["id"] = vessel.get("id", "")
            clean["name"] = vessel["name"]
            if is_new:
                self.vessels.append(clean)
            elif index is not None:
                self.vessels[index] = clean
            save_vessels(self.vessels)
            self.vessel = _copy_vessel_for_edit(clean)
            self._refresh_vessel_combo()
            for i, v in enumerate(self.vessels):
                if v.get("id_vessel_name") == clean.get("id_vessel_name") and v.get("id_doc_reg_num") == clean.get("id_doc_reg_num"):
                    self.vessel_combo.current(i)
                    break
            win.destroy()

        btn_f = ttk.Frame(f)
        btn_f.pack(pady=(8, 0))
        ttk.Button(btn_f, text="Cancel", command=win.destroy).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_f, text="Save", command=save_vessel_from_editor).pack(side=tk.LEFT)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

    def _add_crew_member(self):
        self._open_crew_member_editor(_copy_person_for_edit({}), is_new=True)

    def _edit_crew_member(self):
        i = self.crew_members_listbox.curselection()
        if not i:
            _tk_alert(self.root, "Edit crew member", "Select a crew member to edit.")
            return
        idx = int(i[0])
        if idx < 0 or idx >= len(self.crew_members):
            return
        self._open_crew_member_editor(_copy_person_for_edit(self.crew_members[idx]), index=idx)

    def _open_crew_member_editor(self, person: dict, is_new: bool = False, index: int | None = None):
        win = tk.Toplevel(self.root)
        win.title("New crew member" if is_new else "Edit crew member")
        win.transient(self.root)
        win.grab_set()
        win.minsize(400, 420)
        outer = ttk.Frame(win, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)
        form_f = ttk.Frame(outer)
        form_f.pack(fill=tk.BOTH, expand=True)
        rows = [
            ("Name", "name"), ("Address", "address"), ("City", "city"), ("State", "state"), ("Zip", "zip_code"),
            ("Gender", "gender"), ("Home phone", "home_phone"), ("Note", "note"),
            ("PFD", "pfd"), ("PLB UIN", "plb_uin"),
            ("Vehicle year/make/model", "vehicle_year_make_model"), ("Vehicle license", "vehicle_license_num"),
            ("Vehicle parked at", "vehicle_parked_at"), ("Vessel trailered", "vessel_trailored"),
            ("Float plan note", "float_plan_note"),
        ]
        r = 0
        person["_dob_e"] = None
        person["_age_label"] = None
        for label, key in rows:
            if key == "gender":
                ttk.Label(form_f, text="Gender").grid(row=r, column=0, sticky=tk.W, pady=1)
                gender_opts = get_options(get_option_key_for_field("gender") or "OPR-Gender")
                gender_combo = ttk.Combobox(form_f, width=33, values=gender_opts, state="readonly")
                gval = str(person.get("gender", "")).strip()
                if gval in gender_opts:
                    gender_combo.set(gval)
                elif gval.upper() in ("M", "F"):
                    gender_combo.set(gval.upper())
                else:
                    gender_combo.current(0)
                gender_combo.grid(row=r, column=1, sticky=tk.EW, padx=(8, 0), pady=1)
                person["_e_gender"] = gender_combo
                r += 1
                ttk.Label(form_f, text="Date of birth").grid(row=r, column=0, sticky=tk.W, pady=1)
                dob_e = ttk.Entry(form_f, width=35)
                dob_e.insert(0, str(person.get("dob", "")))
                dob_e.grid(row=r, column=1, sticky=tk.EW, padx=(8, 0), pady=1)
                person["_dob_e"] = dob_e
                r += 1
                ttk.Label(form_f, text="Age").grid(row=r, column=0, sticky=tk.W, pady=1)
                age_label = ttk.Label(form_f, text=person.get("age") or _age_from_dob(person.get("dob", "")) or "—")
                age_label.grid(row=r, column=1, sticky=tk.W, padx=(8, 0), pady=1)
                person["_age_label"] = age_label

                def dob_changed(_event=None):
                    age = _age_from_dob(dob_e.get().strip())
                    age_label.config(text=age or "—")

                dob_e.bind("<KeyRelease>", dob_changed)
                dob_e.bind("<FocusOut>", dob_changed)
                r += 1
            elif key == "pfd":
                pfd_var = tk.BooleanVar(value=(str(person.get("pfd", "")).strip().lower() in ("yes", "true", "1")))
                person["_v_pfd"] = pfd_var
                ttk.Checkbutton(form_f, text="PFD (life jacket)", variable=pfd_var).grid(row=r, column=0, columnspan=2, sticky=tk.W, pady=1)
                r += 1
            else:
                ttk.Label(form_f, text=label).grid(row=r, column=0, sticky=tk.W, pady=1)
                val = str(person.get(key, ""))
                if key == "home_phone":
                    val = _format_phone(val) or (DEFAULT_PHONE_COUNTRY + " " if not val.strip() else val)
                options_key = get_option_key_for_field(key)
                if options_key:
                    opts = get_options(options_key)
                    e = ttk.Combobox(form_f, width=33, values=opts, state="readonly")
                    if val:
                        e.set(val)
                else:
                    e = ttk.Entry(form_f, width=35)
                    e.insert(0, val)
                e.grid(row=r, column=1, sticky=tk.EW, padx=(8, 0), pady=1)
                person["_e_" + key] = e
                if key == "home_phone":
                    e.bind("<FocusOut>", lambda ev, ent=e: _format_phone_entry(ent))
                r += 1
        form_f.columnconfigure(1, weight=1)

        def save_crew_member():
            if "_e_home_phone" in person:
                _format_phone_entry(person["_e_home_phone"])
            person["dob"] = person["_dob_e"].get().strip()
            person["age"] = _age_from_dob(person["dob"]) if person["dob"] else ""
            if "_v_pfd" in person:
                person["pfd"] = "Yes" if person["_v_pfd"].get() else ""
            for key in ["name", "address", "city", "state", "zip_code", "gender", "home_phone", "note", "plb_uin",
                        "vehicle_year_make_model", "vehicle_license_num", "vehicle_parked_at", "vessel_trailored", "float_plan_note"]:
                if "_e_" + key in person:
                    person[key] = person["_e_" + key].get().strip()
            clean = {k: person.get(k, "") for k in DEFAULT_PERSON}
            if is_new:
                self.crew_members.append(clean)
            elif index is not None:
                self.crew_members[index] = clean
            save_crew_members(self.crew_members)
            self._refresh_crew_members_list()
            win.destroy()

        ttk.Separator(outer, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(12, 8))
        btn_f = ttk.Frame(outer)
        btn_f.pack(fill=tk.X)
        ttk.Button(btn_f, text="Save", command=save_crew_member).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_f, text="Cancel", command=win.destroy).pack(side=tk.LEFT)
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)

    def _add_leg(self):
        """Open dialog to add one leg with both departure and arrival."""
        self._add_leg_dialog()

    def _add_leg_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("Add leg")
        win.minsize(360, 380)
        win.transient(self.root)
        win.grab_set()
        outer = ttk.Frame(win, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)
        form_f = ttk.Frame(outer)
        form_f.pack(fill=tk.BOTH, expand=True)
        depart_mode_opts = get_options(get_option_key_for_field("depart_mode") or "01DepartMode")
        row = 0

        # Departure
        ttk.Label(form_f, text="Departure", font=("", 10, "bold")).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(0, 4))
        row += 1
        ttk.Label(form_f, text="Departure date").grid(row=row, column=0, sticky=tk.W, pady=2)
        e_date = ttk.Entry(form_f, width=15)
        e_date.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
        row += 1
        ttk.Label(form_f, text="Departure time").grid(row=row, column=0, sticky=tk.W, pady=2)
        e_time = ttk.Entry(form_f, width=15)
        e_time.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
        row += 1
        ttk.Label(form_f, text="Departure location").grid(row=row, column=0, sticky=tk.W, pady=2)
        e_loc = ttk.Entry(form_f, width=35)
        e_loc.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
        row += 1
        ttk.Label(form_f, text="Mode of travel").grid(row=row, column=0, sticky=tk.W, pady=2)
        e_mode = ttk.Combobox(form_f, width=18, values=depart_mode_opts, state="readonly")
        e_mode.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
        row += 1

        # Arrival
        ttk.Label(form_f, text="Arrival", font=("", 10, "bold")).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(12, 4))
        row += 1
        ttk.Label(form_f, text="Arrival date").grid(row=row, column=0, sticky=tk.W, pady=2)
        e_ad = ttk.Entry(form_f, width=15)
        e_ad.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
        row += 1
        ttk.Label(form_f, text="Arrival time").grid(row=row, column=0, sticky=tk.W, pady=2)
        e_at = ttk.Entry(form_f, width=15)
        e_at.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
        row += 1
        ttk.Label(form_f, text="Arrival location").grid(row=row, column=0, sticky=tk.W, pady=2)
        e_al = ttk.Entry(form_f, width=35)
        e_al.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
        row += 1
        ttk.Label(form_f, text="Reason for stop").grid(row=row, column=0, sticky=tk.W, pady=2)
        e_reason = ttk.Entry(form_f, width=25)
        e_reason.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
        row += 1

        def save():
            leg = {
                "depart_date": e_date.get().strip(), "depart_time": e_time.get().strip(),
                "depart_location": e_loc.get().strip(), "depart_mode": e_mode.get().strip(),
                "arrive_date": e_ad.get().strip(), "arrive_time": e_at.get().strip(),
                "arrive_location": e_al.get().strip(), "arrive_reason": e_reason.get().strip(),
            }
            self.itinerary.append(leg)
            self._refresh_itinerary_display()
            win.destroy()

        form_f.columnconfigure(1, weight=1)
        ttk.Separator(outer, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(12, 8))
        btn_f = ttk.Frame(outer)
        btn_f.pack(fill=tk.X)
        ttk.Button(btn_f, text="Save", command=save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_f, text="Cancel", command=win.destroy).pack(side=tk.LEFT)

    def _remove_leg(self):
        i = self.itinerary_list.curselection()
        if not i:
            _tk_alert(self.root, "Remove", "Select a leg to remove.")
            return
        idx = int(i[0])
        if 0 <= idx < len(self.itinerary):
            self.itinerary.pop(idx)
            self._refresh_itinerary_display()

    def _refresh_itinerary_display(self):
        self.itinerary_list.delete(0, tk.END)
        for i, leg in enumerate(self.itinerary):
            dep = f"Depart: {leg.get('depart_date')} {leg.get('depart_time')} @ {leg.get('depart_location')} ({leg.get('depart_mode')})"
            arr = f"Arrive: {leg.get('arrive_date')} {leg.get('arrive_time')} @ {leg.get('arrive_location')}" + (f" — {leg.get('arrive_reason')}" if leg.get('arrive_reason') else "")
            if leg.get('arrive_date') or leg.get('arrive_location'):
                self.itinerary_list.insert(tk.END, f"{dep} → {arr}")
            else:
                self.itinerary_list.insert(tk.END, dep)

    def _save_plan(self):
        """Save current plan state to a .floatplan JSON file for later edit."""
        self._on_contact_changed()
        for i, v in self._on_board_vars.items():
            if v.get():
                self.on_board_indices.add(i)
            else:
                self.on_board_indices.discard(i)
        vessel_name = (self.vessel.get("name") or self.vessel.get("id_vessel_name") or "").strip()
        if vessel_name == "(No vessel selected)":
            vessel_name = ""
        operator_name = ""
        if self.selected_operator_index is not None and 0 <= self.selected_operator_index < len(self.crew_members):
            operator_name = (self.crew_members[self.selected_operator_index].get("name") or "").strip()
        on_board_names = []
        for i in self.on_board_indices:
            if 0 <= i < len(self.crew_members):
                name = (self.crew_members[i].get("name") or "").strip()
                if name and name not in on_board_names:
                    on_board_names.append(name)
        plan = {
            "version": 1,
            "vessel_name": vessel_name,
            "operator_name": operator_name,
            "on_board_names": on_board_names,
            "itinerary": self.itinerary,
            "rescue_authority": self.rescue_authority,
            "rescue_authority_phone": self.rescue_authority_phone,
            "contact1": self.contact1,
            "contact1_phone": self.contact1_phone,
            "contact2": self.contact2,
            "contact2_phone": self.contact2_phone,
            "operator_has_vessel_experience": self.operator_has_vessel_experience,
            "operator_has_area_experience": self.operator_has_area_experience,
        }
        path = filedialog.asksaveasfilename(
            defaultextension=".floatplan",
            filetypes=[("Float plan", "*.floatplan"), ("JSON", "*.json")],
            initialfile="float_plan.floatplan",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2)
            _tk_alert(self.root, "Saved", f"Plan saved to {path}")
        except Exception as e:
            _tk_alert(self.root, "Error", str(e))

    def _open_plan(self):
        """Load a saved .floatplan file using the native file dialog."""
        start_dir = DATA_DIR if DATA_DIR.exists() else Path.home()
        path = filedialog.askopenfilename(
            title="Open plan",
            initialdir=str(start_dir),
            filetypes=[("Float plan", "*.floatplan"), ("JSON", "*.json")],
        )
        if not path:
            return
        self._on_plan_file_selected(path)

    def _on_plan_file_selected(self, path: str) -> None:
        """Load and apply a chosen plan file."""
        try:
            with open(path, encoding="utf-8") as f:
                plan = json.load(f)
        except Exception as e:
            _tk_alert(self.root, "Error", f"Could not open plan: {e}")
            return
        if not isinstance(plan, dict):
            _tk_alert(self.root, "Error", "Invalid plan file.")
            return
        self.root.after(100, self._apply_loaded_plan, plan, path)

    def _apply_loaded_plan(self, plan: dict, path: str):
        """Apply a loaded plan dict to state and refresh UI (called after file dialog)."""
        vessel_name = (plan.get("vessel_name") or "").strip()
        vessel_index = None
        for i, v in enumerate(self.vessels):
            name = (v.get("name") or v.get("id_vessel_name") or "").strip()
            if name and name == vessel_name:
                vessel_index = i
                break
        if vessel_index is not None:
            self.vessel = _copy_vessel_for_edit(self.vessels[vessel_index])
        else:
            self.vessel = _copy_vessel_for_edit(DEFAULT_VESSEL)
            self.vessel["name"] = "(No vessel selected)"
        operator_name = (plan.get("operator_name") or "").strip()
        self.selected_operator_index = None
        for i, m in enumerate(self.crew_members):
            if (m.get("name") or "").strip() == operator_name:
                self.selected_operator_index = i
                break
        on_board_names = list(plan.get("on_board_names") or [])
        self.on_board_indices = set()
        for i, m in enumerate(self.crew_members):
            name = (m.get("name") or "").strip()
            if name and name in on_board_names:
                self.on_board_indices.add(i)
        self.itinerary = list(plan.get("itinerary") or [])
        self.rescue_authority = (plan.get("rescue_authority") or "").strip()
        self.rescue_authority_phone = (plan.get("rescue_authority_phone") or "").strip()
        self.contact1 = (plan.get("contact1") or "").strip()
        self.contact1_phone = (plan.get("contact1_phone") or "").strip()
        self.contact2 = (plan.get("contact2") or "").strip()
        self.contact2_phone = (plan.get("contact2_phone") or "").strip()
        self.operator_has_vessel_experience = bool(plan.get("operator_has_vessel_experience"))
        self.operator_has_area_experience = bool(plan.get("operator_has_area_experience"))
        self.op_has_vessel_exp_var.set(self.operator_has_vessel_experience)
        self.op_has_area_exp_var.set(self.operator_has_area_experience)
        self._refresh_vessel_combo()
        if vessel_index is not None and 0 <= vessel_index < len(self.vessels):
            self.vessel_combo.current(vessel_index)
            self.vessel = _copy_vessel_for_edit(self.vessels[vessel_index])
        else:
            self.vessel_combo.set("")
        self._refresh_crew_members_list()
        self._refresh_itinerary_display()
        self._refresh_rescue_ui()
        self._refresh_contact_ui()
        _tk_alert(self.root, "Opened", f"Plan loaded from {path}")

    def _generate_pdf(self):
        if not TEMPLATE_PDF.exists():
            _tk_alert(self.root, "Error", f"Template not found: {TEMPLATE_PDF}")
            return
        # Ensure pypdf has a real AES provider (cryptography or pycryptodome). Otherwise PDF gen will fail.
        try:
            from pypdf._crypt_providers import crypt_provider
            if crypt_provider[0] == "local_crypt_fallback":
                _tk_alert(
                    self.root,
                    "PDF dependencies missing",
                    "PDF encryption support is not available in this environment.\n\n"
                    "Run the app with:\n  ./run.sh\n"
                    "so the correct Python environment (with cryptography or pycryptodome) is used.",
                )
                return
        except Exception:
            pass
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile="float_plan.pdf",
        )
        if not path:
            return
        try:
            self._on_contact_changed()
            vessel_for_pdf = {
                **self.vessel,
                "rescue_authority": self.rescue_authority,
                "rescue_authority_phone": self.rescue_authority_phone,
                "contact1": self.contact1,
                "contact1_phone": self.contact1_phone,
                "contact2": self.contact2,
                "contact2_phone": self.contact2_phone,
            }
            # Sync on-board from checkboxes
            for i, v in self._on_board_vars.items():
                if v.get():
                    self.on_board_indices.add(i)
                else:
                    self.on_board_indices.discard(i)
            if self.selected_operator_index is None or not self.crew_members:
                _tk_alert(self.root, "Error", "Select an operator and at least one person on board.")
                return
            operator = self.crew_members[self.selected_operator_index]
            op_age = _age_from_dob(operator.get("dob", "")) if operator.get("dob") else operator.get("age", "")
            op_with_exp = {**operator, "age": op_age, "vessel_experience": "Yes" if self.operator_has_vessel_experience else "", "area_experience": "Yes" if self.operator_has_area_experience else ""}
            # POB = passengers/crew list: operator first (if on board), then other on-board; age from DOB when present
            def pob_record(p: dict) -> dict:
                age = _age_from_dob(p.get("dob", "")) if p.get("dob") else p.get("age", "")
                return {**{k: p.get(k, "") for k in ["name", "dob", "age", "gender", "home_phone", "note", "pfd", "plb_uin"]}, "age": age}
            persons = []
            # Add operator as first in passengers/crew list (operator is always on board for the plan)
            persons.append(pob_record(operator))
            for i in sorted(self.on_board_indices):
                if i != self.selected_operator_index and i < len(self.crew_members):
                    persons.append(pob_record(self.crew_members[i]))
            crew_for_pdf = {"operator": op_with_exp, "persons": persons}
            fill_float_plan(TEMPLATE_PDF, path, vessel_for_pdf, crew_for_pdf, self.itinerary)
            _tk_alert(self.root, "Done", f"Saved to {path}")
        except Exception as e:
            _tk_alert(self.root, "Error", str(e))

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    FloatPlanApp().run()
