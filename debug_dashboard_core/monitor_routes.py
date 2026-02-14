"""Monitor API routes — Flask Blueprint for main service agent monitoring.

Per-workspace connector: each workspace with monitor.enabled: true has its own
MainServiceConnector. The connector is resolved at request time via the
dd_workspace cookie.

Endpoints:
    GET  /api/monitor/status           — 3-state connectivity (service, DB, SSE)
    GET  /api/monitor/sessions         — List sessions (keyset pagination)
    GET  /api/monitor/sessions/<id>    — Session detail + tool invocations
    GET  /api/monitor/sessions/<id>/events — SSE stream for live session
    GET  /api/monitor/budget           — Aggregate budget stats
    GET  /api/monitor/stats            — Today's summary
    GET  /api/monitor/models           — Model performance comparison
    GET  /api/monitor/live             — SSE stream for real-time processing events
    GET  /api/monitor/live/status      — Current active processing status (REST)
"""

import json
import time
from flask import Blueprint, current_app, jsonify, request, Response

monitor_bp = Blueprint("monitor", __name__)

# Reference to the Flask app (set by init_monitor_blueprint)
_app = None


def init_monitor_blueprint(app):
    """Initialize with the Flask app reference for per-workspace connector lookup."""
    global _app
    _app = app


def _get_connector():
    """Resolve the connector for the current workspace (cookie-based).

    Returns (connector, None) on success, or (None, error_response) on failure.
    """
    app = _app or current_app._get_current_object()
    connectors = app.config.get("MONITOR_CONNECTORS", {})

    # Resolve current workspace from cookie
    ws_id = request.cookies.get("dd_workspace")
    if not ws_id or ws_id not in app.config.get("WORKSPACES", {}):
        ws_id = app.config.get("DEFAULT_WORKSPACE", "")

    connector = connectors.get(ws_id)
    if connector is None:
        return None, (jsonify({
            "error": "Monitor not configured for this workspace",
            "workspace_id": ws_id,
        }), 503)

    return connector, None


# ── Status ────────────────────────────────────────────────────

@monitor_bp.route("/api/monitor/status")
def monitor_status():
    """3-state health: service_online, db_readable, sse_available."""
    connector, err = _get_connector()
    if err:
        return err
    return jsonify(connector.get_status())


# ── Sessions List ─────────────────────────────────────────────

@monitor_bp.route("/api/monitor/sessions")
def monitor_sessions():
    """List sessions with keyset pagination and optional filters.

    Query params:
        limit (int, default 20)
        cursor (str, created_at for keyset pagination)
        status (str, filter: completed/exceeded/error/cancelled)
        model (str, filter by model_name)
    """
    connector, err = _get_connector()
    if err:
        return err

    if not connector.db_reader:
        return jsonify({"error": "Database not available", "sessions": []}), 503

    limit = min(int(request.args.get("limit", 20)), 100)
    cursor = request.args.get("cursor")
    status = request.args.get("status")
    model = request.args.get("model")

    result = connector.db_reader.get_sessions(
        limit=limit, cursor=cursor, status=status, model=model
    )
    return jsonify(result)


# ── Session Detail ────────────────────────────────────────────

@monitor_bp.route("/api/monitor/sessions/<session_id>")
def monitor_session_detail(session_id):
    """Session detail + tool invocations (loaded on click only)."""
    connector, err = _get_connector()
    if err:
        return err

    if not connector.db_reader:
        return jsonify({"error": "Database not available"}), 503

    detail = connector.db_reader.get_session_detail(session_id)
    if not detail:
        return jsonify({"error": "Session not found"}), 404

    return jsonify(detail)


# ── Live SSE Stream ───────────────────────────────────────────

@monitor_bp.route("/api/monitor/sessions/<session_id>/events")
def monitor_session_events(session_id):
    """SSE stream relaying live events from main service.

    Connects to main service SSE via proxy (1:N broadcast).
    """
    connector, err = _get_connector()
    if err:
        return err

    if not connector.service_online:
        return jsonify({"error": "Main service is offline"}), 503

    # Get video_id for this session
    if connector.db_reader:
        detail = connector.db_reader.get_session_detail(session_id)
        video_id = detail.get("video_id") if detail else None
    else:
        video_id = None

    if not video_id:
        return jsonify({"error": "Cannot determine video_id for session"}), 404

    # Subscribe proxy to main service SSE (idempotent if already subscribed)
    connector.sse_proxy.subscribe(video_id)

    # Register this client
    client_q = connector.sse_proxy.register_client()

    def event_stream():
        try:
            # Send initial connection event
            yield f"data: {json.dumps({'type': 'connected', 'session_id': session_id, 'video_id': video_id})}\n\n"

            while True:
                try:
                    event = client_q.get(timeout=30)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except Exception:
                    # Heartbeat
                    yield f": heartbeat {int(time.time())}\n\n"
        except GeneratorExit:
            pass
        finally:
            connector.sse_proxy.unregister_client(client_q)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Budget Stats ──────────────────────────────────────────────

@monitor_bp.route("/api/monitor/budget")
def monitor_budget():
    """Aggregate budget statistics across all sessions."""
    connector, err = _get_connector()
    if err:
        return err

    if not connector.db_reader:
        return jsonify({"error": "Database not available"}), 503

    stats = connector.db_reader.get_budget_stats()
    return jsonify(stats)


# ── Today Stats ───────────────────────────────────────────────

@monitor_bp.route("/api/monitor/stats")
def monitor_stats():
    """Today's summary: sessions, cost, success rate."""
    connector, err = _get_connector()
    if err:
        return err

    if not connector.db_reader:
        return jsonify({"error": "Database not available"}), 503

    stats = connector.db_reader.get_stats_today()

    # Also check for running session
    running = connector.db_reader.detect_running_session()
    stats["running_session"] = running

    return jsonify(stats)


# ── Model Comparison ──────────────────────────────────────────

@monitor_bp.route("/api/monitor/models")
def monitor_models():
    """Per-model performance statistics."""
    connector, err = _get_connector()
    if err:
        return err

    if not connector.db_reader:
        return jsonify({"error": "Database not available"}), 503

    models = connector.db_reader.get_model_stats()
    distinct = connector.db_reader.get_distinct_models()

    return jsonify({"models": models, "available_models": distinct})


# ── Live Processing Feed ─────────────────────────────────────

@monitor_bp.route("/api/monitor/live")
def monitor_live_feed():
    """SSE stream for real-time processing events.

    Auto-detects new video processing via ActiveProcessingDetector
    and relays step-by-step progress to dashboard clients.
    """
    connector, err = _get_connector()
    if err:
        return err

    detector = connector.live_detector
    client_q = detector.register_client()

    def event_stream():
        try:
            # Initial connection event
            init = {"type": "connected"}
            if detector.active_video:
                init["active_video"] = detector.active_video
                init["active_title"] = detector.active_title
                init["is_processing"] = True
            yield f"data: {json.dumps(init)}\n\n"

            while True:
                try:
                    event = client_q.get(timeout=30)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except Exception:
                    # Heartbeat to keep connection alive
                    yield f": heartbeat {int(time.time())}\n\n"
        except GeneratorExit:
            pass
        finally:
            detector.unregister_client(client_q)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@monitor_bp.route("/api/monitor/live/status")
def monitor_live_status():
    """Current active processing status (REST endpoint)."""
    connector, err = _get_connector()
    if err:
        return err

    detector = connector.live_detector
    return jsonify({
        "active_video": detector.active_video,
        "active_title": detector.active_title,
        "is_processing": detector.active_video is not None,
    })


@monitor_bp.route("/api/monitor/live/callback", methods=["POST"])
def monitor_live_callback():
    """메인 서비스에서 실시간 로그를 수신하는 콜백 엔드포인트."""
    connector, err = _get_connector()
    if err:
        return err

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "No JSON body"}), 400

    detector = connector.live_detector
    detector.receive_callback(data)
    return jsonify({"ok": True})
