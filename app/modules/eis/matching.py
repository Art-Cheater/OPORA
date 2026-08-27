"""Сопоставление текста ЕИС с адресными объектами Опоры (scoring)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.modules.requests.address_format import normalize_address, split_address_query
from app.models.work_objects.work_object import WorkObject

_WORD_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)
_SETTLEMENT_RE = re.compile(
    r"(?:деревня|дер\.?|д\.?|поселок|посёлок|пос\.?|п\.?|село|с\.?|микрорайон|мкр\.?)\s+"
    r"([а-яёa-z0-9\-]+(?:\s+[а-яёa-z0-9\-]+)?)",
    re.IGNORECASE,
)
_STREET_RE = re.compile(
    r"(?:улица|ул(?:\.|\s+)|проспект|пр-кт\.?|пр-т\.?|пр(?:\.|\s+)|"
    r"переулок|пер(?:\.|\s+)|бульвар|б-р\.?|"
    r"площадь|пл(?:\.|\s+)|шоссе|ш(?:\.|\s+)|тракт|"
    r"проезд|пр-д\.?|набережная|наб(?:\.|\s+))\s*"
    r"([а-яёa-z0-9\-]+)",
    re.IGNORECASE,
)
_HOUSE_RE = re.compile(
    r"(?:дом|д\.?|корп\.?|корпус|стр\.?|строение)\s*(\d+[а-яёa-z]?)",
    re.IGNORECASE,
)
_HOUSE_GLUED_RE = re.compile(r"(\d+[а-яёa-z]?)\s*$", re.IGNORECASE)

_STOPWORDS = {
    "выполнение",
    "работ",
    "работы",
    "по",
    "устройству",
    "устройство",
    "наружного",
    "освещения",
    "освещение",
    "недостающего",
    "электрического",
    "российская",
    "федерация",
    "область",
    "обл",
    "кировская",
    "кировской",
    "город",
    "города",
    "киров",
    "кирова",
    "г",
    "о",
    "го",
    "в",
    "на",
    "и",
    "за",
    "его",
    "пределами",
    "расстоянии",
    "не",
    "менее",
    "метров",
    "м",
    "ул",
    "улица",
    "проезд",
    "между",
    "дом",
    "д",
    "п",
    "пос",
    "поселок",
    "посёлок",
    "деревня",
    "дер",
    "село",
    "с",
    "микрорайон",
    "мкр",
    "переулок",
    "пер",
    "проспект",
    "корпус",
    "корп",
    "строение",
    "стр",
}

# Порог: уверенный матч; разрыв со 2-м кандидатом
_MATCH_MIN = 0.82
_MATCH_GAP = 0.08
_AMBIGUOUS_MIN = 0.70


@dataclass
class AddressMatch:
    work_object: WorkObject | None
    reason: str
    candidates: int = 0
    status: str = "unmatched"  # matched | ambiguous | unmatched
    matched_by: str | None = None
    score: float = 0.0
    candidate_details: list[dict] = field(default_factory=list)

    def to_extra(self) -> dict:
        return {
            "match_status": self.status,
            "matched_by": self.matched_by,
            "score": round(self.score, 4),
            "reason": self.reason,
            "candidates": self.candidate_details[:8],
        }


def _words(text: str | None) -> set[str]:
    return {item.casefold() for item in _WORD_RE.findall(text or "") if item}


def _norm_house(value: str | None) -> str:
    raw = (value or "").casefold().replace(" ", "")
    return raw


def houses_conflict(a: str | None, b: str | None) -> bool:
    """Строгое сравнение номеров: 18≠180, 18≠18а."""
    ha, hb = _norm_house(a), _norm_house(b)
    if not ha or not hb:
        return False
    return ha != hb


def distinctive_tokens(text: str | None) -> set[str]:
    tokens: set[str] = set()
    raw = text or ""
    for match in _SETTLEMENT_RE.finditer(raw):
        tokens.update(_words(match.group(1)))
    for match in _STREET_RE.finditer(raw):
        tokens.update(_words(match.group(1)))
    for match in _HOUSE_RE.finditer(raw):
        tokens.add(match.group(1).casefold())
    _, street_name, house = split_address_query(raw)
    if street_name:
        tokens.update(_words(street_name))
    if house:
        tokens.add(house.casefold())
    leftover = _words(raw) - _STOPWORDS
    tokens.update({item for item in leftover if len(item) >= 5 or item.isdigit()})
    return {item for item in tokens if item and item not in _STOPWORDS}


def extract_address_parts(text: str | None) -> dict[str, set[str] | str | None]:
    raw = text or ""
    settlements: set[str] = set()
    for match in _SETTLEMENT_RE.finditer(raw):
        settlements.update(_words(match.group(1)))
    street_type, street_name, house = split_address_query(raw)
    streets = _words(street_name) if street_name else set()
    for match in _STREET_RE.finditer(raw):
        streets.update(_words(match.group(1)))
    house_val = house or None
    if not house_val:
        for match in _HOUSE_RE.finditer(raw):
            house_val = match.group(1)
            break
    return {
        "settlements": settlements,
        "streets": streets,
        "street_type": street_type,
        "house": _norm_house(house_val) or None,
        "tokens": distinctive_tokens(raw),
        "normalized": normalize_address(raw) if raw.strip() else "",
    }


def object_haystack(obj: WorkObject) -> str:
    return " ".join([obj.address or "", obj.name or ""])


def _token_jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _score_object(query_parts: dict, obj: WorkObject) -> tuple[float, str]:
    hay = object_haystack(obj)
    obj_parts = extract_address_parts(hay)
    q_house = query_parts.get("house")
    o_house = obj_parts.get("house")
    if houses_conflict(q_house, o_house):
        return 0.0, "house_conflict"

    q_norm = query_parts.get("normalized") or ""
    o_norm = normalize_address(obj.address or obj.name or "")
    if q_norm and o_norm and q_norm == o_norm:
        return 1.0, "exact_address"

    # Взаимное вхождение нормализованных адресов (только при достаточной длине)
    if (
        q_norm
        and o_norm
        and len(q_norm) >= 12
        and len(o_norm) >= 12
        and (q_norm in o_norm or o_norm in q_norm)
    ):
        return 0.98, "normalized_address"

    # Совпадение с одним из нормализованных запросов (несколько текстов)
    for cand in query_parts.get("normalized_set") or set():
        if not cand or len(cand) < 12:
            continue
        if cand == o_norm or (len(o_norm) >= 12 and (cand in o_norm or o_norm in cand)):
            return 0.97, "normalized_address"

    q_streets: set[str] = query_parts.get("streets") or set()
    o_streets: set[str] = obj_parts.get("streets") or set()
    q_settl: set[str] = query_parts.get("settlements") or set()
    o_settl: set[str] = obj_parts.get("settlements") or set()

    # Разные населённые пункты при наличии обоих — отказ
    if q_settl and o_settl and q_settl.isdisjoint(o_settl):
        # «киров» уже в stopwords; деревня X vs деревня Y
        return 0.0, "locality_conflict"

    street_overlap = bool(q_streets & o_streets) or (
        q_streets and o_streets and _token_jaccard(q_streets, o_streets) >= 0.5
    )
    house_ok = bool(q_house and o_house and q_house == o_house)
    locality_ok = (not q_settl) or (not o_settl) or bool(q_settl & o_settl)

    if street_overlap and house_ok and locality_ok and q_settl and o_settl and q_settl & o_settl:
        return 0.96, "locality_street_house"
    if street_overlap and house_ok and locality_ok:
        return 0.93, "street_house"

    q_tokens: set[str] = query_parts.get("tokens") or set()
    hay_tokens = _words(hay)
    if q_tokens and q_tokens <= hay_tokens:
        return 0.88, "token_subset"

    # Название объекта
    name_tokens = _words(obj.name) - _STOPWORDS
    if q_tokens and name_tokens:
        jac = _token_jaccard(q_tokens, name_tokens)
        if jac >= 0.7 and (not q_house or not o_house or q_house == o_house):
            return 0.8 + 0.1 * jac, "object_name"

    # Осторожный fuzzy: только если дом совпал (или дом не извлечён), улица похожа
    if house_ok or (not q_house and not o_house):
        jac_street = _token_jaccard(q_streets, o_streets) if q_streets and o_streets else 0.0
        jac_all = _token_jaccard(q_tokens, hay_tokens)
        fuzzy = max(jac_street, jac_all * 0.9)
        if fuzzy >= 0.75 and house_ok:
            return 0.78 + 0.1 * fuzzy, "fuzzy"
        if fuzzy >= 0.85 and not q_house:
            return 0.76 + 0.08 * fuzzy, "fuzzy"

    return max(_token_jaccard(q_tokens, hay_tokens) * 0.5, 0.0), "weak"


def match_work_objects(
    texts: list[str | None],
    objects: list[WorkObject],
) -> AddressMatch:
    """Скоринг: один явный победитель → matched; близкие → ambiguous; иначе unmatched."""
    cleaned = [t for t in texts if (t or "").strip()]
    if not cleaned:
        return AddressMatch(None, "В тексте ЕИС нет адреса для сопоставления", 0, status="unmatched")

    query_tokens: set[str] = set()
    settlements: set[str] = set()
    streets: set[str] = set()
    house: str | None = None
    normalized_set: set[str] = set()
    for text in cleaned:
        parts = extract_address_parts(text)
        query_tokens |= parts["tokens"]  # type: ignore[operator]
        settlements |= parts["settlements"]  # type: ignore[operator]
        streets |= parts["streets"]  # type: ignore[operator]
        if not house and parts.get("house"):
            house = parts["house"]  # type: ignore[assignment]
        norm = parts.get("normalized") or ""
        if norm:
            normalized_set.add(norm)

    if not query_tokens and not normalized_set:
        return AddressMatch(None, "В тексте ЕИС нет адреса для сопоставления", 0, status="unmatched")

    query_parts = {
        "tokens": query_tokens,
        "settlements": settlements,
        "streets": streets,
        "house": house,
        "normalized": next(iter(normalized_set), ""),
        "normalized_set": normalized_set,
    }

    scored: list[tuple[float, str, WorkObject]] = []
    for obj in objects:
        score, method = _score_object(query_parts, obj)
        if score > 0.05:
            scored.append((score, method, obj))

    scored.sort(key=lambda item: item[0], reverse=True)
    # unique by id keeping best
    best_by_id: dict = {}
    for score, method, obj in scored:
        prev = best_by_id.get(obj.id)
        if prev is None or score > prev[0]:
            best_by_id[obj.id] = (score, method, obj)
    ranked = sorted(best_by_id.values(), key=lambda item: item[0], reverse=True)

    details = [
        {
            "object_id": str(obj.id),
            "address": (obj.display_address or obj.name or "")[:120],
            "score": round(score, 4),
            "matched_by": method,
        }
        for score, method, obj in ranked[:8]
    ]

    if not ranked:
        return AddressMatch(
            None,
            f"Объект из ЕИС не найден в плане: {', '.join(sorted(query_tokens))}",
            0,
            status="unmatched",
            candidate_details=details,
        )

    best_score, best_method, best_obj = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else 0.0

    if best_score >= _MATCH_MIN and (best_score - second) >= _MATCH_GAP:
        return AddressMatch(
            best_obj,
            "Совпал адрес объекта",
            len(ranked),
            status="matched",
            matched_by=best_method,
            score=best_score,
            candidate_details=details,
        )

    if best_score >= _AMBIGUOUS_MIN and len(ranked) > 1 and (best_score - second) < _MATCH_GAP:
        return AddressMatch(
            None,
            "Несколько объектов подходят под адрес ЕИС: "
            + ", ".join((item.display_address or item.name or "")[:80] for _, _, item in ranked[:5]),
            len(ranked),
            status="ambiguous",
            matched_by=best_method,
            score=best_score,
            candidate_details=details,
        )

    if best_score >= _MATCH_MIN and len(ranked) == 1:
        return AddressMatch(
            best_obj,
            "Совпал адрес объекта",
            1,
            status="matched",
            matched_by=best_method,
            score=best_score,
            candidate_details=details,
        )

    return AddressMatch(
        None,
        f"Объект из ЕИС не найден в плане: {', '.join(sorted(query_tokens))}",
        len(ranked),
        status="unmatched",
        score=best_score,
        candidate_details=details,
    )
