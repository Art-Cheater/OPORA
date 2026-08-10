"""Маршруты корпоративного мессенджера."""

from __future__ import annotations

import uuid

from flask import (
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
)
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.core.exceptions import NotFoundError, ValidationError
from app.models.auth.constants import PERM_MESSENGER_USE
from app.modules.messenger.blueprint import messenger_bp
from app.modules.messenger.repositories import MessengerRepository
from app.modules.messenger.serializers import (
    serialize_conversation,
    serialize_message,
    serialize_search_result,
    serialize_user,
)
from app.modules.messenger.services import MessengerService


def _online_timeout() -> int:
    return int(current_app.config.get("MESSENGER_ONLINE_TIMEOUT", 120))


@messenger_bp.route("/")
@login_required
@permission_required(PERM_MESSENGER_USE)
def index():
    MessengerService.heartbeat(current_user.id)
    return render_template("messenger/index.html")


@messenger_bp.route("/api/heartbeat", methods=["POST"])
@login_required
@permission_required(PERM_MESSENGER_USE)
def heartbeat():
    MessengerService.heartbeat(current_user.id)
    return jsonify({"ok": True})


@messenger_bp.route("/api/unread-count")
@login_required
@permission_required(PERM_MESSENGER_USE)
def unread_count():
    from flask import make_response

    total = MessengerRepository.total_unread_count(current_user.id)
    response = make_response(jsonify({"total": total}))
    response.set_etag(f"unread-{current_user.id}-{total}", weak=True)
    response.headers["Cache-Control"] = "private, no-cache"
    return response.make_conditional(request)


@messenger_bp.route("/api/events")
@login_required
@permission_required(PERM_MESSENGER_USE)
def events_stream():
    """Лёгкий SSE: периодически отдаёт unread без тяжёлого polling с клиента."""
    import json
    import time

    from flask import Response, current_app, stream_with_context

    user_id = current_user.id
    interval = max(5, int(current_app.config.get("MESSENGER_POLL_INTERVAL_MS", 8000) / 1000))

    @stream_with_context
    def generate():
        last = None
        # ~30 минут максимум на соединение
        for _ in range(max(1, int(1800 / interval))):
            total = MessengerRepository.total_unread_count(user_id)
            if total != last:
                payload = {"total": total}
                if last is not None and total > (last or 0):
                    preview = MessengerRepository.latest_unread_preview(user_id)
                    if preview:
                        payload["preview"] = preview
                yield f"event: unread\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last = total
            else:
                yield ": keepalive\n\n"
            time.sleep(interval)

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@messenger_bp.route("/api/users")
@login_required
@permission_required(PERM_MESSENGER_USE)
def users():
    query = request.args.get("q", "")
    users_list = MessengerRepository.list_users(current_user.id, query)
    user_ids = [user.id for user in users_list]
    presence_map = MessengerRepository.presence_map(user_ids, _online_timeout())
    return jsonify(
        {
            "users": [
                serialize_user(
                    user,
                    online=presence_map.get(str(user.id), {}).get("is_online", False),
                    last_seen_at=presence_map.get(str(user.id), {}).get("last_seen_at"),
                )
                for user in users_list
            ]
        }
    )


@messenger_bp.route("/api/conversations")
@login_required
@permission_required(PERM_MESSENGER_USE)
def conversations():
    items = MessengerRepository.list_conversations(current_user.id)
    peer_ids = [conv.other_user_id(current_user.id) for conv in items]
    presence_map = MessengerRepository.presence_map(peer_ids, _online_timeout())
    return jsonify(
        {
            "conversations": [
                serialize_conversation(
                    conv, current_user.id, presence_map=presence_map
                )
                for conv in items
            ],
            "total_unread": MessengerRepository.total_unread_count(current_user.id),
        }
    )


@messenger_bp.route("/api/conversations/open/<uuid:peer_id>", methods=["POST"])
@login_required
@permission_required(PERM_MESSENGER_USE)
def open_conversation(peer_id: uuid.UUID):
    from app.extensions import db
    from app.modules.auth.repositories import UserRepository

    peer = UserRepository.get_by_id(peer_id)
    if peer is None or peer.deleted_at is not None:
        return jsonify({"error": "Сотрудник не найден."}), 404

    try:
        conversation = MessengerRepository.get_or_create_conversation(
            current_user.id,
            peer_id,
            created_by=current_user.id,
        )
        db.session.commit()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    presence_map = MessengerRepository.presence_map([peer_id], _online_timeout())
    return jsonify(
        serialize_conversation(conversation, current_user.id, presence_map=presence_map)
    )


@messenger_bp.route("/api/conversations/<uuid:conversation_id>/messages")
@login_required
@permission_required(PERM_MESSENGER_USE)
def messages(conversation_id: uuid.UUID):
    try:
        conversation = MessengerService.ensure_access(conversation_id, current_user.id)
    except NotFoundError as exc:
        return jsonify({"error": exc.message}), 404

    before_id = request.args.get("before_id")
    before_uuid = uuid.UUID(before_id) if before_id else None
    items = MessengerRepository.list_messages(conversation.id, before_id=before_uuid)
    MessengerService.mark_read(conversation, current_user.id)

    peer_id = conversation.other_user_id(current_user.id)
    presence_map = MessengerRepository.presence_map([peer_id], _online_timeout())

    return jsonify(
        {
            "conversation": serialize_conversation(
                conversation, current_user.id, presence_map=presence_map
            ),
            "messages": [serialize_message(msg, current_user.id) for msg in items],
        }
    )


@messenger_bp.route("/api/conversations/<uuid:conversation_id>/messages", methods=["POST"])
@login_required
@permission_required(PERM_MESSENGER_USE)
def send_message(conversation_id: uuid.UUID):
    try:
        conversation = MessengerService.ensure_access(conversation_id, current_user.id)
        payload = request.json if request.is_json else request.form
        body = payload.get("body") if payload else None
        reply_raw = payload.get("reply_to_id") if payload else None
        reply_to_id = uuid.UUID(str(reply_raw)) if reply_raw else None
        message = MessengerService.send_message(
            conversation,
            sender_id=current_user.id,
            body=body,
            reply_to_id=reply_to_id,
        )
    except (ValueError, TypeError):
        return jsonify({"error": "Некорректный идентификатор ответа."}), 400
    except NotFoundError as exc:
        return jsonify({"error": exc.message}), 404
    except ValidationError as exc:
        return jsonify({"error": exc.message}), 400

    return jsonify({"message": serialize_message(message, current_user.id)}), 201


@messenger_bp.route("/api/conversations/<uuid:conversation_id>/attachments", methods=["POST"])
@login_required
@permission_required(PERM_MESSENGER_USE)
def send_attachment(conversation_id: uuid.UUID):
    try:
        conversation = MessengerService.ensure_access(conversation_id, current_user.id)
        file = request.files.get("file")
        reply_raw = request.form.get("reply_to_id")
        reply_to_id = uuid.UUID(str(reply_raw)) if reply_raw else None
        message = MessengerService.send_file(
            conversation,
            sender_id=current_user.id,
            file_storage=file,
            reply_to_id=reply_to_id,
        )
    except (ValueError, TypeError):
        return jsonify({"error": "Некорректный идентификатор ответа."}), 400
    except NotFoundError as exc:
        return jsonify({"error": exc.message}), 404
    except ValidationError as exc:
        return jsonify({"error": exc.message}), 400

    return jsonify({"message": serialize_message(message, current_user.id)}), 201


@messenger_bp.route("/api/conversations/<uuid:conversation_id>/read", methods=["POST"])
@login_required
@permission_required(PERM_MESSENGER_USE)
def mark_read(conversation_id: uuid.UUID):
    try:
        conversation = MessengerService.ensure_access(conversation_id, current_user.id)
        count = MessengerService.mark_read(conversation, current_user.id)
    except NotFoundError as exc:
        return jsonify({"error": exc.message}), 404

    return jsonify({"marked": count, "total_unread": MessengerRepository.total_unread_count(current_user.id)})


@messenger_bp.route("/api/search")
@login_required
@permission_required(PERM_MESSENGER_USE)
def search():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify({"results": [], "error": "Минимум 2 символа для поиска."})

    items = MessengerRepository.search_messages(current_user.id, query)
    results = []
    for message in items:
        conversation = MessengerRepository.get_conversation(message.conversation_id)
        if conversation is None:
            continue
        message.conversation = conversation
        results.append(serialize_search_result(message, current_user.id))

    return jsonify({"results": results, "query": query})


@messenger_bp.route("/api/messages/<uuid:message_id>/file")
@login_required
@permission_required(PERM_MESSENGER_USE)
def download_file(message_id: uuid.UUID):
    from app.extensions import db
    from app.models.messenger.messenger_message import MessengerMessage

    msg = db.session.get(MessengerMessage, message_id)
    if msg is None or msg.deleted_at is not None or not msg.has_attachment:
        return jsonify({"error": "Файл не найден."}), 404

    try:
        MessengerService.ensure_access(msg.conversation_id, current_user.id)
    except NotFoundError:
        return jsonify({"error": "Доступ запрещён."}), 403

    try:
        path = MessengerService.get_file_path(msg)
    except NotFoundError:
        return jsonify({"error": "Файл не найден."}), 404

    from app.core.upload_utils import resolve_download_filename

    download_name = resolve_download_filename(
        msg.file_name,
        storage_key=msg.storage_key,
        mime_type=msg.mime_type,
    )

    force_download = request.args.get("download") == "1"
    as_attachment = force_download or not msg.is_image

    return send_file(
        path,
        as_attachment=as_attachment,
        download_name=download_name,
        mimetype=msg.mime_type or "application/octet-stream",
    )
