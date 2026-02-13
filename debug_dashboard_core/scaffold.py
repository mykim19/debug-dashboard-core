"""Workspace scanner and scaffold generator.

Responsibilities:
    1. scan_workspace()   — detect project characteristics
    2. render_templates() — generate file contents from scan results
    3. write_scaffold()   — write files to disk (respects --force / --dry-run)
"""

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional


# ── Workspace Scanner ─────────────────────────────────

_SKIP_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
    ".debugger", "debug_dashboard", "downloads", "uploads", "logs",
    "backups", ".pytest_cache", "chroma_db", ".claude", ".tox",
    "dist", "build", "egg-info", ".mypy_cache", ".ruff_cache",
}

_MAIN_CANDIDATES = ["app.py", "main.py", "manage.py", "server.py", "wsgi.py"]

_PRIORITY_PACKAGES = {
    "flask", "django", "fastapi", "sqlalchemy", "celery",
    "whisper", "torch", "tensorflow", "numpy", "pandas",
    "flask_socketio", "gunicorn", "uvicorn", "requests",
    "pydantic", "alembic", "pytest",
}


def scan_workspace(workspace: Path) -> Dict[str, Any]:
    """Scan workspace for project characteristics. Returns discovery dict."""
    result: Dict[str, Any] = {
        "project_name": workspace.name,
        "db_files": [],
        "db_tables": {},          # {db_file: [table_names]}
        "main_file": None,
        "packages": [],
        "python_dirs": [],
        "has_env": False,
        "has_git": False,
        "framework": None,        # "Flask" / "FastAPI" / "Django" / None
    }

    # 1. Detect main file
    for candidate in _MAIN_CANDIDATES:
        if (workspace / candidate).is_file():
            result["main_file"] = candidate
            break

    # 2. Find *.db / *.sqlite / *.sqlite3 files (top-level only)
    for pattern in ("*.db", "*.sqlite", "*.sqlite3"):
        for f in workspace.glob(pattern):
            if not f.name.startswith(".") and f.name not in result["db_files"]:
                result["db_files"].append(f.name)

    # 3. List tables from discovered DB files
    for db_name in result["db_files"]:
        db_path = workspace / db_name
        try:
            conn = sqlite3.connect(str(db_path))
            tables = [
                row[0] for row in
                conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                if not row[0].startswith("sqlite_")
            ]
            conn.close()
            result["db_tables"][db_name] = tables
        except Exception:
            result["db_tables"][db_name] = []

    # 4. Scan requirements.txt
    req_path = workspace / "requirements.txt"
    if req_path.is_file():
        try:
            for line in req_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and not line.startswith("-"):
                    pkg = re.split(r"[=><!\[;]", line)[0].strip()
                    if pkg:
                        result["packages"].append(pkg)
        except Exception:
            pass

    # 5. Fallback: scan pyproject.toml (simple heuristic)
    if not result["packages"]:
        pyproject = workspace / "pyproject.toml"
        if pyproject.is_file():
            try:
                content = pyproject.read_text(encoding="utf-8")
                in_deps = False
                for line in content.splitlines():
                    if re.match(r"\[(project\.dependencies|tool\.poetry\.dependencies)\]", line.strip()):
                        in_deps = True
                        continue
                    if in_deps:
                        if line.strip().startswith("["):
                            break
                        m = re.match(r'["\']?([a-zA-Z0-9_-]+)', line.strip())
                        if m:
                            result["packages"].append(m.group(1))
            except Exception:
                pass

    # 6. Detect Python package directories
    for child in sorted(workspace.iterdir()):
        if (child.is_dir()
                and child.name not in _SKIP_DIRS
                and not child.name.startswith(".")
                and (child / "__init__.py").exists()):
            result["python_dirs"].append(child.name)

    # 7. Detect framework (quick heuristic from main file)
    if result["main_file"]:
        try:
            src = (workspace / result["main_file"]).read_text(encoding="utf-8", errors="ignore")[:3000]
            if "from flask" in src.lower() or "Flask(" in src:
                result["framework"] = "Flask"
            elif "from fastapi" in src.lower() or "FastAPI(" in src:
                result["framework"] = "FastAPI"
            elif "from django" in src.lower() or "django" in src.lower():
                result["framework"] = "Django"
        except Exception:
            pass

    # 8. Basic checks
    result["has_env"] = (workspace / ".env").is_file()
    result["has_git"] = (workspace / ".git").is_dir()

    # 9. Feature detection — for smart checker enablement
    result["features"] = _detect_features(workspace, result)

    return result


def _detect_features(workspace: Path, scan: Dict[str, Any]) -> Dict[str, bool]:
    """Detect project features to auto-enable relevant checkers."""
    features: Dict[str, bool] = {
        "has_ytdlp": False,       # yt-dlp pipeline (YouTube)
        "has_whisper": False,      # OpenAI Whisper transcription
        "has_knowledge_graph": False,  # knowledge_nodes/edges tables
        "has_ontology": False,     # ontology / concept tables
        "has_rag": False,          # RAG pipeline (embeddings, LLM search)
        "has_golden": False,       # Golden sentence extraction
        "has_citations": False,    # Citation management
        "has_search_index": False, # FTS5 / search index
        "has_skills": False,       # Skill system (skill.md files)
        "has_agent": False,        # AI agent system (budget, invocations)
        "has_tests": False,        # Test directory
    }

    # Package-based detection
    pkg_lower = {p.lower().replace("-", "_") for p in scan.get("packages", [])}
    features["has_whisper"] = "whisper" in pkg_lower or "openai_whisper" in pkg_lower
    features["has_rag"] = any(p in pkg_lower for p in ("langchain", "chromadb", "lightrag", "faiss_cpu"))

    # Source file detection
    if scan.get("main_file"):
        try:
            src = (workspace / scan["main_file"]).read_text(encoding="utf-8", errors="ignore")[:5000]
            src_lower = src.lower()
            features["has_ytdlp"] = "yt_dlp" in src_lower or "yt-dlp" in src_lower or "ytdl" in src_lower
        except Exception:
            pass

    # Directory-based detection
    features["has_skills"] = (workspace / "skills").is_dir()
    features["has_tests"] = (workspace / "tests").is_dir() or (workspace / "test").is_dir()

    if (workspace / "agent").is_dir():
        features["has_agent"] = True

    # Service file detection (K-Scaffold style)
    svc_dir = workspace / "backend" / "services"
    if svc_dir.is_dir():
        features["has_rag"] = True
        if (svc_dir / "golden_extractor.py").is_file():
            features["has_golden"] = True
        if (svc_dir / "lightrag_service.py").is_file():
            features["has_rag"] = True

    # DB table-based detection
    all_tables = set()
    for db_tables in scan.get("db_tables", {}).values():
        all_tables.update(db_tables)

    features["has_knowledge_graph"] = "knowledge_nodes" in all_tables and "knowledge_edges" in all_tables
    features["has_ontology"] = "global_nodes" in all_tables or "concept_synonyms" in all_tables
    features["has_golden"] = features["has_golden"] or "golden_sentences" in all_tables
    features["has_citations"] = "citations" in all_tables
    features["has_search_index"] = any("fts" in t.lower() or "search" in t.lower() for t in all_tables)
    features["has_agent"] = (features["has_agent"]
                             or "agent_sessions" in all_tables
                             or "budget_history" in all_tables
                             or "agent_runs" in all_tables)

    return features


# ── Template Rendering ────────────────────────────────

def _titleize(name: str) -> str:
    """Convert dir name to human title: 'my-project' → 'My Project'"""
    return name.replace("-", " ").replace("_", " ").title()


def _select_key_packages(packages: List[str], limit: int = 8) -> List[str]:
    """Select most relevant packages for environment checking."""
    selected = [p for p in packages if p.lower().replace("-", "_") in _PRIORITY_PACKAGES]
    for p in packages:
        if p not in selected and len(selected) < limit:
            selected.append(p)
    return selected or ["flask"]


def _yaml_list(items: List[str]) -> str:
    """Format list as inline YAML: ["a", "b"]"""
    if not items:
        return "[]"
    return "[" + ", ".join(f'"{item}"' for item in items) + "]"


def render_templates(
    workspace: Path,
    output_dir: Path,
    scan: Dict[str, Any],
    project_name: str,
    port: int,
    core_path: Path,
) -> Dict[str, str]:
    """Generate file contents from scan results. Returns {relative_path: content}."""
    files: Dict[str, str] = {}

    # ① app.py — thin launcher
    files["app.py"] = f'''"""Debug Dashboard — thin launcher (auto-generated)"""

import sys
from pathlib import Path

# debugger_agent root — so debug_dashboard_core is importable
# To make this portable, pip install debug_dashboard_core in the future
sys.path.insert(0, {str(core_path)!r})

from debug_dashboard_core.app import create_app

APP_DIR = Path(__file__).resolve().parent
app = create_app(config_path=str(APP_DIR / "config.yaml"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port={port}, debug=False, threaded=True)
'''

    # ② config.yaml — pre-filled from scan
    db_path = scan["db_files"][0] if scan["db_files"] else "app.db"
    tables = scan["db_tables"].get(db_path, [])
    required_tables = tables[:10]
    optional_tables = tables[10:20]
    key_packages = _select_key_packages(scan["packages"])
    main_file = scan["main_file"] or "app.py"
    scan_dirs = ["."] + [d + "/" for d in scan["python_dirs"]]
    first_table = required_tables[0] if required_tables else ""
    framework = scan["framework"] or "Unknown"

    features = scan.get("features", {})

    # Build checks_order — builtin first, then auto-detected
    checks_order_lines = [
        f"checks_order:",
        f"  - environment",
        f"  - database",
        f"  - performance",
        f"  - security",
        f"  # ── common checkers (auto-enabled) ──",
        f"  - api_health",
        f"  - dependency",
        f"  - code_quality",
    ]
    if features.get("has_tests"):
        checks_order_lines.append(f"  - test_coverage")
    else:
        checks_order_lines.append(f"  # - test_coverage")
    checks_order_lines.append(f"  - config_drift")

    # Domain-specific checkers — enabled only if features detected
    domain_lines = []
    if features.get("has_ytdlp"):
        domain_lines.append(f"  - ytdlp_pipeline")
    if features.get("has_whisper"):
        domain_lines.append(f"  - whisper_health")
    if features.get("has_knowledge_graph"):
        domain_lines.append(f"  - knowledge_graph")
    if features.get("has_ontology"):
        domain_lines.append(f"  - ontology_sync")
    if features.get("has_ytdlp"):
        domain_lines.append(f"  - url_pattern")
    if features.get("has_agent"):
        domain_lines.append(f"  - agent_budget")
    if features.get("has_rag"):
        domain_lines.append(f"  - rag_pipeline")
    if features.get("has_golden"):
        domain_lines.append(f"  - golden_quality")
    if features.get("has_citations"):
        domain_lines.append(f"  - citation_integrity")
    if features.get("has_search_index"):
        domain_lines.append(f"  - search_index")
    if features.get("has_skills"):
        domain_lines.append(f"  - skill_template")
    if features.get("has_golden") or features.get("has_rag"):
        domain_lines.append(f"  - schema_migration")

    if domain_lines:
        checks_order_lines.append(f"  # ── domain-specific checkers (auto-detected) ──")
        checks_order_lines.extend(domain_lines)

    checks_order_lines.append(f"  # Add more custom checkers below:")
    checks_order_lines.append(f"  # - my_custom_checker")

    # Build checks section
    checks_lines = [
        f"",
        f"checks:",
        f"  environment:",
        f"    enabled: true",
        f"    packages: {_yaml_list(key_packages)}",
        f'    cleanup_dir: "downloads"',
        f"    env_template: |",
        f"      # Auto-generated .env template ({framework})",
        f"      FLASK_SECRET_KEY=change-me-to-random-string",
        f"",
        f"  database:",
        f"    enabled: {'true' if scan['db_files'] else 'false  # TODO: no DB file detected'}",
        f"    required_tables: {_yaml_list(required_tables)}",
        f"    optional_tables: {_yaml_list(optional_tables)}",
        f"",
        f"  performance:",
        f"    enabled: true",
        f'    main_table: "{first_table}"{"  # TODO: set your main table" if not first_table else ""}',
        f"    index_columns: []  # TODO: add columns that need indexes",
        f"    n_plus_1_dirs: {_yaml_list(scan['python_dirs'])}",
        f"",
        f"  security:",
        f"    enabled: true",
        f'    main_file: "{main_file}"',
        f"    scan_dirs: {_yaml_list(scan_dirs)}",
        f"",
        f"  # ── Common checkers ──",
        f"  api_health:",
        f"    enabled: true",
        f'    main_file: "{main_file}"',
        f"    scan_dirs: {_yaml_list(scan_dirs)}",
        f"",
        f"  dependency:",
        f"    enabled: true",
        f"    scan_dirs: {_yaml_list(scan_dirs)}",
        f"",
        f"  code_quality:",
        f"    enabled: true",
        f"    scan_dirs: {_yaml_list(scan_dirs)}",
        f"    file_line_limit: 500",
        f"    func_line_limit: 80",
        f"    todo_warn_threshold: 10",
        f"",
        f"  test_coverage:",
        f"    enabled: {'true' if features.get('has_tests') else 'false'}",
        f"",
        f"  config_drift:",
        f"    enabled: true",
        f"    scan_dirs: {_yaml_list(scan_dirs)}",
    ]

    # Domain-specific checker configs
    if features.get("has_ytdlp"):
        checks_lines.extend([
            f"",
            f"  # ── YouTube/Media ──",
            f"  ytdlp_pipeline:",
            f"    enabled: true",
            f'    main_file: "{main_file}"',
            f'    output_dir: "downloads"',
        ])
    if features.get("has_whisper"):
        checks_lines.extend([
            f"",
            f"  whisper_health:",
            f"    enabled: true",
            f'    model: "medium"',
            f"    scan_dirs: {_yaml_list(scan_dirs)}",
        ])
    if features.get("has_knowledge_graph"):
        checks_lines.extend([
            f"",
            f"  # ── Knowledge/Ontology ──",
            f"  knowledge_graph:",
            f"    enabled: true",
            f"    min_mapping_pct: 50",
        ])
    if features.get("has_ontology"):
        checks_lines.extend([
            f"",
            f"  ontology_sync:",
            f"    enabled: true",
        ])
    if features.get("has_ytdlp"):
        checks_lines.extend([
            f"",
            f"  url_pattern:",
            f"    enabled: true",
            f'    url_files: ["app.py", "utils/content_hash.py"]',
        ])
    if features.get("has_agent"):
        checks_lines.extend([
            f"",
            f"  # ── Agent ──",
            f"  agent_budget:",
            f"    enabled: true",
            f"    daily_cost_limit: 5.0",
        ])
    if features.get("has_rag"):
        checks_lines.extend([
            f"",
            f"  # ── RAG Pipeline ──",
            f"  rag_pipeline:",
            f"    enabled: true",
            f"    embedding_dim: 768",
        ])
    if features.get("has_golden"):
        checks_lines.extend([
            f"",
            f"  golden_quality:",
            f"    enabled: true",
            f"    exact_min_pct: 70",
        ])
    if features.get("has_citations"):
        checks_lines.extend([
            f"",
            f"  citation_integrity:",
            f"    enabled: true",
        ])
    if features.get("has_search_index"):
        checks_lines.extend([
            f"",
            f"  search_index:",
            f"    enabled: true",
            f"    cache_warn_rows: 10000",
        ])
    if features.get("has_skills"):
        checks_lines.extend([
            f"",
            f"  skill_template:",
            f"    enabled: true",
            f'    skills_dir: "skills"',
        ])
    if features.get("has_golden") or features.get("has_rag"):
        total_tables = sum(len(v) for v in scan.get("db_tables", {}).values())
        checks_lines.extend([
            f"",
            f"  schema_migration:",
            f"    enabled: true",
            f"    expected_table_count: {total_tables}",
        ])

    config_lines = [
        f"config_schema_version: 1",
        f"",
        f"project:",
        f'  name: "{project_name}"',
        f'  root: "{workspace}"',
        f'  db_path: "{db_path}"',
        f"",
        f"dashboard:",
        f"  port: {port}",
        f"",
        f"plugins:",
        f'  dirs: ["scanner"]',
        f"",
    ] + checks_order_lines + checks_lines

    files["config.yaml"] = "\n".join(config_lines) + "\n"

    # ③ scanner/__init__.py
    files["scanner/__init__.py"] = "# Project-specific checkers — add .py files here, auto-discovered\n"

    # ④ scanner/sample_checker.py
    files["scanner/sample_checker.py"] = '''"""
Sample checker — rename and customize for your project.

To activate:
  1. Rename this file (e.g., auth_checker.py)
  2. Change `name` to a unique identifier
  3. Add it to checks_order in config.yaml
  4. Optionally add config under checks.<name> in config.yaml
"""

from pathlib import Path
from debug_dashboard_core.scanner.base import BaseChecker, CheckResult, PhaseReport


class SampleChecker(BaseChecker):
    name = "sample"          # unique ID — must match checks_order / config key
    display_name = "SAMPLE"
    description = "A sample checker to get you started."
    icon = "🔍"
    color = "#6366f1"
    tooltip_why = "Replace with why this check matters."
    tooltip_what = "Replace with what is being inspected."
    tooltip_result = "Replace with what PASS/WARN/FAIL mean."

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)

        # Example: check if a file exists
        # target = project_root / "some_file.py"
        # if target.exists():
        #     report.add(CheckResult("file_check", CheckResult.PASS, "File found"))
        # else:
        #     report.add(CheckResult("file_check", CheckResult.WARN, "File not found",
        #                            fixable=True, fix_desc="Create the missing file"))

        report.add(CheckResult("placeholder", CheckResult.SKIP,
                               "Sample checker — customize me"))
        return report

    def fix(self, check_name: str, project_root: Path, config: dict) -> dict:
        # Example auto-fix
        return {"success": False, "message": "No auto-fix for this check"}
'''

    return files


# ── File Writer ───────────────────────────────────────

def write_scaffold(output_dir: Path, files: Dict[str, str], force: bool) -> bool:
    """Write generated files to disk. Returns True on success."""
    # Check existing files
    if output_dir.exists() and not force:
        existing = [f for f in files if (output_dir / f).exists()]
        if existing:
            print(f"\n  Error: {output_dir} already has files: {', '.join(existing)}")
            print(f"  Use --force to overwrite, or --output-dir to choose a different location.\n")
            return False

    # Write
    for rel_path, content in files.items():
        full_path = output_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

    return True


# ── Post-init Message ─────────────────────────────────

def _print_success(output_dir: Path, workspace: Path, project_name: str,
                   port: int, scan: Dict[str, Any]) -> None:
    """Print post-init summary."""
    # Try to make output_dir relative for cleaner display
    try:
        rel = output_dir.relative_to(workspace)
    except ValueError:
        rel = output_dir

    fw = scan.get("framework") or "Unknown"

    print(f"""
  ✅ Debug Dashboard initialized for "{project_name}"

  Generated files:
    {rel}/app.py                    — thin launcher
    {rel}/config.yaml               — project configuration
    {rel}/scanner/__init__.py       — custom checker package
    {rel}/scanner/sample_checker.py — template checker

  Detected:
    Framework:    {fw}
    Main file:    {scan['main_file'] or '(not found)'}
    DB files:     {', '.join(scan['db_files']) or '(none)'}
    Packages:     {len(scan['packages'])} from requirements
    Source dirs:  {', '.join(scan['python_dirs']) or '(none)'}
    .env:         {'exists' if scan['has_env'] else 'not found'}

  Next steps:
    1. Review and edit {rel}/config.yaml
    2. Add custom checkers in {rel}/scanner/
    3. Start the dashboard:

       python {rel}/app.py
       # or
       python -m debug_dashboard_core run {workspace}

    Dashboard will be at: http://localhost:{port}
""")


def _print_dry_run(output_dir: Path, files: Dict[str, str], scan: Dict[str, Any]) -> None:
    """Print what would be created (--dry-run mode)."""
    print(f"\n  [dry-run] Would create in {output_dir}:\n")
    for rel_path, content in files.items():
        lines = content.count("\n")
        print(f"    {rel_path:40s}  ({lines} lines)")

    fw = scan.get("framework") or "Unknown"
    print(f"\n  Scan results:")
    print(f"    Framework:    {fw}")
    print(f"    Main file:    {scan['main_file'] or '(not found)'}")
    print(f"    DB files:     {', '.join(scan['db_files']) or '(none)'}")
    print(f"    Tables:       {sum(len(v) for v in scan['db_tables'].values())}")
    print(f"    Packages:     {len(scan['packages'])}")
    print(f"    Source dirs:  {', '.join(scan['python_dirs']) or '(none)'}")
    print()


# ── Public API ────────────────────────────────────────

def scaffold_project(
    workspace: Path,
    output_dir: Path,
    project_name: Optional[str] = None,
    port: int = 5010,
    core_path: Optional[Path] = None,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    """Scaffold debug dashboard for a workspace. Returns exit code."""
    # Resolve
    name = project_name or _titleize(workspace.name)
    if core_path is None:
        core_path = Path(__file__).resolve().parent.parent

    # 1. Scan
    scan = scan_workspace(workspace)

    # 2. Render
    files = render_templates(
        workspace=workspace,
        output_dir=output_dir,
        scan=scan,
        project_name=name,
        port=port,
        core_path=core_path,
    )

    # 3. Dry-run or write
    if dry_run:
        _print_dry_run(output_dir, files, scan)
        return 0

    if not write_scaffold(output_dir, files, force):
        return 1

    _print_success(output_dir, workspace, name, port, scan)
    return 0
