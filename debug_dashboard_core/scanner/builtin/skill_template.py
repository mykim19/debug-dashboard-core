"""Builtin: Skill Template checker — skill↔DB template ref integrity, unused skills.

Checks:
  - template_refs: skill template_id references valid DB templates
  - skill_files: skill.md files parseable and valid
  - unused_templates: DB templates not referenced by any skill

Applicable when: config has checks.skill_template.enabled = true
"""

import re
import sqlite3
from pathlib import Path

from ..base import BaseChecker, CheckResult, PhaseReport


class SkillTemplateChecker(BaseChecker):
    name = "skill_template"
    display_name = "SKILL REF"
    description = "Skill↔DB template reference integrity, skill file validity, and unused template detection."
    tooltip_why = "Skill의 template_id가 DB에 없으면 스킬 실행이 실패하고, 미사용 템플릿은 관리 부담입니다."
    tooltip_what = "skill.md의 template_id→DB 참조 무결성, 스킬 파일 파싱, 미사용 템플릿을 검사합니다."
    tooltip_result = "PASS: 참조 무결성 양호 · WARN: 미사용 템플릿 존재 · FAIL: 깨진 참조 발견"
    icon = "🎯"
    color = "#ec4899"

    def is_applicable(self, config: dict) -> bool:
        return config.get("checks", {}).get(self.name, {}).get("enabled", False)

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        phase_cfg = config.get("checks", {}).get(self.name, {})

        skills_dir = phase_cfg.get("skills_dir", "skills")
        db_path_str = config.get("project", {}).get("db_path", "rag_data.db")
        db_path = project_root / db_path_str

        # Find skill files
        skills_path = project_root / skills_dir
        skill_files = []
        template_refs = set()

        if skills_path.is_dir():
            for f in skills_path.rglob("*.md"):
                if f.name.startswith("."):
                    continue
                skill_files.append(f)

                # Parse template references
                try:
                    text = f.read_text(encoding="utf-8", errors="ignore")
                    # Look for template_id patterns
                    for m in re.finditer(r"template_id[:\s]+[\"']?(\d+)", text):
                        template_refs.add(int(m.group(1)))
                    # Also look for {{ template:<id> }} style
                    for m in re.finditer(r"\{\{\s*template:(\d+)\s*\}\}", text):
                        template_refs.add(int(m.group(1)))
                except Exception:
                    continue

        # Check 1: Skill files
        if skill_files:
            valid = 0
            invalid = []
            for sf in skill_files:
                try:
                    text = sf.read_text(encoding="utf-8", errors="ignore")
                    # Basic validation: has frontmatter or key fields
                    if "---" in text or "name:" in text.lower() or "purpose:" in text.lower():
                        valid += 1
                    else:
                        invalid.append(str(sf.relative_to(project_root)))
                except Exception:
                    invalid.append(str(sf.relative_to(project_root)))

            if invalid:
                report.add(CheckResult("skill_files", CheckResult.WARN,
                                       f"{valid} valid, {len(invalid)} invalid skill file(s)",
                                       details={"invalid": invalid[:10]}))
            else:
                report.add(CheckResult("skill_files", CheckResult.PASS,
                                       f"{valid} skill files validated"))
        else:
            report.add(CheckResult("skill_files", CheckResult.SKIP,
                                   f"No skill files in {skills_dir}/"))

        # DB checks
        if not db_path.is_file():
            if template_refs:
                report.add(CheckResult("template_refs", CheckResult.WARN,
                                       f"{len(template_refs)} template refs but no database"))
            else:
                report.add(CheckResult("template_refs", CheckResult.SKIP, "No database"))
            report.add(CheckResult("unused_templates", CheckResult.SKIP, "No database"))
            return report

        try:
            conn = sqlite3.connect(str(db_path))
            tables = {row[0] for row in
                      conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

            # Check 2: Template reference integrity
            template_table = None
            for candidate in ["prompt_templates", "templates"]:
                if candidate in tables:
                    template_table = candidate
                    break

            if template_table and template_refs:
                db_ids = {row[0] for row in
                          conn.execute(f"SELECT id FROM {template_table}").fetchall()}
                broken = template_refs - db_ids
                if broken:
                    report.add(CheckResult("template_refs", CheckResult.FAIL,
                                           f"{len(broken)} broken template ref(s): {sorted(broken)[:10]}",
                                           details={"broken_ids": sorted(broken)[:10],
                                                    "total_refs": len(template_refs)}))
                else:
                    report.add(CheckResult("template_refs", CheckResult.PASS,
                                           f"All {len(template_refs)} template references valid"))
            elif template_refs:
                report.add(CheckResult("template_refs", CheckResult.WARN,
                                       f"{len(template_refs)} refs but no templates table"))
            else:
                report.add(CheckResult("template_refs", CheckResult.SKIP,
                                       "No template references in skill files"))

            # Check 3: Unused templates
            if template_table:
                try:
                    total_templates = conn.execute(
                        f"SELECT COUNT(*) FROM {template_table}"
                    ).fetchone()[0]
                    if total_templates > 0 and template_refs:
                        db_ids = {row[0] for row in
                                  conn.execute(f"SELECT id FROM {template_table}").fetchall()}
                        unused = db_ids - template_refs
                        if unused and len(unused) < total_templates:
                            report.add(CheckResult("unused_templates", CheckResult.WARN,
                                                   f"{len(unused)}/{total_templates} templates not referenced by skills",
                                                   details={"unused_ids": sorted(unused)[:15]}))
                        elif unused:
                            report.add(CheckResult("unused_templates", CheckResult.WARN,
                                                   f"Most templates unused ({len(unused)}/{total_templates})"))
                        else:
                            report.add(CheckResult("unused_templates", CheckResult.PASS,
                                                   f"All {total_templates} templates referenced"))
                    else:
                        report.add(CheckResult("unused_templates", CheckResult.SKIP,
                                               "No templates or no skill refs to compare"))
                except Exception as e:
                    report.add(CheckResult("unused_templates", CheckResult.WARN, f"Error: {e}"))
            else:
                report.add(CheckResult("unused_templates", CheckResult.SKIP,
                                       "No templates table"))

            conn.close()
        except Exception as e:
            report.add(CheckResult("template_refs", CheckResult.FAIL, f"DB error: {e}"))

        return report
