# Gunicorn config for Float Plan web app (behind Cloudflare tunnel)
# Usage: gunicorn -c gunicorn_config.py web_app:app

import os

config_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "config.yaml"))
host = os.environ.get("HOST", "127.0.0.1")
port = os.environ.get("PORT", "5000")
if os.path.exists(config_path):
    try:
        import yaml
        with open(config_path) as f:
            c = yaml.safe_load(f)
        w = c.get("web", {}) or {}
        host = str(w.get("host", host))
        port = str(w.get("port", port))
    except Exception:
        pass
host = os.environ.get("HOST", host)
port = os.environ.get("PORT", port)

bind = f"{host}:{port}"
backlog = 2048
workers = 1
worker_class = "sync"
worker_connections = 1000
timeout = 30
keepalive = 2

accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

proc_name = "float_plan"
daemon = False
pidfile = None
