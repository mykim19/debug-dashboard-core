"""
Debug Dashboard Core — Flask app factory.

Supports multi-workspace mode:
  - Cookie-based workspace selection (per-user independent)
  - Workspace ID via SHA1 hash of config path (collision-proof)
  - Lazy per-workspace registry caching (no global singleton mutation)

Usage:
    from debug_dashboard_core.app import create_app
    app = create_app(config_path="config.yaml")
    app = create_app(config_path="config.yaml", extra_workspaces=["../other/.debugger/config.yaml"])
    app.run(port=5010)
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from flask import Flask, jsonify, make_response, render_template, Response, request

from .scanner.base import PhaseReport, CheckResult, BaseChecker
from .scanner.registry import CheckerRegistry
from . import storage


# ── Helpers ────────────────────────────────────────────

def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Override values win."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate_config(config: dict) -> dict:
    """Validate config at startup. Returns sanitized config."""
    if not config.get("project", {}).get("root"):
        raise ValueError("config.yaml: project.root is required")
    return config


def _make_ws_id(config_path: Path) -> str:
    """Generate workspace ID from config path hash (10-char hex)."""
    return hashlib.sha1(str(config_path.resolve()).encode()).hexdigest()[:10]


# ── Workspace Persistence ─────────────────────────────

def _ws_registry_path(config_path: Path) -> Path:
    """Return path to workspaces.json (sibling of primary config)."""
    return config_path.parent / "workspaces.json"


def _load_saved_workspaces(config_path: Path) -> List[str]:
    """Load extra workspace config paths from workspaces.json."""
    reg = _ws_registry_path(config_path)
    if not reg.exists():
        return []
    try:
        data = json.loads(reg.read_text(encoding="utf-8"))
        return [p for p in data.get("extra_workspaces", []) if Path(p).exists()]
    except Exception:
        return []


def _save_workspace_registry(config_path: Path, workspaces: Dict[str, dict],
                              default_ws_id: str) -> None:
    """Persist extra workspace config paths to workspaces.json."""
    extras = []
    for ws_id, ws in workspaces.items():
        if ws_id == default_ws_id:
            continue  # primary workspace is always loaded from CLI
        cfg_path = ws.get("config_path")
        if cfg_path:
            extras.append(str(cfg_path))

    reg = _ws_registry_path(config_path)
    reg.write_text(json.dumps({
        "extra_workspaces": extras,
        "_note": "Auto-managed by Debug Dashboard. Persists UI-added workspaces across restarts."
    }, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Workspace Loading ──────────────────────────────────

def _load_workspace(config_path: Path, defaults: dict) -> dict:
    """Load a single workspace from config file. Returns workspace dict."""
    config_path = config_path.resolve()

    project_config = {}
    if config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            project_config = yaml.safe_load(f) or {}

    config = deep_merge(defaults, project_config)
    config = _validate_config(config)

    # Resolve project root
    project_root = Path(config.get("project", {}).get("root", "."))
    if not project_root.is_absolute():
        project_root = config_path.parent / project_root
    project_root = project_root.resolve()

    ws_id = _make_ws_id(config_path)
    name = config.get("project", {}).get("name", config_path.parent.name)

    return {
        "id": ws_id,
        "name": name,
        "config": config,
        "project_root": project_root,
        "config_path": config_path,
    }


def _resolve_plugin_dirs(config: dict, config_path: Path,
                         extra_plugin_dirs: List[str] = None) -> List[str]:
    """Resolve plugin directories from config + extra args. Returns list of absolute paths."""
    all_dirs = list(extra_plugin_dirs or [])
    config_dirs = config.get("plugins", {}).get("dirs", [])
    for d in config_dirs:
        p = Path(d)
        if not p.is_absolute():
            p = config_path.parent / p
        p_str = str(p.resolve())
        if p_str not in [str(Path(x).resolve()) for x in all_dirs]:
            all_dirs.append(p_str)

    # Resolve any remaining relative paths
    resolved = []
    for d in all_dirs:
        p = Path(d)
        if not p.is_absolute():
            p = config_path.parent / p
        resolved.append(str(p.resolve()))
    return resolved


def _init_registry_for(ws: dict) -> List[BaseChecker]:
    """Initialize checkers for a workspace using isolated discovery.

    Uses CheckerRegistry.discover_isolated() to avoid mutating global state.
    Returns ordered, enabled checker instances.
    """
    config = ws["config"]
    config_path = ws["config_path"]

    plugin_dirs = _resolve_plugin_dirs(config, config_path)
    checkers_dict, load_errors = CheckerRegistry.discover_isolated(plugin_dirs)

    # Store load errors on workspace for UI notification
    ws["_load_errors"] = load_errors

    # Apply checks_order + enabled filter
    order = config.get("checks_order", [])
    registered_names = set(checkers_dict.keys())

    # Sanitize order
    valid_order = [n for n in order if n in registered_names]
    for n in order:
        if n not in registered_names:
            print(f"[workspace:{ws['id']}] ⚠ checks_order contains unknown checker: '{n}'")

    # Order checkers
    if valid_order:
        ordered = []
        for name in valid_order:
            ordered.append(checkers_dict[name])
        for name, checker in checkers_dict.items():
            if name not in valid_order:
                ordered.append(checker)
    else:
        ordered = list(checkers_dict.values())

    # Filter enabled
    enabled = [c for c in ordered if c.is_applicable(config)]
    return enabled


# ── App Factory ────────────────────────────────────────

def create_app(config_path: str, db_path: str = None,
               plugin_dirs: List[str] = None,
               extra_workspaces: List[str] = None) -> Flask:
    """Create a Flask debug dashboard app.

    Args:
        config_path: Path to primary project config.yaml
        db_path: Override for dashboard SQLite DB location
        plugin_dirs: Additional plugin directories (merged with config.plugins.dirs)
        extra_workspaces: Additional workspace config.yaml paths for multi-workspace mode
    """
    CORE_DIR = Path(__file__).parent
    config_path = Path(config_path).resolve()

    # Load defaults
    defaults_path = CORE_DIR / "defaults.yaml"
    defaults = {}
    if defaults_path.exists():
        with open(defaults_path, encoding="utf-8") as f:
            defaults = yaml.safe_load(f) or {}

    # ── Load workspaces ──
    main_ws = _load_workspace(config_path, defaults)

    # Merge extra plugin_dirs into main workspace config
    if plugin_dirs:
        existing = main_ws["config"].get("plugins", {}).get("dirs", [])
        for d in plugin_dirs:
            if d not in existing:
                existing.append(d)
        main_ws["config"].setdefault("plugins", {})["dirs"] = existing

    workspaces: Dict[str, dict] = {main_ws["id"]: main_ws}

    # Merge CLI extra workspaces + persisted workspaces (from workspaces.json)
    all_extras = list(extra_workspaces or [])
    saved_extras = _load_saved_workspaces(config_path)
    for sp in saved_extras:
        if sp not in all_extras:
            all_extras.append(sp)

    for extra_path in all_extras:
        try:
            ws = _load_workspace(Path(extra_path), defaults)
            workspaces[ws["id"]] = ws
            print(f"[workspace] ✓ Loaded: {ws['name']} [{ws['id']}] — {ws['config_path']}")
        except Exception as e:
            print(f"[workspace] ⚠ Failed to load {extra_path}: {e}")

    # ── Storage setup ──
    if db_path:
        storage.configure(Path(db_path))
    else:
        default_db = config_path.parent / "debug_dashboard.db"
        storage.configure(default_db)
    storage.init_db()

    # ── Flask app ──
    app = Flask(__name__,
                template_folder=str(CORE_DIR / "templates"),
                static_folder=str(CORE_DIR / "static"))

    app.config["WORKSPACES"] = workspaces
    app.config["DEFAULT_WORKSPACE"] = main_ws["id"]
    app.config["REGISTRIES"] = {}  # ws_id → list of checker instances (lazy init)
    app.config["MONITOR_CONNECTORS"] = {}  # ws_id → MainServiceConnector (per-workspace)
    app.config["_PRIMARY_CONFIG_PATH"] = str(config_path)  # for workspace persistence

    # ── Workspace helpers (request-scoped) ──

    def _current_ws_id() -> str:
        """Get current workspace ID from cookie (falls back to default)."""
        ws_id = request.cookies.get("dd_workspace")
        if ws_id and ws_id in app.config["WORKSPACES"]:
            return ws_id
        return app.config["DEFAULT_WORKSPACE"]

    def _get_ws() -> dict:
        """Get current workspace dict."""
        return app.config["WORKSPACES"][_current_ws_id()]

    def _get_checkers(ws_id: str = None) -> List[BaseChecker]:
        """Get checkers for a workspace (lazy init + cache)."""
        if ws_id is None:
            ws_id = _current_ws_id()
        if ws_id not in app.config["REGISTRIES"]:
            ws = app.config["WORKSPACES"][ws_id]
            checkers = _init_registry_for(ws)
            app.config["REGISTRIES"][ws_id] = checkers
            print(f"[registry:{ws_id}] Loaded {len(checkers)} checkers for '{ws['name']}'")
        return app.config["REGISTRIES"][ws_id]

    def _ws_project_name(ws: dict) -> str:
        """Project name for storage (includes ws_id for uniqueness)."""
        return f"{ws['name']} [{ws['id']}]"

    def _find_checker_by_name(name: str, ws_id: str = None) -> Optional[BaseChecker]:
        """Find a checker by name from the workspace's checker list."""
        for c in _get_checkers(ws_id):
            if c.name == name:
                return c
        return None

    # ── Routes ──────────────────────────────────────────

    @app.route("/")
    def index():
        ws = _get_ws()
        checkers = _get_checkers()
        meta = [c.get_meta() for c in checkers]

        # Build workspace list for template
        ws_list = []
        current_id = _current_ws_id()
        for wid, w in app.config["WORKSPACES"].items():
            ws_list.append({
                "id": wid,
                "name": w["name"],
                "is_current": wid == current_id,
            })

        # Agent status for template
        agent_loop = app.config.get("AGENT_LOOPS", {}).get(current_id)
        agent_state = agent_loop.state.value if agent_loop else "disabled"

        # Monitor status for template (per-workspace)
        monitor_connectors = app.config.get("MONITOR_CONNECTORS", {})
        monitor_on = current_id in monitor_connectors

        return render_template("dashboard.html",
                               project_name=ws["name"],
                               phases=meta,
                               workspaces=ws_list,
                               default_ws_id=app.config["DEFAULT_WORKSPACE"],
                               agent_enabled=agent_loop is not None,
                               agent_state=agent_state,
                               monitor_enabled=monitor_on)

    @app.route("/api/workspaces")
    def api_workspaces():
        """List all workspaces and current selection."""
        current_id = _current_ws_id()
        connectors = app.config.get("MONITOR_CONNECTORS", {})
        ws_list = []
        for wid, w in app.config["WORKSPACES"].items():
            ws_list.append({
                "id": wid,
                "name": w["name"],
                "root": str(w["project_root"]),
                "monitor_enabled": wid in connectors,
            })
        return jsonify({"success": True, "current": current_id, "workspaces": ws_list})

    @app.route("/api/workspace/switch", methods=["POST"])
    def api_workspace_switch():
        """Switch workspace via cookie."""
        data = request.get_json(silent=True) or {}
        ws_id = data.get("id", "")

        if ws_id not in app.config["WORKSPACES"]:
            return jsonify({"success": False, "error": f"Unknown workspace: {ws_id}"}), 400

        ws = app.config["WORKSPACES"][ws_id]
        resp = make_response(jsonify({
            "success": True,
            "workspace": {"id": ws_id, "name": ws["name"]},
        }))
        resp.set_cookie("dd_workspace", ws_id, path="/", samesite="Lax", max_age=365*24*3600)
        return resp

    @app.route("/api/browse")
    def api_browse():
        """List directories for the folder browser UI."""
        raw = request.args.get("path", "").strip()

        if not raw:
            # Default: show common root directories
            roots = []
            for p in [Path("/Volumes"), Path.home(), Path("/")]:
                if p.exists():
                    roots.append({"name": str(p), "path": str(p), "is_project": False})
            return jsonify({"success": True, "current": "/", "parent": None, "dirs": roots})

        target = Path(raw).resolve()
        if not target.is_dir():
            return jsonify({"success": False, "error": f"Not a directory: {raw}"}), 400

        # Safety: reject system directories
        BLOCKED = {"/bin", "/sbin", "/usr/bin", "/usr/sbin", "/System", "/private/var"}
        if str(target) in BLOCKED:
            return jsonify({"success": False, "error": "Access denied"}), 403

        parent = str(target.parent) if target.parent != target else None

        dirs = []
        try:
            for entry in sorted(target.iterdir()):
                if not entry.is_dir():
                    continue
                name = entry.name
                # Skip hidden dirs (except a few useful ones)
                if name.startswith(".") and name not in (".debugger",):
                    continue
                # Detect if this looks like a project (has code/config files)
                is_project = any((entry / marker).exists() for marker in [
                    "app.py", "main.py", "manage.py", "setup.py", "pyproject.toml",
                    "package.json", "Cargo.toml", "go.mod", "Makefile",
                    "requirements.txt", ".git", ".debugger",
                ])
                dirs.append({
                    "name": name,
                    "path": str(entry),
                    "is_project": is_project,
                })
        except PermissionError:
            return jsonify({"success": False, "error": "Permission denied"}), 403

        return jsonify({
            "success": True,
            "current": str(target),
            "parent": parent,
            "dirs": dirs,
        })

    @app.route("/api/workspace/add", methods=["POST"])
    def api_workspace_add():
        """Add a workspace at runtime by directory path. Auto-scaffolds if needed."""
        data = request.get_json(silent=True) or {}
        raw_path = data.get("path", "").strip()

        if not raw_path:
            return jsonify({"success": False, "error": "path is required"}), 400

        p = Path(raw_path).resolve()
        if not p.is_dir():
            return jsonify({"success": False, "error": f"Not a directory: {raw_path}"}), 400

        # Find or auto-scaffold config
        config_path = None
        for candidate in [
            p / ".debugger" / "config.yaml",
            p / "debug_dashboard" / "config.yaml",
            p / "config.yaml",
        ]:
            if candidate.exists():
                config_path = candidate
                break

        scaffolded = False
        if config_path is None:
            # Auto-scaffold
            from .cli import _auto_scaffold_workspace
            result = _auto_scaffold_workspace(p)
            if result:
                config_path = Path(result)
                scaffolded = True
            else:
                return jsonify({"success": False, "error": f"Failed to initialize: {raw_path}"}), 500

        # Check if already loaded
        ws_id = _make_ws_id(config_path)
        if ws_id in app.config["WORKSPACES"]:
            ws = app.config["WORKSPACES"][ws_id]
            return jsonify({"success": True, "workspace": {
                "id": ws_id, "name": ws["name"],
                "root": str(ws["project_root"]),
            }, "already_loaded": True})

        # Load workspace
        try:
            ws = _load_workspace(config_path, defaults)
            app.config["WORKSPACES"][ws["id"]] = ws

            # ── Persist to workspaces.json ──
            try:
                _save_workspace_registry(
                    config_path=Path(app.config["_PRIMARY_CONFIG_PATH"]),
                    workspaces=app.config["WORKSPACES"],
                    default_ws_id=app.config["DEFAULT_WORKSPACE"],
                )
            except Exception as pe:
                print(f"[workspace] ⚠ Persist failed: {pe}")

            # ── Initialize monitor connector if workspace has monitor config ──
            _maybe_init_monitor_for_ws(app, ws)

            print(f"[workspace] ✓ Added at runtime: {ws['name']} [{ws['id']}]")
            return jsonify({"success": True, "workspace": {
                "id": ws["id"], "name": ws["name"],
                "root": str(ws["project_root"]),
            }, "scaffolded": scaffolded})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/workspace/remove", methods=["POST"])
    def api_workspace_remove():
        """Remove a workspace from the runtime list (does not delete files)."""
        data = request.get_json(silent=True) or {}
        ws_id = data.get("id", "")

        if ws_id not in app.config["WORKSPACES"]:
            return jsonify({"success": False, "error": f"Unknown workspace: {ws_id}"}), 400

        if ws_id == app.config["DEFAULT_WORKSPACE"]:
            return jsonify({"success": False, "error": "Cannot remove the primary workspace"}), 400

        ws = app.config["WORKSPACES"].pop(ws_id)
        # Also remove cached registry
        app.config["REGISTRIES"].pop(ws_id, None)
        # Stop and remove monitor connector for this workspace
        connectors = app.config.get("MONITOR_CONNECTORS", {})
        if ws_id in connectors:
            try:
                connectors[ws_id].stop()
            except Exception:
                pass
            del connectors[ws_id]

        # ── Persist removal to workspaces.json ──
        try:
            _save_workspace_registry(
                config_path=Path(app.config["_PRIMARY_CONFIG_PATH"]),
                workspaces=app.config["WORKSPACES"],
                default_ws_id=app.config["DEFAULT_WORKSPACE"],
            )
        except Exception:
            pass

        print(f"[workspace] ✗ Removed: {ws['name']} [{ws_id}]")
        return jsonify({"success": True, "removed": ws_id, "name": ws["name"]})

    @app.route("/api/scan/run")
    def scan_run():
        """SSE endpoint — streams phase results in real-time."""
        ws_id = _current_ws_id()
        ws = app.config["WORKSPACES"][ws_id]
        cfg = ws["config"]
        p_root = ws["project_root"]
        project_name = _ws_project_name(ws)
        checkers = _get_checkers(ws_id)

        def generate():
            # Send plugin load errors first (if any)
            load_errors = ws.get("_load_errors", [])
            if load_errors:
                yield f"data: {json.dumps({'type': 'plugin_errors', 'errors': load_errors}, ensure_ascii=False)}\n\n"

            start = time.time()
            all_reports = []
            total_pass = total_warn = total_fail = 0

            for checker in checkers:
                yield f"data: {json.dumps({'type': 'phase_start', 'name': checker.name, 'display': checker.display_name}, ensure_ascii=False)}\n\n"

                t0 = time.time()
                try:
                    report = checker.run(p_root, cfg)
                except Exception as e:
                    report = PhaseReport(checker.name)
                    report.add(CheckResult("error", CheckResult.FAIL, str(e)))
                report.duration_ms = int((time.time() - t0) * 1000)

                rd = report.to_dict()
                rd["meta"] = checker.get_meta()
                all_reports.append(rd)
                total_pass += report.pass_count
                total_warn += report.warn_count
                total_fail += report.fail_count

                yield f"data: {json.dumps({'type': 'phase_done', 'name': checker.name, 'report': rd}, ensure_ascii=False)}\n\n"

            elapsed = int((time.time() - start) * 1000)
            total_active = total_pass + total_warn + total_fail
            health_pct = (total_pass / total_active * 100) if total_active else 100
            overall = "CRITICAL" if total_fail > 0 else ("DEGRADED" if total_warn > 0 else "HEALTHY")

            storage.save_scan(project_name, overall, total_pass, total_warn, total_fail,
                              health_pct, all_reports, elapsed)

            yield f"data: {json.dumps({'type': 'scan_complete', 'overall': overall, 'total_pass': total_pass, 'total_warn': total_warn, 'total_fail': total_fail, 'health_pct': round(health_pct, 1), 'duration_ms': elapsed}, ensure_ascii=False)}\n\n"

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.route("/api/scan/latest")
    def scan_latest():
        ws = _get_ws()
        project_name = _ws_project_name(ws)
        result = storage.get_latest(project_name)
        if result:
            return jsonify({"success": True, "data": result})
        return jsonify({"success": True, "data": None})

    @app.route("/api/scan/history")
    def scan_history():
        ws = _get_ws()
        project_name = _ws_project_name(ws)
        limit = request.args.get("limit", 30, type=int)
        rows = storage.get_history(limit, project_name)
        return jsonify({"success": True, "data": rows})

    @app.route("/api/phase/<name>")
    def phase_single(name):
        ws = _get_ws()
        cfg = ws["config"]
        p_root = ws["project_root"]
        checker = _find_checker_by_name(name)
        if not checker:
            return jsonify({"success": False, "error": f"Phase '{name}' not found"}), 404
        try:
            t0 = time.time()
            report = checker.run(p_root, cfg)
            report.duration_ms = int((time.time() - t0) * 1000)
            rd = report.to_dict()
            rd["meta"] = checker.get_meta()
            return jsonify({"success": True, "data": rd})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @app.route("/api/fix/<phase>/<check>", methods=["POST"])
    def fix_check(phase, check):
        """Execute auto-fix for a specific check."""
        ws = _get_ws()
        cfg = ws["config"]
        p_root = ws["project_root"]
        checker = _find_checker_by_name(phase)
        if not checker:
            return jsonify({"success": False, "error": f"Phase '{phase}' not found"}), 404
        try:
            result = checker.fix(check, p_root, cfg)
            return jsonify(result)
        except Exception as e:
            return jsonify({"success": False, "message": str(e)}), 500

    @app.route("/api/config")
    def get_config():
        ws = _get_ws()
        return jsonify({"success": True, "data": ws["config"]})

    import os as _os

    # In-memory API key store — never persisted to disk
    _api_keys = {}  # workspace_id → api_key_value

    # Provider prefix → env var name mapping
    _PROVIDER_ENV_MAP = {
        "anthropic/": "ANTHROPIC_API_KEY",
        "openai/":    "OPENAI_API_KEY",
        "gemini/":    "GEMINI_API_KEY",
        "deepseek/":  "DEEPSEEK_API_KEY",
    }

    def _env_var_for_model(model: str) -> str:
        """Return the conventional env var name for a model string."""
        for prefix, env_var in _PROVIDER_ENV_MAP.items():
            if model.startswith(prefix):
                return env_var
        return ""

    @app.route("/api/config/llm", methods=["GET", "POST"])
    def config_llm():
        """GET: return current LLM config + key status.
        POST: update LLM config, set API key in env, hot-reload provider.

        POST body:
            model, fallback_model, temperature, max_tokens, timeout_seconds,
            daily_budget_usd — persisted to config.yaml
            api_key — direct API key value (memory + env only, NEVER on disk)
        """
        ws = _get_ws()
        ws_id = _current_ws_id()

        if request.method == "GET":
            llm_cfg = dict(ws["config"].get("llm", {}))
            model = llm_cfg.get("model", "")
            env_var = _env_var_for_model(model)

            # Report key status (never the actual key)
            has_key = False
            key_source = "none"
            if ws_id in _api_keys:
                has_key = True
                key_source = "ui"
            elif env_var and _os.environ.get(env_var):
                has_key = True
                key_source = "env"
            key_masked = ""
            if has_key:
                raw = _api_keys.get(ws_id, "") or _os.environ.get(env_var, "")
                if raw and len(raw) > 8:
                    key_masked = raw[:4] + "•" * (len(raw) - 8) + raw[-4:]
                elif raw:
                    key_masked = "•" * len(raw)

            llm_cfg.pop("api_key_env", None)  # remove legacy field from response

            # Check litellm availability and agent LLM status
            litellm_installed = False
            try:
                import litellm as _lm  # noqa: F401
                litellm_installed = True
            except ImportError:
                pass
            agent_loop = app.config.get("AGENT_LOOPS", {}).get(ws_id)
            agent_llm_active = False
            if agent_loop and hasattr(agent_loop, 'executor'):
                agent_llm_active = agent_loop.executor._llm is not None

            return jsonify({
                "success": True,
                "data": llm_cfg,
                "key_status": {
                    "has_key": has_key,
                    "source": key_source,
                    "env_var": env_var,
                    "masked": key_masked,
                },
                "llm_ready": {
                    "litellm_installed": litellm_installed,
                    "agent_llm_active": agent_llm_active,
                    "model": model,
                },
                "workspace_id": ws_id,
            })

        # POST — update LLM config
        data = request.get_json(silent=True) or {}

        # Separate API key from config fields
        api_key_raw = data.pop("api_key", None)

        ALLOWED_KEYS = {
            "model", "fallback_model",
            "temperature", "max_tokens", "timeout_seconds", "daily_budget_usd",
        }
        updates = {k: v for k, v in data.items() if k in ALLOWED_KEYS}

        if not updates and api_key_raw is None:
            return jsonify({"success": False, "error": "No valid fields provided"}), 400

        # Type validation
        errors = []
        if "model" in updates and not isinstance(updates["model"], str):
            errors.append("model must be a string")
        if "fallback_model" in updates and not isinstance(updates["fallback_model"], str):
            errors.append("fallback_model must be a string")
        if "temperature" in updates:
            try:
                updates["temperature"] = float(updates["temperature"])
                if not 0 <= updates["temperature"] <= 2:
                    errors.append("temperature must be 0–2")
            except (ValueError, TypeError):
                errors.append("temperature must be a number")
        if "max_tokens" in updates:
            try:
                updates["max_tokens"] = int(updates["max_tokens"])
                if updates["max_tokens"] < 100 or updates["max_tokens"] > 32000:
                    errors.append("max_tokens must be 100–32000")
            except (ValueError, TypeError):
                errors.append("max_tokens must be an integer")
        if "timeout_seconds" in updates:
            try:
                updates["timeout_seconds"] = int(updates["timeout_seconds"])
                if updates["timeout_seconds"] < 5 or updates["timeout_seconds"] > 300:
                    errors.append("timeout_seconds must be 5–300")
            except (ValueError, TypeError):
                errors.append("timeout_seconds must be an integer")
        if "daily_budget_usd" in updates:
            try:
                updates["daily_budget_usd"] = float(updates["daily_budget_usd"])
                if updates["daily_budget_usd"] < 0 or updates["daily_budget_usd"] > 100:
                    errors.append("daily_budget_usd must be 0–100")
            except (ValueError, TypeError):
                errors.append("daily_budget_usd must be a number")
        if errors:
            return jsonify({"success": False, "errors": errors}), 400

        # Apply config updates to in-memory config
        if updates:
            if "llm" not in ws["config"]:
                ws["config"]["llm"] = {}
            ws["config"]["llm"].update(updates)

        # Handle API key — set in environment, NEVER write to disk
        key_status_msg = ""
        model = ws["config"].get("llm", {}).get("model", "")
        env_var = _env_var_for_model(model)

        if api_key_raw is not None:
            api_key_raw = str(api_key_raw).strip()
            if api_key_raw:
                _api_keys[ws_id] = api_key_raw
                if env_var:
                    _os.environ[env_var] = api_key_raw
                    key_status_msg = f"key_set:{env_var}"
                else:
                    # Unknown provider — try generic env var
                    generic_var = f"LLM_API_KEY_{ws_id[:6].upper()}"
                    _os.environ[generic_var] = api_key_raw
                    ws["config"]["llm"]["api_key_env"] = generic_var
                    key_status_msg = f"key_set:{generic_var}"
            else:
                # Empty key = clear
                _api_keys.pop(ws_id, None)
                if env_var and env_var in _os.environ:
                    del _os.environ[env_var]
                key_status_msg = "key_cleared"

        # Persist config to disk (WITHOUT api key)
        if updates:
            config_path = ws.get("config_path")
            if config_path and config_path.exists():
                try:
                    with open(config_path, encoding="utf-8") as f:
                        file_cfg = yaml.safe_load(f) or {}
                    if "llm" not in file_cfg:
                        file_cfg["llm"] = {}
                    # Only persist safe fields (no api_key, no api_key_env)
                    safe_updates = {k: v for k, v in updates.items()
                                    if k not in ("api_key", "api_key_env")}
                    file_cfg["llm"].update(safe_updates)
                    with open(config_path, "w", encoding="utf-8") as f:
                        yaml.dump(file_cfg, f, default_flow_style=False, allow_unicode=True)
                except Exception as e:
                    return jsonify({
                        "success": True,
                        "warning": f"In-memory updated, but disk write failed: {e}",
                        "data": ws["config"]["llm"],
                    })

        # Hot-reload LLM provider in the agent loop (if running)
        llm_status = "no_agent"
        agent_loop = app.config.get("AGENT_LOOPS", {}).get(ws_id)
        if agent_loop and hasattr(agent_loop, 'executor'):
            if model:
                try:
                    from .llm.provider import LLMProvider
                    new_provider = LLMProvider(ws["config"])
                    if new_provider.is_available:
                        agent_loop.executor._llm = new_provider
                        llm_status = f"active:{new_provider.model_name}"
                    else:
                        agent_loop.executor._llm = None
                        llm_status = "litellm_not_installed"
                except Exception as e:
                    llm_status = f"reload_error:{e}"
            else:
                agent_loop.executor._llm = None
                llm_status = "disabled"

        # Build safe response (never include raw key)
        resp_data = dict(ws["config"].get("llm", {}))
        resp_data.pop("api_key", None)
        resp_data.pop("api_key_env", None)

        return jsonify({
            "success": True,
            "data": resp_data,
            "llm_status": llm_status,
            "key_status": key_status_msg,
            "workspace_id": ws_id,
        })

    # ── LLM Overview (full scan summary) ─────────────────

    @app.route("/api/llm/overview", methods=["POST"])
    def llm_overview():
        """Generate LLM-powered overview of the full scan results.

        Uses current scan data to produce a Korean executive summary
        covering all phases, not just a single checker.
        """
        ws = _get_ws()
        ws_id = _current_ws_id()

        # Get LLM provider from agent loop
        agent_loop = app.config.get("AGENT_LOOPS", {}).get(ws_id)
        llm = None
        if agent_loop and hasattr(agent_loop, 'executor') and agent_loop.executor._llm:
            llm = agent_loop.executor._llm

        if not llm:
            return jsonify({"success": False, "error": "No LLM provider configured"})

        # Collect current scan data from all phases
        checkers = _get_checkers(ws_id)
        project_root = ws["project_root"]
        config = ws["config"]
        scan_summary = {
            "project": config.get("project", {}).get("name", "Unknown"),
            "phases": {},
        }
        total_pass = 0
        total_warn = 0
        total_fail = 0

        all_phases = []  # for healthy phases summary
        for checker in checkers:
            try:
                report = checker.run(project_root, config)
                rd = report.to_dict()
                checks = rd.get("checks", [])
                p = sum(1 for c in checks if c["status"] == "PASS")
                w = sum(1 for c in checks if c["status"] == "WARN")
                f = sum(1 for c in checks if c["status"] == "FAIL")
                total_pass += p
                total_warn += w
                total_fail += f
                display = (rd.get("meta", {}).get("display_name")
                           or checker.name)

                if w > 0 or f > 0:
                    # Include detailed evidence for failing checks
                    failing_checks = []
                    for c in checks:
                        if c["status"] in ("FAIL", "WARN"):
                            entry = {
                                "name": c["name"],
                                "status": c["status"],
                                "message": c.get("message", ""),
                            }
                            # Include details (evidence) — truncate large ones
                            if c.get("details"):
                                import json as _json
                                det_str = _json.dumps(c["details"], default=str)
                                if len(det_str) > 500:
                                    det_str = det_str[:500] + "..."
                                entry["details"] = det_str
                            if c.get("fix_desc"):
                                entry["fix_desc"] = c["fix_desc"]
                            if c.get("fixable"):
                                entry["fixable"] = True
                            failing_checks.append(entry)
                    scan_summary["phases"][display] = {
                        "pass": p, "warn": w, "fail": f,
                        "issues": failing_checks,
                    }
                else:
                    all_phases.append({"name": display, "checks": p})
            except Exception:
                pass

        scan_summary["healthy_phases"] = [
            f"{ph['name']} ({ph['checks']})" for ph in all_phases
        ]
        scan_summary["totals"] = {
            "pass": total_pass, "warn": total_warn, "fail": total_fail,
            "total_phases": len(checkers),
            "issue_phases": len(scan_summary["phases"]),
            "healthy_phases": len(all_phases),
            "health_pct": round(total_pass / max(total_pass + total_warn + total_fail, 1) * 100),
        }

        try:
            report_text = llm.generate_report(scan_summary)
            from .llm.prompts import parse_analysis_response
            parsed = parse_analysis_response(report_text)
            return jsonify({
                "success": True,
                "overview": report_text,
                "root_causes": parsed.get("root_causes", []),
                "fix_suggestions": parsed.get("fix_suggestions", []),
                "model": llm.model_name,
                "cost_usd": 0,  # tracked internally by cost tracker
                "totals": scan_summary["totals"],
            })
        except Exception as e:
            return jsonify({"success": False, "error": str(e)})

    # ── Report Export ─────────────────────────────────

    @app.route("/api/scan/export")
    def scan_export():
        """Run a full scan and return a downloadable Markdown report."""
        import datetime

        ws = _get_ws()
        cfg = ws["config"]
        p_root = ws["project_root"]
        project_name = cfg.get("project", {}).get("name", "Unknown")
        ws_root = cfg.get("project", {}).get("root", str(p_root))
        checkers = _get_checkers(_current_ws_id())

        # Run all checkers
        start = time.time()
        all_reports = []
        total_pass = total_warn = total_fail = total_skip = 0

        for checker in checkers:
            t0 = time.time()
            try:
                report = checker.run(p_root, cfg)
            except Exception as e:
                report = PhaseReport(checker.name)
                report.add(CheckResult("error", CheckResult.FAIL, str(e)))
            report.duration_ms = int((time.time() - t0) * 1000)
            rd = report.to_dict()
            rd["meta"] = checker.get_meta()
            all_reports.append(rd)
            total_pass += report.pass_count
            total_warn += report.warn_count
            total_fail += report.fail_count
            total_skip += report.skip_count

        elapsed = int((time.time() - start) * 1000)
        total_active = total_pass + total_warn + total_fail
        health_pct = (total_pass / total_active * 100) if total_active else 100
        overall = "CRITICAL" if total_fail > 0 else ("DEGRADED" if total_warn > 0 else "HEALTHY")

        # Build Markdown report
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_emoji = {"CRITICAL": "🔴", "DEGRADED": "🟡", "HEALTHY": "🟢"}.get(overall, "⚪")

        lines = [
            f"# 🏥 System Diagnostics Report",
            f"",
            f"> **Project**: {project_name}",
            f"> **Root**: `{ws_root}`",
            f"> **Generated**: {now}",
            f"> **Duration**: {elapsed}ms",
            f"",
            f"## {status_emoji} Overall Status: **{overall}**",
            f"",
            f"| Metric | Count |",
            f"|--------|-------|",
            f"| ✅ PASS | {total_pass} |",
            f"| ⚠️ WARN | {total_warn} |",
            f"| ❌ FAIL | {total_fail} |",
            f"| ⏭️ SKIP | {total_skip} |",
            f"| **Health** | **{health_pct:.1f}%** |",
            f"",
            f"---",
            f"",
        ]

        for r in all_reports:
            meta = r.get("meta", {})
            icon = meta.get("icon", "")
            display = meta.get("display_name", r.get("name", "?"))
            checks = r.get("checks", [])
            pc = r.get("pass_count", 0)
            wc = r.get("warn_count", 0)
            fc = r.get("fail_count", 0)
            sc = r.get("skip_count", 0)
            duration = r.get("duration_ms", 0)

            if fc > 0:
                phase_status = "🔴 FAIL"
            elif wc > 0:
                phase_status = "🟡 WARN"
            elif sc == len(checks):
                phase_status = "⚪ SKIP"
            else:
                phase_status = "🟢 PASS"

            lines.append(f"## {icon} {display}  —  {phase_status}")
            lines.append(f"")

            if meta.get("tooltip_why"):
                lines.append(f"> {meta['tooltip_why']}")
                lines.append(f"")

            lines.append(f"| Status | Check | Message |")
            lines.append(f"|--------|-------|---------|")

            for c in checks:
                st = c.get("status", "?")
                sym = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌", "SKIP": "⏭️"}.get(st, "?")
                name = c.get("name", "?")
                msg = c.get("message", "").replace("|", "\\|")
                lines.append(f"| {sym} {st} | `{name}` | {msg} |")

            lines.append(f"")

            # Details section for non-PASS checks
            detail_checks = [c for c in checks if c.get("status") in ("WARN", "FAIL") and c.get("details")]
            if detail_checks:
                lines.append(f"<details>")
                lines.append(f"<summary>📋 Details ({len(detail_checks)} items)</summary>")
                lines.append(f"")
                for c in detail_checks:
                    lines.append(f"**{c['name']}**:")
                    d = c.get("details")
                    if isinstance(d, list):
                        for item in d[:10]:
                            if isinstance(item, dict):
                                parts = []
                                for k, v in item.items():
                                    parts.append(f"{k}=`{v}`")
                                lines.append(f"- {', '.join(parts)}")
                            else:
                                lines.append(f"- `{item}`")
                    elif isinstance(d, dict):
                        for k, v in list(d.items())[:10]:
                            if isinstance(v, list):
                                lines.append(f"- **{k}**: {', '.join(f'`{x}`' for x in v[:10])}")
                            else:
                                lines.append(f"- **{k}**: `{v}`")
                    lines.append(f"")

                    if c.get("fixable"):
                        lines.append(f"  🔧 **Auto-fix**: {c.get('fix_desc', '')}")
                        lines.append(f"")

                lines.append(f"</details>")
                lines.append(f"")

            lines.append(f"---")
            lines.append(f"")

        # Action items summary
        action_items = []
        for r in all_reports:
            for c in r.get("checks", []):
                if c.get("status") == "FAIL":
                    phase_name = r.get("meta", {}).get("display_name", r.get("name", "?"))
                    action_items.append(f"❌ **{phase_name}** → `{c['name']}`: {c.get('message', '')}")
                elif c.get("status") == "WARN" and c.get("fixable"):
                    phase_name = r.get("meta", {}).get("display_name", r.get("name", "?"))
                    action_items.append(f"🔧 **{phase_name}** → `{c['name']}`: {c.get('fix_desc', '')}")

        if action_items:
            lines.append(f"## 🎯 Action Items")
            lines.append(f"")
            for i, item in enumerate(action_items, 1):
                lines.append(f"{i}. {item}")
            lines.append(f"")

        lines.append(f"---")
        lines.append(f"*Generated by Debug Dashboard Core • {now}*")

        content = "\n".join(lines)

        # Return as downloadable file
        fmt = request.args.get("format", "md")
        if fmt == "json":
            return jsonify({
                "success": True,
                "report": {
                    "project": project_name,
                    "generated": now,
                    "status": overall,
                    "health_pct": round(health_pct, 1),
                    "summary": {"pass": total_pass, "warn": total_warn, "fail": total_fail, "skip": total_skip},
                    "phases": all_reports,
                    "duration_ms": elapsed,
                }
            })

        # Markdown download
        safe_name = project_name.replace(" ", "_").lower()
        date_str = datetime.datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"diagnostic_report_{safe_name}_{date_str}.md"

        resp = make_response(content)
        resp.headers["Content-Type"] = "text/markdown; charset=utf-8"
        resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return resp

    # ── Agent integration (conditional, per-workspace) ──────────────
    # Each workspace can independently enable agent mode via agent.enabled: true.
    # Blueprint is registered once; each workspace gets its own AgentLoop.
    app.config["AGENT_LOOPS"] = {}  # ws_id → AgentLoop
    _any_agent_enabled = False

    for ws_id, ws in workspaces.items():
        ws_agent_enabled = ws["config"].get("agent", {}).get("enabled", False)
        if not ws_agent_enabled:
            continue

        try:
            from .agent.loop import AgentLoop
            from .agent.observer import FileObserver
            from .agent.reasoner import Reasoner
            from .agent.executor import Executor
            from .agent.graph import CheckerDependencyGraph
            from .agent.memory import AgentMemory
            from .agent_routes import agent_bp, init_agent_blueprint

            # Initialize agent for this workspace
            ws_checkers = _get_checkers(ws_id)
            checker_dict = {c.name: c for c in ws_checkers}
            checker_names = [c.name for c in ws_checkers]

            # Optional LLM provider
            llm_provider = None
            if ws["config"].get("llm", {}).get("model"):
                try:
                    from .llm.provider import LLMProvider
                    llm_provider = LLMProvider(ws["config"])
                    if llm_provider.is_available:
                        print(f"[agent:{ws_id[:6]}] LLM: {llm_provider.model_name}")
                    else:
                        print(f"[agent:{ws_id[:6]}] LLM configured but litellm not installed (Tier 1 only)")
                        llm_provider = None
                except Exception as e:
                    print(f"[agent:{ws_id[:6]}] LLM init failed: {e} (Tier 1 only)")

            # Build dependency graph (merge defaults + checker-declared deps)
            dep_graph = CheckerDependencyGraph()
            for c in ws_checkers:
                if hasattr(c, 'depends_on') and c.depends_on:
                    dep_graph.add_from_checker(c.name, c.depends_on)

            memory = AgentMemory(workspace_id=ws_id)
            observer = FileObserver(ws["project_root"], ws["config"])
            reasoner = Reasoner(ws["config"], checker_names)
            executor = Executor(
                checker_dict, ws["project_root"], ws["config"],
                dep_graph, llm_provider, workspace_id=ws_id
            )

            agent_loop = AgentLoop(
                config=ws["config"],
                checkers_dict=checker_dict,
                project_root=ws["project_root"],
                workspace_id=ws_id,
                memory=memory,
                reasoner=reasoner,
                executor=executor,
                observer=observer,
            )

            init_agent_blueprint(ws_id, agent_loop)
            app.config["AGENT_LOOPS"][ws_id] = agent_loop

            # Register blueprint once (first workspace that enables agent)
            if not _any_agent_enabled:
                app.register_blueprint(agent_bp)
                _any_agent_enabled = True

            # Auto-start if configured
            if ws["config"].get("agent", {}).get("auto_start", True):
                if agent_loop.start():
                    print(f"[agent] ✓ Started for '{ws['name']}' (watching {ws['project_root']})")
                else:
                    print(f"[agent] ⚠ Failed to start for '{ws['name']}' (lock conflict?)")

        except ImportError as e:
            print(f"[agent] ⚠ Agent dependencies missing: {e}")
            break  # No point trying other workspaces if imports fail
        except Exception as e:
            print(f"[agent] ⚠ Agent init error for '{ws['name']}': {e}")

    # ── Monitor integration (per-workspace, config-driven) ──────────
    # Each workspace with monitor.enabled: true gets its own MainServiceConnector.
    # Blueprint registered once; connector lookup is workspace-aware.

    def _maybe_init_monitor_for_ws(the_app, ws):
        """Create a MainServiceConnector for a workspace if monitor config exists.

        Called at startup for all workspaces, and at runtime when adding a workspace.
        Idempotent: skips if connector already exists for this workspace.
        Also lazily registers the monitor blueprint if not yet registered.
        """
        ws_id = ws["id"]
        connectors = the_app.config["MONITOR_CONNECTORS"]
        if ws_id in connectors:
            return connectors[ws_id]  # already initialized

        monitor_cfg = ws.get("config", {}).get("monitor", {})
        if not monitor_cfg.get("enabled", False):
            return None

        try:
            from .live_monitor import MainServiceConnector

            connector = MainServiceConnector(ws["config"])
            connector.start()
            connectors[ws_id] = connector

            # Lazily register monitor blueprint if not yet done
            if not the_app.config.get("_MONITOR_BP_REGISTERED"):
                try:
                    from .monitor_routes import monitor_bp, init_monitor_blueprint
                    init_monitor_blueprint(the_app)
                    the_app.register_blueprint(monitor_bp)
                    the_app.config["_MONITOR_BP_REGISTERED"] = True
                except Exception as bp_err:
                    print(f"[monitor] Blueprint registration failed: {bp_err}")

            db_status = "available" if connector.db_readable else "not found"
            print(f"[monitor:{ws_id[:6]}] ✓ Connector for '{ws['name']}' — DB: {db_status}")
            return connector
        except Exception as e:
            print(f"[monitor:{ws_id[:6]}] ⚠ Init failed for '{ws['name']}': {e}")
            return None

    # Initialize connectors for all workspaces with monitor.enabled
    app.config["_MONITOR_BP_REGISTERED"] = False
    for ws_id, ws in workspaces.items():
        _maybe_init_monitor_for_ws(app, ws)

    # Legacy compat: also set MONITOR_CONNECTOR for any code referencing it
    default_ws_id = app.config["DEFAULT_WORKSPACE"]
    if default_ws_id in app.config["MONITOR_CONNECTORS"]:
        app.config["MONITOR_CONNECTOR"] = app.config["MONITOR_CONNECTORS"][default_ws_id]

    return app


