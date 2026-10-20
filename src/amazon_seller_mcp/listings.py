"""Alteração de preço pela Listings Items API 2021-08-01, com prévia, limites e registro em CSV."""

from __future__ import annotations

import copy
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_NAME = "alteracoes_preco.csv"
LOG_COLUMNS = ["data_hora", "sku", "asin", "marketplace", "preco_anterior", "preco_novo", "variacao_pct",
               "status", "submission_id", "problemas"]


def current_price(attributes: dict[str, Any], marketplace_id: str) -> tuple[float | None, str | None]:
    """Lê o preço atual (our_price) e a moeda do atributo purchasable_offer."""
    offer = _offer_for(attributes, marketplace_id)
    if not offer:
        return None, None
    for price in offer.get("our_price") or []:
        for item in price.get("schedule") or []:
            value = item.get("value_with_tax")
            if value is not None:
                try:
                    return round(float(value), 2), offer.get("currency")
                except (TypeError, ValueError):
                    pass
    return None, offer.get("currency")


def price_patch(attributes: dict[str, Any], marketplace_id: str, new_price: float, currency: str) -> list[dict[str, Any]]:
    """Monta o patch de purchasable_offer trocando só o our_price e mantendo os demais campos da oferta
    (preço promocional, preço mínimo/máximo etc.)."""
    offers = copy.deepcopy(attributes.get("purchasable_offer") or [])
    target = _offer_for({"purchasable_offer": offers}, marketplace_id)
    if target is None:
        target = {"marketplace_id": marketplace_id, "currency": currency}
        offers.append(target)
    target.setdefault("currency", currency)
    target["our_price"] = [{"schedule": [{"value_with_tax": round(new_price, 2)}]}]
    return [{"op": "replace", "path": "/attributes/purchasable_offer", "value": offers}]


def summary(item: dict[str, Any], marketplace_id: str) -> dict[str, Any]:
    for s in item.get("summaries") or []:
        if s.get("marketplaceId") == marketplace_id:
            return s
    return (item.get("summaries") or [{}])[0]


def issues_text(issues: list[dict[str, Any]] | None) -> list[str]:
    return [f"{i.get('severity', '')} {i.get('code', '')}: {i.get('message', '')}".strip() for i in issues or []]


def append_log(folder: Path, row: dict[str, Any]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / LOG_NAME
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow({k: row.get(k, "") for k in LOG_COLUMNS})
    return path


def now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def _offer_for(attributes: dict[str, Any], marketplace_id: str) -> dict[str, Any] | None:
    offers = [o for o in attributes.get("purchasable_offer") or [] if isinstance(o, dict)]
    for o in offers:
        if o.get("marketplace_id") == marketplace_id and o.get("audience", "ALL") == "ALL":
            return o
    return next((o for o in offers if o.get("marketplace_id") == marketplace_id), None)
