"""Armazenamento local e leitura dos relatórios baixados (TSV/CSV, JSON e XML).

Relatórios podem ter centenas de milhares de linhas, então em vez de devolver o arquivo inteiro
ao Claude, ele é salvo em disco e lido em páginas, com filtros e agregações.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

csv.field_size_limit(2**31 - 1)

EXTENSIONS = {"tsv": ".tsv", "csv": ".csv", "json": ".json", "xml": ".xml", "text": ".txt"}
FILTER_RE = re.compile(r"^\s*(.+?)\s*(>=|<=|!=|=|~|>|<)\s*(.*?)\s*$")


class ReportFileError(ValueError):
    pass


# --- gravação ---------------------------------------------------------------------


def decode(content: bytes, charset: str | None = None) -> str:
    for encoding in filter(None, [charset, "utf-8-sig", "cp1252"]):
        try:
            return content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace")


def detect_format(text: str) -> str:
    head = text.lstrip()[:1]
    if head in ("{", "["):
        return "json"
    if head == "<":
        return "xml"
    first_line = text.split("\n", 1)[0]
    if "\t" in first_line:
        return "tsv"
    if "," in first_line:
        return "csv"
    return "text"


def save_report(reports_dir: Path, report_type: str, report_id: str, text: str) -> tuple[Path, str]:
    fmt = detect_format(text)
    reports_dir.mkdir(parents=True, exist_ok=True)
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", report_id)
    path = reports_dir / f"{report_type}_{safe_id}{EXTENSIONS[fmt]}"
    path.write_text(text, encoding="utf-8")
    return path, fmt


def resolve_file(reports_dir: Path, name: str) -> Path:
    """Aceita apenas arquivos dentro da pasta de relatórios."""
    path = (reports_dir / Path(name).name).resolve()
    if path.parent != reports_dir.resolve() or not path.is_file():
        disponiveis = ", ".join(p.name for p in list_files(reports_dir)[:20]) or "nenhum"
        raise ReportFileError(f"Arquivo {name!r} não encontrado na pasta de relatórios. Disponíveis: {disponiveis}")
    return path


def list_files(reports_dir: Path) -> list[Path]:
    if not reports_dir.is_dir():
        return []
    return sorted((p for p in reports_dir.iterdir() if p.is_file()), key=lambda p: p.stat().st_mtime, reverse=True)


# --- leitura em linhas -------------------------------------------------------------


def format_of(path: Path) -> str:
    return {v: k for k, v in EXTENSIONS.items()}.get(path.suffix, "text")


def load_rows(path: Path, json_path: str | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    """Carrega o relatório como tabela: (colunas, linhas). JSON é achatado com chaves 'a.b.c'."""
    fmt = format_of(path)
    text = path.read_text(encoding="utf-8")
    if fmt in ("tsv", "csv"):
        if fmt == "tsv":
            reader = csv.reader(io.StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE)
        else:
            reader = csv.reader(io.StringIO(text))
        header = next(reader, [])
        header = [h.strip().lstrip("﻿") for h in header]
        rows = [dict(zip(header, (v.strip() for v in row))) for row in reader if any(v.strip() for v in row)]
        return header, rows
    if fmt == "json":
        node = navigate(json.loads(text), json_path)
        if isinstance(node, dict):
            node = [node]
        if not isinstance(node, list):
            raise ReportFileError("O caminho JSON informado não aponta para uma lista ou objeto.")
        rows = [flatten(item) if isinstance(item, dict) else {"valor": item} for item in node]
        columns: dict[str, None] = {}
        for row in rows:
            columns.update(dict.fromkeys(row))
        return list(columns), rows
    raise ReportFileError(f"Relatórios no formato {fmt} não podem ser lidos como tabela; use ler_relatorio_bruto.")


def navigate(data: Any, json_path: str | None) -> Any:
    if not json_path:
        return data
    for part in json_path.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            chaves = list(data)[:30] if isinstance(data, dict) else f"lista com {len(data)} itens" if isinstance(data, list) else type(data).__name__
            raise ReportFileError(f"Caminho JSON inválido em {part!r}. Opções neste nível: {chaves}")
    return data


def flatten(obj: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in obj.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(flatten(value, f"{name}."))
        elif isinstance(value, list) and all(not isinstance(v, (dict, list)) for v in value):
            out[name] = ", ".join(str(v) for v in value)
        elif isinstance(value, list):
            out[name] = json.dumps(value, ensure_ascii=False)
        else:
            out[name] = value
    return out


def json_outline(data: Any, depth: int = 0, max_depth: int = 3) -> Any:
    """Estrutura resumida de um JSON (chaves e tamanhos de listas), para orientar a navegação."""
    if isinstance(data, dict):
        if depth >= max_depth:
            return f"objeto com {len(data)} chaves"
        return {k: json_outline(v, depth + 1, max_depth) for k, v in data.items()}
    if isinstance(data, list):
        if not data:
            return "lista vazia"
        return {f"lista com {len(data)} itens, exemplo do primeiro": json_outline(data[0], depth + 1, max_depth)}
    return data


# --- filtros e agregação ---------------------------------------------------------------


def parse_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    s = re.sub(r"[^\d,.\-]", "", str(value))
    if not s or not re.search(r"\d", s):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):  # 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:  # 1,234.56
            s = s.replace(",", "")
    elif "," in s:
        integer, _, decimals = s.rpartition(",")
        s = s.replace(",", "") if s.count(",") > 1 or len(decimals) == 3 else f"{integer.replace(',', '')}.{decimals}"
    try:
        return float(s)
    except ValueError:
        return None


def check_columns(requested: list[str], columns: list[str]) -> None:
    unknown = [c for c in requested if c not in columns]
    if unknown:
        raise ReportFileError(f"Colunas inexistentes: {unknown}. Colunas: {columns}")


def parse_filters(filters: Iterable[str] | None, columns: list[str]) -> list[tuple[str, str, str]]:
    parsed = []
    for f in filters or []:
        m = FILTER_RE.match(f)
        if not m:
            raise ReportFileError(f"Filtro inválido: {f!r}. Use 'coluna=valor', 'coluna~texto', 'coluna>10' etc.")
        column, op, value = m.groups()
        check_columns([column], columns)
        parsed.append((column, op, value))
    return parsed


def matches(row: dict[str, Any], filters: list[tuple[str, str, str]]) -> bool:
    for column, op, expected in filters:
        actual = row.get(column)
        text = "" if actual is None else str(actual)
        if op == "=" and text.casefold() != expected.casefold():
            return False
        if op == "!=" and text.casefold() == expected.casefold():
            return False
        if op == "~" and expected.casefold() not in text.casefold():
            return False
        if op in (">", "<", ">=", "<="):
            a, b = parse_number(actual), parse_number(expected)
            if a is None or b is None:
                # Comparação textual (útil para datas ISO, ex.: purchase-date>=2026-09-01)
                a, b = text, expected  # type: ignore[assignment]
            if not {">": a > b, "<": a < b, ">=": a >= b, "<=": a <= b}[op]:  # type: ignore[operator]
                return False
    return True


def select(row: dict[str, Any], columns: list[str] | None) -> dict[str, Any]:
    return {c: row.get(c) for c in columns} if columns else row


def aggregate(rows: list[dict[str, Any]], group_by: list[str], sum_columns: list[str]) -> list[dict[str, Any]]:
    groups: dict[tuple, dict[str, Any]] = defaultdict(lambda: {"_linhas": 0, **{c: 0.0 for c in sum_columns}})
    for row in rows:
        key = tuple(row.get(c) for c in group_by)
        acc = groups[key]
        acc["_linhas"] += 1
        for c in sum_columns:
            acc[c] += parse_number(row.get(c)) or 0.0
    result = [{**dict(zip(group_by, key)), **{k: round(v, 4) if isinstance(v, float) else v for k, v in acc.items()}}
              for key, acc in groups.items()]
    sort_key = sum_columns[0] if sum_columns else "_linhas"
    result.sort(key=lambda r: r[sort_key], reverse=True)
    return result
