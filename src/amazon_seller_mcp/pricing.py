"""Leitura das respostas da Product Pricing API v0 em formato simples (preço, Buy Box, ofertas, ranking)."""

from __future__ import annotations

from typing import Any

# CompetitivePriceId "1" = Buy Box de produto novo; "2" = Buy Box de usado.
BUY_BOX_NEW = "1"
CANAIS = {"amazon": "FBA", "merchant": "FBM"}


def _amount(money: dict[str, Any] | None) -> float | None:
    if not isinstance(money, dict):
        return None
    value = money.get("Amount")
    try:
        return round(float(value), 2) if value is not None else None
    except (TypeError, ValueError):
        return None


def _currency(*moneys: dict[str, Any] | None) -> str | None:
    for m in moneys:
        if isinstance(m, dict) and m.get("CurrencyCode"):
            return m["CurrencyCode"]
    return None


def _price_block(block: dict[str, Any] | None) -> dict[str, Any] | None:
    """Converte um bloco com LandedPrice/ListingPrice/Shipping em {preco, frete, preco_total, moeda}."""
    if not isinstance(block, dict):
        return None
    listing, shipping, landed = block.get("ListingPrice"), block.get("Shipping"), block.get("LandedPrice")
    preco, frete, total = _amount(listing), _amount(shipping), _amount(landed)
    if total is None and preco is not None:
        total = round(preco + (frete or 0.0), 2)
    if preco is None and total is None:
        return None
    return {"preco": preco, "frete": frete, "preco_total": total, "moeda": _currency(landed, listing, shipping)}


def _rankings(raw: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        {"categoria": r.get("ProductCategoryId"), "posicao": r.get("Rank")}
        for r in raw or []
        if isinstance(r, dict) and r.get("Rank") is not None
    ]


def _error(item: dict[str, Any]) -> str:
    err = item.get("error") or item.get("errors") or item.get("status")
    if isinstance(err, list):
        err = err[0] if err else None
    if isinstance(err, dict):
        return " — ".join(str(err[k]) for k in ("code", "message") if err.get(k)) or str(err)
    return str(err or "sem detalhes")


def competitive_item(item: dict[str, Any]) -> dict[str, Any]:
    """Resumo de um item de getCompetitivePricing: Buy Box, nº de ofertas e ranking de vendas."""
    asin = item.get("ASIN") or (item.get("Product", {}).get("Identifiers", {}).get("MarketplaceASIN", {}).get("ASIN"))
    if item.get("status") not in (None, "Success"):
        return {"asin": asin, "erro": _error(item)}
    product = item.get("Product") or {}
    pricing = product.get("CompetitivePricing") or {}
    prices = [p for p in pricing.get("CompetitivePrices") or [] if isinstance(p, dict)]

    buy_box = next((p for p in prices if str(p.get("CompetitivePriceId")) == BUY_BOX_NEW), None)
    if buy_box is None:
        buy_box = next((p for p in prices if str(p.get("condition", "")).lower() == "new"), None)

    ofertas = {
        str(o.get("condition", "?")).lower(): o.get("Count")
        for o in pricing.get("NumberOfOfferListings") or []
        if isinstance(o, dict)
    }
    result: dict[str, Any] = {
        "asin": asin,
        "buy_box": _price_block((buy_box or {}).get("Price")),
        "buy_box_e_minha": bool((buy_box or {}).get("belongsToRequester")) if buy_box else None,
        "ofertas_por_condicao": ofertas,
        "ranking_vendas": _rankings(product.get("SalesRankings")),
    }
    if result["buy_box"] is None:
        result["observacao"] = "Sem preço de Buy Box (produto sem estoque, sem oferta ativa ou Buy Box suprimida)."
    return result


def item_offers(payload: dict[str, Any], limite: int = 10) -> dict[str, Any]:
    """Resumo de getItemOffers: Buy Box, menores preços por canal e as ofertas mais baratas."""
    if payload.get("status") not in (None, "Success"):
        return {"asin": payload.get("ASIN"), "erro": _error(payload)}
    summary = payload.get("Summary") or {}

    buy_boxes = [b for b in summary.get("BuyBoxPrices") or [] if isinstance(b, dict)]
    buy_box = next((b for b in buy_boxes if str(b.get("condition", "")).lower() == "new"), buy_boxes[0] if buy_boxes else None)

    menores = []
    for low in summary.get("LowestPrices") or []:
        if not isinstance(low, dict):
            continue
        block = _price_block(low)
        if block:
            canal = str(low.get("fulfillmentChannel", "")).lower()
            menores.append({"condicao": low.get("condition"), "canal": CANAIS.get(canal, low.get("fulfillmentChannel")), **block})

    ofertas = []
    for offer in payload.get("Offers") or []:
        if not isinstance(offer, dict):
            continue
        block = _price_block(offer) or {}
        rating = offer.get("SellerFeedbackRating") or {}
        ofertas.append({
            **block,
            "fba": offer.get("IsFulfilledByAmazon"),
            "prime": (offer.get("PrimeInformation") or {}).get("IsPrime"),
            "ganha_buy_box": offer.get("IsBuyBoxWinner"),
            "e_minha": offer.get("MyOffer"),
            "condicao": offer.get("SubCondition"),
            "vendedor_avaliacao_positiva_pct": rating.get("SellerPositiveFeedbackRating"),
            "vendedor_qtd_avaliacoes": rating.get("FeedbackCount"),
        })
    ofertas.sort(key=lambda o: (o.get("preco_total") is None, o.get("preco_total") or 0.0))

    return {
        "asin": payload.get("ASIN"),
        "total_ofertas": summary.get("TotalOfferCount"),
        "buy_box": _price_block(buy_box),
        "menores_precos": menores,
        "ranking_vendas": _rankings(summary.get("SalesRankings")),
        "ofertas": ofertas[:max(1, limite)],
        "ofertas_omitidas": max(0, len(ofertas) - max(1, limite)),
    }


def own_price_item(item: dict[str, Any]) -> dict[str, Any]:
    """Resumo de um item de getPricing por SKU: o preço atual da sua própria oferta."""
    sku = item.get("SellerSKU")
    if item.get("status") not in (None, "Success"):
        return {"sku": sku, "erro": _error(item)}
    product = item.get("Product") or {}
    asin = (product.get("Identifiers") or {}).get("MarketplaceASIN", {}).get("ASIN")
    offers = [o for o in product.get("Offers") or [] if isinstance(o, dict)]
    if not offers:
        return {"sku": sku, "asin": asin, "observacao": "Nenhuma oferta ativa para este SKU."}
    offer = offers[0]
    canal = str(offer.get("FulfillmentChannel", "")).lower()
    return {
        "sku": sku,
        "asin": asin,
        "preco_atual": _price_block(offer.get("BuyingPrice")),
        "preco_regular": _amount(offer.get("RegularPrice")),
        "canal": CANAIS.get(canal, offer.get("FulfillmentChannel")),
        "condicao": offer.get("ItemCondition"),
    }
