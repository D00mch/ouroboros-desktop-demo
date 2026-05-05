"""Local employee directory lookup from CSV stored in the runtime data dir."""

from __future__ import annotations

import csv
import json
import os
import pathlib
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Iterable, List

from ouroboros.paths import get_data_dir
from ouroboros.tools.registry import ToolContext, ToolEntry

_REF_RE = re.compile(r"^row:(\d+)$")

_SHORT_FIELD_PRIORITY = (
    "employee_id",
    "tab_number",
    "hr_position",
    "position",
    "title",
    "profile_structure",
    "department",
    "division",
    "team",
    "unit",
    "manager",
    "supervisor",
    "email",
    "phone",
    "contact",
)


@dataclass(frozen=True)
class EmployeeRecord:
    ref: str
    row_number: int
    fields: dict[str, Any]
    display_name: str
    employee_id: str
    tab_number: str
    full_name_norm: str
    short_name_norm: str
    reverse_short_name_norm: str
    employee_id_norm: str
    tab_number_norm: str
    name_tokens: tuple[str, ...]
    full_tokens: tuple[str, ...]
    short_tokens: tuple[str, ...]
    reverse_short_tokens: tuple[str, ...]


@dataclass(frozen=True)
class ScoredCandidate:
    record: EmployeeRecord
    score: float


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower().replace("ё", "е")
    normalized = normalized.replace("_", " ")
    normalized = re.sub(r"[^\w\s]+", " ", normalized, flags=re.UNICODE)
    return re.sub(r"\s+", " ", normalized, flags=re.UNICODE).strip()


def _split_tokens(value: str) -> tuple[str, ...]:
    normalized = _normalize_text(value)
    return tuple(token for token in normalized.split(" ") if token)


def _parse_field_value(value: str) -> Any:
    raw = (value or "").strip()
    if not raw:
        return ""
    if raw.startswith("[") or raw.startswith("{"):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _display_name(fields: dict[str, Any]) -> str:
    parts = [
        str(fields.get("profile_last_name", "") or "").strip(),
        str(fields.get("profile_first_name", "") or "").strip(),
        str(fields.get("profile_patronymic", "") or "").strip(),
    ]
    return " ".join(part for part in parts if part).strip()


def _build_record(row_number: int, row: dict[str, str]) -> EmployeeRecord:
    fields = {key: _parse_field_value(value) for key, value in row.items()}
    display_name = _display_name(fields)
    last_name = str(fields.get("profile_last_name", "") or "").strip()
    first_name = str(fields.get("profile_first_name", "") or "").strip()
    patronymic = str(fields.get("profile_patronymic", "") or "").strip()
    full_name = " ".join(part for part in (last_name, first_name, patronymic) if part).strip()
    short_name = " ".join(part for part in (last_name, first_name) if part).strip()
    reverse_short_name = " ".join(part for part in (first_name, last_name) if part).strip()
    employee_id = str(fields.get("employee_id", "") or "").strip()
    tab_number = str(fields.get("tab_number", "") or "").strip()
    return EmployeeRecord(
        ref=f"row:{row_number}",
        row_number=row_number,
        fields=fields,
        display_name=display_name or short_name or employee_id or tab_number or f"row:{row_number}",
        employee_id=employee_id,
        tab_number=tab_number,
        full_name_norm=_normalize_text(full_name),
        short_name_norm=_normalize_text(short_name),
        reverse_short_name_norm=_normalize_text(reverse_short_name),
        employee_id_norm=_normalize_text(employee_id),
        tab_number_norm=_normalize_text(tab_number),
        name_tokens=_split_tokens(display_name),
        full_tokens=_split_tokens(full_name),
        short_tokens=_split_tokens(short_name),
        reverse_short_tokens=_split_tokens(reverse_short_name),
    )


def _resolve_csv_path(ctx: ToolContext) -> pathlib.Path:
    override = (os.environ.get("OUROBOROS_EMPLOYEE_CSV", "") or "").strip()
    if override:
        return pathlib.Path(override).expanduser()
    return get_data_dir(ctx) / "employees.csv"


def _load_records(csv_path: pathlib.Path) -> list[EmployeeRecord]:
    records: list[EmployeeRecord] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=1):
            if not row:
                continue
            cleaned = {str(key or "").strip(): str(value or "") for key, value in row.items()}
            if not any(value.strip() for value in cleaned.values()):
                continue
            records.append(_build_record(row_number, cleaned))
    return records


def _ordered_prefix_match(query_tokens: tuple[str, ...], candidate_tokens: tuple[str, ...]) -> bool:
    return bool(query_tokens) and len(query_tokens) <= len(candidate_tokens) and all(
        candidate_tokens[index].startswith(token)
        for index, token in enumerate(query_tokens)
    )


def _unordered_prefix_count(query_tokens: tuple[str, ...], candidate_tokens: tuple[str, ...]) -> int:
    if not query_tokens or not candidate_tokens:
        return 0
    matched = 0
    remaining = list(candidate_tokens)
    for token in query_tokens:
        for index, candidate in enumerate(remaining):
            if candidate.startswith(token):
                matched += 1
                remaining.pop(index)
                break
    return matched


def _best_ratio(query_norm: str, variants: Iterable[str]) -> float:
    best = 0.0
    for variant in variants:
        if not variant:
            continue
        best = max(best, SequenceMatcher(a=query_norm, b=variant).ratio())
    return best


def _score_record(query_norm: str, query_tokens: tuple[str, ...], record: EmployeeRecord) -> float:
    score = 0.0

    if query_norm and query_norm in {record.employee_id_norm, record.tab_number_norm}:
        return 140.0

    if query_norm and query_norm == record.full_name_norm:
        return 120.0
    if query_norm and query_norm == record.short_name_norm:
        score = max(score, 115.0)
    if query_norm and query_norm == record.reverse_short_name_norm:
        score = max(score, 112.0)

    ordered_variants = (
        (record.full_tokens, 104.0),
        (record.short_tokens, 100.0),
        (record.reverse_short_tokens, 97.0),
    )
    for candidate_tokens, base_score in ordered_variants:
        if _ordered_prefix_match(query_tokens, candidate_tokens):
            score = max(score, base_score + min(len(query_tokens), 4) * 4.0)

    prefix_matches = _unordered_prefix_count(query_tokens, record.name_tokens)
    if prefix_matches:
        score = max(score, 74.0 + prefix_matches * 8.0 - max(0, len(query_tokens) - prefix_matches) * 10.0)

    if query_norm and any(query_norm in variant for variant in (
        record.full_name_norm,
        record.short_name_norm,
        record.reverse_short_name_norm,
    ) if variant):
        score = max(score, 84.0)

    ratio = _best_ratio(
        query_norm,
        (record.full_name_norm, record.short_name_norm, record.reverse_short_name_norm),
    )
    if ratio >= 0.60:
        score = max(score, round(52.0 + ratio * 36.0, 2))

    return round(score, 2)


def _short_fields(fields: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    seen: set[str] = set()

    def _add(key: str) -> None:
        if key in fields and key not in seen:
            value = fields[key]
            if value not in ("", None):
                result[key] = value
                seen.add(key)

    for key in _SHORT_FIELD_PRIORITY:
        _add(key)

    for key, value in fields.items():
        if len(result) >= 6:
            break
        lower_key = key.lower()
        if key in seen or value in ("", None):
            continue
        if lower_key.startswith("profile_") and lower_key not in {
            "profile_structure",
            "profile_email",
            "profile_phone",
        }:
            continue
        if lower_key in {"profile_last_name", "profile_first_name", "profile_patronymic"}:
            continue
        result[key] = value
        seen.add(key)

    return result


def _found_payload(query: str, source: pathlib.Path, candidate: ScoredCandidate) -> dict[str, Any]:
    return {
        "status": "found",
        "query": query,
        "source": str(source),
        "employee": {
            "ref": candidate.record.ref,
            "display_name": candidate.record.display_name,
            "score": candidate.score,
            "fields": candidate.record.fields,
        },
    }


def _ambiguous_payload(query: str, source: pathlib.Path, candidates: list[ScoredCandidate]) -> dict[str, Any]:
    return {
        "status": "ambiguous",
        "query": query,
        "source": str(source),
        "message": "Several employees match. Ask the user to choose one candidate in plain text. Do not choose automatically.",
        "candidates": [
            {
                "ref": candidate.record.ref,
                "display_name": candidate.record.display_name,
                "score": candidate.score,
                "fields": _short_fields(candidate.record.fields),
            }
            for candidate in candidates
        ],
    }


def _pick_result(query: str, source: pathlib.Path, scored: list[ScoredCandidate]) -> dict[str, Any]:
    if not scored or scored[0].score < 60.0:
        return {
            "status": "not_found",
            "query": query,
            "source": str(source),
            "message": "No employees matched the query.",
        }

    top = scored[0]
    close_candidates = [candidate for candidate in scored if candidate.score >= max(88.0, top.score - 6.0)]

    if top.score >= 118.0 and len(close_candidates) == 1:
        return _found_payload(query, source, top)

    if len(close_candidates) == 1:
        second_score = scored[1].score if len(scored) > 1 else 0.0
        if top.score >= 94.0 and top.score - second_score >= 8.0:
            return _found_payload(query, source, top)

    if len(close_candidates) > 1:
        return _ambiguous_payload(query, source, close_candidates[:5])

    if top.score >= 82.0:
        return _found_payload(query, source, top)

    return {
        "status": "not_found",
        "query": query,
        "source": str(source),
        "message": "No employees matched the query confidently enough.",
    }


def _lookup_by_ref(records: Iterable[EmployeeRecord], ref: str) -> EmployeeRecord | None:
    match = _REF_RE.fullmatch((ref or "").strip())
    if not match:
        return None
    row_number = int(match.group(1))
    for record in records:
        if record.row_number == row_number:
            return record
    return None


def _employee_lookup(ctx: ToolContext, query: str = "", ref: str = "") -> str:
    source = _resolve_csv_path(ctx)
    payload_base = {
        "query": query,
        "source": str(source),
    }

    if not query and not ref:
        return json.dumps(
            {
                "status": "error",
                **payload_base,
                "message": "Provide either `query` or `ref`.",
            },
            ensure_ascii=False,
            indent=2,
        )

    try:
        if not source.exists():
            return json.dumps(
                {
                    "status": "error",
                    **payload_base,
                    "message": f"employees.csv not found. Place the file at {source}.",
                },
                ensure_ascii=False,
                indent=2,
            )

        records = _load_records(source)
    except Exception as exc:
        return json.dumps(
            {
                "status": "error",
                **payload_base,
                "message": f"Failed to read employees.csv: {type(exc).__name__}: {exc}",
            },
            ensure_ascii=False,
            indent=2,
        )

    if ref:
        record = _lookup_by_ref(records, ref)
        if record is None:
            result = {
                "status": "not_found",
                **payload_base,
                "message": f"Employee reference not found: {ref}",
            }
        else:
            result = _found_payload(query, source, ScoredCandidate(record=record, score=150.0))
        return json.dumps(result, ensure_ascii=False, indent=2)

    query_norm = _normalize_text(query)
    query_tokens = _split_tokens(query)
    scored = sorted(
        (
            ScoredCandidate(record=record, score=_score_record(query_norm, query_tokens, record))
            for record in records
        ),
        key=lambda candidate: (-candidate.score, candidate.record.display_name, candidate.record.ref),
    )
    result = _pick_result(query, source, scored)
    return json.dumps(result, ensure_ascii=False, indent=2)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry(
            "employee_lookup",
            {
                "name": "employee_lookup",
                "description": (
                    "Read-only lookup of employee data from the local employees.csv file in the runtime data directory. "
                    "Supports search by full or partial name, employee_id, tab_number, and row ref."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Employee name, employee_id, or tab_number to search for.",
                        },
                        "ref": {
                            "type": "string",
                            "description": "Previously returned employee ref such as row:3.",
                        },
                    },
                },
            },
            _employee_lookup,
            timeout_sec=30,
        ),
    ]
