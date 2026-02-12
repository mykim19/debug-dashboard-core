# Debug Dashboard 리팩토링: 코어 + 플러그인 구조

> 작성일: 2026-02-12
> 최종 수정: 2026-02-12 (GPT 1차+2차+에이전트 운영 구조 검토 반영)
> 작업 디렉토리: `/Volumes/01_Kioxia/debugger_agent/`
> 목적: 범용 디버거 에이전트 플랫폼 — 어떤 서비스에든 플러그인 체커만 추가하여 대시보드 구성

---

## Context

현재 `project0914/debug_dashboard/`의 8개 체커 중 4개(environment, security, performance, database)는 범용적이고, 4개(url_parsing, ytdlp, duplication, ux_quality)는 YouTube 프로젝트 전용입니다. 범용 체커와 프레임워크(Flask앱, SSE, 프론트엔드, storage)를 코어로 분리하면, 다른 프로젝트에서 코어만 가져와 전용 체커만 추가 작성하여 대시보드를 빠르게 구성할 수 있습니다.

**핵심 목표**: 코어 프레임워크 + 범용 체커 분리, 프로젝트별 플러그인 체커 구조

---

## 설계 원칙

### 에이전트 표준 프로토콜 (4단계)

각 서비스 에이전트(체커)는 다음 4단계를 표준으로 따릅니다:

```
Inspector(진단) → Evidence(근거) → Recommendation(권고) → Fixer(안전 수정)
```

| 단계 | 구현 | 설명 |
|------|------|------|
| **Inspector** | `checker.run()` → PhaseReport | 서비스 상태를 읽기 전용으로 진단 |
| **Evidence** | `CheckResult.details.evidence` | 근거를 파일/라인/스니펫으로 남김 |
| **Recommendation** | `CheckResult.message` + `fix_desc` | 무엇을 왜 고쳐야 하는지 권고 |
| **Fixer** | `checker.fix()` | 안전한 범위 내에서 자동 수정 (현재: TODO 마커 수준) |

### 에이전트 권한 레벨

| 레벨 | 설명 | 현재 적용 |
|------|------|-----------|
| **READ** | 진단만 (run) — 파일/DB/환경 읽기 | 모든 체커의 `run()` |
| **SAFE_FIX** | TODO 마커 추가, config 수정, 캐시 클리어 | 현재 `fix()` |
| **PR_ONLY** | 코드 수정은 diff/PR 제안까지만 | 향후 과제 |
| **ADMIN** | DB 마이그레이션, 배포, 롤백 | 미계획 |

> **원칙**: 기본은 **READ**(읽기 전용). fix는 **SAFE_FIX** 범위만 허용.
> 코드 수정이 필요한 fix는 향후 **PR_ONLY** 레벨로 확장하며, dry-run + diff + rollback 안전장치를 함께 구현.

### 서비스 간 경계 원칙

- 각 서비스 에이전트는 **자기 프로젝트(`project.root`)만 진단**
- 다른 서비스의 파일/DB/설정을 읽거나 수정하지 않음
- 서비스 간 교차 진단이 필요하면 향후 **오케스트레이터**가 조정 (현재는 각자 독립 실행)

---

## 원본 소스 위치

- 프레임워크: `/Volumes/01_Kioxia/project0914/debug_dashboard/`
- 체커: `/Volumes/01_Kioxia/project0914/debug_dashboard/scanner/`
- 프론트엔드: `/Volumes/01_Kioxia/project0914/debug_dashboard/static/`, `templates/`

---

## 현재 구조 분석

### 프레임워크 (이미 범용적)
- `scanner/base.py` — BaseChecker, CheckResult, PhaseReport 인터페이스
- `scanner/registry.py` — pkgutil 기반 auto-discovery (scanner/ 하나만 스캔)
- `app.py` — Flask 라우트 6개 + SSE 스트리밍
- `storage.py` — SQLite 스캔 이력 저장
- `static/` + `templates/` — SF/Cyberpunk 테마 (Jinja2 동적 렌더링, 체커명 하드코딩 없음)

### 체커 분류

| 체커 | 분류 | 이유 |
|------|------|------|
| **environment.py** | SEMI-GENERIC | Python/패키지/디스크 — `downloads/`, `.env` 템플릿만 설정화 필요 |
| **security.py** | SEMI-GENERIC | SQL injection/XSS/CORS — `app.py` 경로만 설정화 필요 |
| **performance.py** | SEMI-GENERIC | DB 인덱스/N+1/블로킹I/O — 테이블명/컬럼 설정화 필요 |
| **database_check.py** | SEMI-GENERIC | SQLite 무결성/FK — 비디오 전용 로직 분리 필요 |
| **url_parsing.py** | PROJECT-SPECIFIC | `from app import get_video_id_from_url` 직접 import |
| **ytdlp_env.py** | PROJECT-SPECIFIC | yt-dlp 바이너리/JS 런타임 검사 |
| **duplication.py** | PROJECT-SPECIFIC | YouTube 함수 중복, `YT_DLP_PATH` 패턴 |
| **ux_quality.py** | PROJECT-SPECIFIC | 한국어 혼용 검출, `agent/api*.py` 구조 |

### BaseChecker 인터페이스 (변경 없음)

```python
class BaseChecker:
    # 메타데이터 (서브클래스에서 정의)
    name: str              # 고유 ID — "유일한 진실" (파일명은 무관)
    display_name: str      # UI 표시명 (e.g., "ENVIRONMENT")
    description: str       # 설명
    tooltip_why: str       # 왜 이 검사가 필요한지 (한국어)
    tooltip_what: str      # 무엇을 검사하는지
    tooltip_result: str    # 결과가 의미하는 것
    icon: str              # 이모지
    color: str             # Hex 색상

    # 필수 구현
    def run(self, project_root: Path, config: dict) -> PhaseReport: ...

    # 선택 구현
    def fix(self, check_name: str, project_root: Path, config: dict) -> dict: ...

    # 기본 제공
    def get_meta(self) -> dict: ...
    def is_applicable(self, config: dict) -> bool: ...
```

> **중요 원칙**: 체커의 `name` 속성이 유일한 식별자입니다. 파일명(`ytdlp_env.py`)과 name(`"ytdlp"`)은 다를 수 있으며, `checks_order`와 `config.checks.*`는 모두 `name`을 기준으로 합니다.

### CheckResult / PhaseReport

```python
class CheckResult:
    PASS = "PASS" | FAIL = "FAIL" | WARN = "WARN" | SKIP = "SKIP"
    def __init__(self, name, status, message="", details=None, fixable=False, fix_desc=""): ...

class PhaseReport:
    def __init__(self, name): self.checks = []
    def add(self, result: CheckResult): ...
    # properties: pass_count, fail_count, warn_count, skip_count, total_active, health_pct
    # NEW: duration_ms (체커 실행 시간)
```

### Evidence 표준 (NEW — GPT 검토 반영)

`CheckResult.details`에 다음 표준 키를 권장합니다:

```python
details = {
    "evidence": {
        "file": "app.py",           # 파일 경로 (project_root 상대)
        "line_start": 142,          # 시작 라인
        "line_end": 145,            # 끝 라인 (optional)
        "snippet": "conn.execute(f\"SELECT...\")",  # 코드 스니펫 (optional)
        "rule_id": "sql_injection"  # 규칙 ID (optional)
    }
}
```

이를 통해 UI에서 "파일:라인" 클릭 → 해당 위치 이동 기능을 붙일 수 있습니다.

---

## 리팩토링 후 디렉토리 구조

```
/Volumes/01_Kioxia/debugger_agent/              ← 범용 디버거 에이전트 루트
  docs/
    refactoring-plan-debug-dashboard-core.md    ← 이 문서
  debug_dashboard_core/                          ← 재사용 가능한 코어
    __init__.py                                  ← __version__ = "1.0.0"
    app.py                                       ← Flask 앱 팩토리 (create_app)
    storage.py                                   ← 스캔 이력 저장
    defaults.yaml                                ← 범용 체커 기본 설정
    scanner/
      __init__.py
      base.py                                    ← BaseChecker/CheckResult/PhaseReport
      registry.py                                ← 다중 디렉토리 auto-discovery (핵심)
      builtin/
        __init__.py
        environment.py                           ← 범용화
        security.py                              ← 범용화
        performance.py                           ← 범용화
        database_check.py                        ← 범용화 (무결성/테이블/FK만)
    static/                                      ← SF 테마 프론트엔드
    templates/                                   ← dashboard.html

  examples/                                      ← 프로젝트별 적용 예시
    project0914/                                 ← YouTube Knowledge Hub 예시
      app.py                                     ← thin launcher
      config.yaml                                ← 프로젝트 설정
      scanner/                                   ← 프로젝트 전용 체커
        __init__.py
        url_parsing.py
        ytdlp_env.py
        duplication.py
        ux_quality.py
        database_videos.py                       ← NEW: 비디오 전용 DB 체커
```

---

## 구현 단계 (8 Phase)

### Phase 1: 코어 패키지 골격 생성

| 작업 | 파일 |
|------|------|
| 패키지 초기화 | `debug_dashboard_core/__init__.py` (`__version__ = "1.0.0"`) |
| 스캐너 패키지 | `debug_dashboard_core/scanner/__init__.py` |
| 빌트인 패키지 | `debug_dashboard_core/scanner/builtin/__init__.py` |

### Phase 2: 코어 프레임워크 이전

| 원본 (project0914) | 대상 (debugger_agent) | 변경사항 |
|---------------------|----------------------|----------|
| `debug_dashboard/scanner/base.py` | `core/scanner/base.py` | PhaseReport에 `duration_ms` 추가 |
| `debug_dashboard/storage.py` | `core/storage.py` | DB_PATH를 외부에서 override 가능하게, 자동 init 제거 |
| `debug_dashboard/static/` | `core/static/` | 없음 (전체 복사) |
| `debug_dashboard/templates/` | `core/templates/` | 없음 (전체 복사) |

### Phase 3: 레지스트리 다중 디렉토리 auto-discovery (핵심 변경)

**`debug_dashboard_core/scanner/registry.py`**

현재: `pkgutil.iter_modules([scanner_dir])` → scanner/ 하나만 스캔

변경 후 2단계 스캔:
1. `core/scanner/builtin/` → 범용 체커 로드 (pkgutil 패키지 스캔)
2. `config.plugins.dirs` + `plugin_dirs` 인자 → `importlib.util.spec_from_file_location`으로 .py 파일 개별 로드

```python
class CheckerRegistry:
    @classmethod
    def configure(cls, extra_dirs: list = None):
        """플러그인 디렉토리 설정"""

    @classmethod
    def reset(cls):
        """재초기화 — sys.modules에서 플러그인 모듈도 정리"""

    @classmethod
    def auto_discover(cls):
        """1) builtin/ 스캔  2) extra_dirs 스캔"""

    @classmethod
    def get_all(cls, order: list = None) -> list:
        """config 기반 정렬 (기존 하드코딩 제거)"""

    @classmethod
    def get_enabled(cls, config: dict, order: list = None) -> list:
        """enabled 필터링"""

    @classmethod
    def get_by_name(cls, name: str) -> BaseChecker:
        """이름으로 조회"""
```

**플러그인 모듈 네이밍** (GPT 1차+2차 검토 반영):

> **주의**: 서로 다른 프로젝트의 플러그인 디렉토리 이름이 동일하면(e.g., 둘 다 `scanner/`) 모듈명이 충돌합니다.
> `directory.name`만으로는 유니크성이 부족하므로, **부모 디렉토리명을 포함**합니다.

```python
# Before (충돌 위험):
module_name = f"_plugin_{py_file.stem}"

# 1차 개선 (여전히 충돌 가능):
# dir_name = directory.name  # "scanner" — 프로젝트 간 동일할 수 있음
# module_name = f"debugger_plugin.{dir_name}.{py_file.stem}"

# 최종 (부모+디렉토리 기반 유니크):
parent_name = directory.parent.name  # e.g., "project0914"
dir_name = directory.name            # e.g., "scanner"
module_name = f"debugger_plugin.{parent_name}.{dir_name}.{py_file.stem}"
# → "debugger_plugin.project0914.scanner.url_parsing"
```

**reset()에서 sys.modules 정리** (GPT 검토 반영):
```python
@classmethod
def reset(cls):
    cls._checkers = {}
    cls._discovered = False
    cls._extra_dirs = []
    # 플러그인 모듈 정리
    to_remove = [k for k in sys.modules if k.startswith("debugger_plugin.")]
    for k in to_remove:
        del sys.modules[k]
```

**플러그인 실패 격리** (GPT 1차+2차 검토 반영):

> **_load_errors UI 노출 정책**: 수집된 에러는 `/api/scan/run` SSE 시작 시 `plugin_errors` 이벤트로 전송하고,
> 프론트엔드 상단에 `⚠ N개 플러그인 로딩 실패` 배지로 표시합니다.

```python
# registry.py — 실패 격리 + 에러 수집
@classmethod
def _scan_directory_as_files(cls, directory: Path):
    for py_file in sorted(directory.glob("*.py")):
        if py_file.stem in ("__init__", "base", "registry"):
            continue
        try:
            # ... 로딩 로직
        except Exception as e:
            # 실패 시 스캔 중단하지 않고 WARN 로그
            print(f"[registry] ⚠ Plugin load failed: {py_file.name} — {e}")
            cls._load_errors.append({"file": py_file.name, "error": str(e)})

# app.py — SSE 시작 시 에러 노출
def generate():
    # 플러그인 로딩 에러가 있으면 먼저 전송
    if CheckerRegistry._load_errors:
        yield f"data: {json.dumps({'type': 'plugin_errors', 'errors': CheckerRegistry._load_errors}, ensure_ascii=False)}\n\n"
    # ... 이후 phase_start/phase_done 순서대로 스트리밍
```

### Phase 4: Flask 앱 팩토리 생성

**`debug_dashboard_core/app.py`** — `create_app()` 팩토리 함수

```python
def create_app(config_path, db_path=None, plugin_dirs=None) -> Flask:
    """
    Args:
        config_path: 프로젝트 config.yaml 경로
        db_path: 대시보드 SQLite DB 위치 (override)
        plugin_dirs: 프로젝트 전용 체커 디렉토리 목록
    """
```

**plugin_dirs 정책** (GPT 검토 반영):
> 인자 `plugin_dirs`와 `config.plugins.dirs`는 **병합(union)** 됩니다. 둘 다 지정하면 양쪽 디렉토리를 모두 스캔합니다.

**Config 검증** (GPT 1차+2차 검토 반영):

> **unknown checker 처리 정책**: WARN 로그를 찍되, unknown 이름은 `checks_order`에서 **자동 제거**하여
> 유효한 이름만으로 구성된 fallback order를 사용합니다.

```python
def _validate_config(config: dict, registry: CheckerRegistry) -> dict:
    """기동 시 config 기본 검증. 정제된 config를 반환."""
    # 1. 필수 키 체크
    if not config.get("project", {}).get("root"):
        raise ValueError("config.yaml: project.root is required")

    # 2. checks_order 이름 검증 + unknown 자동 제거
    order = config.get("checks_order", [])
    registered = {c.name for c in registry.get_all()}
    valid_order = []
    for name in order:
        if name in registered:
            valid_order.append(name)
        else:
            print(f"[config] ⚠ checks_order contains unknown checker: '{name}' — removed from order")
    config["checks_order"] = valid_order

    return config
```

**Config deep merge** (defaults.yaml + project config.yaml):
```python
def deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
```

**duration_ms 측정 주체** (GPT 2차 검토 반영):

> **원칙: 코어가 측정한다.** 체커는 `duration_ms`를 신경 쓸 필요 없습니다.
> `app.py`의 scan 루프에서 `checker.run()` 전후로 타이머를 재서 `report.duration_ms`를 자동 채웁니다.
> 체커별로 측정하게 하면 누락/불일치가 생기므로, 코어 wrapper로 통일합니다.

```python
# app.py — scan_run() 내부
for checker in checkers:
    yield f"data: {json.dumps({'type': 'phase_start', ...})}\n\n"
    t0 = time.time()
    try:
        report = checker.run(project_root, cfg)
    except Exception as e:
        report = PhaseReport(checker.name)
        report.add(CheckResult("error", CheckResult.FAIL, str(e)))
    report.duration_ms = int((time.time() - t0) * 1000)  # 코어가 측정
    # ...
```

6개 라우트 (기존과 동일):
- `GET /` — 대시보드 UI
- `GET /api/scan/run` — SSE 스트리밍 스캔
- `GET /api/scan/latest` — 최근 스캔 결과
- `GET /api/scan/history` — 스캔 이력
- `GET /api/phase/<name>` — 단일 phase 실행
- `POST /api/fix/<phase>/<check>` — auto-fix 실행

### Phase 5: 범용 체커 4개 일반화

각 체커의 하드코딩을 config 키로 변환:

| 체커 | 현재 하드코딩 | → config 키 | 기본값 |
|------|-------------|-------------|--------|
| **environment** | `downloads/` | `checks.environment.cleanup_dir` | `"downloads"` |
| | `.env` 템플릿 내용 | `checks.environment.env_template` | `{FLASK_SECRET_KEY: "change-me"}` |
| **security** | `app.py` | `checks.security.main_file` | `"app.py"` |
| **performance** | `"videos"` 테이블 | `checks.performance.main_table` | `""` (미설정시 스킵) |
| | `["status","source_type","content_hash"]` | `checks.performance.index_columns` | `[]` |
| | `agent/` | `checks.performance.n_plus_1_dirs` | `[]` |
| | `app.py` | `checks.performance.main_file` | `"app.py"` |
| **database_check** | 비디오 전용 로직 | 제거 (별도 체커로 분리) | - |

import 경로 변경: `from .base import ...` → `from ..base import ...` (builtin/ 하위로 이동)

### Phase 6: database_videos.py 분리 (NEW)

현재 `database_check.py`에서 추출할 비디오 전용 로직:
- content_hash 커버리지 검사
- status 분포 검사 (pending/failed/completed/processing)
- orphan 파일 검사 (script_txt_path가 존재하지 않는 파일 참조)
- ontology 통계 (global_nodes/edges)
- 해당 fix() 메서드들

→ `examples/project0914/scanner/database_videos.py` (DatabaseVideosChecker)

```python
from debug_dashboard_core.scanner.base import BaseChecker, CheckResult, PhaseReport

class DatabaseVideosChecker(BaseChecker):
    name = "database_videos"
    display_name = "DB·VIDEOS"
    description = "Video table: content hash, status, orphan files, ontology stats."
    icon = "🎬"
    color = "#8b5cf6"
```

### Phase 7: 프로젝트 전용 체커 import 경로 변경

4개 파일에서 1줄씩만 변경:

```python
# Before (현재):
from .base import BaseChecker, CheckResult, PhaseReport

# After:
from debug_dashboard_core.scanner.base import BaseChecker, CheckResult, PhaseReport
```

대상 파일:
- `examples/project0914/scanner/url_parsing.py`
- `examples/project0914/scanner/ytdlp_env.py`
- `examples/project0914/scanner/duplication.py`
- `examples/project0914/scanner/ux_quality.py`

### Phase 8: config.yaml 확장 + thin launcher

**config.yaml 신규 키:**

```yaml
plugins:
  dirs: ["scanner"]                    # 플러그인 디렉토리 (project_root 상대경로)

checks_order:                           # 표시 순서 (기존 registry.py 하드코딩 대체)
  - environment
  - url_parsing
  - ytdlp
  - database
  - database_videos
  - duplication
  - performance
  - security
  - ux_quality
```

**examples/project0914/app.py** → thin launcher:

```python
#!/usr/bin/env python3
"""Knowledge Hub Debug Dashboard — project-specific launcher."""
import sys
from pathlib import Path

DEBUGGER_ROOT = Path(__file__).parent.parent.parent  # debugger_agent/
sys.path.insert(0, str(DEBUGGER_ROOT))

from debug_dashboard_core.app import create_app

APP_DIR = Path(__file__).parent
app = create_app(
    config_path=str(APP_DIR / "config.yaml"),
    db_path=str(APP_DIR / "debug_dashboard.db"),
    plugin_dirs=[str(APP_DIR / "scanner")],
)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5010, debug=False, threaded=True)
```

**defaults.yaml** (코어 기본 설정):

```yaml
config_schema_version: "1.0"

checks:
  environment:
    enabled: true
    packages: ["flask"]
    cleanup_dir: "downloads"
    env_template:
      FLASK_SECRET_KEY: "change-me-to-random-string"
  database:
    enabled: true
    required_tables: []
    optional_tables: []
  performance:
    enabled: true
    main_table: ""
    index_columns: []
    n_plus_1_dirs: []
    main_file: "app.py"
  security:
    enabled: true
    scan_dirs: ["."]
    main_file: "app.py"

checks_order: ["environment", "database", "performance", "security"]
```

---

## 다른 프로젝트에서 사용하는 방법

### 1) debugger_agent/debug_dashboard_core/ 를 프로젝트에 복사 (또는 심볼릭 링크)

### 2) 최소 구성 생성

```
other-project/
  debug_dashboard/
    app.py                  ← thin launcher (10줄)
    config.yaml             ← 이 프로젝트 설정
    scanner/                ← 이 프로젝트 전용 체커
      auth_check.py
      api_schema.py
```

### 3) config.yaml 작성

```yaml
config_schema_version: "1.0"

project:
  name: "Other Service"
  root: "/path/to/other-project"
  db_path: "app.db"

plugins:
  dirs: ["debug_dashboard/scanner"]

checks_order: [environment, security, performance, database, auth_check, api_schema]

checks:
  environment:
    packages: ["fastapi", "sqlalchemy"]
  database:
    required_tables: ["users", "orders"]
  performance:
    main_table: "orders"
    index_columns: ["status", "user_id"]
  auth_check: { enabled: true }
  api_schema: { enabled: true }
```

### 4) 전용 체커 작성 예시

```python
# other-project/debug_dashboard/scanner/auth_check.py
from debug_dashboard_core.scanner.base import BaseChecker, CheckResult, PhaseReport
from pathlib import Path

class AuthChecker(BaseChecker):
    name = "auth_check"
    display_name = "AUTH"
    description = "Authentication and authorization checks."
    icon = "🔑"
    color = "#f59e0b"
    tooltip_why = "인증/인가 설정 오류는 보안 사고로 이어집니다."
    tooltip_what = "JWT 설정, 세션 관리, 권한 검사를 확인합니다."
    tooltip_result = "PASS는 안전한 설정, WARN은 개선 권장, FAIL은 즉시 조치 필요."

    def run(self, project_root: Path, config: dict) -> PhaseReport:
        report = PhaseReport(self.name)
        # ... 이 프로젝트만의 인증 검사 로직
        return report
```

---

## GPT 검토 반영 사항

### 1차+2차 반영 (이번 리팩토링에 포함)

| 항목 | 반영 내용 | 출처 |
|------|-----------|------|
| 모듈 네이밍 | `_plugin_{stem}` → `debugger_plugin.{parent}.{dir}.{stem}` (부모+디렉토리 기반 유니크) | GPT 1차 2-A, 2차 리스크1 |
| reset() | `sys.modules`에서 `debugger_plugin.*` 제거 포함 | GPT 1차 2-A |
| config 검증 | `project.root` 필수 체크, `checks_order` unknown → WARN + **자동 제거** fallback | GPT 1차 2-C, 2차 리스크3 |
| Evidence 표준 | `CheckResult.details`에 `evidence` 권장 키: `{file, line_start, line_end, snippet, rule_id}` | GPT 1차 3-1 |
| PhaseReport 시간 | `duration_ms` 필드 추가, **코어 wrapper에서 측정** (체커는 관여 안 함) | GPT 1차 3-3, 2차 리스크4 |
| plugin_dirs 정책 | 인자 + config **병합(union)**, 문서 명시 | GPT 1차 4-4 |
| 플러그인 실패 격리 | import 실패 시 WARN 로그 + `_load_errors` 수집, 스캔 중단 안 함 | GPT 1차 4-6 |
| _load_errors UI 노출 | SSE `plugin_errors` 이벤트로 전송 + 프론트엔드 상단 배지 표시 | GPT 2차 리스크2 |
| name 원칙 | "체커의 `name` 속성이 유일한 진실" 문서 강조 | GPT 1차 4-1 |
| config_schema_version | `defaults.yaml`과 프로젝트 `config.yaml`에 버전 필드 추가 | GPT 1차 2-B |
| storage init 안전성 | 모듈 로드 시 자동 `init_db()` 제거, `create_app()`에서만 명시적 호출 | GPT 1차 4-3 |

### 향후 과제

| 항목 | 시점 | 출처 |
|------|------|------|
| Fix dry-run + diff + backup | fix가 실제 코드 수정할 때 | GPT 1차 3-2 |
| `pip install -e` 패키징 | 프로젝트 3개 이상 시 | GPT 1차 2-B |
| Applicability 자동 탐지 (Flask/FastAPI/Node) | 수요 발생 시 | GPT 1차 3-4 |
| `main_file` 자동 탐지 (app.py/main.py/server.py) | 범용 적용 사례 축적 후 | GPT 1차 4-5 |
| LLM 협업 exporter (PR 코멘트/주간 리포트) | 대시보드 운영 안정화 후 | GPT 1차 3-5 |
| DB 그룹 카드 (DATABASE + DB·VIDEOS 묶기) | UI 피드백 수렴 후 | GPT 1차 4-2 |
| strict_config 모드 (CI에서 unknown checker → 부팅 실패) | CI/CD 통합 시 | GPT 2차 리스크3 |
| Fix 에이전트 분리 (Inspector와 Fixer를 별도 에이전트로) | fix가 실제 코드를 변경할 때 | GPT 에이전트 구조 |
| PR_ONLY 권한 레벨 (코드 수정 → diff/PR 제안까지) | fix 확장 시 | GPT 에이전트 구조 |
| 중앙 Orchestrator (허브-스포크 모델) | 서비스 3개 이상 시 | GPT 에이전트 구조 |
| 서비스별 에이전트 표준 프롬프트/역할 정의서 | 에이전트 LLM 통합 시 | GPT 에이전트 구조 |

---

## 파일 변경 요약

### debugger_agent/ (NEW — 코어)

| 파일 | 작업 |
|------|------|
| `debug_dashboard_core/__init__.py` | 생성 (`__version__ = "1.0.0"`) |
| `debug_dashboard_core/app.py` | Flask 앱 팩토리 + config 검증 |
| `debug_dashboard_core/storage.py` | 기존 복사 + DB_PATH override + 자동 init 제거 |
| `debug_dashboard_core/defaults.yaml` | 범용 체커 기본 설정 + schema version |
| `debug_dashboard_core/scanner/__init__.py` | 생성 |
| `debug_dashboard_core/scanner/base.py` | 기존 복사 + PhaseReport.duration_ms + Evidence 표준 주석 |
| `debug_dashboard_core/scanner/registry.py` | 다중 디렉토리 discovery + 유니크 네이밍 + 실패 격리 |
| `debug_dashboard_core/scanner/builtin/__init__.py` | 생성 |
| `debug_dashboard_core/scanner/builtin/environment.py` | 범용화 |
| `debug_dashboard_core/scanner/builtin/security.py` | 범용화 |
| `debug_dashboard_core/scanner/builtin/performance.py` | 범용화 |
| `debug_dashboard_core/scanner/builtin/database_check.py` | 범용화 (비디오 로직 제거) |
| `debug_dashboard_core/static/` | 기존 복사 |
| `debug_dashboard_core/templates/` | 기존 복사 |

### debugger_agent/examples/project0914/ (프로젝트 전용)

| 파일 | 작업 |
|------|------|
| `app.py` | thin launcher |
| `config.yaml` | 프로젝트 설정 (plugins, checks_order) |
| `scanner/__init__.py` | 생성 |
| `scanner/url_parsing.py` | import 1줄 변경 |
| `scanner/ytdlp_env.py` | import 1줄 변경 |
| `scanner/duplication.py` | import 1줄 변경 |
| `scanner/ux_quality.py` | import 1줄 변경 |
| `scanner/database_videos.py` | NEW: 비디오 전용 DB 체커 |

### project0914/debug_dashboard/ (기존 — 리팩토링 후 처리)

코어로 이전 후 기존 `project0914/debug_dashboard/`는:
- 옵션 A: 삭제하고 `debugger_agent/examples/project0914/`을 사용
- 옵션 B: thin launcher로 교체하여 `debugger_agent/debug_dashboard_core/`를 참조

---

## 기존 기능 보존 확인

| 항목 | 보존 |
|------|------|
| 8개 체커 전부 동작 (+ database_videos = 9개) | ✅ |
| SSE 실시간 스트리밍 | ✅ |
| FIX ALL / 개별 FIX | ✅ |
| TODO 마커 패턴 | ✅ |
| SF/Cyberpunk 테마 | ✅ |
| 스캔 이력 저장 | ✅ |
| port 5010 | ✅ |

---

## 검증 방법

1. `python examples/project0914/app.py` 실행 → http://localhost:5010 접속
2. "Run Scan" 클릭 → 9개 phase 순서대로 SSE 스트리밍 확인
3. 각 phase 카드 클릭 → 모달에서 개별 check 결과 확인
4. FIX 버튼 → auto-fix 동작 확인
5. FIX ALL → 순차 실행 + 프로그레스바 + 재스캔 확인
6. 스캔 이력 (history) 조회 확인

---

## 주의사항

1. **플러그인 import**: `spec_from_file_location`으로 로드 → 상대 import 불가 → 반드시 `from debug_dashboard_core.scanner.base import ...` 절대 import
2. **url_parsing.py 동적 import**: `sys.path.insert(0, str(project_root))` + `from app import get_video_id_from_url` — project_root가 정확해야 함
3. **storage 자동 init 제거**: 코어에서는 `create_app()`에서만 `init_db()` 호출
4. **DB 카드 분리**: DATABASE + DB·VIDEOS 두 개로 나뉨 — 의도된 변경
5. **name 속성**: 체커의 `name`이 유일한 식별자, 파일명과 무관할 수 있음
6. **plugin_dirs 병합**: 인자 + config 양쪽 모두 스캔 (union)
7. **모듈명 유니크성**: 플러그인 디렉토리가 모두 `scanner/`로 동일해도, 부모 디렉토리명(`project0914` 등)이 모듈명에 포함되어 충돌 방지
8. **_load_errors UI 노출**: 플러그인 로딩 실패는 SSE `plugin_errors` 이벤트로 전송 → 프론트엔드 상단 배지로 표시
9. **unknown checker 자동 제거**: `checks_order`에 registry에 없는 이름이 있으면 WARN 로그 찍고 order에서 자동 제거
10. **duration_ms 측정**: 체커가 아닌 **코어(app.py)**가 `run()` 호출 전후로 측정 → 체커 개발자는 시간 측정 불필요
11. **에이전트 경계**: 각 서비스 에이전트는 자기 `project.root`만 진단 — 다른 서비스 파일/DB 접근 금지
12. **권한 레벨**: 현재는 READ + SAFE_FIX만 허용 — 코드 변경 fix는 향후 PR_ONLY 레벨로 확장 예정
