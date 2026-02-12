"""Builtin: Agent Budget checker — token usage, cost tracking, rate limits.

Checks:
  - budget_table: budget_history and tool_invocations tables exist
  - daily_cost: recent daily cost within threshold
  - invocation_errors: recent tool invocation failure rate

Applicable when: config has checks.agent_budget.enabled = true
"""

import sqlite3
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class AgentBudgetChecker(BaseChecker):
    name = "agent_budget"
    display_name = "AGENT COST"
    description = "Agent token usage, daily cost tracking, and tool invocation error rates."
    tooltip_why = "LLM API 비용이 예산을 초과하면 서비스가 중단되고, 높은 실패율은 파이프라인 오류를 의미합니다."
    tooltip_what = "budget_history 일간 비용, tool_invocations 실패율, 최근 세션 토큰 사용량을 검사합니다."
    tooltip_result = "PASS: 비용/에러율 정상 · WARN: 비용 증가 추세 · FAIL: 예산 초과/높은 에러율"
    icon = "💰"
    color = "#eab308"

    def is_applicable(self, config: dict) -> bool:
        return config.get("checks", {}).get(self.name, {}).get("enabled", False)

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        db_path_str = config.get("project", {}).get("db_path", "scripts.db")
        db_path = project_root / db_path_str
        daily_limit = phase_cfg.get("daily_cost_limit", 5.0)  # USD
        error_rate_warn = phase_cfg.get("error_rate_warn", 0.1)  # 10%

        if not db_path.is_file():
            report.add(CheckResult("budget_table", CheckResult.SKIP,
                                   f"Database not found: {db_path_str}"))
            return report

        try:
            conn = sqlite3.connect(str(db_path))
            tables = {row[0] for row in
                      conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

            # Check 1: Tables exist
            has_budget = "budget_history" in tables
            has_invocations = "tool_invocations" in tables
            has_sessions = "agent_sessions" in tables

            if has_budget or has_invocations:
                parts = []
                if has_budget:
                    parts.append("budget_history")
                if has_invocations:
                    parts.append("tool_invocations")
                if has_sessions:
                    parts.append("agent_sessions")
                report.add(CheckResult("budget_table", CheckResult.PASS,
                                       f"Tables: {', '.join(parts)}"))
            else:
                report.add(CheckResult("budget_table", CheckResult.SKIP,
                                       "No budget/invocation tables found"))
                conn.close()
                return report

            # Check 2: Daily cost
            if has_budget:
                try:
                    # Try to find cost column (schema may vary)
                    cols = [row[1] for row in conn.execute("PRAGMA table_info(budget_history)").fetchall()]
                    cost_col = None
                    for candidate in ["cost", "total_cost", "amount"]:
                        if candidate in cols:
                            cost_col = candidate
                            break

                    if cost_col:
                        # Last 7 days cost
                        row = conn.execute(f"""
                            SELECT COALESCE(SUM({cost_col}), 0)
                            FROM budget_history
                            WHERE created_at >= datetime('now', '-1 day')
                        """).fetchone()
                        daily_cost = row[0] if row else 0

                        total_row = conn.execute(f"""
                            SELECT COALESCE(SUM({cost_col}), 0), COUNT(*)
                            FROM budget_history
                        """).fetchone()
                        total_cost = total_row[0]
                        total_records = total_row[1]

                        if daily_cost > daily_limit:
                            report.add(CheckResult("daily_cost", CheckResult.FAIL,
                                                   f"Daily cost: ${daily_cost:.2f} (limit: ${daily_limit:.2f})",
                                                   details={"daily": daily_cost, "total": total_cost,
                                                            "records": total_records}))
                        elif daily_cost > daily_limit * 0.7:
                            report.add(CheckResult("daily_cost", CheckResult.WARN,
                                                   f"Daily cost: ${daily_cost:.2f} (70%+ of ${daily_limit:.2f} limit)",
                                                   details={"daily": daily_cost, "total": total_cost}))
                        else:
                            report.add(CheckResult("daily_cost", CheckResult.PASS,
                                                   f"Daily: ${daily_cost:.2f} / Total: ${total_cost:.2f} ({total_records} records)"))
                    else:
                        report.add(CheckResult("daily_cost", CheckResult.SKIP,
                                               f"No cost column found in budget_history"))
                except Exception as e:
                    report.add(CheckResult("daily_cost", CheckResult.WARN, f"Cost check error: {e}"))
            else:
                report.add(CheckResult("daily_cost", CheckResult.SKIP,
                                       "No budget_history table"))

            # Check 3: Tool invocation error rate
            if has_invocations:
                try:
                    cols = [row[1] for row in conn.execute("PRAGMA table_info(tool_invocations)").fetchall()]
                    status_col = None
                    for candidate in ["status", "success", "error"]:
                        if candidate in cols:
                            status_col = candidate
                            break

                    if status_col:
                        total = conn.execute("SELECT COUNT(*) FROM tool_invocations").fetchone()[0]
                        if total > 0:
                            if status_col == "success":
                                errors = conn.execute(
                                    f"SELECT COUNT(*) FROM tool_invocations WHERE {status_col} = 0"
                                ).fetchone()[0]
                            elif status_col == "error":
                                errors = conn.execute(
                                    f"SELECT COUNT(*) FROM tool_invocations WHERE {status_col} IS NOT NULL AND {status_col} != ''"
                                ).fetchone()[0]
                            else:
                                errors = conn.execute(
                                    f"SELECT COUNT(*) FROM tool_invocations WHERE {status_col} = 'error' OR {status_col} = 'failed'"
                                ).fetchone()[0]

                            rate = errors / total
                            if rate > error_rate_warn:
                                report.add(CheckResult("invocation_errors", CheckResult.WARN,
                                                       f"Error rate: {errors}/{total} ({rate:.0%})",
                                                       details={"errors": errors, "total": total}))
                            else:
                                report.add(CheckResult("invocation_errors", CheckResult.PASS,
                                                       f"Error rate: {errors}/{total} ({rate:.0%})"))
                        else:
                            report.add(CheckResult("invocation_errors", CheckResult.SKIP,
                                                   "No tool invocations recorded"))
                    else:
                        report.add(CheckResult("invocation_errors", CheckResult.SKIP,
                                               "No status column in tool_invocations"))
                except Exception as e:
                    report.add(CheckResult("invocation_errors", CheckResult.WARN, f"Error: {e}"))
            else:
                report.add(CheckResult("invocation_errors", CheckResult.SKIP,
                                       "No tool_invocations table"))

            conn.close()
        except Exception as e:
            report.add(CheckResult("budget_table", CheckResult.FAIL, f"DB error: {e}"))

        return report
