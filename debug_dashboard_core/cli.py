"""CLI for Debug Dashboard Core — init / run / agent subcommands.

Usage:
    python -m debug_dashboard_core init  <workspace> [--name] [--port] [--output-dir] [--force] [--dry-run]
    python -m debug_dashboard_core run   <workspace> [--config] [--port] [--host]
    python -m debug_dashboard_core agent <workspace> [--config] [--port] [--host] [--no-watch] [--no-llm]
"""

import argparse
import sys
from pathlib import Path


# ── Safety checks ─────────────────────────────────────

_DANGEROUS_PATHS = {"/", "/bin", "/usr", "/etc", "/var", "/tmp", "/System", "/Library"}


def _validate_workspace(workspace: Path) -> None:
    """Reject dangerous workspace paths."""
    resolved = str(workspace.resolve())

    if resolved in _DANGEROUS_PATHS:
        print(f"  Error: refusing to use system directory as workspace: {resolved}")
        sys.exit(1)

    if resolved == str(Path.home()):
        print(f"  Error: refusing to use home directory as workspace: {resolved}")
        sys.exit(1)

    if ".." in workspace.parts:
        print(f"  Error: workspace path must not contain '..': {workspace}")
        sys.exit(1)

    if not workspace.is_dir():
        print(f"  Error: workspace not found: {workspace}")
        sys.exit(1)


# ── Subcommands ───────────────────────────────────────

def cmd_init(args) -> int:
    """Scaffold debug dashboard for a workspace."""
    from .scaffold import scaffold_project

    workspace = Path(args.workspace).resolve()
    _validate_workspace(workspace)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else workspace / ".debugger"
    core_path = Path(__file__).resolve().parent.parent  # debugger_agent/

    return scaffold_project(
        workspace=workspace,
        output_dir=output_dir,
        project_name=args.name,
        port=args.port,
        core_path=core_path,
        force=args.force,
        dry_run=args.dry_run,
    )


def _resolve_extra_workspaces(add_workspace_args: list) -> list:
    """Resolve --add-workspace arguments to config.yaml paths.

    If a directory has no existing config, auto-scaffolds one by scanning
    the project (README, code structure, DB, packages, framework).
    """
    extra = []
    for raw in (add_workspace_args or []):
        p = Path(raw).resolve()
        if p.is_file() and p.name.endswith((".yaml", ".yml")):
            extra.append(str(p))
        elif p.is_dir():
            # Search for config.yaml in standard locations
            found = None
            for candidate in [
                p / ".debugger" / "config.yaml",
                p / "debug_dashboard" / "config.yaml",
                p / "config.yaml",
            ]:
                if candidate.exists():
                    found = str(candidate)
                    break

            if found:
                extra.append(found)
            else:
                # Auto-scaffold: scan the project and generate config
                config_path = _auto_scaffold_workspace(p)
                if config_path:
                    extra.append(config_path)
        else:
            print(f"[workspace] ⚠ Not found: {raw}")
    return extra


def _auto_scaffold_workspace(workspace: Path) -> str | None:
    """Auto-scaffold debug dashboard for a workspace directory.

    Scans the project (framework, DB, packages, source dirs) and
    generates .debugger/ with config.yaml and scanner templates.

    Returns config.yaml path on success, None on failure.
    """
    from .scaffold import scaffold_project

    output_dir = workspace / ".debugger"
    core_path = Path(__file__).resolve().parent.parent

    print(f"[workspace] ⚡ Auto-initializing: {workspace.name}")
    print(f"  Scanning project structure...")

    try:
        exit_code = scaffold_project(
            workspace=workspace,
            output_dir=output_dir,
            project_name=None,  # auto-detect from dir name
            port=5010,          # default, not used for extra workspaces
            core_path=core_path,
            force=False,        # don't overwrite existing
            dry_run=False,
        )
        if exit_code == 0:
            config_path = output_dir / "config.yaml"
            if config_path.exists():
                print(f"  ✓ Generated: {config_path}")
                return str(config_path)
        print(f"[workspace] ⚠ Auto-init failed for {workspace}")
        return None
    except Exception as e:
        print(f"[workspace] ⚠ Auto-init error for {workspace}: {e}")
        return None


def cmd_run(args) -> int:
    """Start debug dashboard directly."""
    workspace = Path(args.workspace).resolve()

    # Auto-detect config location
    if args.config:
        config_path = Path(args.config).resolve()
    elif (workspace / ".debugger" / "config.yaml").exists():
        config_path = workspace / ".debugger" / "config.yaml"
    elif (workspace / "debug_dashboard" / "config.yaml").exists():
        config_path = workspace / "debug_dashboard" / "config.yaml"
    elif (workspace / "config.yaml").exists():
        config_path = workspace / "config.yaml"
    else:
        print(f"\n  Error: No config.yaml found for {workspace}")
        print(f"  Run 'python -m debug_dashboard_core init {workspace}' first.\n")
        return 1

    # Ensure debug_dashboard_core is importable
    core_parent = Path(__file__).resolve().parent.parent
    if str(core_parent) not in sys.path:
        sys.path.insert(0, str(core_parent))

    from .app import create_app

    # Port: CLI override > config > default 5010
    port = args.port
    if port is None:
        import yaml
        with open(config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        port = cfg.get("dashboard", {}).get("port", 5010)

    # Resolve extra workspaces
    extra_workspaces = _resolve_extra_workspaces(getattr(args, 'add_workspace', None))

    app = create_app(config_path=str(config_path), extra_workspaces=extra_workspaces)

    ws_count = len(app.config.get("WORKSPACES", {}))
    print(f"\n  Debug Dashboard starting at http://{args.host}:{port}")
    print(f"  Config: {config_path}")
    if ws_count > 1:
        print(f"  Workspaces: {ws_count} loaded")
    print()
    app.run(host=args.host, port=port, debug=False, threaded=True)
    return 0


def cmd_agent(args) -> int:
    """Start in agent mode: file watcher + rule-based reasoning + optional LLM."""
    workspace = Path(args.workspace).resolve()

    # Auto-detect config (same logic as cmd_run)
    if args.config:
        config_path = Path(args.config).resolve()
    elif (workspace / ".debugger" / "config.yaml").exists():
        config_path = workspace / ".debugger" / "config.yaml"
    elif (workspace / "debug_dashboard" / "config.yaml").exists():
        config_path = workspace / "debug_dashboard" / "config.yaml"
    elif (workspace / "config.yaml").exists():
        config_path = workspace / "config.yaml"
    else:
        print(f"\n  Error: No config.yaml found for {workspace}")
        print(f"  Run 'python -m debug_dashboard_core init {workspace}' first.\n")
        return 1

    core_parent = Path(__file__).resolve().parent.parent
    if str(core_parent) not in sys.path:
        sys.path.insert(0, str(core_parent))

    # Override config to enable agent mode
    import yaml
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    # Force agent.enabled = true
    cfg.setdefault("agent", {})["enabled"] = True

    if args.no_watch:
        cfg["agent"]["auto_scan_on_change"] = False

    if args.no_llm:
        cfg.setdefault("llm", {})["model"] = ""

    port = args.port
    if port is None:
        port = cfg.get("dashboard", {}).get("port", 5010)

    # Write temporary augmented config
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, prefix="agent_") as tmp:
        yaml.safe_dump(cfg, tmp, allow_unicode=True)
        tmp_config = tmp.name

    from .app import create_app

    extra_workspaces = _resolve_extra_workspaces(getattr(args, 'add_workspace', None))
    app = create_app(config_path=tmp_config, extra_workspaces=extra_workspaces)

    ws_count = len(app.config.get("WORKSPACES", {}))
    agent_count = len(app.config.get("AGENT_LOOPS", {}))
    print(f"\n  Debug Dashboard AGENT MODE")
    print(f"  URL: http://{args.host}:{port}")
    print(f"  Config: {config_path}")
    print(f"  Workspaces: {ws_count} | Agents: {agent_count}")
    if args.no_watch:
        print(f"  File watcher: DISABLED")
    if args.no_llm:
        print(f"  LLM: DISABLED")
    print()
    app.run(host=args.host, port=port, debug=False, threaded=True)

    # Cleanup
    import os
    try:
        os.unlink(tmp_config)
    except OSError:
        pass
    return 0


# ── Main ──────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="debug_dashboard_core",
        description="Debug Dashboard Core — diagnostic framework CLI",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- init ---
    init_p = subparsers.add_parser("init", help="Scaffold debug dashboard for a project")
    init_p.add_argument("workspace", help="Path to project workspace")
    init_p.add_argument("--name", default=None, help="Project name (default: directory name)")
    init_p.add_argument("--port", type=int, default=5010, help="Dashboard port (default: 5010)")
    init_p.add_argument("--output-dir", default=None, help="Output directory (default: <workspace>/.debugger/)")
    init_p.add_argument("--force", action="store_true", help="Overwrite existing files")
    init_p.add_argument("--dry-run", action="store_true", help="Show what would be created without writing")

    # --- run ---
    run_p = subparsers.add_parser("run", help="Start debug dashboard for a project")
    run_p.add_argument("workspace", help="Path to project workspace")
    run_p.add_argument("--config", default=None, help="Config file path (default: auto-detect)")
    run_p.add_argument("--port", type=int, default=None, help="Override port")
    run_p.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    run_p.add_argument("--add-workspace", action="append", default=[],
                        help="Additional workspace (directory or config.yaml path). Repeatable.")

    # --- agent ---
    agent_p = subparsers.add_parser("agent", help="Start in agent mode (with file watcher + LLM)")
    agent_p.add_argument("workspace", help="Path to project workspace")
    agent_p.add_argument("--config", default=None, help="Config file path")
    agent_p.add_argument("--port", type=int, default=None, help="Override port")
    agent_p.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    agent_p.add_argument("--no-watch", action="store_true", help="Disable file watcher")
    agent_p.add_argument("--no-llm", action="store_true", help="Disable LLM integration")
    agent_p.add_argument("--add-workspace", action="append", default=[],
                          help="Additional workspace. Repeatable.")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "init":
        return cmd_init(args)
    elif args.command == "run":
        return cmd_run(args)
    elif args.command == "agent":
        return cmd_agent(args)

    return 0
