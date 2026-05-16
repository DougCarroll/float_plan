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

## Web app

The same vessel/crew data and PDF generation are available as a web app, so you can run it on a server and use it behind a **Cloudflare tunnel** (like [anchor_watch](../anchor_watch)).

**Prerequisites:** Create the venv and install base deps once with `./run.sh` (or `run.bat` on Windows). Then:

```bash
./run_web.sh
```

This installs web dependencies (Flask, gunicorn, PyYAML) into the same `.venv`, then starts the web app. Default port is 5503; override with `PORT=5503 ./run_web.sh` or use a `config.yaml` (copy from `config.example.yaml`) with `web.port` and optional `web.host`.

- **URL:** `http://127.0.0.1:5503` (or your configured host/port). The page lets you select vessel and operator, choose who’s on board, add itinerary legs, set rescue authority and contacts, and **Generate PDF** to download the filled form.
- **Data:** Vessels and crew are read from the same `data/` directory as the desktop app. Add or edit vessels/crew with the desktop app; the web app is for filling a plan and generating the PDF.
- **Cloudflare:** Run your tunnel (e.g. `cloudflared tunnel --url http://127.0.0.1:5503`) and optionally protect the URL with [Cloudflare Access](https://developers.cloudflare.com/cloudflare-one/policies/access/). The app may bind `0.0.0.0` (see `config.example.yaml`) so it is reachable on your LAN or from port-forwarding; cloudflared on the **same** machine should still target **`http://127.0.0.1:PORT`**. To restrict the process to loopback only, set `web.host: "127.0.0.1"` (or `HOST=127.0.0.1` in `.env`).
- **Tunnel shows “connection refused” / site down on macOS:** In Zero Trust, set the route service to **`http://127.0.0.1:5503`** instead of **`http://localhost:5503`** (macOS often resolves `localhost` to IPv6 first). Current `gunicorn_config.py` also binds **`[::1]:PORT`** alongside `127.0.0.1` / `0.0.0.0` so `localhost` can work after you **restart Gunicorn** (`launchctl kickstart …` or `./start-service.sh`).

**Run as a service (macOS):** Like [anchor_watch](../anchor_watch), you can run the web app under launchd so it starts at login and restarts if it exits. For **production**, set **`SECRET_KEY`** in `.env` (required when **`PRODUCTION=1`**, **`FLASK_ENV=production`**, or **`REQUIRE_ENV_SECRET=1`**); the app will not use `data/.flask_secret` in those modes. For casual local use without those flags, you may omit **`SECRET_KEY`** and let the app create **`data/.flask_secret`** once. Optionally set **`PORT`**, **`TRUST_PROXY=1`** behind Cloudflare, and **`RATE_LIMIT_STORAGE_URI`** / **`REDIS_URL`** if you run multiple Gunicorn workers. Both `run_web.sh` and `start-service.sh` source `.env`. Run `./run_web.sh` once to create `.venv` and install dependencies, then:

```bash
./install_launchd.sh
```

This installs a Launch Agent at `~/Library/LaunchAgents/com.svburnttoast.floatplan.plist` with label **`com.svburnttoast.floatplan`** (legacy `com.floatplan` is removed on install). Logs go to `data/service.log` and `data/service.error.log`. To restart: `launchctl kickstart -k "gui/$(id -u)/com.svburnttoast.floatplan"`. To stop: `launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.svburnttoast.floatplan.plist`. To check: `launchctl list | grep svburnttoast.floatplan`.

## Git / GitHub — don’t push secrets

The repo’s `.gitignore` is set up so these are **not** committed:

- **`.env`**, **`.env.*`** — SECRET_KEY, PORT, etc.
- **`config.yaml`** — local web port/host (copy from `config.example.yaml`).
- **`data/`** — vessels, crew, user DB (`float_plan.db`), `.flask_secret`, service logs.
- **`*.secret`**, **`secrets/`** — any other secret files.

Before your first push (or after adding new secrets), run `git status` and `git check-ignore -v <file>` if unsure; never add the files above.
