/* ── SF Debug Dashboard — Client JS ── */

(function () {
  "use strict";

  // ── State ──
  let scanning = false;
  let phaseReports = {};   // name → report
  let historyData = [];

  // ── Architecture Registry (per-workspace agent diagrams) ──
  const ARCH_REGISTRY = {
    "knowledge hub": {
      title: "Knowledge Hub Agent Pipeline",
      subtitle: "Video \u2192 Script Extraction \u2192 Knowledge Generation \u2192 Finalization",
      nodes: [
        { id: "orchestrator", label: "PlanOrchestrator",
          role: "\uCD5C\uC0C1\uC704 \uCEE8\uD2B8\uB864\uB7EC\n\uC138\uC158 \uC0DD\uBA85\uC8FC\uAE30 \uAD00\uB9AC \u2014 \uC2E4\uD589 \uC2DC\uC791\uBD80\uD130 \uC885\uB8CC\uAE4C\uC9C0 \uC804\uCCB4 \uD30C\uC774\uD504\uB77C\uC778\uC744 \uC624\uCF00\uC2A4\uD2B8\uB808\uC774\uC158\n\uC608\uC0B0 \uAC00\uB4DC \u2014 \uD1A0\uD070/\uBE44\uC6A9/\uD0C0\uC784\uC544\uC6C3 \uD55C\uB3C4 \uCD08\uACFC \uC2DC \uC790\uB3D9 \uC911\uB2E8\nPlanner\u2192Validator\u2192Executor \uD750\uB984\uC744 \uC21C\uCC28\uC801\uC73C\uB85C \uD638\uCD9C",
          type: "controller", col: 0, row: 0 },
        { id: "planner", label: "AgentPlanner",
          role: "LLM \uAE30\uBC18 \uC2E4\uD589 \uACC4\uD68D \uC218\uB9BD\n\uBE44\uB514\uC624 \uC2A4\uD06C\uB9BD\uD2B8\uB97C \uBD84\uC11D\uD558\uC5EC \uC9C0\uC2DD \uC0DD\uC131 \uB2E8\uACC4\uB97C \uACC4\uD68D\nGemini / DeepSeek \uBAA8\uB378 \uC120\uD0DD \uAC00\uB2A5\n\uCD5C\uC801 \uB3C4\uAD6C\uC640 \uC21C\uC11C\uB97C \uACB0\uC815\uD558\uC5EC \uC2E4\uD589 \uACC4\uD68D \uBC18\uD658",
          type: "planner", col: 0, row: 1 },
        { id: "validator", label: "PlanValidator",
          role: "\uACC4\uD68D \uAD6C\uC870 \uAC80\uC99D\n\uD544\uC218 \uD544\uB4DC \uC874\uC7AC \uC5EC\uBD80, \uB3C4\uAD6C \uC774\uB984 \uC720\uD6A8\uC131 \uD655\uC778\n\uC21C\uD658 \uCC38\uC870\uB098 \uBD88\uAC00\uB2A5\uD55C \uC758\uC874\uC131 \uD0D0\uC9C0\n\uAC80\uC99D \uC2E4\uD328 \uC2DC Planner\uC5D0\uAC8C \uC7AC\uACC4\uD68D \uC694\uCCAD",
          type: "validator", col: 0, row: 2 },
        { id: "executor", label: "PlanExecutor",
          role: "\uACC4\uD68D\uB41C \uB2E8\uACC4\uB97C \uC21C\uCC28\uC801\uC73C\uB85C \uC2E4\uD589\n\uAC01 step\uC5D0 \uB300\uD574 \uD574\uB2F9 \uB3C4\uAD6C(Tool)\uB97C \uD638\uCD9C\n\uB2E8\uACC4\uBCC4 \uC624\uB958 \uBC1C\uC0DD \uC2DC \uC7AC\uC2DC\uB3C4 \uB610\uB294 \uC2A4\uD0B5 \uCC98\uB9AC\n\uC2E4\uD589 \uACB0\uACFC\uB97C Orchestrator\uC5D0\uAC8C \uBCF4\uACE0",
          type: "executor", col: 0, row: 3 },
        { id: "script_loader", label: "ScriptLoader",
          role: "\uBE44\uB514\uC624 \uC2A4\uD06C\uB9BD\uD2B8 \uB85C\uB4DC \uB3C4\uAD6C\nYouTube \uB4F1\uC758 \uC601\uC0C1\uC5D0\uC11C \uC790\uB9C9/\uC2A4\uD06C\uB9BD\uD2B8\uB97C \uCD94\uCD9C\n\uAD6C\uC870\uD654\uB41C \uD14D\uC2A4\uD2B8\uB85C \uBCC0\uD658 \uD6C4 \uB2E4\uC74C \uB2E8\uACC4\uC5D0 \uC804\uB2EC\nLLM \uC5C6\uC774 \uB3D9\uC791 (\uBE44\uC6A9 \uBC1C\uC0DD \uC5C6\uC74C)",
          type: "tool", col: -1, row: 4 },
        { id: "stepaz_gen", label: "StepazGenerator",
          role: "LLM \uAE30\uBC18 \uC9C0\uC2DD \uB2E8\uACC4 \uC0DD\uC131\uAE30\n\uC2A4\uD06C\uB9BD\uD2B8\uB97C \uBD84\uC11D\uD558\uC5EC \uD559\uC2B5\uC6A9 \uC9C0\uC2DD \uB2E8\uACC4\uB85C \uBCC0\uD658\n\uD578\uC2EC \uAC1C\uB150 \uCD94\uCD9C, \uC694\uC57D, \uAD6C\uC870\uD654 \uC218\uD589\n\uC8FC\uC694 LLM \uBE44\uC6A9 \uBC1C\uC0DD \uAD6C\uAC04",
          type: "tool", col: 0, row: 4 },
        { id: "knowledge_final", label: "Finalization",
          role: "\uC9C0\uC2DD \uCD5C\uC885 \uC870\uB9BD \uB3C4\uAD6C\n\uC0DD\uC131\uB41C \uC9C0\uC2DD \uB2E8\uACC4\uB97C \uCD5C\uC885 \uACB0\uACFC\uBB3C\uB85C \uC870\uD569\n\uD488\uC9C8 \uAC80\uC99D \uBC0F \uD3EC\uB9F7 \uC815\uB9AC\n\uCD5C\uC885 \uC0B0\uCD9C\uBB3C\uC744 \uC800\uC7A5\uC18C\uC5D0 \uAE30\uB85D",
          type: "tool", col: 1, row: 4 },
        { id: "budget", label: "BudgetMonitor",
          role: "\uC608\uC0B0 \uAC10\uC2DC \uC5D0\uC774\uC804\uD2B8\n\uD1A0\uD070 \uC0AC\uC6A9\uB7C9 \uC2E4\uC2DC\uAC04 \uCD94\uC801 \u2014 \uD55C\uB3C4 \uCD08\uACFC \uC2DC \uACBD\uACE0\nAPI \uBE44\uC6A9 \uB204\uC801 \uACC4\uC0B0 \u2014 \uC77C\uC77C \uD55C\uB3C4 \uAD00\uB9AC\n\uC2E4\uD589 \uC2DC\uAC04 \uD0C0\uC774\uBA38 \u2014 \uD0C0\uC784\uC544\uC6C3 \uC2DC \uAC15\uC81C \uC885\uB8CC",
          type: "guard", col: 1, row: 1 },
      ],
      edges: [
        { from: "orchestrator", to: "planner", label: "\uACC4\uD68D" },
        { from: "planner", to: "validator", label: "\uAC80\uC99D" },
        { from: "validator", to: "executor", label: "\uC2E4\uD589" },
        { from: "executor", to: "script_loader" },
        { from: "executor", to: "stepaz_gen" },
        { from: "executor", to: "knowledge_final" },
        { from: "budget", to: "orchestrator", dashed: true, label: "\uAC10\uC2DC" },
      ],
    },
    "rag project": {
      title: "K-Scaffold Agent Pipeline",
      subtitle: "Task \u2192 Plan \u2192 Execute Steps \u2192 Validate \u2192 Complete",
      nodes: [
        { id: "controller", label: "AgentController",
          role: "ReAct \uB8E8\uD504 \uCEE8\uD2B8\uB864\uB7EC\n\uC784\uBB34 \uC218\uC2E0 \u2192 \uACC4\uD68D \u2192 \uC2E4\uD589 \u2192 \uACB0\uACFC \uD655\uC778 \uC21C\uD658 \uAD00\uB9AC\n\uB3D9\uC801(dynamic) / \uC21C\uCC28(sequential) \uB450 \uAC00\uC9C0 \uC2E4\uD589 \uBAA8\uB4DC \uC9C0\uC6D0\n\uC608\uC0B0 \uAC00\uB4DC \u2014 \uD1A0\uD070/\uBE44\uC6A9/\uD0C0\uC784\uC544\uC6C3 \uD55C\uB3C4 \uAD00\uB9AC",
          type: "controller", col: 0, row: 0 },
        { id: "planner", label: "Planner",
          role: "LLM \uAE30\uBC18 \uC791\uC5C5 \uACC4\uD68D \uC218\uB9BD\nGemini 2.5 Flash \uBAA8\uB378 + \uCEE8\uD14D\uC2A4\uD2B8 \uCE90\uC2F1 \uD65C\uC6A9\n\uC785\uB825\uB41C \uC791\uC5C5\uC744 \uBD84\uC11D\uD558\uC5EC \uCD5C\uC801 \uB3C4\uAD6C\uC640 \uC21C\uC11C \uACB0\uC815\n\uC2A4\uD0AC \uC720\uD615\uC5D0 \uB530\uB77C \uCF54\uB4DC\uBD84\uC11D/\uB9AC\uC11C\uCE58 \uD30C\uC774\uD504\uB77C\uC778 \uC120\uD0DD",
          type: "planner", col: 0, row: 1 },
        { id: "tool_executor", label: "ToolExecutor",
          role: "\uB3C4\uAD6C \uC2E4\uD589 \uC5D4\uC9C4\n\uACC4\uD68D\uB41C \uAC01 \uB2E8\uACC4\uC758 \uB3C4\uAD6C\uB97C \uC2E4\uC81C\uB85C \uD638\uCD9C\u00B7\uC2E4\uD589\ncode_analysis: 6\uB2E8\uACC4 (AST \uD30C\uC2F1, \uC758\uC874\uC131 \uB9F5\uD551 \uB4F1)\nresearch_analysis: 6\uB2E8\uACC4 (\uBB38\uC11C \uBD84\uC11D, \uC694\uC57D \uB4F1)\n\uC2E4\uD589 \uACB0\uACFC\uB97C Controller\uC5D0\uAC8C \uBC18\uD658",
          type: "executor", col: 0, row: 2 },
        { id: "policy_engine", label: "PolicyEngine",
          role: "\uC815\uCC45 \uBC0F \uC2B9\uC778 \uC5D4\uC9C4\nHuman-gate \u2014 \uC911\uC694 \uC791\uC5C5 \uC2E4\uD589 \uC804 \uC0AC\uC6A9\uC790 \uC2B9\uC778 \uC694\uCCAD\n\uAC00\uB4DC\uB808\uC77C \u2014 \uC704\uD5D8\uD55C \uC791\uC5C5\uC774\uB098 \uBC94\uC704 \uCD08\uACFC \uCC28\uB2E8\n\uC548\uC804 \uAC80\uC0AC \u2014 \uC2E4\uD589 \uC804 \uC785\uB825/\uCD9C\uB825 \uAC80\uC99D",
          type: "validator", col: 1, row: 1 },
        { id: "code_skill", label: "CodeAnalysis",
          role: "\uCF54\uB4DC \uBD84\uC11D \uC2A4\uD0AC (6\uB2E8\uACC4 \uD30C\uC774\uD504\uB77C\uC778)\n1. \uD504\uB85C\uC81D\uD2B8 \uAD6C\uC870 \uC2A4\uCE94\n2. AST \uD30C\uC2F1 \uBC0F \uCF54\uB4DC \uBD84\uC11D\n3. \uC758\uC874\uC131 \uB9F5\uD551\n4. \uCF54\uB4DC \uD488\uC9C8 \uD3C9\uAC00\n5. \uBCF4\uC548 \uCDE8\uC57D\uC810 \uAC80\uC0AC\n6. \uBD84\uC11D \uBCF4\uACE0\uC11C \uC0DD\uC131",
          type: "tool", col: -1, row: 3 },
        { id: "research_skill", label: "Research",
          role: "\uB9AC\uC11C\uCE58 \uBD84\uC11D \uC2A4\uD0AC (6\uB2E8\uACC4 \uD30C\uC774\uD504\uB77C\uC778)\n1. \uBB38\uC11C \uC218\uC9D1 \uBC0F \uC804\uCC98\uB9AC\n2. \uD575\uC2EC \uB0B4\uC6A9 \uCD94\uCD9C\n3. \uC8FC\uC81C\uBCC4 \uBD84\uB958 \uBC0F \uAD6C\uC870\uD654\n4. \uAD00\uB828\uC131 \uBD84\uC11D \uBC0F \uAD50\uCC28 \uCC38\uC870\n5. \uC694\uC57D \uBC0F \uD569\uC131\n6. \uCD5C\uC885 \uBCF4\uACE0\uC11C \uC0DD\uC131",
          type: "tool", col: 1, row: 3 },
      ],
      edges: [
        { from: "controller", to: "planner", label: "\uACC4\uD68D" },
        { from: "planner", to: "tool_executor", label: "\uC2E4\uD589" },
        { from: "tool_executor", to: "code_skill" },
        { from: "tool_executor", to: "research_skill" },
        { from: "policy_engine", to: "controller", dashed: true, label: "\uC2B9\uC778" },
        { from: "tool_executor", to: "controller", dashed: true, label: "\uACB0\uACFC" },
      ],
    },
  };

  // ── DOM refs ──
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const btnScan      = $("#btnScan");
  const statusBanner  = $("#statusBanner");
  const statusValue   = $("#statusValue");
  const progressFill  = $("#progressFill");
  const statPass      = $("#statPass .stat-num");
  const statWarn      = $("#statWarn .stat-num");
  const statFail      = $("#statFail .stat-num");
  const statDuration  = $("#statDuration");
  const phaseGrid     = $("#phaseGrid");
  const historyBody   = $("#historyBody");
  const modalBackdrop = $("#modalBackdrop");
  const modalClose    = $("#modalClose");
  const healthCanvas  = $("#healthChart");
  const btnTheme      = $("#btnTheme");
  const themeIcon     = $("#themeIcon");

  // ── Theme toggle ──
  function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    themeIcon.textContent = theme === "dark" ? "\u263E" : "\u2600";
    localStorage.setItem("dd-theme", theme);
    drawChart();
  }

  btnTheme.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    applyTheme(current === "dark" ? "light" : "dark");
  });

  // ── Init ──
  function init() {
    const saved = localStorage.getItem("dd-theme") || "dark";
    applyTheme(saved);
    loadLatest();
    loadHistory();

    // card click → modal, hover → tooltip
    const tooltip = $("#tooltip");
    let tooltipTimer = null;

    $$(".phase-card").forEach((card) => {
      card.addEventListener("click", () => {
        const name = card.dataset.phase;
        if (phaseReports[name]) openModal(phaseReports[name]);
      });

      card.addEventListener("mouseenter", (e) => {
        const why = card.dataset.tipWhy;
        if (!why) return;
        tooltipTimer = setTimeout(() => {
          tooltip.innerHTML = buildTooltipHTML(card);
          positionTooltip(tooltip, card);
          tooltip.classList.add("visible");
        }, 400);
      });

      card.addEventListener("mouseleave", () => {
        clearTimeout(tooltipTimer);
        tooltip.classList.remove("visible");
      });
    });

    modalClose.addEventListener("click", closeModal);
    modalBackdrop.addEventListener("click", (e) => {
      if (e.target === modalBackdrop) closeModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeModal();
    });

    btnScan.addEventListener("click", startScan);

    // ── Export button ──
    const btnExport = document.getElementById("btnExport");
    if (btnExport) {
      btnExport.addEventListener("click", async () => {
        btnExport.disabled = true;
        btnExport.textContent = "⏳ EXPORTING…";
        try {
          // Trigger file download via hidden anchor
          const a = document.createElement("a");
          a.href = "/api/scan/export?format=md";
          a.download = "";
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);

          setTimeout(() => {
            btnExport.innerHTML = "<span>📄</span> EXPORT";
            btnExport.disabled = false;
          }, 2000);
        } catch (err) {
          console.error("Export failed:", err);
          btnExport.innerHTML = "<span>📄</span> EXPORT";
          btnExport.disabled = false;
        }
      });
    }

    // ── AI Overview (full scan LLM summary) ──
    const btnAiOverview = document.getElementById("btnAiOverview");
    const aiPanel = document.getElementById("aiOverviewPanel");
    const aiContent = document.getElementById("aiOverviewContent");
    const aiClose = document.getElementById("aiOverviewClose");
    if (btnAiOverview && aiPanel && aiContent) {
      btnAiOverview.addEventListener("click", async () => {
        btnAiOverview.disabled = true;
        btnAiOverview.innerHTML = "<span>\u23F3</span> \uBD84\uC11D \uC911...";
        aiContent.innerHTML = '<div style="color:var(--text-muted)">\uD83E\uDDE0 LLM\uC774 \uC804\uCCB4 \uC2A4\uCE94 \uACB0\uACFC\uB97C \uBD84\uC11D\uD558\uACE0 \uC788\uC2B5\uB2C8\uB2E4...</div>';
        aiPanel.style.display = "block";
        try {
          const wsParam = document.cookie.match(/workspace_id=([^;]+)/);
          const qs = wsParam ? "?workspace_id=" + wsParam[1] : "";
          const res = await fetch("/api/llm/overview" + qs, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
          });
          const json = await res.json();
          if (json.success) {
            let html = "";
            const totals = json.totals || {};
            html += `<div class="ai-overview-totals">\uD83D\uDCCA \uC804\uCCB4: ${totals.pass || 0} PASS \xB7 ${totals.warn || 0} WARN \xB7 ${totals.fail || 0} FAIL (\uAC74\uAC15\uB3C4 ${totals.health_pct || 0}%) \xB7 ${totals.total_phases || "?"}\uAC1C \uD398\uC774\uC988 \uC911 ${totals.issue_phases || "?"}\uAC1C \uC774\uC288</div>`;

            // Always show the full overview text first (main analysis body)
            if (json.overview) {
              // Convert markdown-like formatting to HTML
              const formatted = escapeHtml(json.overview)
                .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
                .replace(/### (Root Causes|Fix Plan|Risks|Summary)/g, '')  // remove headers (shown separately)
                .replace(/\n/g, '<br>');
              html += `<div class="ai-overview-body">${formatted}</div>`;
            }

            // Also show parsed structured sections with icons
            if (json.root_causes && json.root_causes.length) {
              html += '<div class="llm-result-section"><h4>\uD83D\uDD0D \uADFC\uBCF8 \uC6D0\uC778</h4><ul>';
              json.root_causes.forEach(c => { html += `<li>${escapeHtml(c)}</li>`; });
              html += "</ul></div>";
            }
            if (json.fix_suggestions && json.fix_suggestions.length) {
              html += '<div class="llm-result-section"><h4>\uD83D\uDEE0 \uC218\uC815 \uBC29\uC548</h4><ol>';
              json.fix_suggestions.forEach(s => {
                const t = typeof s === "string" ? s : (s.action || JSON.stringify(s));
                html += `<li>${escapeHtml(t)}</li>`;
              });
              html += "</ol></div>";
            }
            if (json.model) {
              html += `<div class="llm-result-meta">Model: ${escapeHtml(json.model)}</div>`;
            }
            aiContent.innerHTML = html;
          } else {
            // Show friendly error
            const err = json.error || "Unknown error";
            const errLower = err.toLowerCase();
            if (errLower.includes("no llm provider") || errLower.includes("authenticationerror") || errLower.includes("api key")) {
              aiContent.innerHTML = '<div class="llm-result-error llm-result-no-provider"><span>\u26A0 LLM \uC124\uC815 \uD544\uC694</span><button class="btn-open-llm-config" onclick="document.getElementById(\'btnLlmConfig\').click()">LLM CONFIG \u2192</button></div>';
            } else {
              aiContent.innerHTML = `<div class="llm-result-error">\u274C ${escapeHtml(err)}</div>`;
            }
          }
        } catch (e) {
          aiContent.innerHTML = '<div class="llm-result-error">\u274C Network error</div>';
        }
        btnAiOverview.innerHTML = "<span>\uD83E\uDDE0</span> AI \uC694\uC57D";
        btnAiOverview.disabled = false;
      });
      if (aiClose) {
        aiClose.addEventListener("click", () => { aiPanel.style.display = "none"; });
      }
    }

    // ── Workspace switcher ──
    const wsSel = document.getElementById("workspaceSelect");
    if (wsSel) {
      wsSel.addEventListener("change", async (e) => {
        wsSel.disabled = true;
        try {
          const res = await fetch("/api/workspace/switch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: e.target.value }),
          });
          const json = await res.json();
          if (json.success) {
            location.reload();
          } else {
            wsSel.disabled = false;
            console.error("Workspace switch failed:", json.error);
          }
        } catch (err) {
          wsSel.disabled = false;
          console.error("Workspace switch error:", err);
        }
      });
    }

    // ── Workspace manager ──
    initWorkspaceManager();
  }

  // ── Workspace Manager ──
  function initWorkspaceManager() {
    const btnManage    = document.getElementById("btnManageWs");
    const backdrop     = document.getElementById("wsModalBackdrop");
    const closeBtn     = document.getElementById("wsModalClose");
    const pathInput    = document.getElementById("wsPathInput");
    const btnAdd       = document.getElementById("btnWsAdd");
    const btnBrowse    = document.getElementById("btnWsBrowse");
    const statusEl     = document.getElementById("wsAddStatus");
    const listEl       = document.getElementById("wsList");
    const browserEl    = document.getElementById("wsBrowser");
    const browserUpBtn = document.getElementById("wsBrowserUp");
    const browserPath  = document.getElementById("wsBrowserPath");
    const browserList  = document.getElementById("wsBrowserList");
    const defaultWsId  = window.__DD_DEFAULT_WS || "";

    let browserVisible = false;
    let browserCurrentPath = "";

    if (!btnManage || !backdrop) return;

    function openWsModal() {
      loadWsList();
      statusEl.textContent = "";
      statusEl.className = "ws-add-status";
      pathInput.value = "";
      closeBrowser();
      backdrop.classList.add("open");
      setTimeout(() => pathInput.focus(), 100);
    }

    function closeWsModal() {
      backdrop.classList.remove("open");
    }

    btnManage.addEventListener("click", openWsModal);
    closeBtn.addEventListener("click", closeWsModal);
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeWsModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && backdrop.classList.contains("open")) closeWsModal();
    });

    // ── Folder Browser ──
    function openBrowser() {
      browserVisible = true;
      browserEl.classList.add("open");
      browseTo("");  // show roots
    }

    function closeBrowser() {
      browserVisible = false;
      browserEl.classList.remove("open");
    }

    function toggleBrowser() {
      if (browserVisible) closeBrowser();
      else openBrowser();
    }

    btnBrowse.addEventListener("click", toggleBrowser);

    browserUpBtn.addEventListener("click", () => {
      if (!browserCurrentPath) return;
      // Go to parent
      const parts = browserCurrentPath.replace(/\/+$/, "").split("/");
      parts.pop();
      const parent = parts.join("/") || "/";
      if (parent === "/") {
        browseTo("");  // show roots
      } else {
        browseTo(parent);
      }
    });

    async function browseTo(path) {
      browserList.innerHTML = '<div class="ws-browser-loading">Loading...</div>';
      try {
        const url = path ? `/api/browse?path=${encodeURIComponent(path)}` : "/api/browse";
        const res = await fetch(url);
        const json = await res.json();
        if (!json.success) {
          browserList.innerHTML = `<div class="ws-browser-error">${escapeHtml(json.error || "Error")}</div>`;
          return;
        }
        browserCurrentPath = json.current || "";
        browserPath.textContent = json.current || "/";
        browserPath.title = json.current || "/";
        browserUpBtn.disabled = !json.parent;
        renderBrowserDirs(json.dirs);
      } catch (e) {
        browserList.innerHTML = '<div class="ws-browser-error">Network error</div>';
      }
    }

    function renderBrowserDirs(dirs) {
      browserList.innerHTML = "";

      // "Use this folder" button for current directory
      if (browserCurrentPath && browserCurrentPath !== "/") {
        const currentRow = document.createElement("div");
        currentRow.className = "ws-browser-current";
        currentRow.innerHTML = `
          <button class="ws-browser-use-current" title="Register this folder as workspace">
            \u2714 USE THIS FOLDER
          </button>
        `;
        browserList.appendChild(currentRow);
        currentRow.querySelector(".ws-browser-use-current").addEventListener("click", () => {
          pathInput.value = browserCurrentPath;
          closeBrowser();
          addWorkspace();
        });
      }

      if (dirs.length === 0) {
        const emptyEl = document.createElement("div");
        emptyEl.className = "ws-browser-empty";
        emptyEl.textContent = "No subdirectories";
        browserList.appendChild(emptyEl);
        return;
      }
      dirs.forEach((d) => {
        const row = document.createElement("div");
        row.className = "ws-browser-item" + (d.is_project ? " ws-browser-project" : "");
        row.innerHTML = `
          <span class="ws-browser-icon">${d.is_project ? "\uD83D\uDCCA" : "\uD83D\uDCC1"}</span>
          <span class="ws-browser-name">${escapeHtml(d.name)}</span>
          <button class="ws-browser-select" title="Add as workspace">+ ADD</button>
        `;
        browserList.appendChild(row);

        // Click folder name / icon → navigate into it
        const nameSpan = row.querySelector(".ws-browser-name");
        nameSpan.addEventListener("click", () => browseTo(d.path));
        const iconSpan = row.querySelector(".ws-browser-icon");
        iconSpan.addEventListener("click", () => browseTo(d.path));

        // Click "+ ADD" → add workspace
        row.querySelector(".ws-browser-select").addEventListener("click", (e) => {
          e.stopPropagation();
          pathInput.value = d.path;
          closeBrowser();
          addWorkspace();
        });
      });
    }

    // ── Workspace list ──
    async function loadWsList() {
      try {
        const res = await fetch("/api/workspaces");
        const json = await res.json();
        if (!json.success) return;
        renderWsList(json.workspaces, json.current);
      } catch (e) {
        console.error("loadWsList:", e);
      }
    }

    function renderWsList(workspaces, currentId) {
      listEl.innerHTML = "";
      workspaces.forEach((ws) => {
        const row = document.createElement("div");
        row.className = "ws-item" + (ws.id === currentId ? " ws-active" : "");
        const isPrimary = ws.id === defaultWsId;
        row.innerHTML = `
          <div class="ws-item-info">
            <span class="ws-item-name">${escapeHtml(ws.name)}</span>
            ${isPrimary ? '<span class="ws-item-badge">PRIMARY</span>' : ""}
            <span class="ws-item-path">${escapeHtml(ws.root)}</span>
          </div>
          ${isPrimary ? "" : `<button class="ws-item-remove" data-id="${ws.id}" title="Remove workspace">&times;</button>`}
        `;
        listEl.appendChild(row);

        const rmBtn = row.querySelector(".ws-item-remove");
        if (rmBtn) {
          rmBtn.addEventListener("click", () => removeWorkspace(ws.id, ws.name));
        }
      });
    }

    // ── Add workspace ──
    btnAdd.addEventListener("click", addWorkspace);
    pathInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") addWorkspace();
    });

    async function addWorkspace() {
      const path = pathInput.value.trim();
      if (!path) return;

      btnAdd.disabled = true;
      btnAdd.textContent = "ADDING...";
      statusEl.textContent = "";
      statusEl.className = "ws-add-status";

      try {
        const res = await fetch("/api/workspace/add", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path }),
        });
        const json = await res.json();

        if (json.success) {
          const w = json.workspace;
          let msg = `\u2713 ${w.name}`;
          if (json.already_loaded) msg += " (already loaded)";
          else if (json.scaffolded) msg += " \u2014 auto-analyzed";

          statusEl.textContent = msg;
          statusEl.className = "ws-add-status ws-status-ok";
          pathInput.value = "";

          loadWsList();
          await refreshDropdown();

          // Auto-switch to newly added workspace
          if (!json.already_loaded) {
            statusEl.textContent = msg + " \u2014 switching...";
            try {
              await fetch("/api/workspace/switch", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ id: w.id }),
              });
            } catch (_) {}
            location.reload();
            return;
          }
        } else {
          statusEl.textContent = "\u2717 " + (json.error || "Failed");
          statusEl.className = "ws-add-status ws-status-err";
        }
      } catch (e) {
        statusEl.textContent = "\u2717 Network error";
        statusEl.className = "ws-add-status ws-status-err";
      }

      btnAdd.disabled = false;
      btnAdd.textContent = "+ ADD";
    }

    // ── Remove workspace ──
    async function removeWorkspace(wsId, wsName) {
      try {
        const res = await fetch("/api/workspace/remove", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: wsId }),
        });
        const json = await res.json();

        if (json.success) {
          statusEl.textContent = `\u2713 Removed: ${wsName}`;
          statusEl.className = "ws-add-status ws-status-ok";
          loadWsList();
          refreshDropdown();
        } else {
          statusEl.textContent = "\u2717 " + (json.error || "Failed");
          statusEl.className = "ws-add-status ws-status-err";
        }
      } catch (e) {
        statusEl.textContent = "\u2717 Network error";
        statusEl.className = "ws-add-status ws-status-err";
      }
    }

    // ── Refresh dropdown ──
    async function refreshDropdown() {
      try {
        const res = await fetch("/api/workspaces");
        const json = await res.json();
        if (!json.success) return;

        const sel = document.getElementById("workspaceSelect");
        if (!sel) return;

        const currentVal = sel.value;
        sel.innerHTML = "";
        json.workspaces.forEach((ws) => {
          const opt = document.createElement("option");
          opt.value = ws.id;
          opt.textContent = ws.name;
          if (ws.id === currentVal) opt.selected = true;
          sel.appendChild(opt);
        });
      } catch (e) {
        console.error("refreshDropdown:", e);
      }
    }
  }   // end initWorkspaceManager

  // ── Tooltip build & positioning ──
  function buildTooltipHTML(card) {
    const why = card.dataset.tipWhy || "";
    const what = card.dataset.tipWhat || "";
    const resultBase = card.dataset.tipResult || "";
    const name = card.dataset.phase;
    const report = phaseReports[name];

    let resultClass = "";
    let liveStats = "";
    if (report) {
      const checks = report.checks || [];
      const pass = checks.filter((c) => c.status === "PASS").length;
      const warn = checks.filter((c) => c.status === "WARN").length;
      const fail = checks.filter((c) => c.status === "FAIL").length;
      if (fail > 0) resultClass = "has-fail";
      else if (warn > 0) resultClass = "has-warn";
      liveStats = `<div class="tip-result-live"><span class="rpass">${pass} PASS</span> &middot; <span class="rwarn">${warn} WARN</span> &middot; <span class="rfail">${fail} FAIL</span></div>`;
    }

    return `
      <div class="tip-section">
        <span class="tip-label tip-label-why">WHY &mdash; \uC774 \uB2E8\uACC4\uAC00 \uD544\uC694\uD55C \uC774\uC720</span>
        <div class="tip-text">${escapeHtml(why)}</div>
      </div>
      <div class="tip-section">
        <span class="tip-label tip-label-what">WHAT &mdash; \uD604\uC7AC \uC810\uAC80 \uD56D\uBAA9</span>
        <div class="tip-text">${escapeHtml(what)}</div>
      </div>
      <div class="tip-section">
        <span class="tip-label tip-label-result ${resultClass}">RESULT &mdash; \uACB0\uB860</span>
        <div class="tip-text">${escapeHtml(resultBase)}</div>
        ${liveStats}
      </div>
    `;
  }

  function positionTooltip(tip, anchor) {
    const rect = anchor.getBoundingClientRect();
    const tipW = 380;
    let left = rect.left + rect.width / 2 - tipW / 2;
    let top = rect.bottom + 10;

    // keep within viewport
    if (left < 8) left = 8;
    if (left + tipW > window.innerWidth - 8) left = window.innerWidth - tipW - 8;
    // if overflows bottom, show above
    const tipH = tip.offsetHeight || 200;
    if (top + tipH > window.innerHeight - 8) top = rect.top - tipH - 10;

    tip.style.left = left + "px";
    tip.style.top = top + "px";
    tip.style.width = tipW + "px";
  }

  // ── Load latest scan ──
  async function loadLatest() {
    try {
      const res = await fetch("/api/scan/latest");
      const json = await res.json();
      if (json.success && json.data) {
        const d = json.data;
        setStatus(d.overall_status, d.total_pass, d.total_warn, d.total_fail, d.health_pct, d.duration_ms);
        if (d.phases_json) {
          const phases = JSON.parse(d.phases_json);
          phases.forEach((r) => {
            phaseReports[r.name] = r;
            updateCard(r.name, r);
          });
        }
      }
    } catch (e) {
      console.error("loadLatest error:", e);
    }
  }

  // ── Load history ──
  async function loadHistory() {
    try {
      const res = await fetch("/api/scan/history?limit=30");
      const json = await res.json();
      if (json.success) {
        historyData = json.data || [];
        renderHistory();
        drawChart();
      }
    } catch (e) {
      console.error("loadHistory error:", e);
    }
  }

  // ── SSE scan ──
  function startScan() {
    if (scanning) return;
    scanning = true;
    btnScan.disabled = true;
    btnScan.querySelector(".btn-scan-text").textContent = "SCANNING...";
    phaseReports = {};

    statusBanner.className = "status-banner scanning";
    statusValue.textContent = "SCANNING";
    progressFill.style.width = "0%";
    statPass.textContent = "—";
    statWarn.textContent = "—";
    statFail.textContent = "—";
    statDuration.textContent = "";

    // Reset all cards
    $$(".phase-card").forEach((card) => {
      card.className = "phase-card";
      card.querySelector(".card-pass").textContent = "—";
      card.querySelector(".card-total").textContent = "—";
      card.querySelector(".card-bar-fill").style.width = "0";
      card.querySelector(".card-status-text").textContent = "WAITING";
      card.querySelector(".card-badge").textContent = "\u22EF";
    });

    const totalPhases = $$(".phase-card").length;
    let doneCount = 0;

    const evtSource = new EventSource("/api/scan/run");

    evtSource.onmessage = (event) => {
      let msg;
      try { msg = JSON.parse(event.data); } catch { return; }

      if (msg.type === "phase_start") {
        const card = $(`#card-${msg.name}`);
        if (card) {
          card.classList.add("scanning");
          card.querySelector(".card-status-text").textContent = "SCANNING...";
        }
      }

      if (msg.type === "phase_done") {
        doneCount++;
        const pct = Math.round((doneCount / totalPhases) * 100);
        progressFill.style.width = pct + "%";

        phaseReports[msg.name] = msg.report;
        updateCard(msg.name, msg.report);
      }

      if (msg.type === "scan_complete") {
        evtSource.close();
        scanning = false;
        btnScan.disabled = false;
        btnScan.querySelector(".btn-scan-text").textContent = "INITIATE SCAN";

        setStatus(msg.overall, msg.total_pass, msg.total_warn, msg.total_fail, msg.health_pct, msg.duration_ms);
        loadHistory();
      }
    };

    evtSource.onerror = () => {
      evtSource.close();
      scanning = false;
      btnScan.disabled = false;
      btnScan.querySelector(".btn-scan-text").textContent = "INITIATE SCAN";
      statusValue.textContent = "ERROR";
    };
  }

  // ── Update a single phase card ──
  function updateCard(name, report) {
    const card = $(`#card-${name}`);
    if (!card) return;

    card.classList.remove("scanning", "pass", "warn", "fail");

    const checks = report.checks || [];
    const total = checks.length;
    const pass = checks.filter((c) => c.status === "PASS").length;
    const warn = checks.filter((c) => c.status === "WARN").length;
    const fail = checks.filter((c) => c.status === "FAIL").length;

    card.querySelector(".card-pass").textContent = pass;
    card.querySelector(".card-total").textContent = total;

    const pct = total > 0 ? Math.round((pass / total) * 100) : 100;
    card.querySelector(".card-bar-fill").style.width = pct + "%";

    // Determine card class
    if (fail > 0) {
      card.classList.add("fail");
      card.querySelector(".card-status-text").textContent = `${fail} FAILED`;
    } else if (warn > 0) {
      card.classList.add("warn");
      card.querySelector(".card-status-text").textContent = `${warn} WARNING`;
    } else {
      card.classList.add("pass");
      card.querySelector(".card-status-text").textContent = "ALL CLEAR";
    }
  }

  // ── Set overall status ──
  function setStatus(overall, pass, warn, fail, healthPct, durationMs) {
    const cls = overall === "HEALTHY" ? "healthy" : overall === "CRITICAL" ? "critical" : "degraded";
    statusBanner.className = `status-banner ${cls}`;
    statusValue.textContent = overall;
    progressFill.style.width = (healthPct || 0) + "%";
    statPass.textContent = pass;
    statWarn.textContent = warn;
    statFail.textContent = fail;
    if (durationMs !== undefined) {
      statDuration.textContent = (durationMs / 1000).toFixed(1) + "s elapsed";
    }
    // GPT Review #8: update status description with cause summary
    updateStatusDescription(overall, fail, warn);
  }

  // GPT Review #8: descriptive status summary — shows which phases caused WARN/FAIL
  function updateStatusDescription(overall, failCount, warnCount) {
    const descEl = document.getElementById("statusDescription");
    if (!descEl) return;

    if (overall === "HEALTHY") {
      descEl.innerHTML = '<span class="desc-label">ALL CLEAR</span> — All checkers passed. System is operating normally.';
      return;
    }

    // Collect phase names that have WARN or FAIL from phaseReports
    const failPhases = [];
    const warnPhases = [];
    for (const [name, report] of Object.entries(phaseReports)) {
      const checks = (report.checks || []);
      const fc = checks.filter(c => c.status === "FAIL").length;
      const wc = checks.filter(c => c.status === "WARN").length;
      const displayName = (report.meta && report.meta.display_name) || name;
      if (fc > 0) failPhases.push(displayName);
      else if (wc > 0) warnPhases.push(displayName);
    }

    let html = "";
    if (overall === "CRITICAL") {
      html = `<span class="desc-label">CRITICAL</span> — `;
      if (failPhases.length > 0) {
        html += `FAIL in <span class="desc-phases">${failPhases.join(", ")}</span>`;
      }
      if (warnPhases.length > 0) {
        html += (failPhases.length > 0 ? " · " : "") + `WARN in <span class="desc-phases">${warnPhases.join(", ")}</span>`;
      }
      html += ". Click a card for details.";
    } else if (overall === "DEGRADED") {
      html = `<span class="desc-label">DEGRADED</span> — `;
      if (warnPhases.length > 0) {
        html += `WARN in <span class="desc-phases">${warnPhases.join(", ")}</span>`;
      }
      html += ". Review warnings to prevent escalation.";
    }

    descEl.innerHTML = html;
  }

  // ── Render history table ──
  function renderHistory() {
    historyBody.innerHTML = "";
    historyData.forEach((row) => {
      const tr = document.createElement("tr");
      const statusCls = row.overall_status === "HEALTHY" ? "healthy" : row.overall_status === "CRITICAL" ? "critical" : "degraded";
      tr.innerHTML = `
        <td>${formatTime(row.timestamp)}</td>
        <td><span class="badge-status badge-${statusCls}">${row.overall_status}</span></td>
        <td style="color:var(--green);font-weight:600">${row.total_pass}</td>
        <td style="color:var(--amber);font-weight:600">${row.total_warn}</td>
        <td style="color:var(--red);font-weight:600">${row.total_fail}</td>
        <td>${row.health_pct.toFixed(1)}%</td>
        <td>${(row.duration_ms / 1000).toFixed(1)}s</td>
      `;
      historyBody.appendChild(tr);
    });
  }

  function formatTime(ts) {
    if (!ts) return "—";
    const d = new Date(ts);
    const pad = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  // ── Canvas chart ──
  function drawChart() {
    const ctx = healthCanvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const rect = healthCanvas.getBoundingClientRect();
    healthCanvas.width = rect.width * dpr;
    healthCanvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const isDark = (document.documentElement.getAttribute("data-theme") || "dark") === "dark";

    // Background
    ctx.clearRect(0, 0, w, h);

    const data = [...historyData].reverse(); // oldest first
    if (data.length < 2) {
      ctx.fillStyle = isDark ? "#64748b" : "#94a3b8";
      ctx.font = "12px monospace";
      ctx.textAlign = "center";
      ctx.fillText("Run scans to build health timeline", w / 2, h / 2);
      return;
    }

    const padL = 40, padR = 16, padT = 16, padB = 30;
    const plotW = w - padL - padR;
    const plotH = h - padT - padB;

    // Grid lines
    ctx.strokeStyle = isDark ? "rgba(255,255,255,0.06)" : "rgba(0,0,0,0.06)";
    ctx.lineWidth = 1;
    for (let p = 0; p <= 100; p += 25) {
      const y = padT + plotH - (p / 100) * plotH;
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(w - padR, y);
      ctx.stroke();

      ctx.fillStyle = isDark ? "#64748b" : "#94a3b8";
      ctx.font = "10px monospace";
      ctx.textAlign = "right";
      ctx.fillText(p + "%", padL - 6, y + 4);
    }

    // Plot line
    const step = plotW / (data.length - 1);
    const points = data.map((d, i) => ({
      x: padL + i * step,
      y: padT + plotH - (d.health_pct / 100) * plotH,
      pct: d.health_pct,
    }));

    // Gradient fill
    const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
    grad.addColorStop(0, isDark ? "rgba(6,182,212,0.15)" : "rgba(6,182,212,0.1)");
    grad.addColorStop(1, "transparent");

    ctx.beginPath();
    ctx.moveTo(points[0].x, padT + plotH);
    points.forEach((p) => ctx.lineTo(p.x, p.y));
    ctx.lineTo(points[points.length - 1].x, padT + plotH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Line
    ctx.beginPath();
    points.forEach((p, i) => (i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y)));
    ctx.strokeStyle = "#06b6d4";
    ctx.lineWidth = 2;
    ctx.shadowColor = "rgba(6,182,212,0.4)";
    ctx.shadowBlur = 8;
    ctx.stroke();
    ctx.shadowBlur = 0;

    // Dots
    points.forEach((p) => {
      const color = p.pct >= 80 ? "#22c55e" : p.pct >= 50 ? "#f59e0b" : "#ef4444";
      ctx.beginPath();
      ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
    });

    // X-axis labels
    ctx.fillStyle = isDark ? "#64748b" : "#94a3b8";
    ctx.font = "10px monospace";
    ctx.textAlign = "center";
    const labelStep = Math.max(1, Math.floor(data.length / 6));
    data.forEach((d, i) => {
      if (i % labelStep === 0 || i === data.length - 1) {
        const x = padL + i * step;
        ctx.fillText(formatTime(d.timestamp).slice(5, 11), x, h - 6);
      }
    });
  }

  window.addEventListener("resize", drawChart);

  // ── Modal ──
  let currentModalPhase = null;

  function openModal(report) {
    const meta = report.meta || {};
    const checks = report.checks || [];
    currentModalPhase = report.name;

    // Set data-phase for DEEP ANALYZE button to read
    const phaseModal = document.getElementById("phaseModal");
    if (phaseModal) phaseModal.setAttribute("data-phase", report.name);

    $("#modalIcon").textContent = meta.icon || "";
    $("#modalTitle").textContent = (meta.display_name || report.name) + " ANALYSIS";

    const total = checks.length;
    const pass = checks.filter((c) => c.status === "PASS").length;
    const warn = checks.filter((c) => c.status === "WARN").length;
    const fail = checks.filter((c) => c.status === "FAIL").length;
    const pct = total > 0 ? Math.round((pass / total) * 100) : 100;

    $("#modalSummary").textContent = `${pass} / ${total} checks passed    ${warn} warnings    ${fail} failures`;

    const mFill = $("#modalProgressFill");
    mFill.style.width = pct + "%";
    if (fail > 0) { mFill.style.background = "var(--red)"; mFill.style.boxShadow = "0 0 8px var(--red)"; }
    else if (warn > 0) { mFill.style.background = "var(--amber)"; mFill.style.boxShadow = "0 0 8px var(--amber)"; }
    else { mFill.style.background = "var(--green)"; mFill.style.boxShadow = "0 0 8px var(--green)"; }

    const container = $("#modalChecks");
    container.innerHTML = "";

    // FIX ALL button — insert before checks list
    const fixableCount = checks.filter((c) => c.fixable).length;
    const fixAllWrap = $("#modalFixAll");
    if (fixAllWrap) fixAllWrap.remove();

    if (fixableCount > 0) {
      const wrap = document.createElement("div");
      wrap.className = "fix-all-bar";
      wrap.id = "modalFixAll";
      wrap.innerHTML = `
        <div class="fix-all-top">
          <span class="fix-all-label">\u26A0 ${fixableCount} fixable items</span>
          <button class="btn-fix-all" id="btnFixAll">
            <span class="btn-fix-all-icon">\u2692</span>
            <span class="btn-fix-all-text">FIX ALL</span>
          </button>
        </div>
        <div class="fix-all-progress-track" id="fixAllProgressTrack">
          <div class="fix-all-progress-fill" id="fixAllProgressFill"></div>
        </div>
      `;
      container.parentNode.insertBefore(wrap, container);
      wrap.querySelector("#btnFixAll").addEventListener("click", () => {
        executeFixAll(report.name);
      });
    }

    // Sort: FAIL first, then WARN, then PASS, then SKIP
    const order = { FAIL: 0, WARN: 1, PASS: 2, SKIP: 3 };
    const sorted = [...checks].sort((a, b) => (order[a.status] ?? 4) - (order[b.status] ?? 4));

    sorted.forEach((check) => {
      const statusIcon = check.status === "PASS" ? "\u2713" : check.status === "WARN" ? "\u26A0" : check.status === "FAIL" ? "\u2717" : "\u2014";
      const cls = check.status.toLowerCase();

      const item = document.createElement("div");
      item.className = `check-item check-${cls}`;

      const hasDetails = check.details && (typeof check.details === "object" ? Object.keys(check.details).length > 0 : true);
      const fixBtn = check.fixable ? `<button class="btn-fix" data-phase="${report.name}" data-check="${check.name}">AUTO-FIX</button>` : "";
      const fixDescRow = (check.fixable && check.fix_desc)
        ? `<div class="fix-row"><span class="fix-desc-icon">\u2692</span><span class="fix-desc-text">${escapeHtml(check.fix_desc)}</span>${fixBtn}</div>`
        : "";
      const inlineFixBtn = (check.fixable && check.fix_desc) ? "" : fixBtn;

      item.innerHTML = `
        <div class="check-head">
          <span class="check-status-icon">${statusIcon}</span>
          <span class="check-name">${check.name}</span>
          <span class="check-message">${check.message || ""}</span>
          ${inlineFixBtn}
        </div>
        ${fixDescRow}
        ${hasDetails ? `<div class="check-details">${formatDetails(check.details)}</div>` : ""}
      `;

      if (hasDetails) {
        item.querySelector(".check-head").addEventListener("click", (e) => {
          if (e.target.classList.contains("btn-fix")) return;
          const det = item.querySelector(".check-details");
          det.classList.toggle("open");
        });
      }

      const fixBtnEl = item.querySelector(".btn-fix");
      if (fixBtnEl) {
        fixBtnEl.addEventListener("click", (e) => {
          e.stopPropagation();
          executeFix(fixBtnEl, report.name, check.name);
        });
      }

      container.appendChild(item);
    });

    modalBackdrop.classList.add("open");

    // Show cached LLM analysis result if available for this phase
    if (typeof _llmAnalysisCache !== "undefined" && _llmAnalysisCache[report.name]) {
      const cached = _llmAnalysisCache[report.name];
      const cachedHTML = _buildLLMAnalysisHTML(cached);
      const phModal = document.getElementById("phaseModal");
      if (phModal) _injectLLMResultInModal(phModal, cachedHTML);
    }
  }

  // ── Refresh a single phase after fix ──
  async function refreshPhase(phase) {
    try {
      const res = await fetch(`/api/phase/${phase}`);
      const json = await res.json();
      if (json.success && json.data) {
        phaseReports[phase] = json.data;
        updateCard(phase, json.data);
      }
    } catch (e) {
      console.error("refreshPhase error:", e);
    }
  }

  // ── Auto-fix execution ──
  async function executeFix(btn, phase, checkName) {
    btn.disabled = true;
    btn.classList.add("fixing");
    btn.innerHTML = `<span class="fix-btn-text">\u2692 \uC218\uC815 \uC911...</span><span class="fix-btn-bar"><span class="fix-btn-bar-fill"></span></span>`;

    // Show fix progress in the check item
    const item = btn.closest(".check-item");
    let statusDiv = null;
    if (item) {
      statusDiv = document.createElement("div");
      statusDiv.className = "fix-status-msg";
      statusDiv.innerHTML = `<span class="fix-status-icon">\u23F3</span> <span class="fix-status-text">${escapeHtml(checkName)} \uC218\uC815\uC744 \uC2E4\uD589\uD558\uACE0 \uC788\uC2B5\uB2C8\uB2E4...</span>`;
      item.appendChild(statusDiv);
    }

    try {
      const res = await fetch(`/api/fix/${phase}/${checkName}`, { method: "POST" });
      const json = await res.json();

      if (json.success) {
        btn.classList.remove("fixing");
        btn.classList.add("fixed");
        btn.innerHTML = `<span class="fix-btn-text">\u2713 \uC644\uB8CC</span>`;

        // Update the check item visual
        if (item) {
          item.className = "check-item check-pass";
          const icon = item.querySelector(".check-status-icon");
          if (icon) { icon.textContent = "\u2713"; icon.style.color = "var(--green)"; }
          const msg = item.querySelector(".check-message");
          if (msg) msg.textContent = json.message || "Fixed";
        }
        // Show completion message
        if (statusDiv) {
          const doneMsg = json.message || "\uC218\uC815 \uC644\uB8CC";
          statusDiv.innerHTML = `<span class="fix-status-icon fix-status-ok">\u2705</span> <span class="fix-status-text">${escapeHtml(doneMsg)}</span>`;
          setTimeout(() => { if (statusDiv.parentNode) statusDiv.remove(); }, 5000);
        }

        // Refresh phase card in background
        refreshPhase(phase);
      } else {
        btn.classList.remove("fixing");
        btn.classList.add("fix-error");
        btn.innerHTML = `<span class="fix-btn-text">\u274C \uC2E4\uD328</span>`;
        btn.title = json.message || "Fix failed";
        if (statusDiv) {
          statusDiv.innerHTML = `<span class="fix-status-icon fix-status-err">\u274C</span> <span class="fix-status-text">\uC2E4\uD328: ${escapeHtml(json.message || "unknown error")}</span>`;
        }
        setTimeout(() => {
          btn.classList.remove("fix-error");
          btn.innerHTML = `<span class="fix-btn-text">\uC7AC\uC2DC\uB3C4</span>`;
          btn.disabled = false;
          if (statusDiv && statusDiv.parentNode) statusDiv.remove();
        }, 5000);
      }
    } catch (e) {
      btn.classList.remove("fixing");
      btn.classList.add("fix-error");
      btn.innerHTML = `<span class="fix-btn-text">\u274C \uC624\uB958</span>`;
      if (statusDiv) {
        statusDiv.innerHTML = `<span class="fix-status-icon fix-status-err">\u274C</span> <span class="fix-status-text">\uB124\uD2B8\uC6CC\uD06C \uC624\uB958</span>`;
      }
      setTimeout(() => {
        btn.classList.remove("fix-error");
        btn.innerHTML = `<span class="fix-btn-text">\uC7AC\uC2DC\uB3C4</span>`;
        btn.disabled = false;
        if (statusDiv && statusDiv.parentNode) statusDiv.remove();
      }, 5000);
    }
  }

  // ── FIX ALL — batch auto-fix ──
  async function executeFixAll(phase) {
    const allBtns = Array.from($$("#modalChecks .btn-fix")).filter(
      (b) => !b.disabled && !b.classList.contains("fixed")
    );
    if (allBtns.length === 0) return;

    const fixAllBtn = $("#btnFixAll");
    const progressTrack = $("#fixAllProgressTrack");
    const progressFillEl = $("#fixAllProgressFill");

    if (fixAllBtn) {
      fixAllBtn.disabled = true;
      fixAllBtn.querySelector(".btn-fix-all-text").textContent = `\uC218\uC815 \uC911 0/${allBtns.length}...`;
      fixAllBtn.classList.add("fixing");
    }
    if (progressTrack) progressTrack.classList.add("active");
    if (progressFillEl) { progressFillEl.style.width = "0%"; progressFillEl.className = "fix-all-progress-fill"; }

    let done = 0;
    let success = 0;
    for (const btn of allBtns) {
      const checkName = btn.dataset.check;
      await executeFix(btn, phase, checkName);
      done++;
      if (btn.classList.contains("fixed")) success++;
      const pct = Math.round((done / allBtns.length) * 100);
      if (fixAllBtn) {
        fixAllBtn.querySelector(".btn-fix-all-text").textContent = `\uC218\uC815 \uC911 ${done}/${allBtns.length}...`;
      }
      if (progressFillEl) progressFillEl.style.width = pct + "%";
    }

    if (fixAllBtn) {
      fixAllBtn.classList.remove("fixing");
      if (success === allBtns.length) {
        fixAllBtn.classList.add("fixed");
        fixAllBtn.querySelector(".btn-fix-all-text").textContent = `\u2713 \uC804\uCCB4 \uC218\uC815 \uC644\uB8CC (${success}\uAC1C)`;
        if (progressFillEl) progressFillEl.classList.add("done");
      } else {
        fixAllBtn.querySelector(".btn-fix-all-text").textContent = `${success}/${allBtns.length}\uAC1C \uC218\uC815 \uC644\uB8CC`;
        fixAllBtn.disabled = false;
        if (progressFillEl) progressFillEl.classList.add("partial");
      }
    }

    // Re-scan the phase and refresh card + modal with live data
    try {
      const res = await fetch(`/api/phase/${phase}`);
      const json = await res.json();
      if (json.success && json.data) {
        phaseReports[phase] = json.data;
        updateCard(phase, json.data);
        // Re-render modal with updated scan results
        openModal(json.data);
      }
    } catch (e) {
      console.error("Post-fixAll refresh error:", e);
    }
  }

  function closeModal() {
    modalBackdrop.classList.remove("open");
    // Clean up LLM result from modal
    const modal = document.getElementById("phaseModal");
    if (modal) {
      const llmResult = modal.querySelector(".llm-modal-result");
      if (llmResult) llmResult.remove();
      // Also remove the injected DEEP ANALYZE button so it re-creates fresh next time
      const deepBtn = modal.querySelector(".btn-deep-analyze");
      if (deepBtn) deepBtn.remove();
    }
  }

  function formatDetails(details) {
    if (!details) return "";
    if (typeof details === "string") return escapeHtml(details);
    if (Array.isArray(details)) {
      return details.map((d) => {
        if (typeof d === "object") {
          return Object.entries(d).map(([k, v]) => `${k}: ${v}`).join("  |  ");
        }
        return String(d);
      }).map(escapeHtml).join("\n");
    }
    if (typeof details === "object") {
      return Object.entries(details).map(([k, v]) => {
        if (Array.isArray(v)) return `${k}:\n  ${v.join("\n  ")}`;
        return `${k}: ${v}`;
      }).map(escapeHtml).join("\n");
    }
    return escapeHtml(String(details));
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ══════════════════════════════════════════════════════
  // AGENT PANEL — SSE client, state display, LLM panel
  // ══════════════════════════════════════════════════════

  function initAgent() {
    if (!window.__DD_AGENT_ENABLED) return;

    const stateEl = document.getElementById("agentState");
    const logEl = document.getElementById("agentEventLog");
    const toggleBtn = document.getElementById("btnAgentToggle");
    const scanBtn = document.getElementById("btnAgentScan");
    const llmBadge = document.getElementById("agentLlmBadge");
    const llmPanel = document.getElementById("agentLLMPanel");
    const llmContent = document.getElementById("llmPanelContent");
    const llmClose = document.getElementById("llmPanelClose");

    let agentRunning = window.__DD_AGENT_STATE !== "idle" && window.__DD_AGENT_STATE !== "disabled";
    let eventSource = null;
    const maxLogEntries = 30;
    // GPT Review #3C: SSE dedupe — track seen event IDs to prevent duplicates on reconnect
    const _seenEventIds = new Set();
    const MAX_SEEN_IDS = 500;
    let _lastEventId = "";
    // GPT Review #7-1: consecutive failure detection for observer status
    let _observerFailCount = 0;
    const OBSERVER_DOWN_THRESHOLD = 2;  // require 2 consecutive failures before showing DOWN

    // GPT Review #8: agent state descriptions for each state
    const _agentStateDescriptions = {
      idle:         "Agent is stopped. Click ▶ to start autonomous file monitoring and auto-scanning.",
      observing:    "Agent is actively watching project files for changes. Detected changes will trigger relevant checkers automatically.",
      reasoning:    "Agent is analyzing a detected event to determine which checkers need to run.",
      executing:    "Agent is running the selected checkers in dependency order.",
      waiting_llm:  "Agent is waiting for LLM analysis response. This may take a few seconds.",
      error:        "Agent encountered an error. It will auto-recover shortly. Check the event log for details.",
      disabled:     "Agent mode is not enabled for this workspace.",
    };

    function updateStateDisplay(state) {
      if (!stateEl) return;
      stateEl.textContent = state.toUpperCase();
      stateEl.setAttribute("data-state", state);
      agentRunning = state !== "idle" && state !== "disabled";
      if (toggleBtn) {
        document.getElementById("agentToggleIcon").innerHTML = agentRunning ? "&#9724;" : "&#9654;";
        // GPT Review #8: dynamic tooltip for toggle button based on state
        toggleBtn.title = agentRunning
          ? "Stop the agent loop — disables file watching and auto-scanning"
          : "Start the agent loop — enables file watching and auto-scanning (Observe → Reason → Act)";
      }
      // GPT Review #8: update agent state description
      const descEl = document.getElementById("agentStateDescription");
      if (descEl) {
        descEl.textContent = _agentStateDescriptions[state] || "";
      }
    }

    function addLogEntry(event) {
      if (!logEl) return;
      // Remove "empty" placeholder
      const empty = logEl.querySelector(".agent-log-empty");
      if (empty) empty.remove();

      const entry = document.createElement("div");
      entry.className = "agent-log-entry";
      const time = new Date(event.timestamp || Date.now());
      const timeStr = time.toLocaleTimeString("en", {hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit"});

      let msg = "";
      const d = event.data || {};
      switch (event.type) {
        case "file_changed":
          msg = `${d.file_count || 0} file(s) → [${(d.affected_checkers||[]).join(", ")}]`;
          break;
        case "scan_completed":
          if (d.skipped) { msg = "Skipped (in progress)"; }
          else { msg = `${d.overall} — P:${d.total_pass} W:${d.total_warn} F:${d.total_fail} (${d.health_pct}%)`; }
          break;
        case "scan_requested":
          msg = d.checkers ? `Manual: [${d.checkers.join(", ")}]` : "Full scan requested";
          break;
        case "insight_generated":
          // GPT Review #6 UI + #7-2: handle purge notification via stacking system
          if (d.purge) {
            msg = `Purge: ${d.total_deleted} rows cleaned (events:${d.events_deleted || 0}, analyses:${d.analyses_deleted || 0})`;
            showNotificationBanner("purge", "\uD83D\uDDD1 " + msg, 30000);
          } else {
            msg = (d.insights || []).map(i => i.message).join("; ") || "Insight";
          }
          break;
        case "llm_analysis_completed":
          if (d.error) { msg = `Error: ${d.error}`; }
          else { msg = `${d.checker} analyzed (${d.model}, $${(d.cost_usd||0).toFixed(4)})`; }
          break;
        case "agent_state_changed":
          msg = `${d.old || "?"} → ${d.new || "?"}`;
          if (d.error) msg = `Error: ${d.error}`;
          break;
        default:
          msg = event.type;
      }

      entry.innerHTML = `
        <span class="agent-log-time">${timeStr}</span>
        <span class="agent-log-type" data-type="${event.type}">${(event.type||"").replace(/_/g," ").toUpperCase()}</span>
        <span class="agent-log-msg">${escapeHtml(msg)}</span>
      `;
      logEl.prepend(entry);

      // Limit entries
      while (logEl.children.length > maxLogEntries) {
        logEl.removeChild(logEl.lastChild);
      }
    }

    function _buildLLMAnalysisHTML(data) {
      let html = "";
      if (data.error) {
        const err = data.error || "";
        const errLower = err.toLowerCase();
        const isNoProvider = errLower.includes("no llm provider");
        const isAuthError = errLower.includes("authenticationerror") || errLower.includes("api key not valid") || errLower.includes("api_key_invalid") || errLower.includes("invalid api key") || errLower.includes("incorrect api key");
        const isNotInstalled = errLower.includes("litellm is not installed");
        if (isNoProvider || isNotInstalled) {
          const msg = isNotInstalled
            ? "\u26A0 litellm \uBBF8\uC124\uCE58 \u2014 pip install litellm \uC2E4\uD589 \uD6C4 \uC11C\uBC84 \uC7AC\uC2DC\uC791 \uD544\uC694"
            : "\u26A0 LLM \uBAA8\uB378\uC774 \uC124\uC815\uB418\uC9C0 \uC54A\uC558\uC2B5\uB2C8\uB2E4";
          html = `<div class="llm-result-error llm-result-no-provider">
            <span>${msg}</span>
            <button class="btn-open-llm-config" onclick="document.getElementById('btnLlmConfig').click()">LLM CONFIG \u2192</button>
            <span class="llm-result-hint">\uBAA8\uB378\uACFC API \uD0A4\uB97C \uC124\uC815\uD558\uBA74 \uADFC\uBCF8 \uC6D0\uC778 \uBD84\uC11D\uC744 \uC218\uD589\uD560 \uC218 \uC788\uC2B5\uB2C8\uB2E4</span>
          </div>`;
        } else if (isAuthError) {
          html = `<div class="llm-result-error llm-result-no-provider">
            <span>\u26A0 API \uD0A4\uAC00 \uC720\uD6A8\uD558\uC9C0 \uC54A\uC2B5\uB2C8\uB2E4</span>
            <button class="btn-open-llm-config" onclick="document.getElementById('btnLlmConfig').click()">LLM CONFIG\uC5D0\uC11C API \uD0A4 \uC7AC\uC124\uC815 \u2192</button>
            <span class="llm-result-hint">API \uD0A4\uB97C \uC785\uB825\uD558\uACE0 SAVE \uBC84\uD2BC\uC744 \uB20C\uB7EC\uC8FC\uC138\uC694. \uD0A4\uB294 \uC11C\uBC84 \uBA54\uBAA8\uB9AC\uC5D0\uB9CC \uBCF4\uAD00\uB429\uB2C8\uB2E4.</span>
          </div>`;
        } else {
          html = `<div class="llm-result-error">\u274C Error: ${escapeHtml(data.error)}</div>`;
        }
      } else {
        if (data.analysis) {
          html += `<div class="llm-result-summary">${escapeHtml(data.analysis)}</div>`;
        }
        if (data.root_causes && data.root_causes.length) {
          html += '<div class="llm-result-section"><h4>\uD83D\uDD0D \uADFC\uBCF8 \uC6D0\uC778</h4><ul>';
          data.root_causes.forEach(c => { html += `<li>${escapeHtml(c)}</li>`; });
          html += "</ul></div>";
        }
        if (data.fix_suggestions && data.fix_suggestions.length) {
          html += '<div class="llm-result-section"><h4>\uD83D\uDEE0 \uC218\uC815 \uBC29\uC548</h4><ol>';
          data.fix_suggestions.forEach(s => {
            const text = typeof s === "string" ? s : (s.action || JSON.stringify(s));
            html += `<li>${escapeHtml(text)}</li>`;
          });
          html += "</ol></div>";
        }
        if (data.evidence && typeof data.evidence === "object" && Object.keys(data.evidence).length > 0) {
          html += '<div class="llm-result-section"><h4>\uD83D\uDCCB \uBD84\uC11D \uADFC\uAC70</h4><div class="llm-result-evidence">';
          for (const [k, v] of Object.entries(data.evidence)) {
            html += `<div><span style="color:var(--text-muted)">${escapeHtml(k)}:</span> ${escapeHtml(String(v))}</div>`;
          }
          html += "</div></div>";
        } else if (data.evidence && typeof data.evidence === "string") {
          html += `<div class="llm-result-section"><h4>\uD83D\uDCCB \uBD84\uC11D \uADFC\uAC70</h4><div class="llm-result-evidence">${escapeHtml(data.evidence)}</div></div>`;
        }
        if (data.model) {
          html += `<div class="llm-result-meta">Model: ${escapeHtml(data.model)} | Cost: $${(data.cost_usd||0).toFixed(4)}</div>`;
        }
      }
      return html;
    }

    // Store latest analysis per checker for re-display when modal re-opens
    const _llmAnalysisCache = {};

    function showLLMAnalysis(data) {
      const html = _buildLLMAnalysisHTML(data);

      // Cache analysis result for this checker
      if (data.checker) _llmAnalysisCache[data.checker] = data;

      // Show result inside the modal (primary display location)
      const modal = document.getElementById("phaseModal");
      const backdrop = document.getElementById("modalBackdrop");
      const modalOpen = backdrop && backdrop.classList.contains("open");
      const modalPhase = modal ? modal.getAttribute("data-phase") : "";

      if (modalOpen && modalPhase === data.checker) {
        _injectLLMResultInModal(modal, html);
      }
      // If modal is not open for this checker, result is cached and
      // will be shown when the user opens that checker's modal
    }

    function _injectLLMResultInModal(modal, html) {
      let resultDiv = modal.querySelector(".llm-modal-result");
      if (!resultDiv) {
        resultDiv = document.createElement("div");
        resultDiv.className = "llm-modal-result";
        const checksDiv = modal.querySelector(".modal-checks");
        if (checksDiv) {
          checksDiv.parentNode.insertBefore(resultDiv, checksDiv);
        } else {
          modal.appendChild(resultDiv);
        }
      }
      resultDiv.innerHTML = '<div class="llm-modal-result-header">\uD83D\uDCA1 LLM \uBD84\uC11D \uACB0\uACFC</div>' + html;
      resultDiv.scrollIntoView({behavior: "smooth", block: "nearest"});
    }

    // Connect SSE — GPT Review #3C: supports Last-Event-ID reconnection + dedupe
    function connectSSE() {
      if (eventSource) { eventSource.close(); }
      // Use native EventSource — it auto-sends Last-Event-ID on reconnect
      eventSource = new EventSource("/api/agent/events");
      eventSource.onmessage = function(e) {
        try {
          const event = JSON.parse(e.data);
          if (event.type === "heartbeat") return;

          // GPT Review #5-3 + #6-3 + #7-5: SSE gap detection — precise wording
          if (event.type === "_gap") {
            const d = event.data || {};
            // GPT Review #7-5: precise gap wording — "N개 이벤트 미수신" instead of vague "누락"
            let gapMsg;
            if (d.dropped_count > 0) {
              gapMsg = `SSE 재연결: ${d.replayed || "?"}개 복구, ${d.dropped_count}개 이벤트 미수신 (ID ${d.from_id}~${d.to_id})`;
            } else {
              gapMsg = `SSE 재연결: ${d.replayed || "?"}개 복구. 전체 이력은 History에서 확인하세요.`;
            }
            addLogEntry({ type: "_gap", data: { message: gapMsg }, timestamp: new Date().toISOString(), source: "system" });
            // GPT Review #7-2: show gap notification with priority stacking
            showNotificationBanner("gap", gapMsg, 15000);
            return;
          }

          // GPT Review #3C: dedupe — skip if we've seen this event ID
          if (e.lastEventId) {
            _lastEventId = e.lastEventId;
            if (_seenEventIds.has(e.lastEventId)) return;
            _seenEventIds.add(e.lastEventId);
            // Prune old IDs to prevent memory leak
            if (_seenEventIds.size > MAX_SEEN_IDS) {
              const iter = _seenEventIds.values();
              for (let i = 0; i < MAX_SEEN_IDS / 2; i++) {
                _seenEventIds.delete(iter.next().value);
              }
            }
          }

          // Update state display
          if (event.type === "agent_state_changed" && event.data) {
            updateStateDisplay(event.data.new || "observing");
          }

          // Show LLM analysis
          if (event.type === "llm_analysis_completed") {
            showLLMAnalysis(event.data);
          }

          // Update scan results on dashboard
          if (event.type === "scan_completed" && event.data && !event.data.skipped) {
            const reports = event.data.reports || {};
            for (const [name, report] of Object.entries(reports)) {
              updateCard(name, report);
            }
            // Update status banner
            const d = event.data;
            document.getElementById("statusValue").textContent = d.overall;
            document.getElementById("statPass").querySelector(".stat-num").textContent = d.total_pass;
            document.getElementById("statWarn").querySelector(".stat-num").textContent = d.total_warn;
            document.getElementById("statFail").querySelector(".stat-num").textContent = d.total_fail;
          }

          addLogEntry(event);
        } catch (err) { /* ignore parse errors */ }
      };
      eventSource.onerror = function() {
        // Auto-reconnect after 3s — EventSource auto-sends Last-Event-ID
        eventSource.close();
        setTimeout(connectSSE, 3000);
      };
    }

    // GPT Review #7-2: notification banner stacking system
    // Priority order: watcher_down (permanent) > budget (permanent) > gap (15s) > purge (30s)
    const _activeBanners = new Map();  // type → { el, timer, priority }
    const _bannerPriority = { watcher_down: 0, budget: 1, gap: 2, purge: 3 };
    const bannerContainer = document.getElementById("agentNotificationArea");

    function showNotificationBanner(type, message, duration) {
      // Remove existing banner of same type
      dismissBanner(type);

      const priority = _bannerPriority[type] ?? 99;
      const el = document.createElement("div");
      el.className = `agent-notification agent-notification-${type}`;
      el.setAttribute("data-priority", priority);
      el.innerHTML = `
        <span class="notif-msg">${escapeHtml(message)}</span>
        <button class="notif-dismiss" title="Dismiss">&times;</button>
      `;
      el.querySelector(".notif-dismiss").addEventListener("click", () => dismissBanner(type));

      let timer = null;
      if (duration > 0) {
        timer = setTimeout(() => dismissBanner(type), duration);
      }
      _activeBanners.set(type, { el, timer, priority });

      // Insert in priority order
      if (bannerContainer) {
        const existing = Array.from(bannerContainer.children);
        let inserted = false;
        for (const child of existing) {
          const childP = parseInt(child.getAttribute("data-priority") || "99");
          if (priority < childP) {
            bannerContainer.insertBefore(el, child);
            inserted = true;
            break;
          }
        }
        if (!inserted) bannerContainer.appendChild(el);
      }
    }

    function dismissBanner(type) {
      const banner = _activeBanners.get(type);
      if (banner) {
        if (banner.timer) clearTimeout(banner.timer);
        if (banner.el.parentNode) banner.el.parentNode.removeChild(banner.el);
        _activeBanners.delete(type);
      }
    }

    // GPT Review #7-3: budget display update helper — uses notification stacking
    function updateBudgetDisplay(budgetData) {
      if (budgetData.exceeded || budgetData.blocked) {
        showNotificationBanner("budget", "\u26A0 LLM budget exceeded — analysis blocked until reset", 0);
      } else if (budgetData.usage_pct >= 80) {
        showNotificationBanner("budget",
          `\u26A0 LLM budget ${budgetData.usage_pct.toFixed(0)}% used ($${(budgetData.spent||0).toFixed(2)}/$${(budgetData.limit||0).toFixed(2)})`, 0);
      } else {
        dismissBanner("budget");
      }
    }

    // Fetch LLM cost
    async function updateLLMCost() {
      try {
        const res = await fetch("/api/agent/cost" + _wsQueryParam());
        const json = await res.json();
        if (json.success && json.data && json.data.enabled !== false) {
          if (llmBadge) {
            llmBadge.style.display = "flex";
            const costEl = document.getElementById("llmCostBadge");
            if (costEl) costEl.textContent = `$${(json.data.total_usd || 0).toFixed(2)}`;
          }
          // GPT Review #7-3: update budget status
          if (json.data.budget) {
            updateBudgetDisplay(json.data.budget);
          }
        }
      } catch (e) { /* ignore */ }
    }

    // Button handlers
    if (toggleBtn) {
      toggleBtn.addEventListener("click", async () => {
        const endpoint = agentRunning ? "/api/agent/stop" : "/api/agent/start";
        try {
          const res = await fetch(endpoint, {method: "POST"});
          const json = await res.json();
          if (json.state) updateStateDisplay(json.state);
        } catch (e) { console.error("Agent toggle error:", e); }
      });
    }

    if (scanBtn) {
      // GPT Review #7-4: preserve button width during rate-limit text swap
      const _scanBtnOrigText = scanBtn.textContent;

      scanBtn.addEventListener("click", async () => {
        try {
          const res = await fetch("/api/agent/scan" + _wsQueryParam(), {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({})
          });
          const json = await res.json();
          // GPT Review #6 UI + #7-4: show rate-limit feedback with stable width
          if (json.rate_limited) {
            const wait = Math.ceil(json.retry_after || 2);
            scanBtn.classList.add("rate-limited");
            scanBtn.textContent = `${wait}s`;
            scanBtn.disabled = true;
            // Countdown timer for precise feedback
            let remaining = wait;
            const timer = setInterval(() => {
              remaining--;
              if (remaining > 0) {
                scanBtn.textContent = `${remaining}s`;
              } else {
                clearInterval(timer);
                scanBtn.textContent = _scanBtnOrigText;
                scanBtn.disabled = false;
                scanBtn.classList.remove("rate-limited");
              }
            }, 1000);
          }
        } catch (e) { console.error("Agent scan error:", e); }
      });
    }

    if (llmClose) {
      llmClose.addEventListener("click", () => {
        if (llmPanel) llmPanel.style.display = "none";
      });
    }

    // GPT Review #6 UI: Observer/watchdog status polling
    const observerBadge = document.getElementById("agentObserverBadge");
    const observerIcon = document.getElementById("observerIcon");
    const observerLabel = document.getElementById("observerLabel");

    async function updateObserverStatus() {
      try {
        const res = await fetch("/api/agent/status" + _wsQueryParam());
        const json = await res.json();
        if (!json.success || !json.enabled) return;
        const running = json.observer_running;
        if (running) {
          _observerFailCount = 0;  // reset on success
          if (observerBadge) {
            observerBadge.setAttribute("data-status", "alive");
            if (observerIcon) observerIcon.textContent = "\uD83D\uDC41";
            if (observerLabel) observerLabel.textContent = "Watching";
          }
          dismissBanner("watcher_down");
        } else {
          // GPT Review #7-1: require consecutive failures before showing DOWN
          _observerFailCount++;
          if (_observerFailCount >= OBSERVER_DOWN_THRESHOLD) {
            if (observerBadge) {
              observerBadge.setAttribute("data-status", "dead");
              if (observerIcon) observerIcon.textContent = "\u26A0";
              if (observerLabel) observerLabel.textContent = "Watcher DOWN";
            }
            showNotificationBanner("watcher_down", "\u26A0 File watcher is not running — auto-scan disabled", 0);
          }
        }
        // GPT Review #7-3: update LLM budget display from status response
        if (json.llm_budget) {
          updateBudgetDisplay(json.llm_budget);
        }
      } catch (e) {
        // Network failure also counts as observer fail
        _observerFailCount++;
        if (_observerFailCount >= OBSERVER_DOWN_THRESHOLD) {
          if (observerBadge) {
            observerBadge.setAttribute("data-status", "dead");
            if (observerIcon) observerIcon.textContent = "\u26A0";
            if (observerLabel) observerLabel.textContent = "Watcher DOWN";
          }
          showNotificationBanner("watcher_down", "\u26A0 Agent unreachable — check server status", 0);
        }
      }
    }

    // GPT Review #7-6: workspace-scoped polling helper
    function _wsQueryParam() {
      const wsSel = document.getElementById("workspaceSelect");
      const wsId = wsSel ? wsSel.value : "";
      return wsId ? "?workspace_id=" + encodeURIComponent(wsId) : "";
    }

    // GPT Review #7-2: purge notification now handled by stacking system (showNotificationBanner)

    // Initial state
    updateStateDisplay(window.__DD_AGENT_STATE || "disabled");
    connectSSE();
    updateLLMCost();
    updateObserverStatus();
    // Refresh cost + observer status every 60s
    setInterval(updateLLMCost, 60000);
    setInterval(updateObserverStatus, 30000);
  }

  // ══════════════════════════════════════════════════════
  // LLM CONFIGURATION MODAL
  // ══════════════════════════════════════════════════════

  function initLlmConfig() {
    if (!window.__DD_AGENT_ENABLED) return;

    const backdrop = document.getElementById("llmConfigBackdrop");
    const modal    = document.getElementById("llmConfigModal");
    const closeBtn = document.getElementById("llmConfigClose");
    const openBtn  = document.getElementById("btnLlmConfig");
    const saveBtn  = document.getElementById("btnLlmSave");
    const clearBtn = document.getElementById("btnLlmClear");
    const statusEl = document.getElementById("llmConfigStatus");

    // Input refs
    const fModel    = document.getElementById("llmModel");
    const fFallback = document.getElementById("llmFallback");
    const fApiKey   = document.getElementById("llmApiKey");
    const fKeyToggle = document.getElementById("llmKeyToggle");
    const fKeyStatus = document.getElementById("llmKeyStatus");
    const fTemp     = document.getElementById("llmTemperature");
    const fMaxTok   = document.getElementById("llmMaxTokens");
    const fTimeout  = document.getElementById("llmTimeout");
    const fBudget   = document.getElementById("llmBudget");

    if (!backdrop || !modal || !openBtn) return;

    function _wsQueryParam() {
      const wsSel = document.getElementById("workspaceSelect");
      const wsId = wsSel ? wsSel.value : "";
      return wsId ? "?workspace_id=" + encodeURIComponent(wsId) : "";
    }

    // Show/hide API key toggle
    if (fKeyToggle && fApiKey) {
      fKeyToggle.addEventListener("click", () => {
        const isPassword = fApiKey.type === "password";
        fApiKey.type = isPassword ? "text" : "password";
        fKeyToggle.textContent = isPassword ? "\u2715" : "\uD83D\uDC41";
        fKeyToggle.title = isPassword ? "Hide API key" : "Show API key";
      });
    }

    // Open modal
    openBtn.addEventListener("click", async () => {
      backdrop.classList.add("open");
      statusEl.textContent = "";
      statusEl.className = "llm-status";
      await loadLlmConfig();
    });

    // Close modal
    function closeModal() {
      backdrop.classList.remove("open");
      // Always hide key on close
      if (fApiKey) fApiKey.type = "password";
      if (fKeyToggle) { fKeyToggle.textContent = "\uD83D\uDC41"; fKeyToggle.title = "Show API key"; }
    }
    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeModal();
    });

    // Load current config + key status
    async function loadLlmConfig() {
      try {
        const res = await fetch("/api/config/llm" + _wsQueryParam());
        const json = await res.json();
        if (json.success && json.data) {
          const d = json.data;
          fModel.value    = d.model || "";
          fFallback.value = d.fallback_model || "";
          fTemp.value     = d.temperature ?? 0.3;
          fMaxTok.value   = d.max_tokens ?? 2000;
          fTimeout.value  = d.timeout_seconds ?? 30;
          fBudget.value   = d.daily_budget_usd ?? 5.0;
          updatePresetHighlight(d.model || "");

          // Show key status
          if (fApiKey) fApiKey.value = "";  // never pre-fill actual key
          if (fKeyStatus && json.key_status) {
            const ks = json.key_status;
            if (ks.has_key) {
              const src = ks.source === "ui" ? "UI\uc5d0\uc11c \uc124\uc815\ub428" : "\ud658\uacbd\ubcc0\uc218\uc5d0\uc11c \ub85c\ub4dc\ub428";
              fKeyStatus.innerHTML = `<span class="llm-key-ok">\u2713 ${ks.masked}</span> <span class="llm-key-src">(${src})</span>`;
            } else if (d.model && !d.model.startsWith("ollama/")) {
              fKeyStatus.innerHTML = '<span class="llm-key-warn">\u26A0 API \ud0a4\uac00 \uc124\uc815\ub418\uc9c0 \uc54a\uc74c \u2014 SAVE \ud6c4 \uc801\uc6a9\ub429\ub2c8\ub2e4</span>';
            } else {
              fKeyStatus.textContent = "";
            }
          }

          // Show LLM readiness status
          if (json.llm_ready) {
            const lr = json.llm_ready;
            let readyHTML = "";
            if (!lr.litellm_installed) {
              readyHTML = '<span class="llm-key-warn">\u26A0 litellm \ubbf8\uc124\uce58 \u2014 <code>pip install litellm</code> \uc2e4\ud589 \ud6c4 \uc11c\ubc84 \uc7ac\uc2dc\uc791 \ud544\uc694</span>';
            } else if (lr.model && !lr.agent_llm_active) {
              const ks = json.key_status;
              if (!ks.has_key && !lr.model.startsWith("ollama/")) {
                readyHTML = '<span class="llm-key-warn">\u26A0 API \ud0a4\ub97c \uc785\ub825\ud558\uace0 SAVE \ubc84\ud2bc\uc744 \ub20c\ub7ec\uc8fc\uc138\uc694</span>';
              } else {
                readyHTML = '<span class="llm-key-warn">\u26A0 LLM provider \ucd08\uae30\ud654 \uc2e4\ud328 \u2014 \ubaa8\ub378\uba85 \ud655\uc778 \ud544\uc694</span>';
              }
            } else if (lr.agent_llm_active) {
              readyHTML = '<span class="llm-key-ok">\u2713 LLM \ud65c\uc131 \u2014 DEEP ANALYZE \uc0ac\uc6a9 \uac00\ub2a5</span>';
            }
            statusEl.innerHTML = readyHTML;
            statusEl.className = "llm-status";
          }
        }
      } catch (e) {
        statusEl.textContent = "Failed to load config";
        statusEl.className = "llm-status llm-status-error";
      }
    }

    // Preset buttons
    document.querySelectorAll(".llm-preset").forEach(btn => {
      btn.addEventListener("click", () => {
        const model = btn.dataset.model;
        fModel.value = model;
        updatePresetHighlight(model);
        // Focus API key field if cloud model selected (not ollama)
        if (fApiKey && !model.startsWith("ollama/")) {
          fApiKey.placeholder = _placeholderForModel(model);
          fApiKey.focus();
        }
      });
    });

    function _placeholderForModel(model) {
      if (model.startsWith("anthropic/")) return "sk-ant-...";
      if (model.startsWith("openai/"))    return "sk-...";
      if (model.startsWith("gemini/"))    return "AIza...";
      if (model.startsWith("deepseek/"))  return "sk-...";
      return "API key";
    }

    function updatePresetHighlight(model) {
      document.querySelectorAll(".llm-preset").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.model === model);
      });
    }

    fModel.addEventListener("input", () => updatePresetHighlight(fModel.value));

    // Save config
    saveBtn.addEventListener("click", async () => {
      saveBtn.disabled = true;
      saveBtn.textContent = "SAVING...";
      statusEl.textContent = "";
      statusEl.className = "llm-status";

      const payload = {
        model: fModel.value.trim(),
        fallback_model: fFallback.value.trim(),
        temperature: parseFloat(fTemp.value) || 0.3,
        max_tokens: parseInt(fMaxTok.value) || 2000,
        timeout_seconds: parseInt(fTimeout.value) || 30,
        daily_budget_usd: parseFloat(fBudget.value) || 5.0,
      };
      // Include API key only if user typed something
      const keyVal = fApiKey ? fApiKey.value.trim() : "";
      if (keyVal) {
        payload.api_key = keyVal;
      }

      try {
        const res = await fetch("/api/config/llm" + _wsQueryParam(), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const json = await res.json();

        if (json.success) {
          let msg = "\u2713 Saved";
          if (json.key_status) {
            if (json.key_status.startsWith("key_set:")) {
              msg += ` · Key → ${json.key_status.replace("key_set:", "")}`;
            } else if (json.key_status === "key_cleared") {
              msg += " · Key cleared";
            }
          }
          if (json.llm_status) {
            if (json.llm_status.startsWith("active:")) {
              msg += ` · LLM active: ${json.llm_status.replace("active:", "")}`;
            } else if (json.llm_status === "disabled") {
              msg += " · LLM disabled";
            } else if (json.llm_status === "litellm_not_installed") {
              msg += " · \u26A0 litellm not installed (pip install litellm)";
            } else if (json.llm_status.startsWith("reload_error:")) {
              msg += ` · \u26A0 ${json.llm_status}`;
            }
          }
          if (json.warning) msg += ` | ${json.warning}`;
          statusEl.textContent = msg;
          statusEl.className = "llm-status llm-status-ok";

          // Clear key field after save and refresh status
          if (fApiKey) fApiKey.value = "";
          await loadLlmConfig();
        } else {
          const errMsg = json.errors ? json.errors.join(", ") : (json.error || "Unknown error");
          statusEl.textContent = "\u2717 " + errMsg;
          statusEl.className = "llm-status llm-status-error";
        }
      } catch (e) {
        statusEl.textContent = "\u2717 Network error";
        statusEl.className = "llm-status llm-status-error";
      }

      saveBtn.disabled = false;
      saveBtn.textContent = "SAVE & APPLY";
    });

    // Clear / disable LLM
    clearBtn.addEventListener("click", async () => {
      fModel.value = "";
      fFallback.value = "";
      if (fApiKey) fApiKey.value = "";
      updatePresetHighlight("");
      saveBtn.click();
    });
  }

  // ══════════════════════════════════════════════════════
  // AGENT TIMELINE — unified event/scan/analysis view
  // ══════════════════════════════════════════════════════

  function initTimeline() {
    if (!window.__DD_AGENT_ENABLED) return;

    const section = document.getElementById("agentTimelineSection");
    const list = document.getElementById("timelineList");
    const filterType = document.getElementById("timelineFilterType");
    const filterSeverity = document.getElementById("timelineFilterSeverity");
    const refreshBtn = document.getElementById("btnTimelineRefresh");
    const moreBtn = document.getElementById("btnTimelineMore");

    if (!section || !list) return;
    section.style.display = "";

    let _timelineOffset = 0;
    const PAGE_SIZE = 30;
    let _allEvents = [];

    function _wsParam() {
      const wsSel = document.getElementById("workspaceSelect");
      const wsId = wsSel ? wsSel.value : "";
      return wsId ? "&workspace_id=" + encodeURIComponent(wsId) : "";
    }

    async function loadTimeline(append) {
      if (!append) {
        _timelineOffset = 0;
        _allEvents = [];
        list.innerHTML = '<div class="timeline-empty">Loading...</div>';
      }
      try {
        // Fetch events from agent history
        const res = await fetch(`/api/agent/history?limit=${PAGE_SIZE}&since_id=${_timelineOffset}${_wsParam()}`);
        const json = await res.json();
        if (!json.success) return;

        const events = (json.data || []).map(evt => {
          let data = {};
          try { data = JSON.parse(evt.data_json || "{}"); } catch(e) {}
          return {
            id: evt.id,
            type: evt.event_type || "unknown",
            timestamp: evt.timestamp,
            source: evt.source || "",
            workspace_id: evt.workspace_id || "",
            data: data,
          };
        });

        if (!append) list.innerHTML = "";
        _allEvents = append ? _allEvents.concat(events) : events;

        if (events.length > 0) {
          _timelineOffset = events[0].id;  // newest id for pagination
        }

        renderTimeline();

        // Show/hide "Load More"
        if (moreBtn) {
          moreBtn.style.display = events.length >= PAGE_SIZE ? "" : "none";
        }

        if (_allEvents.length === 0) {
          list.innerHTML = '<div class="timeline-empty">No agent events yet. Start a scan or enable file watching.</div>';
        }
      } catch (e) {
        console.error("loadTimeline:", e);
        if (!append) list.innerHTML = '<div class="timeline-empty">Failed to load timeline</div>';
      }
    }

    function renderTimeline() {
      const typeFilter = filterType ? filterType.value : "all";
      const sevFilter = filterSeverity ? filterSeverity.value : "all";

      list.innerHTML = "";
      const filtered = _allEvents.filter(evt => {
        if (typeFilter !== "all" && evt.type !== typeFilter) return false;
        if (sevFilter !== "all") {
          const d = evt.data || {};
          // Map severity from various event types
          let sev = "info";
          if (evt.type === "scan_completed") {
            sev = d.has_critical ? "critical" : (d.total_fail > 0 ? "high" : "info");
          } else if (evt.type === "insight_generated") {
            const insights = d.insights || [];
            const maxSev = insights.reduce((acc, i) => {
              if (i.severity === "critical") return "critical";
              if (i.severity === "high" && acc !== "critical") return "high";
              return acc;
            }, "info");
            sev = maxSev;
          } else if (evt.type === "llm_analysis_completed") {
            sev = d.error ? "high" : "info";
          }
          if (sevFilter !== sev) return false;
        }
        return true;
      });

      if (filtered.length === 0) {
        list.innerHTML = '<div class="timeline-empty">No events match the current filter.</div>';
        return;
      }

      filtered.forEach(evt => {
        const el = document.createElement("div");
        el.className = `timeline-item timeline-${evt.type.replace(/_/g, "-")}`;

        const d = evt.data || {};
        const ts = new Date(evt.timestamp);
        const timeStr = ts.toLocaleTimeString("en", {hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit"});
        const dateStr = ts.toLocaleDateString("en", {month: "short", day: "numeric"});

        // Icon per type
        const icons = {
          file_changed: "\uD83D\uDCC4",
          scan_completed: d.skipped ? "\u23ED" : (d.has_critical ? "\uD83D\uDED1" : "\u2705"),
          scan_requested: "\uD83D\uDD0D",
          insight_generated: "\uD83D\uDCA1",
          llm_analysis_completed: d.error ? "\u274C" : "\uD83E\uDDE0",
          agent_state_changed: "\u2699\uFE0F",
        };
        const icon = icons[evt.type] || "\u2022";

        // Summary per type
        let summary = "";
        switch (evt.type) {
          case "file_changed":
            summary = `${d.file_count || 0} file(s) changed \u2192 [${(d.affected_checkers||[]).join(", ")}]`;
            break;
          case "scan_completed":
            if (d.skipped) { summary = "Scan skipped (already in progress)"; }
            else { summary = `${d.overall || "?"} \u2014 P:${d.total_pass} W:${d.total_warn} F:${d.total_fail} (${d.health_pct || 0}%) in ${(d.duration_ms||0)}ms`; }
            break;
          case "scan_requested":
            summary = d.checkers ? `Manual scan: [${d.checkers.join(", ")}]` : "Full scan requested";
            break;
          case "insight_generated":
            if (d.purge) { summary = `Data purge: ${d.total_deleted} rows cleaned`; }
            else { summary = (d.insights || []).map(i => i.message).join("; ") || "Insight"; }
            break;
          case "llm_analysis_completed":
            if (d.error) { summary = `Analysis error: ${d.error}`; }
            else { summary = `${d.checker} analyzed (${d.model || "?"}, $${(d.cost_usd||0).toFixed(4)})`; }
            break;
          case "agent_state_changed":
            summary = `State: ${d.old || "?"} \u2192 ${d.new || "?"}`;
            if (d.error) summary = `Error: ${d.error}`;
            break;
          default:
            summary = evt.type;
        }

        // Severity badge
        let sevBadge = "";
        if (evt.type === "scan_completed" && !d.skipped) {
          const cls = d.has_critical ? "critical" : (d.total_fail > 0 ? "high" : "ok");
          const label = d.overall || "?";
          sevBadge = `<span class="timeline-sev timeline-sev-${cls}">${label}</span>`;
        }
        if (evt.type === "insight_generated" && d.insights) {
          const crits = d.insights.filter(i => i.severity === "critical").length;
          if (crits > 0) sevBadge = `<span class="timeline-sev timeline-sev-critical">${crits} CRITICAL</span>`;
        }

        el.innerHTML = `
          <div class="timeline-dot">${icon}</div>
          <div class="timeline-body">
            <div class="timeline-head">
              <span class="timeline-time">${dateStr} ${timeStr}</span>
              <span class="timeline-type">${evt.type.replace(/_/g, " ").toUpperCase()}</span>
              ${sevBadge}
            </div>
            <div class="timeline-summary">${escapeHtml(summary)}</div>
          </div>
        `;
        list.appendChild(el);
      });
    }

    // Event listeners
    if (filterType) filterType.addEventListener("change", renderTimeline);
    if (filterSeverity) filterSeverity.addEventListener("change", renderTimeline);
    if (refreshBtn) refreshBtn.addEventListener("click", () => loadTimeline(false));
    if (moreBtn) moreBtn.addEventListener("click", () => loadTimeline(true));

    // Initial load
    loadTimeline(false);
  }

  // Add "DEEP ANALYZE" button to phase detail modal (patch openModal)
  const _origOpenModal = typeof openModal === "function" ? openModal : null;
  function patchModalForAgent() {
    if (!window.__DD_AGENT_ENABLED) return;
    // Watch for modal open to inject analyze button
    const observer = new MutationObserver(() => {
      const modal = document.getElementById("phaseModal");
      if (!modal || modal.style.display === "none") return;
      const header = modal.querySelector(".modal-header");
      if (!header || header.querySelector(".btn-deep-analyze")) return;
      // Get phase name from modal title
      const titleEl = header.querySelector(".modal-title");
      if (!titleEl) return;

      const btn = document.createElement("button");
      btn.className = "btn-deep-analyze";
      btn.textContent = "DEEP ANALYZE";
      btn.title = "LLM root cause analysis";
      btn.addEventListener("click", async () => {
        // Extract phase name from card data
        const phaseName = modal.getAttribute("data-phase") || "";
        if (!phaseName) return;
        btn.textContent = "ANALYZING...";
        btn.disabled = true;
        try {
          await fetch("/api/agent/analyze", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({checker: phaseName})
          });
        } catch (e) { console.error(e); }
        setTimeout(() => { btn.textContent = "DEEP ANALYZE"; btn.disabled = false; }, 3000);
      });
      header.insertBefore(btn, header.querySelector(".modal-close"));
    });
    const backdrop = document.getElementById("modalBackdrop");
    if (backdrop) {
      observer.observe(backdrop, {attributes: true, attributeFilter: ["class", "style"]});
    }
  }

  // ══════════════════════════════════════════════════════════
  // AGENT MONITOR — Main service session monitoring
  // ══════════════════════════════════════════════════════════

  function initMonitor() {
    if (!window.__DD_MONITOR_ENABLED) return;

    const panel = document.getElementById("monitorPanel");
    if (!panel) return;

    // DOM refs
    const dotSvc = document.getElementById("monDotService");
    const dotDB  = document.getElementById("monDotDB");
    const dotSSE = document.getElementById("monDotSSE");
    const sessionList = document.getElementById("monSessionList");
    const detailView  = document.getElementById("monDetail");
    const btnRefresh  = document.getElementById("btnMonitorRefresh");
    const btnMore     = document.getElementById("btnMonitorMore");
    const btnBack     = document.getElementById("monBack");
    const filterStatus = document.getElementById("monFilterStatus");
    const filterModel  = document.getElementById("monFilterModel");

    let nextCursor = null;
    let pollTimer = null;
    let currentDetailId = null;

    // ── Status Check ──
    async function checkStatus() {
      try {
        const resp = await fetch("/api/monitor/status");
        const s = await resp.json();
        _setDot(dotSvc, s.service_online);
        _setDot(dotDB,  s.db_readable);
        _setDot(dotSSE, s.sse_available);
      } catch(e) {
        _setDot(dotSvc, false);
        _setDot(dotDB, false);
        _setDot(dotSSE, false);
      }
    }

    function _setDot(el, online) {
      if (!el) return;
      el.classList.toggle("online", !!online);
      el.classList.toggle("offline", !online);
    }

    // ── Stats ──
    async function loadStats() {
      try {
        const [budgetResp, todayResp] = await Promise.all([
          fetch("/api/monitor/budget"),
          fetch("/api/monitor/stats"),
        ]);
        const budget = await budgetResp.json();
        const today  = await todayResp.json();

        _setText("monStatTotal", _fmtNum(budget.total_sessions || 0));
        _setText("monStatCost", (budget.total_cost || 0).toFixed(2));
        _setText("monStatToday", today.sessions_today || 0);
        _setText("monStatRate", today.success_rate || 0);
      } catch(e) { /* ignore */ }
    }

    function _setText(id, val) {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    }
    function _fmtNum(n) { return n >= 1000 ? (n/1000).toFixed(1) + "K" : n; }

    // ── Load Sessions ──
    async function loadSessions(append) {
      const status = filterStatus ? filterStatus.value : "all";
      const model  = filterModel ? filterModel.value : "all";
      let url = `/api/monitor/sessions?limit=20&status=${status}&model=${model}`;
      if (append && nextCursor) url += `&cursor=${encodeURIComponent(nextCursor)}`;

      try {
        const resp = await fetch(url);
        const data = await resp.json();

        if (!append) sessionList.innerHTML = "";

        if (!data.sessions || data.sessions.length === 0) {
          if (!append) {
            sessionList.innerHTML = '<div class="monitor-loading">No sessions found</div>';
          }
          btnMore.style.display = "none";
          return;
        }

        for (const s of data.sessions) {
          sessionList.appendChild(_renderCard(s));
        }

        nextCursor = data.next_cursor;
        btnMore.style.display = nextCursor ? "block" : "none";
      } catch(e) {
        if (!append) {
          sessionList.innerHTML = '<div class="monitor-loading">Failed to load sessions</div>';
        }
      }
    }

    // ── Render Session Card ──
    function _renderCard(s) {
      const div = document.createElement("div");
      div.className = `monitor-card ${s.status || ""}`;
      div.setAttribute("data-session-id", s.session_id);

      const title = s.video_title || s.video_id || "Unknown";
      const model = s.model_name || "";
      const cost  = "$" + (s.cost || 0).toFixed(4);
      const dur   = (s.duration_sec || 0).toFixed(1) + "s";
      const calls = s.tool_calls || 0;
      const time  = _fmtTime(s.created_at);

      div.innerHTML = `
        <div class="monitor-card-main">
          <div class="monitor-card-title">${escapeHtml(title)}</div>
          <div class="monitor-card-info">
            <span>${escapeHtml(model)}</span>
            <span>${calls} calls</span>
            <span>${dur}</span>
            <span>${time}</span>
          </div>
        </div>
        <span class="monitor-card-cost">${cost}</span>
        <span class="monitor-card-badge ${s.status || ""}">${(s.status || "?").toUpperCase()}</span>
      `;

      div.addEventListener("click", () => showDetail(s.session_id));
      return div;
    }

    function _fmtTime(iso) {
      if (!iso) return "";
      try {
        const d = new Date(iso);
        const hh = String(d.getHours()).padStart(2, "0");
        const mm = String(d.getMinutes()).padStart(2, "0");
        const MM = String(d.getMonth()+1).padStart(2, "0");
        const DD = String(d.getDate()).padStart(2, "0");
        return `${MM}/${DD} ${hh}:${mm}`;
      } catch(e) { return iso; }
    }

    // ── Session Detail ──
    async function showDetail(sessionId) {
      currentDetailId = sessionId;
      sessionList.style.display = "none";
      btnMore.style.display = "none";
      detailView.style.display = "block";

      // Loading
      document.getElementById("monDetailTitle").textContent = "Loading...";
      document.getElementById("monTimeline").innerHTML = "";

      try {
        const resp = await fetch(`/api/monitor/sessions/${sessionId}`);
        const d = await resp.json();
        if (d.error) {
          document.getElementById("monDetailTitle").textContent = "Error: " + d.error;
          return;
        }

        // Title + badge
        const titleEl = document.getElementById("monDetailTitle");
        titleEl.textContent = d.video_title || d.video_id || sessionId;

        const badge = document.getElementById("monDetailBadge");
        badge.textContent = (d.status || "?").toUpperCase();
        badge.className = `monitor-detail-badge monitor-card-badge ${d.status || ""}`;

        // Meta info
        const meta = document.getElementById("monDetailMeta");
        meta.innerHTML = `
          <span>Model: ${escapeHtml(d.model_name || "?")}</span>
          <span>Provider: ${escapeHtml(d.provider || "?")}</span>
          <span>Cost: $${(d.cost || 0).toFixed(4)}</span>
          <span>Duration: ${(d.duration_sec || 0).toFixed(1)}s</span>
          <span>Tokens: ${_fmtNum(d.total_tokens || 0)}</span>
          <span>${_fmtTime(d.created_at)}</span>
        `;

        // Budget bars
        _updateBudgetBar("budgetToolFill", "budgetToolVal",
          d.tool_calls || 0, d.max_tool_calls || 25,
          `${d.tool_calls || 0}/${d.max_tool_calls || 25}`);

        _updateBudgetBar("budgetTokenFill", "budgetTokenVal",
          d.total_tokens || 0, d.max_tokens || 50000,
          `${_fmtNum(d.total_tokens || 0)}/${_fmtNum(d.max_tokens || 50000)}`);

        _updateBudgetBar("budgetCostFill", "budgetCostVal",
          d.cost || 0, d.max_cost || 0.3,
          `$${(d.cost || 0).toFixed(4)}/$${(d.max_cost || 0.3).toFixed(2)}`);

        _updateBudgetBar("budgetDurFill", "budgetDurVal",
          d.duration_sec || 0, d.max_duration_sec || 120,
          `${(d.duration_sec || 0).toFixed(0)}s/${d.max_duration_sec || 120}s`);

        // Timeline (tool invocations)
        _renderTimeline(d.invocations || []);

      } catch(e) {
        document.getElementById("monDetailTitle").textContent = "Failed to load session";
      }
    }

    function _updateBudgetBar(fillId, valId, current, max, label) {
      const fill = document.getElementById(fillId);
      const val  = document.getElementById(valId);
      if (!fill || !val) return;

      const pct = max > 0 ? Math.min(current / max * 100, 100) : 0;
      fill.style.width = pct + "%";
      fill.className = "budget-fill" + (pct >= 80 ? " danger" : pct >= 50 ? " warn" : "");
      val.textContent = label;
    }

    function _renderTimeline(invocations) {
      const tl = document.getElementById("monTimeline");
      tl.innerHTML = "";

      if (invocations.length === 0) {
        tl.innerHTML = '<div class="monitor-loading">No tool invocations recorded</div>';
        return;
      }

      for (const inv of invocations) {
        const step = document.createElement("div");
        step.className = `monitor-step ${inv.status || ""}`;

        const dur = inv.duration_ms ? (inv.duration_ms / 1000).toFixed(1) + "s" : "?";
        const tokens = (inv.tokens_in || 0) + (inv.tokens_out || 0);
        const cost = inv.cost ? "$" + inv.cost.toFixed(4) : "";

        step.innerHTML = `
          <span class="monitor-step-num">#${inv.iteration || "?"}</span>
          <span class="monitor-step-tool">${escapeHtml(inv.tool_name || "?")}</span>
          <div class="monitor-step-info">
            <span>${inv.status === "success" ? "\u2713" : inv.status === "error" ? "\u2717" : "\u23F3"}</span>
            <span>${dur}</span>
            ${tokens > 0 ? `<span>${_fmtNum(tokens)} tok</span>` : ""}
            ${cost ? `<span>${cost}</span>` : ""}
            <button class="monitor-step-toggle" data-inv-id="${inv.id}">Show</button>
          </div>
          <div class="monitor-step-detail" id="inv-detail-${inv.id}">
            <div><strong>Input:</strong> ${escapeHtml((inv.input_summary || "N/A").substring(0, 500))}</div>
            <div style="margin-top:4px"><strong>Output:</strong> ${escapeHtml((inv.output_summary || "N/A").substring(0, 500))}</div>
          </div>
        `;

        // Toggle detail (collapsed by default — GPT Review #8)
        const toggleBtn = step.querySelector(".monitor-step-toggle");
        if (toggleBtn) {
          toggleBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            const detEl = document.getElementById(`inv-detail-${inv.id}`);
            if (detEl) {
              detEl.classList.toggle("open");
              toggleBtn.textContent = detEl.classList.contains("open") ? "Hide" : "Show";
            }
          });
        }

        tl.appendChild(step);
      }
    }

    function hideDetail() {
      detailView.style.display = "none";
      sessionList.style.display = "";
      currentDetailId = null;
      if (nextCursor) btnMore.style.display = "block";
    }

    // ── Load Model Filter Options ──
    async function loadModelFilter() {
      try {
        const resp = await fetch("/api/monitor/models");
        const data = await resp.json();
        if (data.available_models && filterModel) {
          for (const m of data.available_models) {
            const opt = document.createElement("option");
            opt.value = m;
            opt.textContent = m;
            filterModel.appendChild(opt);
          }
        }
      } catch(e) { /* ignore */ }
    }

    // ── Polling (incremental — GPT Review #9) ──
    function startPolling() {
      pollTimer = setInterval(async () => {
        await checkStatus();
        // Only refresh list if not in detail view
        if (!currentDetailId) {
          await loadStats();
          // Incremental: only refresh top of list (not full reload)
          // For simplicity, reload latest 20 sessions
          nextCursor = null;
          await loadSessions(false);
        }
      }, 3000);
    }

    // ── Event Listeners ──
    if (btnRefresh) btnRefresh.addEventListener("click", () => {
      nextCursor = null;
      loadSessions(false);
      loadStats();
      checkStatus();
    });

    if (btnMore) btnMore.addEventListener("click", () => loadSessions(true));
    if (btnBack) btnBack.addEventListener("click", hideDetail);

    if (filterStatus) filterStatus.addEventListener("change", () => {
      nextCursor = null;
      loadSessions(false);
    });
    if (filterModel) filterModel.addEventListener("change", () => {
      nextCursor = null;
      loadSessions(false);
    });

    // ── Init ──
    checkStatus();
    loadStats();
    loadSessions(false);
    loadModelFilter();
    startPolling();
  }

  // ── Live Feed ──
  function initLiveFeed() {
    if (!window.__DD_MONITOR_ENABLED) return;

    const feed = document.getElementById('liveFeed');
    if (!feed) return;

    let eventSource = null;
    let elapsedTimer = null;
    let startTime = null;

    function connect() {
      if (eventSource) {
        try { eventSource.close(); } catch(e) {}
      }

      eventSource = new EventSource('/api/monitor/live');

      eventSource.onmessage = function(e) {
        try {
          const data = JSON.parse(e.data);

          if (data.type === 'connected') {
            if (data.is_processing) {
              showLiveFeed(data);
            }
            return;
          }

          if (data.type === 'processing_detected') {
            showProcessingStart(data);
          }

          if (data.type === 'live_progress') {
            showLiveFeed(data);
            updateProgress(data);
            updateStepTimeline(data);
          }

          if (data.type === 'live_complete') {
            showCompletion(data);
            setTimeout(function() {
              hideLiveFeed();
              // Refresh session list to show the new completed session
              const btnRefresh = document.getElementById('btnMonitorRefresh');
              if (btnRefresh) btnRefresh.click();
            }, 5000);
          }
        } catch(err) {
          // ignore parse errors
        }
      };

      eventSource.onerror = function() {
        eventSource.close();
        setTimeout(connect, 3000);
      };
    }

    function showProcessingStart(data) {
      feed.style.display = 'block';
      feed.className = 'live-feed';
      document.getElementById('liveTitle').textContent = data.title || data.video_id || '';
      document.getElementById('liveProgressFill').style.width = '0%';
      document.getElementById('liveProgressPct').textContent = '0%';
      document.getElementById('liveStepCurrent').textContent = 'Processing detected...';
      document.getElementById('liveTimeline').innerHTML = '';
      startTime = Date.now();
      startElapsedTimer();
    }

    function showLiveFeed(data) {
      feed.style.display = 'block';
      document.getElementById('liveTitle').textContent = data.title || data.video_id || '';
      if (!startTime) {
        startTime = Date.now();
        startElapsedTimer();
      }
    }

    function updateProgress(data) {
      var pct = 0;
      if (data.sections_total && data.sections_total > 0) {
        pct = Math.round((data.sections_done || 0) / data.sections_total * 100);
      } else if (data.total && data.total > 0) {
        pct = Math.round((data.step || 0) / data.total * 100);
      }

      var fill = document.getElementById('liveProgressFill');
      fill.style.width = pct + '%';
      fill.className = 'live-progress-fill';
      document.getElementById('liveProgressPct').textContent = pct + '%';

      var msg = data.message || '';
      document.getElementById('liveStepCurrent').textContent = msg;
    }

    function updateStepTimeline(data) {
      if (!data.step) return;

      var timeline = document.getElementById('liveTimeline');
      var stepNum = data.step;
      var stepEl = timeline.querySelector('[data-step="' + stepNum + '"]');

      if (!stepEl) {
        stepEl = document.createElement('div');
        stepEl.className = 'live-step fade-in';
        stepEl.dataset.step = stepNum;
        timeline.appendChild(stepEl);
      }

      var msg = data.message || '';
      var icon = '\u23F3';  // hourglass default
      if (msg.indexOf('\u2705') >= 0) { icon = '\u2705'; }       // checkmark
      else if (msg.indexOf('\u26A0') >= 0) { icon = '\u26A0\uFE0F'; }  // warning
      else if (msg.indexOf('\u274C') >= 0) { icon = '\u274C'; }  // x mark

      stepEl.innerHTML =
        '<span class="live-step-icon">' + icon + '</span>' +
        '<span class="live-step-num">Step ' + stepNum + '/' + (data.total || '?') + '</span>' +
        '<span class="live-step-msg">' + escapeHtml(msg) + '</span>';

      if (msg.indexOf('\u2705') >= 0) {
        stepEl.classList.add('completed');
      }
    }

    function showCompletion(data) {
      var fill = document.getElementById('liveProgressFill');
      fill.style.width = '100%';
      fill.className = 'live-progress-fill ' + (data.success ? 'success' : 'failed');
      document.getElementById('liveProgressPct').textContent = '100%';
      document.getElementById('liveStepCurrent').textContent =
        data.success ? '\u2705 Processing complete!' : '\u274C Processing failed';
      stopElapsedTimer();
    }

    function hideLiveFeed() {
      feed.style.display = 'none';
      document.getElementById('liveTimeline').innerHTML = '';
      document.getElementById('liveProgressFill').style.width = '0%';
      document.getElementById('liveProgressFill').className = 'live-progress-fill';
      document.getElementById('liveProgressPct').textContent = '0%';
      document.getElementById('liveStepCurrent').textContent = '';
      startTime = null;
      stopElapsedTimer();
    }

    function startElapsedTimer() {
      stopElapsedTimer();
      elapsedTimer = setInterval(function() {
        if (!startTime) return;
        var secs = Math.floor((Date.now() - startTime) / 1000);
        var mm = String(Math.floor(secs / 60)).padStart(2, '0');
        var ss = String(secs % 60).padStart(2, '0');
        document.getElementById('liveElapsed').textContent = mm + ':' + ss;
      }, 1000);
    }

    function stopElapsedTimer() {
      if (elapsedTimer) {
        clearInterval(elapsedTimer);
        elapsedTimer = null;
      }
    }

    // Check if something is already processing on page load
    fetch('/api/monitor/live/status')
      .then(function(r) { return r.json(); })
      .then(function(d) {
        if (d.is_processing) {
          showLiveFeed(d);
        }
      })
      .catch(function() {});

    connect();
  }

  // ── Section Fold/Collapse Toggle ──────────────────────────────
  // Each collapsible section stores its fold state in localStorage.
  // Keys: dd_fold_<section-key> = "1" (collapsed) or absent (expanded)

  function initSectionFold() {
    var STORAGE_PREFIX = "dd_fold_";

    // Restore saved fold states
    document.querySelectorAll(".collapsible-section[data-fold-key]").forEach(function(section) {
      var key = section.getAttribute("data-fold-key");
      if (!key) return;
      var saved = localStorage.getItem(STORAGE_PREFIX + key);
      if (saved === "1") {
        applyFold(section, key, true, false);
      }
    });

    // Click handler: toggle buttons
    document.querySelectorAll("[data-fold-btn]").forEach(function(btn) {
      btn.addEventListener("click", function(e) {
        e.stopPropagation();
        var key = btn.getAttribute("data-fold-btn");
        var section = document.querySelector('[data-fold-key="' + key + '"]');
        if (!section) return;
        var isCollapsed = section.classList.contains("is-collapsed");
        applyFold(section, key, !isCollapsed, true);
      });
    });

    // Click handler: section headers (click anywhere on header to toggle)
    document.querySelectorAll(".collapsible-section .section-header").forEach(function(header) {
      header.addEventListener("click", function(e) {
        // Don't toggle if clicking on controls/selects/buttons inside the header
        if (e.target.closest("select, .timeline-controls, .monitor-controls, .agent-controls, .btn-agent, .btn-monitor, .btn-llm-config, .agent-llm-badge, .agent-observer-badge")) return;
        // Don't double-fire if the toggle button itself was clicked
        if (e.target.closest("[data-fold-btn]")) return;

        var section = header.closest(".collapsible-section");
        if (!section) return;
        var key = section.getAttribute("data-fold-key");
        if (!key) return;
        var isCollapsed = section.classList.contains("is-collapsed");
        applyFold(section, key, !isCollapsed, true);
      });
    });

    // Also let agent-header clicks toggle (agent-header is not .section-header)
    document.querySelectorAll(".collapsible-section .agent-header").forEach(function(header) {
      header.addEventListener("click", function(e) {
        if (e.target.closest("button, select, .agent-controls, .agent-llm-badge, .agent-observer-badge, .btn-llm-config, .btn-agent")) return;
        if (e.target.closest("[data-fold-btn]")) return;
        var section = header.closest(".collapsible-section");
        if (!section) return;
        var key = section.getAttribute("data-fold-key");
        if (!key) return;
        var isCollapsed = section.classList.contains("is-collapsed");
        applyFold(section, key, !isCollapsed, true);
      });
    });

    // Also let monitor-header clicks toggle
    document.querySelectorAll(".collapsible-section .monitor-header").forEach(function(header) {
      header.addEventListener("click", function(e) {
        if (e.target.closest("button, select, .monitor-controls, .monitor-status-dots, .btn-monitor")) return;
        if (e.target.closest("[data-fold-btn]")) return;
        var section = header.closest(".collapsible-section");
        if (!section) return;
        var key = section.getAttribute("data-fold-key");
        if (!key) return;
        var isCollapsed = section.classList.contains("is-collapsed");
        applyFold(section, key, !isCollapsed, true);
      });
    });
  }

  function applyFold(section, key, collapse, save) {
    var STORAGE_PREFIX = "dd_fold_";
    var btn = section.querySelector("[data-fold-btn]");
    var body = section.querySelector("[data-fold-body]");

    if (collapse) {
      section.classList.add("is-collapsed");
      if (btn) btn.classList.add("collapsed");
      if (body) body.classList.add("collapsed");
    } else {
      section.classList.remove("is-collapsed");
      if (btn) btn.classList.remove("collapsed");
      if (body) body.classList.remove("collapsed");
    }

    if (save) {
      if (collapse) {
        localStorage.setItem(STORAGE_PREFIX + key, "1");
      } else {
        localStorage.removeItem(STORAGE_PREFIX + key);
      }
    }
  }

  // ── Architecture Diagram ──────────────────────────────────────
  function initArchitecture() {
    const wsName = (window.__DD_WS_NAME || "").toLowerCase();
    if (!wsName) return;

    // Find matching architecture
    let archData = null;
    for (const [key, data] of Object.entries(ARCH_REGISTRY)) {
      if (wsName.includes(key.toLowerCase())) { archData = data; break; }
    }
    if (!archData) return;

    const section = document.getElementById("archSection");
    if (!section) return;
    section.style.display = "";

    // Set titles
    const titleEl = document.getElementById("archTitleDetail");
    if (titleEl) titleEl.textContent = archData.title;
    const subEl = document.getElementById("archSubtitle");
    if (subEl) subEl.textContent = archData.subtitle;

    // Build SVG
    const container = document.getElementById("archContainer");
    if (!container) return;
    const result = _buildArchSVG(archData, container);

    // Create tooltip
    _createArchTooltip();

    // Start particle animation
    _startArchParticles(archData, result);

    // Render legend
    _renderArchLegend(archData);
  }

  // ── SVG Constants ──
  const _ARCH = {
    SVG_W: 800, NODE_W: 140, NODE_H: 44,
    COL_GAP: 180, ROW_GAP: 80,
    MARGIN_X: 100, MARGIN_Y: 50,
    NS: "http://www.w3.org/2000/svg",
  };

  function _archNodePos(node) {
    const cx = _ARCH.SVG_W / 2 + node.col * _ARCH.COL_GAP;
    const cy = _ARCH.MARGIN_Y + node.row * _ARCH.ROW_GAP;
    return { x: cx - _ARCH.NODE_W / 2, y: cy - _ARCH.NODE_H / 2, cx, cy };
  }

  function _buildArchSVG(archData, container) {
    const NS = _ARCH.NS;
    const maxRow = Math.max(...archData.nodes.map(n => n.row));
    const svgH = _ARCH.MARGIN_Y * 2 + maxRow * _ARCH.ROW_GAP + _ARCH.NODE_H;

    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + _ARCH.SVG_W + " " + svgH);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");

    // Defs: arrowhead marker + glow filter
    const defs = document.createElementNS(NS, "defs");

    const marker = document.createElementNS(NS, "marker");
    marker.setAttribute("id", "archArrow");
    marker.setAttribute("viewBox", "0 0 10 10");
    marker.setAttribute("refX", "9"); marker.setAttribute("refY", "5");
    marker.setAttribute("markerWidth", "6"); marker.setAttribute("markerHeight", "6");
    marker.setAttribute("orient", "auto-start-reverse");
    const arrow = document.createElementNS(NS, "path");
    arrow.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
    arrow.setAttribute("class", "arch-arrow");
    marker.appendChild(arrow);
    defs.appendChild(marker);

    // Glow filter for nodes
    const filter = document.createElementNS(NS, "filter");
    filter.setAttribute("id", "archGlow");
    filter.setAttribute("x", "-20%"); filter.setAttribute("y", "-20%");
    filter.setAttribute("width", "140%"); filter.setAttribute("height", "140%");
    const blur = document.createElementNS(NS, "feGaussianBlur");
    blur.setAttribute("stdDeviation", "3"); blur.setAttribute("result", "glow");
    filter.appendChild(blur);
    const merge = document.createElementNS(NS, "feMerge");
    const mn1 = document.createElementNS(NS, "feMergeNode");
    mn1.setAttribute("in", "glow");
    const mn2 = document.createElementNS(NS, "feMergeNode");
    mn2.setAttribute("in", "SourceGraphic");
    merge.appendChild(mn1); merge.appendChild(mn2);
    filter.appendChild(merge);
    defs.appendChild(filter);

    svg.appendChild(defs);

    // Calculate positions
    const positions = {};
    archData.nodes.forEach(n => { positions[n.id] = _archNodePos(n); });

    // ── Edges (behind nodes) ──
    const edgesG = document.createElementNS(NS, "g");
    archData.edges.forEach(edge => {
      const fp = positions[edge.from], tp = positions[edge.to];
      if (!fp || !tp) return;
      const pathEl = _createEdgePath(fp, tp, edge);
      edgesG.appendChild(pathEl);

      // Edge label
      if (edge.label) {
        const lbl = document.createElementNS(NS, "text");
        const mx = (fp.cx + tp.cx) / 2, my = (fp.cy + tp.cy) / 2;
        // Offset label slightly for readability
        const offX = fp.cx === tp.cx ? 10 : 0;
        const offY = fp.cx === tp.cx ? 0 : -8;
        lbl.setAttribute("x", mx + offX);
        lbl.setAttribute("y", my + offY);
        lbl.setAttribute("text-anchor", "middle");
        lbl.setAttribute("class", "arch-edge-label");
        lbl.textContent = edge.label;
        edgesG.appendChild(lbl);
      }
    });
    svg.appendChild(edgesG);

    // ── Nodes ──
    const nodesG = document.createElementNS(NS, "g");
    archData.nodes.forEach(node => {
      const pos = positions[node.id];
      const g = document.createElementNS(NS, "g");
      g.setAttribute("class", "arch-node arch-node-" + node.type);
      g.setAttribute("transform", "translate(" + pos.x + "," + pos.y + ")");

      // Rectangle
      const rect = document.createElementNS(NS, "rect");
      rect.setAttribute("width", _ARCH.NODE_W);
      rect.setAttribute("height", _ARCH.NODE_H);
      g.appendChild(rect);

      // Label (centered in node)
      const text = document.createElementNS(NS, "text");
      text.setAttribute("x", _ARCH.NODE_W / 2);
      text.setAttribute("y", _ARCH.NODE_H / 2 + 5);
      text.setAttribute("text-anchor", "middle");
      text.textContent = node.label;
      g.appendChild(text);

      // Hover events
      g.addEventListener("mouseenter", (e) => _showArchTip(node, e));
      g.addEventListener("mousemove", (e) => _moveArchTip(e));
      g.addEventListener("mouseleave", _hideArchTip);

      nodesG.appendChild(g);
    });
    svg.appendChild(nodesG);

    // ── Particle layer ──
    const particleG = document.createElementNS(NS, "g");
    particleG.setAttribute("id", "archParticles");
    svg.appendChild(particleG);

    container.innerHTML = "";
    container.appendChild(svg);

    return { svg, positions, edgesG };
  }

  function _createEdgePath(fp, tp, edge) {
    const NS = _ARCH.NS;
    let x1, y1, x2, y2;
    const NW = _ARCH.NODE_W, NH = _ARCH.NODE_H;

    if (fp.cy < tp.cy) {
      // Downward flow
      x1 = fp.cx; y1 = fp.cy + NH / 2;
      x2 = tp.cx; y2 = tp.cy - NH / 2;
    } else if (fp.cy > tp.cy) {
      // Upward (feedback) — use right side
      x1 = fp.cx + NW / 2 + 5; y1 = fp.cy;
      x2 = tp.cx + NW / 2 + 5; y2 = tp.cy;
    } else {
      // Same row — horizontal
      if (fp.cx < tp.cx) {
        x1 = fp.cx + NW / 2; y1 = fp.cy;
        x2 = tp.cx - NW / 2; y2 = tp.cy;
      } else {
        x1 = fp.cx - NW / 2; y1 = fp.cy;
        x2 = tp.cx + NW / 2; y2 = tp.cy;
      }
    }

    // Bezier control points
    let d;
    if (fp.cy === tp.cy) {
      // Horizontal: straight line
      d = "M " + x1 + " " + y1 + " L " + x2 + " " + y2;
    } else if (fp.cy > tp.cy) {
      // Upward: curve outward to the right
      const bulge = 40;
      d = "M " + x1 + " " + y1 +
          " C " + (x1 + bulge) + " " + y1 + "," +
                  (x2 + bulge) + " " + y2 + "," +
                  x2 + " " + y2;
    } else {
      // Downward: smooth vertical bezier
      const midY = (y1 + y2) / 2;
      d = "M " + x1 + " " + y1 +
          " C " + x1 + " " + midY + "," +
                  x2 + " " + midY + "," +
                  x2 + " " + y2;
    }

    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", d);
    path.setAttribute("class", "arch-edge" + (edge.dashed ? " dashed" : ""));
    path.setAttribute("marker-end", "url(#archArrow)");
    path.dataset.from = edge.from;
    path.dataset.to = edge.to;
    return path;
  }

  // ── Particles ──
  function _startArchParticles(archData, result) {
    const NS = _ARCH.NS;
    const particleG = document.getElementById("archParticles");
    if (!particleG) return;

    const particles = [];
    const paths = result.edgesG.querySelectorAll(".arch-edge");

    paths.forEach(path => {
      let totalLen;
      try { totalLen = path.getTotalLength(); } catch (e) { return; }
      if (totalLen < 1) return;

      const fromId = path.dataset.from || "";
      const srcNode = archData.nodes.find(n => n.id === fromId);
      const colorCls = srcNode ? ("arch-particle-" + srcNode.type) : "arch-particle-default";

      for (let p = 0; p < 2; p++) {
        const circle = document.createElementNS(NS, "circle");
        circle.setAttribute("class", "arch-particle " + colorCls);
        circle.setAttribute("r", "3");
        particleG.appendChild(circle);

        particles.push({
          el: circle, path: path,
          totalLen: totalLen,
          speed: 0.004 + Math.random() * 0.002,
          progress: p * 0.5,
        });
      }
    });

    if (particles.length === 0) return;

    let animId = null;
    let paused = false;

    function animate() {
      particles.forEach(p => {
        p.progress += p.speed;
        if (p.progress > 1) p.progress -= 1;
        try {
          const pt = p.path.getPointAtLength(p.progress * p.totalLen);
          p.el.setAttribute("cx", pt.x);
          p.el.setAttribute("cy", pt.y);
          // Fade at endpoints
          const fade = Math.min(p.progress * 4, (1 - p.progress) * 4, 1);
          p.el.setAttribute("opacity", String(Math.max(0, fade * 0.8)));
        } catch (e) { /* path not ready */ }
      });
      animId = requestAnimationFrame(animate);
    }

    function startAnim() { if (!animId && !paused) { animate(); } }
    function stopAnim()  { if (animId) { cancelAnimationFrame(animId); animId = null; } }

    startAnim();

    // Pause when section collapsed
    const sectionBody = document.querySelector('[data-fold-body="arch"]');
    if (sectionBody) {
      const obs = new MutationObserver(() => {
        if (sectionBody.classList.contains("collapsed")) { stopAnim(); }
        else { startAnim(); }
      });
      obs.observe(sectionBody, { attributes: true, attributeFilter: ["class"] });
    }

    // Pause when tab hidden
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { paused = true; stopAnim(); }
      else { paused = false; startAnim(); }
    });
  }

  // ── Tooltip ──
  function _createArchTooltip() {
    const container = document.getElementById("archContainer");
    if (!container) return;
    const tip = document.createElement("div");
    tip.className = "arch-tooltip";
    tip.id = "archTooltip";
    tip.innerHTML = '<div class="arch-tooltip-label"></div>' +
                    '<div class="arch-tooltip-type"></div>' +
                    '<div class="arch-tooltip-role"></div>';
    container.appendChild(tip);
  }

  const _ARCH_TYPE_KR = {
    controller: "\uCEE8\uD2B8\uB864\uB7EC", planner: "\uD50C\uB798\uB108",
    validator: "\uAC80\uC99D\uAE30", executor: "\uC2E4\uD589\uAE30",
    tool: "\uB3C4\uAD6C", guard: "\uAC10\uC2DC",
  };
  function _showArchTip(node, e) {
    const tip = document.getElementById("archTooltip");
    if (!tip) return;
    tip.querySelector(".arch-tooltip-label").textContent = node.label;
    const typeKr = _ARCH_TYPE_KR[node.type] || node.type;
    tip.querySelector(".arch-tooltip-type").textContent = typeKr + " (" + node.type + ")";
    tip.querySelector(".arch-tooltip-role").textContent = node.role;
    tip.classList.add("visible");
    _moveArchTip(e);
  }
  function _moveArchTip(e) {
    const tip = document.getElementById("archTooltip");
    if (!tip) return;
    const container = document.getElementById("archContainer");
    if (!container) return;
    const rect = container.getBoundingClientRect();
    let x = e.clientX - rect.left + 15;
    let y = e.clientY - rect.top - 10;
    if (x + 280 > rect.width) x = Math.max(0, rect.width - 290);
    if (y < 0) y = 10;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  function _hideArchTip() {
    const tip = document.getElementById("archTooltip");
    if (tip) tip.classList.remove("visible");
  }

  // ── Legend ──
  function _renderArchLegend(archData) {
    const legend = document.getElementById("archLegend");
    if (!legend) return;
    const types = {
      controller: { label: "\uCEE8\uD2B8\uB864\uB7EC", color: "#06b6d4" },
      planner:    { label: "\uD50C\uB798\uB108",       color: "#a855f7" },
      validator:  { label: "\uAC80\uC99D\uAE30",       color: "#f59e0b" },
      executor:   { label: "\uC2E4\uD589\uAE30",       color: "#22c55e" },
      tool:       { label: "\uB3C4\uAD6C",             color: "#6366f1" },
      guard:      { label: "\uAC10\uC2DC",             color: "#ef4444" },
    };
    const used = new Set(archData.nodes.map(n => n.type));
    let html = "";
    for (const [type, info] of Object.entries(types)) {
      if (!used.has(type)) continue;
      html += '<span class="arch-legend-item">' +
              '<span class="arch-legend-dot" style="background:' + info.color + '20;border-color:' + info.color + '"></span>' +
              info.label + '</span>';
    }
    html += '<span class="arch-legend-item">' +
            '<span class="arch-legend-dot" style="background:#06b6d4;border:none;border-radius:50%;width:6px;height:6px"></span>' +
            '\uB370\uC774\uD130 \uD750\uB984</span>';
    legend.innerHTML = html;
  }

  // ── Start ──
  init();
  initAgent();
  initLlmConfig();
  patchModalForAgent();
  initTimeline();
  initMonitor();
  initLiveFeed();
  initArchitecture();
  initSectionFold();
})();
