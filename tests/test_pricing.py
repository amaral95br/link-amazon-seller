import asyncio

import httpx
import pytest

from amazon_seller_mcp import pricing, server
from amazon_seller_mcp.client import SPAPIClient
from amazon_seller_mcp.config import Config

MKT = "A2Q3Y263D00KWC"


def _money(amount):
    return {"CurrencyCode": "BRL", "Amount": amount}


def competitive(asin, buy_box=None, mine=False, offers=3, rank=1500):
    prices = []
    if buy_box is not None:
        prices.append({"CompetitivePriceId": "1", "condition": "New", "belongsToRequester": mine,
                       "Price": {"LandedPrice": _money(buy_box), "ListingPrice": _money(buy_box - 5),
                                 "Shipping": _money(5)}})
    return {"status": "Success", "ASIN": asin, "Product": {
        "Identifiers": {"MarketplaceASIN": {"MarketplaceId": MKT, "ASIN": asin}},
        "CompetitivePricing": {"CompetitivePrices": prices,
                               "NumberOfOfferListings": [{"condition": "New", "Count": offers}]},
        "SalesRankings": [{"ProductCategoryId": "office_product_display_on_website", "Rank": rank}],
    }}


class FakePricing:
    def __init__(self, deny=False):
        self.deny = deny
        self.batches: list[list[str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazon.com":
            return httpx.Response(200, json={"access_token": "Atza|token", "expires_in": 3600})
        if self.deny:
            return httpx.Response(403, json={"errors": [{"code": "Unauthorized",
                                                         "message": "Access to requested resource is denied."}]})
        path, q = request.url.path, request.url.params
        assert q["MarketplaceId"] == MKT
        if path == "/products/pricing/v0/competitivePrice":
            assert q["ItemType"] == "Asin"
            asins = q["Asins"].split(",")
            self.batches.append(asins)
            payload = []
            for i, a in enumerate(asins):
                if a == "B0ERRO0000":
                    payload.append({"status": "ClientError", "ASIN": a,
                                    "error": {"code": "InvalidInput", "message": "ASIN inválido"}})
                elif a == "B0SEMOFERT":
                    payload.append(competitive(a, buy_box=None, offers=0))
                else:
                    payload.append(competitive(a, buy_box=30.0 + i, mine=(a == "B0MEU00000")))
            return httpx.Response(200, json={"payload": payload})
        if path == "/products/pricing/v0/items/B0H3LL9QS3/offers":
            assert q["ItemCondition"] == "New"
            return httpx.Response(200, json={"payload": {
                "ASIN": "B0H3LL9QS3", "status": "Success", "ItemCondition": "New",
                "Summary": {
                    "TotalOfferCount": 2,
                    "BuyBoxPrices": [{"condition": "New", "LandedPrice": _money(49.9),
                                      "ListingPrice": _money(49.9), "Shipping": _money(0)}],
                    "LowestPrices": [
                        {"condition": "new", "fulfillmentChannel": "Amazon", "LandedPrice": _money(49.9),
                         "ListingPrice": _money(49.9), "Shipping": _money(0)},
                        {"condition": "new", "fulfillmentChannel": "Merchant", "LandedPrice": _money(52.0),
                         "ListingPrice": _money(39.0), "Shipping": _money(13.0)},
                    ],
                    "SalesRankings": [{"ProductCategoryId": "office_product_display_on_website", "Rank": 210}],
                },
                "Offers": [
                    {"SubCondition": "new", "ListingPrice": _money(39.0), "Shipping": _money(13.0),
                     "IsFulfilledByAmazon": False, "IsBuyBoxWinner": False,
                     "PrimeInformation": {"IsPrime": False},
                     "SellerFeedbackRating": {"SellerPositiveFeedbackRating": 91, "FeedbackCount": 40}},
                    {"SubCondition": "new", "ListingPrice": _money(49.9), "Shipping": _money(0),
                     "IsFulfilledByAmazon": True, "IsBuyBoxWinner": True, "MyOffer": False,
                     "PrimeInformation": {"IsPrime": True},
                     "SellerFeedbackRating": {"SellerPositiveFeedbackRating": 98, "FeedbackCount": 1200}},
                ],
            }})
        if path == "/products/pricing/v0/price":
            assert q["ItemType"] == "Sku"
            return httpx.Response(200, json={"payload": [{
                "status": "Success", "SellerSKU": "MEART-CAD-01",
                "Product": {"Identifiers": {"MarketplaceASIN": {"MarketplaceId": MKT, "ASIN": "B0MEU00000"}},
                            "Offers": [{"BuyingPrice": {"ListingPrice": _money(42.0), "LandedPrice": _money(42.0),
                                                        "Shipping": _money(0)},
                                        "RegularPrice": _money(45.0), "FulfillmentChannel": "AMAZON",
                                        "ItemCondition": "New", "SellerSKU": "MEART-CAD-01"}]},
            }]})
        return httpx.Response(404, json={"path": path})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def make(fake):
        config = Config("id", "secret", "refresh", "na", (MKT,), tmp_path)
        client = SPAPIClient(config, http=httpx.AsyncClient(transport=httpx.MockTransport(fake)))
        monkeypatch.setattr(server, "_client", client)
        return client
    return make


def test_precos_asins_em_lotes_de_20_com_erros_por_item(setup):
    fake = FakePricing()
    setup(fake)
    asins = [f"B0TEST{i:04d}" for i in range(23)] + ["B0MEU00000", "B0ERRO0000", "B0SEMOFERT", "b0test0001 "]

    result = asyncio.run(server.precos_asins(asins))

    assert [len(b) for b in fake.batches] == [20, 6]  # duplicado (minúsculo/espaço) removido
    assert result["total"] == 26
    primeiro = result["itens"][0]
    assert primeiro["buy_box"] == {"preco": 25.0, "frete": 5.0, "preco_total": 30.0, "moeda": "BRL"}
    assert primeiro["ofertas_por_condicao"] == {"new": 3}
    assert primeiro["ranking_vendas"] == [{"categoria": "office_product_display_on_website", "posicao": 1500}]
    por_asin = {i["asin"]: i for i in result["itens"]}
    assert por_asin["B0MEU00000"]["buy_box_e_minha"] is True
    assert por_asin["B0ERRO0000"]["erro"] == "InvalidInput — ASIN inválido"
    assert por_asin["B0SEMOFERT"]["buy_box"] is None and "observacao" in por_asin["B0SEMOFERT"]


def test_ofertas_asin_ordena_por_preco_total(setup):
    setup(FakePricing())
    result = asyncio.run(server.ofertas_asin("b0h3ll9qs3"))

    assert result["total_ofertas"] == 2
    assert result["buy_box"]["preco_total"] == 49.9
    assert {m["canal"] for m in result["menores_precos"]} == {"FBA", "FBM"}
    assert [o["preco_total"] for o in result["ofertas"]] == [49.9, 52.0]
    assert result["ofertas"][0]["ganha_buy_box"] is True and result["ofertas"][0]["prime"] is True
    assert result["ranking_vendas"][0]["posicao"] == 210


def test_meus_precos(setup):
    setup(FakePricing())
    result = asyncio.run(server.meus_precos(["MEART-CAD-01"]))
    item = result["itens"][0]
    assert item["asin"] == "B0MEU00000"
    assert item["preco_atual"]["preco_total"] == 42.0
    assert item["preco_regular"] == 45.0
    assert item["canal"] == "FBA"


def test_acesso_negado_vira_mensagem_com_dica(setup):
    setup(FakePricing(deny=True))
    result = asyncio.run(server.precos_asins(["B0H3LL9QS3"]))
    assert result["erro"] == "A Amazon respondeu 403"
    assert "Pricing" in result["dica"]
    assert result["itens_ja_consultados"] == []


def test_validacao_de_entrada(setup):
    setup(FakePricing())
    with pytest.raises(ValueError, match="ao menos um ASIN"):
        asyncio.run(server.precos_asins([" ", ""]))
    with pytest.raises(ValueError, match="Máximo de 200"):
        asyncio.run(server.precos_asins([f"B{i:09d}" for i in range(201)]))


def test_resposta_incompleta_nao_quebra():
    assert pricing.competitive_item({"ASIN": "B1"})["buy_box"] is None
    assert pricing.item_offers({"ASIN": "B1"})["ofertas"] == []
    assert pricing.own_price_item({"SellerSKU": "X", "Product": {}})["observacao"]
