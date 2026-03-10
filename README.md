# Float Plan

Fill the USCG float plan PDF from saved vessel and crew data, plus an itinerary.

Runs on **macOS**, **Linux**, and **Windows** (Python 3.10+ with tkinter).

## Run

**macOS / Linux:**

```bash
./run.sh
```

**Windows (Command Prompt or PowerShell):**

```cmd
run.bat
```

Or run Python directly after setting up the venv once:

- macOS/Linux: `python3 -m venv .venv` then `.venv/bin/pip install -r requirements.txt` and `.venv/bin/python app.py`
- Windows: `python -m venv .venv` then `.venv\Scripts\pip install -r requirements.txt` and `.venv\Scripts\python app.py`

The run scripts create `.venv` if needed, upgrade pip, install dependencies, and start the app. On Unix, `ensure_env.sh` also runs `pip audit` (or `pip check`).

## Usage

1. **Vessel** – Choose a pre-configured vessel, or **New vessel** / **Edit vessel**. Vessel data includes identity, communications, propulsion, navigation, safety & survival, and contact info (emergency contacts, rescue authority).
2. **Crew** – Choose a pre-configured crew, or **New crew** / **Edit crew**. Crew has one operator (full details) and up to 12 persons on board.
3. **Itinerary** – **Set departure** (date, time, location, mode), then **Add arrival / next leg** for each stop (arrival + next departure). Remove legs with **Remove leg**.
4. **Generate PDF…** – Saves a filled copy of `USCGFloatPlan.pdf` for the onshore support team.

Data is stored in the `data/` directory as `vessels.json` and `crew_members.json`.

## Template

The app is wired to the form fields in **USCGFloatPlan.pdf** in this directory. Edit dropdown options in **dropdown_options.json** (Type, Hull material, Mode, Gender). Options are defined in **dropdown_options.json** and match the template’s pull-down menus; the app tries to read options from the PDF when possible, otherwise uses the fallback list. To see or refresh options from the template:

```bash
.venv/bin/python list_pdf_field_options.py
```

If you switch to another template version, run `list_pdf_fields.py` to get field names and update `pdf_fill.py` and `dropdown_options.json` (and the GUI) to match.
