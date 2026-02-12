"""CheckerDependencyGraph — topological sort for checker execution ordering.

Resolves which checkers must run before others, and computes an execution
order via Kahn's algorithm. Handles transitive dependencies automatically.
"""
from typing import Dict, List, Set


# Default dependency definitions.
# Key = checker, Value = list of checkers it depends on (must run first).
DEFAULT_DEPENDENCIES: Dict[str, List[str]] = {
    # Infrastructure checkers depend on environment
    "database": ["environment"],
    "performance": ["environment", "database"],
    "security": ["environment"],
    "api_health": ["environment"],
    "dependency": ["environment"],
    "code_quality": ["environment"],
    "test_coverage": ["environment"],
    "config_drift": ["environment"],

    # Domain-specific checkers
    "ytdlp_pipeline": ["environment"],
    "whisper_health": ["environment"],
    "knowledge_graph": ["database"],
    "ontology_sync": ["database", "knowledge_graph"],
    "url_pattern": ["environment"],
    "agent_budget": ["database"],
    "rag_pipeline": ["database"],
    "golden_quality": ["database"],
    "citation_integrity": ["database", "knowledge_graph"],
    "search_index": ["database"],
    "skill_template": ["environment"],
    "schema_migration": ["database"],
}


class CheckerDependencyGraph:
    """Manages checker dependencies and computes execution order."""

    def __init__(self, dependencies: Dict[str, List[str]] = None):
        self._deps: Dict[str, Set[str]] = {}
        raw = dependencies or DEFAULT_DEPENDENCIES
        for checker, deps in raw.items():
            self._deps[checker] = set(deps)

    def add_dependency(self, checker: str, depends_on: str):
        """Add a single dependency edge."""
        self._deps.setdefault(checker, set()).add(depends_on)

    def add_from_checker(self, checker_name: str, depends_on_list: List[str]):
        """Add dependencies declared by a BaseChecker.depends_on attribute."""
        for dep in depends_on_list:
            self.add_dependency(checker_name, dep)

    def get_dependencies(self, checker: str) -> Set[str]:
        return self._deps.get(checker, set())

    def resolve_order(self, checker_names: List[str]) -> List[str]:
        """Topological sort of requested checkers, pulling in dependencies.

        If checker A depends on B, and only A is requested, B will be
        included and run first (but only if B is in the available set).
        """
        # Expand: include all transitive dependencies
        needed: Set[str] = set()
        to_process = list(checker_names)
        while to_process:
            name = to_process.pop()
            if name in needed:
                continue
            needed.add(name)
            for dep in self._deps.get(name, set()):
                if dep not in needed:
                    to_process.append(dep)

        # Topological sort (Kahn's algorithm)
        in_degree: Dict[str, int] = {n: 0 for n in needed}
        for n in needed:
            for dep in self._deps.get(n, set()):
                if dep in needed:
                    in_degree[n] = in_degree.get(n, 0) + 1

        queue = sorted([n for n in needed if in_degree[n] == 0])
        result: List[str] = []

        while queue:
            node = queue.pop(0)
            result.append(node)
            for n in needed:
                if node in self._deps.get(n, set()):
                    in_degree[n] -= 1
                    if in_degree[n] == 0:
                        # Insert in sorted position for determinism
                        queue.append(n)
                        queue.sort()

        # Safety: add any remaining (handles cycles gracefully)
        remaining = needed - set(result)
        if remaining:
            result.extend(sorted(remaining))

        return result
