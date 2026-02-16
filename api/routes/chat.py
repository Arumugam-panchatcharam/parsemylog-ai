"""
Chat API Routes — LLM-powered log analysis chat
=================================================

Endpoints for managing chat conversations and streaming LLM responses.
All responses are grounded in parsed pipeline evidence (reboots, patterns,
telemetry, device info, and semantic search results).
"""

import json
import logging
from pathlib import Path

from flask import Blueprint, Response, request, jsonify, stream_with_context
from flask_jwt_extended import jwt_required

from api.app import dbm
from api.auth import get_user_id
from logai.utils.constants import UPLOAD_DIRECTORY

logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_project_dir(user_id: int, project_id: str, cpe_id: str = None) -> Path:
    """Get the project directory path, optionally scoped to a CPE."""
    base = Path(f"{UPLOAD_DIRECTORY}/{user_id}/{project_id}")
    if cpe_id:
        return base / cpe_id
    return base


def _verify_project(project_id: str, user_id: int):
    """Verify project belongs to user, return (project, error_response)."""
    project = dbm.get_project_by_id(project_id)
    if not project:
        return None, (jsonify({"error": "Project not found"}), 404)
    if project.user_id != user_id:
        return None, (jsonify({"error": "Access denied"}), 403)
    return project, None


def _check_llm_gates():
    """Check if LLM is enabled. Admin users bypass the enabled toggle."""
    from api.llm_service import is_enabled, is_available
    user_id = get_user_id()
    user = dbm.get_user_by_id(user_id)
    is_admin = user and user.is_admin
    if not is_admin and not is_enabled(dbm):
        return jsonify({"error": "AI Chat is disabled by admin"}), 403
    if not is_available():
        return jsonify({"error": "LLM server is not available. Please contact admin."}), 503
    return None


# ---------------------------------------------------------------------------
# Conversations CRUD
# ---------------------------------------------------------------------------

@chat_bp.route("/<project_id>/chat/conversations", methods=["GET"])
@jwt_required()
def list_conversations(project_id):
    """
    List chat conversations for the current user and project.

    Query params:
        cpe_id (optional): filter to a specific CPE

    Returns: [ { id, title, cpe_id, created_at, updated_at } ]
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    cpe_id = request.args.get("cpe_id")
    convs = dbm.get_conversations(project_id, user_id, cpe_id)

    return jsonify([
        {
            "id": c.id,
            "title": c.title,
            "cpe_id": c.cpe_id,
            "created_at": str(c.created_at) if c.created_at else None,
            "updated_at": str(c.updated_at) if c.updated_at else None,
        }
        for c in convs
    ]), 200


@chat_bp.route("/<project_id>/chat/conversations", methods=["POST"])
@jwt_required()
def create_conversation(project_id):
    """
    Create a new chat conversation.

    Body: { title?: string, cpe_id?: string }
    Returns: { id, title, cpe_id }
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    data = request.get_json(silent=True) or {}
    title = data.get("title", "New conversation")
    cpe_id = data.get("cpe_id")

    conv = dbm.create_conversation(project_id, user_id, cpe_id, title)

    return jsonify({
        "id": conv.id,
        "title": conv.title,
        "cpe_id": conv.cpe_id,
    }), 201


@chat_bp.route("/<project_id>/chat/conversations/<int:conv_id>", methods=["DELETE"])
@jwt_required()
def delete_conversation(project_id, conv_id):
    """Delete a chat conversation and all its messages."""
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    # Verify ownership
    conv = dbm.get_conversation_by_id(conv_id)
    if not conv or conv.user_id != user_id:
        return jsonify({"error": "Conversation not found"}), 404

    dbm.delete_conversation(conv_id)
    return jsonify({"message": "Conversation deleted"}), 200


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

@chat_bp.route("/<project_id>/chat/messages", methods=["GET"])
@jwt_required()
def get_messages(project_id):
    """
    Get messages for a conversation.

    Query params:
        conversation_id (required)
        limit (optional, default 50)

    Returns: [ { id, role, content, context_used, created_at } ]
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    conv_id = request.args.get("conversation_id", type=int)
    if not conv_id:
        return jsonify({"error": "conversation_id required"}), 400

    # Verify ownership
    conv = dbm.get_conversation_by_id(conv_id)
    if not conv or conv.user_id != user_id:
        return jsonify({"error": "Conversation not found"}), 404

    limit = request.args.get("limit", 50, type=int)
    messages = dbm.get_messages(conv_id, limit)

    return jsonify([
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "context_used": json.loads(m.context_used) if m.context_used else None,
            "created_at": str(m.created_at) if m.created_at else None,
        }
        for m in messages
    ]), 200


# ---------------------------------------------------------------------------
# Send message + stream LLM response
# ---------------------------------------------------------------------------

@chat_bp.route("/<project_id>/chat/send", methods=["POST"])
@jwt_required()
def send_message(project_id):
    """
    Send a user message and stream back the LLM response via SSE.

    Body: { conversation_id: int, message: string }

    Gates:
        - LLM must be enabled by admin
        - LLM server must be healthy
        - Indexing should be complete (warning only)

    Returns: text/event-stream with:
        - event: token  — individual response tokens
        - event: context — JSON metadata of evidence used
        - event: done   — signals completion
        - event: error  — error message
    """
    user_id = get_user_id()
    project, err = _verify_project(project_id, user_id)
    if err:
        return err

    # Gate: LLM enabled?
    gate_err = _check_llm_gates()
    if gate_err:
        return gate_err

    data = request.get_json(silent=True) or {}
    conv_id = data.get("conversation_id")
    user_message = (data.get("message") or "").strip()

    if not conv_id or not user_message:
        return jsonify({"error": "conversation_id and message are required"}), 400

    # Verify conversation ownership
    conv = dbm.get_conversation_by_id(conv_id)
    if not conv or conv.user_id != user_id:
        return jsonify({"error": "Conversation not found"}), 404

    # Auto-title from first message (before saving, so count is pre-save)
    msg_count = len(dbm.get_messages(conv_id, limit=3))
    if msg_count == 0:
        conv.title = user_message[:80] + ("..." if len(user_message) > 80 else "")
        dbm.db.session.commit()

    # Resolve project directory
    cpe_id = conv.cpe_id
    project_dir = _get_project_dir(user_id, project_id, cpe_id)

    def generate():
        """SSE generator."""
        import api.llm_service as llm

        try:
            # Check queue position
            pos = llm.queue_position()
            if pos > 0:
                yield f"event: status\ndata: {json.dumps({'message': f'Position {pos + 1} in queue...'})}\n\n"

            # Build evidence-grounded prompt
            system_prompt = llm.build_system_prompt(
                project_name=project.name,
                project_dir=project_dir,
                project_id=project_id,
                cpe_id=cpe_id,
                user_query=user_message,
            )

            # Get conversation history BEFORE saving the new user message
            # to avoid duplicating it in build_messages()
            history = dbm.get_messages(conv_id, limit=llm.MAX_HISTORY_MESSAGES)

            # Save user message to DB now (after fetching history)
            dbm.save_message(conv_id, "user", user_message)

            # Assemble messages (history does NOT contain the new user message,
            # so build_messages adds it exactly once)
            messages = llm.build_messages(system_prompt, history, user_message)

            # Build context metadata for the "Sources" panel
            context_meta = {
                "project": project.name,
                "cpe_id": cpe_id,
                "evidence_sources": [],
            }
            if (project_dir / ".reboots_cache.json").exists():
                context_meta["evidence_sources"].append("reboots")
            if (project_dir / "telemetry" / "response.json").exists():
                context_meta["evidence_sources"].append("telemetry")
            context_meta["evidence_sources"].append("semantic_search")

            # Send context metadata
            yield f"event: context\ndata: {json.dumps(context_meta)}\n\n"

            # Stream LLM response
            full_response = []
            logger.info(f"[Chat] Starting LLM stream for conv {conv_id}")
            for token in llm.chat_completion_stream(messages):
                full_response.append(token)
                yield f"event: token\ndata: {json.dumps({'token': token})}\n\n"

            logger.info(f"[Chat] LLM stream done, {len(full_response)} tokens, {len(''.join(full_response))} chars")

            # Save assistant response
            assistant_content = "".join(full_response)
            dbm.save_message(
                conv_id, "assistant", assistant_content,
                context_used=json.dumps(context_meta),
            )

            yield f"event: done\ndata: {json.dumps({'message': 'complete'})}\n\n"

        except Exception as e:
            logger.error(f"[Chat] Error in SSE stream: {e}", exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering for SSE
        },
    )


# ---------------------------------------------------------------------------
# LLM status (for frontend gate checks)
# ---------------------------------------------------------------------------

@chat_bp.route("/<project_id>/chat/llm-status", methods=["GET"])
@jwt_required()
def llm_status(project_id):
    """
    Get LLM availability status for gate checks.

    Returns: { enabled: bool, available: bool, model_info: {...} | null }
    """
    import api.llm_service as llm

    enabled = llm.is_enabled(dbm)
    available = llm.is_available()
    model_info = llm.get_model_info() if available else None

    return jsonify({
        "enabled": enabled,
        "available": available,
        "model_info": model_info,
    }), 200
