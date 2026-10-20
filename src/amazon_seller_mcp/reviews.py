"""Pedido de avaliação (Solicitations API): seleção de pedidos, envio e registro.

Usado tanto pela ferramenta MCP solicitar_avaliacoes quanto pelo comando automático amazon-seller-avaliacoes.
"""

from __future__ import annotations

import asyncio
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import files, listings
from .client import SPAPIClient, SPAPIError

REVIEW_LOG = "avaliacoes_solicitadas.csv"
REVIEW_LOG_COLUMNS = ["data_hora", "pedido", "marketplace", "resultado"]
STATUS_ELEGIVEIS = ("shipped", "shipped - delivered to buyer", "shipped - picked up")
INTERVALO_SOLICITACOES = 1.1  # a Amazon permite ~1 chamada por segundo
DICA_PERMISSAO = ("Acesso negado. Marque o papel 'Buyer Solicitation' no aplicativo, gere um Refresh "
                  "Token novo e troque no .env.")


def already_requested(folder: Path) -> set[str]:
    path = folder / REVIEW_LOG
    if not path.is_file():
        return set()
    _, rows = files.load_rows(path)
    return {r["pedido"] for r in rows if r.get("resultado") in ("enviado", "ja_solicitado")}


def log_review(folder: Path, pedido: str, mkt: str, resultado: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / REVIEW_LOG
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_LOG_COLUMNS)
        if new:
            w.writeheader()
        w.writerow({"data_hora": listings.now(), "pedido": pedido, "marketplace": mkt, "resultado": resultado})


def orders_from_rows(columns: list[str], rows: list[dict[str, Any]], dias_min: int, dias_max: int,
                     nome: str = "arquivo") -> list[str]:
    """Pedidos enviados/entregues com data de compra entre dias_max e dias_min atrás, sem repetição."""
    for col in ("amazon-order-id", "purchase-date", "order-status"):
        if col not in columns:
            raise ValueError(f"O {nome} não parece um relatório de pedidos (falta a coluna {col}).")
    agora = datetime.now(timezone.utc)
    inicio, fim = agora - timedelta(days=dias_max), agora - timedelta(days=dias_min)
    pedidos: list[str] = []
    for r in rows:
        if r.get("order-status", "").strip().lower() not in STATUS_ELEGIVEIS:
            continue
        try:
            data = datetime.fromisoformat(r["purchase-date"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if inicio <= data <= fim and r["amazon-order-id"] not in pedidos:
            pedidos.append(r["amazon-order-id"])
    return pedidos


async def check_and_send(client: SPAPIClient, lote: list[str], mkt: str, folder: Path,
                         confirmar: bool) -> tuple[dict[str, int], list[dict[str, Any]], SPAPIError | None]:
    """Verifica a elegibilidade de cada pedido e, com confirmar=True, envia o pedido de avaliação.

    Retorna (contagem, erros por pedido, erro de permissão). Um 401/403 logo no primeiro pedido
    interrompe tudo, pois indica que o app não tem o papel Buyer Solicitation.
    """
    contagem = {"enviado": 0, "elegivel": 0, "nao_elegivel": 0, "erro": 0}
    detalhes: list[dict[str, Any]] = []
    for i, pedido in enumerate(lote):
        if i:
            await asyncio.sleep(INTERVALO_SOLICITACOES)
        try:
            if not await client.review_request_allowed(pedido, mkt):
                contagem["nao_elegivel"] += 1
                continue
            if not confirmar:
                contagem["elegivel"] += 1
                continue
            await asyncio.sleep(INTERVALO_SOLICITACOES)
            await client.request_review(pedido, mkt)
            contagem["enviado"] += 1
            log_review(folder, pedido, mkt, "enviado")
        except SPAPIError as e:
            if e.status in (401, 403) and i == 0:
                return contagem, detalhes, e
            contagem["erro"] += 1
            detalhes.append({"pedido": pedido, "erro": f"{e.status}", "detalhes": str(e.body)[:200]})
    return contagem, detalhes, None
