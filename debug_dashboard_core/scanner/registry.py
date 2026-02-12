"""
Plugin registry — auto-discovers BaseChecker subclasses from:
  1. builtin/ directory (core generic checkers via pkgutil)
  2. Extra plugin directories (project-specific checkers via spec_from_file_location)

Module naming for plugins:
  debugger_plugin.{parent_dir}.{dir_name}.{file_stem}
  e.g., debugger_plugin.project0914.scanner.url_parsing
"""

import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

from .base import BaseChecker


class CheckerRegistry:
    _checkers: Dict[str, BaseChecker] = {}
    _discovered: bool = False
    _extra_dirs: List[Path] = []
    _load_errors: List[dict] = []  # plugin load failures for UI notification

    @classmethod
    def configure(cls, extra_dirs: List[str] = None):
        """Set plugin directories. Call before auto_discover()."""
        cls._extra_dirs = [Path(d) for d in (extra_dirs or [])]

    @classmethod
    def reset(cls):
        """Reset registry state. Useful for testing or reconfiguration."""
        cls._checkers = {}
        cls._discovered = False
        cls._extra_dirs = []
        cls._load_errors = []
        # Clean up plugin modules from sys.modules
        to_remove = [k for k in sys.modules if k.startswith("debugger_plugin.")]
        for k in to_remove:
            del sys.modules[k]

    @classmethod
    def auto_discover(cls):
        """Discover checkers from builtin/ and extra plugin directories."""
        if cls._discovered:
            return
        cls._load_errors = []

        # Step 1: Scan builtin/ directory (pkgutil — standard package import)
        builtin_dir = Path(__file__).parent / "builtin"
        if builtin_dir.exists():
            cls._scan_builtin_package(builtin_dir)

        # Step 2: Scan extra plugin directories (spec_from_file_location)
        for plugin_dir in cls._extra_dirs:
            if plugin_dir.exists() and plugin_dir.is_dir():
                cls._scan_directory_as_files(plugin_dir)

        cls._discovered = True

    @classmethod
    def _scan_builtin_package(cls, builtin_dir: Path):
        """Load checkers from builtin/ as a package using pkgutil."""
        for _, module_name, _ in pkgutil.iter_modules([str(builtin_dir)]):
            if module_name in ("base", "registry", "__init__"):
                continue
            try:
                module = importlib.import_module(
                    f".builtin.{module_name}",
                    package="debug_dashboard_core.scanner"
                )
                cls._register_from_module(module)
            except Exception as e:
                print(f"[registry] ⚠ Builtin load failed: {module_name} — {e}")
                cls._load_errors.append({"file": f"builtin/{module_name}.py", "error": str(e)})

    @classmethod
    def _scan_directory_as_files(cls, directory: Path):
        """Load checkers from a plugin directory using spec_from_file_location.
        Each .py file is loaded as an independent module with unique naming."""
        parent_name = directory.parent.name  # e.g., "project0914"
        dir_name = directory.name            # e.g., "scanner"

        for py_file in sorted(directory.glob("*.py")):
            if py_file.stem in ("__init__", "base", "registry"):
                continue
            if py_file.name.startswith("._"):
                continue  # macOS resource fork — skip
            try:
                # Unique module name: debugger_plugin.{parent}.{dir}.{stem}
                module_name = f"debugger_plugin.{parent_name}.{dir_name}.{py_file.stem}"
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                cls._register_from_module(module)
            except Exception as e:
                print(f"[registry] ⚠ Plugin load failed: {py_file.name} — {e}")
                cls._load_errors.append({"file": py_file.name, "error": str(e)})

    @classmethod
    def _register_from_module(cls, module):
        """Find and register BaseChecker subclasses from a loaded module."""
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, BaseChecker)
                    and attr is not BaseChecker
                    and hasattr(attr, 'name')
                    and attr.name):
                cls._checkers[attr.name] = attr()

    @classmethod
    def get_all(cls, order: List[str] = None) -> List[BaseChecker]:
        """Get all checkers, optionally sorted by order list.
        Checkers not in order are appended at the end."""
        cls.auto_discover()
        if order is None:
            # Return in insertion order (builtin first, then plugins)
            return list(cls._checkers.values())

        ordered = []
        for name in order:
            if name in cls._checkers:
                ordered.append(cls._checkers[name])
        # Append any checkers not in the order list
        for name, checker in cls._checkers.items():
            if name not in (order or []):
                ordered.append(checker)
        return ordered

    @classmethod
    def get_enabled(cls, config: dict, order: List[str] = None) -> List[BaseChecker]:
        """Get enabled checkers, filtered by config and optionally sorted."""
        return [c for c in cls.get_all(order=order) if c.is_applicable(config)]

    @classmethod
    def get_by_name(cls, name: str) -> Optional[BaseChecker]:
        """Lookup a checker by its name attribute."""
        cls.auto_discover()
        return cls._checkers.get(name)

    # ── Isolated Discovery (multi-workspace) ──────────

    @classmethod
    def discover_isolated(cls, extra_dirs: List[str] = None) -> tuple:
        """Discover checkers without mutating global registry state.

        Returns (checkers_dict, load_errors) where:
            checkers_dict: {name: BaseChecker instance}
            load_errors: list of {file, error} dicts

        Used by multi-workspace mode to get independent checker sets.
        """
        checkers: Dict[str, BaseChecker] = {}
        load_errors: List[dict] = []

        # 1. Builtin checkers (always the same)
        builtin_dir = Path(__file__).parent / "builtin"
        if builtin_dir.exists():
            for _, module_name, _ in pkgutil.iter_modules([str(builtin_dir)]):
                if module_name in ("base", "registry", "__init__"):
                    continue
                try:
                    module = importlib.import_module(
                        f".builtin.{module_name}",
                        package="debug_dashboard_core.scanner"
                    )
                    cls._register_from_module_to(module, checkers)
                except Exception as e:
                    load_errors.append({"file": f"builtin/{module_name}.py", "error": str(e)})

        # 2. Extra plugin directories
        for d_str in (extra_dirs or []):
            directory = Path(d_str)
            if not directory.exists() or not directory.is_dir():
                continue
            parent_name = directory.parent.name
            dir_name = directory.name

            for py_file in sorted(directory.glob("*.py")):
                if py_file.stem in ("__init__", "base", "registry"):
                    continue
                if py_file.name.startswith("._"):
                    continue
                try:
                    module_name = f"debugger_plugin.{parent_name}.{dir_name}.{py_file.stem}"
                    # Check if already loaded
                    if module_name in sys.modules:
                        module = sys.modules[module_name]
                    else:
                        spec = importlib.util.spec_from_file_location(module_name, py_file)
                        if spec is None or spec.loader is None:
                            continue
                        module = importlib.util.module_from_spec(spec)
                        sys.modules[module_name] = module
                        spec.loader.exec_module(module)
                    cls._register_from_module_to(module, checkers)
                except Exception as e:
                    load_errors.append({"file": py_file.name, "error": str(e)})

        return checkers, load_errors

    @classmethod
    def _register_from_module_to(cls, module, target_dict: Dict[str, BaseChecker]):
        """Register BaseChecker subclasses from a module into target_dict."""
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type)
                    and issubclass(attr, BaseChecker)
                    and attr is not BaseChecker
                    and hasattr(attr, 'name')
                    and attr.name):
                target_dict[attr.name] = attr()
