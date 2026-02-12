"""Agent API routes — Flask Blueprint for agent control and monitoring.

Endpoints:
    GET  /api/agent/status    — Agent state + metadata
    POST /api/agent/start     — Start agent loop
    POST /api/agent/stop      — Stop agent loop
    POST /api/agent/scan      — Queue manual scan (optional checker list)
    POST /api/agent/analyze   — Queue LLM deep analysis for a checker
    GET  /api/agent/events    — SSE stream of real-time agent events
    GET  /api/agent/history   — Agent event history from DB
    GET  /api/agent/analyses  — LLM analysis history from DB
    GET  /api/agent/cost      — LLM cost summary

GPT Review hardening:
  #3C: SSE Last-Event-ID + incremental event IDs for reconnection
  #3D: workspace_id is always resolved (cookie → first available, never empty)
"""
import json
import itertools
from queue import Empty
from flask import Blueprint, jsonify, request, Response

agent_bp = Blueprint("agent", __name__)

# Set by app.py when agent mode is active (per-workspace)
_agent_loops = {}   # workspace_id → AgentLoop

# GPT Review #3C: monotonic event ID counter for SSE reconnection.
# GPT Review #6-4: this counter is GLOBAL (not per-workspace).
# Since it's a single monotonic sequence, JS dedupe with a bounded set
# of event IDs works without needing workspace_id:event_id composite keys.
_sse_event_counter = itertools.count(1)


def init_agent_blueprint(workspace_id: str, agent_loop):
    """Register an AgentLoop for a workspace."""
    _agent_loops[workspace_id] = agent_loop


def _get_loop():
    """Get the AgentLoop for the current workspace (from cookie or default)."""
    ws_id = request.args.get("workspace_id", "")
    if not ws_id:
        ws_id = request.cookies.get("dd_workspace", "")
    if ws_id and ws_id in _agent_loops:
        return _agent_loops[ws_id], ws_id
    # Return first available
    if _agent_loops:
        ws_id = next(iter(_agent_loops))
        return _agent_loops[ws_id], ws_id
    return None, ""


@agent_bp.route("/api/agent/status")
def agent_status():
    loop, ws_id = _get_loop()
    if not loop:
        return jsonify({
            "success": True,
            "enabled": False,
            "state": "disabled",
            "workspace_id": "",
        })
    status = loop.get_status()
    status["success"] = True
    status["enabled"] = True
    return jsonify(status)


@agent_bp.route("/api/agent/start", methods=["POST"])
def agent_start():
    loop, ws_id = _get_loop()
    if not loop:
        return jsonify({"success": False, "error": "Agent not configured"}), 400
    ok = loop.start()
    return jsonify({
        "success": ok,
        "state": loop.state.value,
        "message": "Started" if ok else "Already running or lock conflict",
    })


@agent_bp.route("/api/agent/stop", methods=["POST"])
def agent_stop():
    loop, ws_id = _get_loop()
    if not loop:
        return jsonify({"success": False, "error": "Agent not configured"}), 400
    loop.stop()
    return jsonify({"success": True, "state": loop.state.value})


@agent_bp.route("/api/agent/scan", methods=["POST"])
def agent_scan():
    """Trigger agent scan (specific checkers or all).

    GPT Review #5-5: reports rate-limit status to UI so the user knows
    when their scan was throttled vs actually queued.
    """
    loop, ws_id = _get_loop()
    if not loop:
        return jsonify({"success": False, "error": "Agent not configured"}), 400
    data = request.get_json(silent=True) or {}
    checker_names = data.get("checkers", None)

    # GPT Review #5-5: check rate-limit before queuing.
    # GPT Review #6-5: rate-limit scope is PER-WORKSPACE (each AgentLoop has its own
    # Reasoner with its own _last_manual_scan). Multiple users on the same workspace
    # share the same rate-limit, but different workspaces are independent.
    # The API sets _last_manual_scan eagerly so consecutive rapid API calls
    # are caught even before the background loop processes the event.
    from datetime import datetime as _dt
    reasoner = loop.reasoner
    if reasoner._last_manual_scan:
        elapsed = (_dt.now() - reasoner._last_manual_scan).total_seconds()
        min_interval = reasoner._manual_min_interval
        if elapsed < min_interval:
            remaining = round(min_interval - elapsed, 1)
            return jsonify({
                "success": True,
                "rate_limited": True,
                "retry_after": remaining,
                "message": f"{remaining}초 후 다시 시도하세요",
            })

    # Eagerly mark scan time so immediate re-calls are rate-limited at API level
    reasoner._last_manual_scan = _dt.now()
    loop.request_scan(checker_names)
    return jsonify({"success": True, "message": "Scan queued"})


@agent_bp.route("/api/agent/analyze", methods=["POST"])
def agent_analyze():
    """Trigger LLM deep analysis for a checker."""
    loop, ws_id = _get_loop()
    if not loop:
        return jsonify({"success": False, "error": "Agent not configured"}), 400
    data = request.get_json(silent=True) or {}
    checker = data.get("checker", "")
    if not checker:
        return jsonify({"success": False, "error": "checker is required"}), 400
    loop.request_analysis(checker)
    return jsonify({"success": True, "message": f"Analysis queued for {checker}"})


@agent_bp.route("/api/agent/events")
def agent_events_sse():
    """SSE stream of real-time agent events.

    GPT Review #3C — SSE hardening:
      - Each event has a monotonic `id:` field
      - Client can reconnect with Last-Event-ID header
      - Missed events during disconnection are fetched from storage (since_id)

    Supports:
      ?workspace_id=xxx    — filter by workspace
      Last-Event-ID header — resume from last received event
    """
    loop, ws_id = _get_loop()
    if not loop:
        return jsonify({"success": False, "error": "Agent not configured"}), 400

    # GPT Review #3C: support Last-Event-ID for reconnection
    last_event_id = request.headers.get("Last-Event-ID", "")

    client_queue = loop.register_sse_client()

    def generate():
        # If reconnecting, send missed events from storage first
        if last_event_id:
            try:
                from . import storage as st
                # GPT Review #4-3: configurable replay limit
                replay_limit = loop.config.get("agent", {}).get("sse_replay_limit", 50)
                missed = st.get_agent_events(
                    workspace_id=ws_id,
                    since_id=int(last_event_id),
                    limit=replay_limit,
                )

                # GPT Review #5-3 + #6-3: detect gap — if we hit the replay limit,
                # there may be more events the client will never see.
                # Include range info (from_id, to_id, dropped_count) for debugging.
                total_missed = len(missed)
                if total_missed >= replay_limit:
                    # missed is DESC order: [newest, ..., oldest]
                    oldest_replayed_id = missed[-1].get("id", "?") if missed else "?"
                    newest_replayed_id = missed[0].get("id", "?") if missed else "?"
                    # Estimate: anything between last_event_id and oldest_replayed_id was lost
                    try:
                        dropped_estimate = int(oldest_replayed_id) - int(last_event_id) - 1
                    except (ValueError, TypeError):
                        dropped_estimate = -1  # unknown

                    eid = next(_sse_event_counter)
                    gap_data = {
                        "type": "_gap",
                        "data": {
                            "message": f"일부 이벤트가 누락되었습니다 ({replay_limit}개 이상). 전체 내역은 History에서 확인하세요.",
                            "replayed": replay_limit,
                            "last_event_id": last_event_id,
                            "from_id": last_event_id,
                            "to_id": str(oldest_replayed_id),
                            "dropped_count": max(dropped_estimate, 0),
                        },
                    }
                    yield f"id: {eid}\ndata: {json.dumps(gap_data, ensure_ascii=False, default=str)}\n\n"

                # Reverse to chronological order (storage returns DESC)
                for evt in reversed(missed):
                    eid = next(_sse_event_counter)
                    data = {
                        "type": evt.get("event_type", "unknown"),
                        "timestamp": evt.get("timestamp", ""),
                        "source": evt.get("source", ""),
                        "workspace_id": evt.get("workspace_id", ""),
                        "data": json.loads(evt.get("data_json", "{}")),
                        "_replay": True,
                    }
                    yield f"id: {eid}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
            except Exception:
                pass  # Best-effort replay

        try:
            while True:
                try:
                    event = client_queue.get(timeout=30)
                    eid = next(_sse_event_counter)
                    data = {
                        "type": event.type.value,
                        "timestamp": event.timestamp.isoformat(),
                        "source": event.source,
                        "workspace_id": event.workspace_id,
                        "data": event.data,
                    }
                    yield f"id: {eid}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
                except Empty:
                    # Heartbeat to keep connection alive
                    yield f": heartbeat\n\n"
        except GeneratorExit:
            pass
        finally:
            loop.unregister_sse_client(client_queue)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@agent_bp.route("/api/agent/history")
def agent_event_history():
    """Get recent agent events from storage.

    GPT Review #3D: workspace_id is always resolved — never returns cross-workspace data.
    """
    from . import storage as st
    limit = request.args.get("limit", 100, type=int)
    since_id = request.args.get("since_id", 0, type=int)
    # GPT Review #3D: always enforce workspace boundary
    _, resolved_ws_id = _get_loop()
    ws_id = request.args.get("workspace_id", "") or resolved_ws_id
    events = st.get_agent_events(limit=limit, workspace_id=ws_id, since_id=since_id)
    return jsonify({"success": True, "data": events, "workspace_id": ws_id})


@agent_bp.route("/api/agent/analyses")
def agent_analyses():
    """Get LLM analysis history.

    GPT Review #3D: workspace_id is always resolved — never returns cross-workspace data.
    """
    from . import storage as st
    limit = request.args.get("limit", 20, type=int)
    # GPT Review #3D: always enforce workspace boundary
    _, resolved_ws_id = _get_loop()
    ws_id = request.args.get("workspace_id", "") or resolved_ws_id
    analyses = st.get_llm_analyses(limit=limit, workspace_id=ws_id)
    return jsonify({"success": True, "data": analyses, "workspace_id": ws_id})


@agent_bp.route("/api/agent/cost")
def agent_cost():
    """Get LLM cost summary.

    GPT Review #7-3: includes budget status for UI budget-exceeded display.
    """
    loop, ws_id = _get_loop()
    if not loop or not loop.executor._llm:
        return jsonify({"success": True, "data": {"enabled": False}})
    summary = loop.executor._llm._cost_tracker.get_daily_summary()
    # GPT Review #7-3: add budget status for frontend
    budget_usd = summary.get("budget_usd", 0)
    spent_usd = summary.get("total_usd", 0)
    usage_pct = (spent_usd / budget_usd * 100) if budget_usd > 0 else 0
    summary["budget"] = {
        "limit": budget_usd,
        "spent": spent_usd,
        "usage_pct": round(usage_pct, 1),
        "exceeded": spent_usd >= budget_usd and budget_usd > 0,
        "blocked": not loop.executor._llm._cost_tracker.can_spend(0.001) if budget_usd > 0 else False,
    }
    return jsonify({"success": True, "data": summary})
