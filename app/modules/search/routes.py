"""Маршруты глобального поиска."""

from __future__ import annotations

from flask import jsonify, render_template, request
from flask_login import current_user, login_required

from app.core.decorators import permission_required
from app.core.search import DEFAULT_LIMIT
from app.models.auth.constants import PERM_SEARCH_USE
from app.modules.search.blueprint import search_bp
from app.modules.search.services import SearchService


@search_bp.route("/")
@login_required
@permission_required(PERM_SEARCH_USE)
def index():
    query = request.args.get("q", "")
    limit = request.args.get("limit", DEFAULT_LIMIT, type=int)
    response = SearchService.search(current_user, query, limit=min(limit, 50))
    return render_template(
        "search/index.html",
        query=query,
        results=SearchService.to_dict(response),
    )


@search_bp.route("/api")
@login_required
@permission_required(PERM_SEARCH_USE)
def api():
    query = request.args.get("q", "")
    limit = request.args.get("limit", DEFAULT_LIMIT, type=int)
    response = SearchService.search(current_user, query, limit=min(limit, 50))
    return jsonify(SearchService.to_dict(response))
