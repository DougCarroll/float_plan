# Float Plan

Fill the USCG float plan PDF from saved vessel and crew data, plus an itinerary.

## Run

```bash
./run.sh
```

This updates the virtual environment (pip upgrade, install dependencies, audit) and then starts the app.

`ensure_env.sh` will:

- Create `.venv` if it doesn’t exist  
- Upgrade pip  
- Install/update packages from `requirements.txt`  
- Run `pip audit` (or `pip check` if audit isn’t available)

## Usage

1. **Vessel** – Choose a pre-configured vessel, or **New vessel** / **Edit vessel**. Vessel data includes identity, communications, propulsion, navigation, safety & survival, and contact info (emergency contacts, rescue authority).
2. **Crew** – Choose a pre-configured crew, or **New crew** / **Edit crew**. Crew has one operator (full details) and up to 12 persons on board.
3. **Itinerary** – **Set departure** (date, time, location, mode), then **Add arrival / next leg** for each stop (arrival + next departure). Remove legs with **Remove leg**.
4. **Generate PDF…** – Saves a filled copy of `USCGFloatPlan.pdf` for the onshore support team.

Data is stored in the `data/` directory as `vessels.json` and `crews.json`.

## Template

The app is wired to the form fields in **USCGFloatPlan.pdf** in this directory. Edit dropdown options in **dropdown_options.json** (Type, Hull material, Mode, Gender). Options are defined in **dropdown_options.json** and match the template’s pull-down menus; the app tries to read options from the PDF when possible, otherwise uses the fallback list. To see or refresh options from the template:

```bash
.venv/bin/python list_pdf_field_options.py
```

If you switch to another template version, run `list_pdf_fields.py` to get field names and update `pdf_fill.py` and `dropdown_options.json` (and the GUI) to match.
