import asyncio
import json

import httpx
import pytest

from amazon_seller_mcp import files, listings, server
from amazon_seller_mcp.client import SPAPIClient
from amazon_seller_mcp.config import Config

MKT = "A2Q3Y263D00KWC"
SELLER = "A1MEART0000"


def listing(price, sku, discounted=True):
    offer = {"marketplace_id": MKT, "currency": "BRL", "audience": "ALL",
             "our_price": [{"schedule": [{"value_with_tax": price}]}]}
    if discounted:
        offer["discounted_price"] = [{"schedule": [{"value_with_tax": price - 1, "start_at": "2026-11-01"}]}]
    return {"sku": sku,
            "summaries": [{"marketplaceId": MKT, "asin": "B09WVHMPNQ", "productType": "OFFICE_PRODUCTS",
                           "itemName": "ELII marcadores Morandi 1200 peças"}],
            "attributes": {"purchasable_offer": [offer], "item_name": [{"value": "ELII"}]},
            "issues": []}


class FakeListings:
    def __init__(self, deny=False):
        self.deny = deny
        self.prices = {"ZD/LKCD MJKW": 62.9, "U6-20LJ-JO0E": 29.9}
        self.patches: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazon.com":
            return httpx.Response(200, json={"access_token": "Atza|token", "expires_in": 3600})
        if self.deny:
            return httpx.Response(403, json={"errors": [{"code": "Unauthorized"}]})
        prefix = f"/listings/2021-08-01/items/{SELLER}/"
        raw = request.url.raw_path.decode().split("?")[0]
        assert raw.startswith(prefix), raw
        sku = httpx.URL(f"http://x/{raw[len(prefix):]}").path[1:]
        assert request.url.params["marketplaceIds"] == MKT
        if sku not in self.prices:
            return httpx.Response(404, json={"errors": [{"code": "NOT_FOUND"}]})
        if request.method == "GET":
            assert "attributes" in request.url.params["includedData"]
            return httpx.Response(200, json=listing(self.prices[sku], sku))
        body = json.loads(request.content)
        self.patches.append((sku, body))
        new = body["patches"][0]["value"][0]["our_price"][0]["schedule"][0]["value_with_tax"]
        self.prices[sku] = new
        return httpx.Response(200, json={"sku": sku, "status": "ACCEPTED", "submissionId": "S1", "issues": []})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def make(fake, seller=SELLER):
        config = Config("id", "secret", "refresh", "na", (MKT,), tmp_path, seller_id=seller)
        client = SPAPIClient(config, http=httpx.AsyncClient(transport=httpx.MockTransport(fake)))
        monkeypatch.setattr(server, "_client", client)
        return client
    return make


def test_previa_nao_altera_nada(setup):
    fake = FakeListings()
    setup(fake)
    result = asyncio.run(server.alterar_precos([{"sku": "ZD/LKCD MJKW", "preco": "53,80"}]))

    assert fake.patches == []
    item = result["itens"][0]
    assert item["situacao"] == "previa"
    assert item["preco_atual"] == 62.9 and item["preco_novo"] == 53.8
    assert item["variacao_pct"] == -14.5
    assert not any(k.startswith("_") for k in item)
    assert "confirmar=true" in result["proximo_passo"]


def test_confirmar_envia_mantem_outros_campos_e_registra(setup, tmp_path):
    fake = FakeListings()
    setup(fake)
    result = asyncio.run(server.alterar_precos(
        [{"sku": "ZD/LKCD MJKW", "preco": 53.8}, {"sku": "U6-20LJ-JO0E", "preco": 32.9}], confirmar=True))

    assert result["resumo"] == {"enviado": 2}
    sku, body = fake.patches[0]
    assert sku == "ZD/LKCD MJKW"  # SKU com barra/espaço é codificado na URL
    assert body["productType"] == "OFFICE_PRODUCTS"
    offer = body["patches"][0]["value"][0]
    assert offer["our_price"][0]["schedule"][0]["value_with_tax"] == 53.8
    assert offer["discounted_price"][0]["schedule"][0]["start_at"] == "2026-11-01"  # promoção preservada
    assert offer["currency"] == "BRL" and offer["audience"] == "ALL"

    columns, rows = files.load_rows(tmp_path / listings.LOG_NAME)
    assert columns[0] == "data_hora"
    assert [(r["sku"], r["preco_anterior"], r["preco_novo"], r["status"]) for r in rows] == [
        ("ZD/LKCD MJKW", "62.9", "53.8", "ACCEPTED"), ("U6-20LJ-JO0E", "29.9", "32.9", "ACCEPTED")]


def test_variacao_grande_bloqueada_sem_permissao(setup):
    fake = FakeListings()
    setup(fake)
    result = asyncio.run(server.alterar_precos([{"sku": "ZD/LKCD MJKW", "preco": 40}], confirmar=True))
    assert fake.patches == []
    assert result["itens"][0]["situacao"] == "bloqueado"
    assert "25%" in result["itens"][0]["motivo"]

    result = asyncio.run(server.alterar_precos([{"sku": "ZD/LKCD MJKW", "preco": 40}], confirmar=True,
                                               permitir_variacao_grande=True))
    assert result["itens"][0]["situacao"] == "enviado"


def test_erros_por_item_e_configuracao(setup):
    setup(FakeListings())
    result = asyncio.run(server.alterar_precos([{"sku": "NAO-EXISTE", "preco": 10}, {"sku": "U6-20LJ-JO0E", "preco": 31}]))
    situacoes = {i["sku"]: i["situacao"] for i in result["itens"]}
    assert situacoes == {"NAO-EXISTE": "erro", "U6-20LJ-JO0E": "previa"}
    assert "não encontrado" in result["itens"][0]["dica"]

    setup(FakeListings(deny=True))
    result = asyncio.run(server.alterar_precos([{"sku": "U6-20LJ-JO0E", "preco": 31}]))
    assert "Product Listing" in result["itens"][0]["dica"]

    setup(FakeListings(), seller=None)
    assert "SPAPI_SELLER_ID" in asyncio.run(server.alterar_precos([{"sku": "X", "preco": 1}]))["erro"]

    setup(FakeListings())
    with pytest.raises(ValueError, match="repetidos"):
        asyncio.run(server.alterar_precos([{"sku": "A", "preco": 1}, {"sku": "A", "preco": 2}]))
    with pytest.raises(ValueError, match="Preço inválido"):
        asyncio.run(server.alterar_precos([{"sku": "A", "preco": "abc"}]))


def test_patch_cria_oferta_quando_nao_existe():
    patches = listings.price_patch({}, MKT, 19.9, "BRL")
    assert patches[0]["value"] == [{"marketplace_id": MKT, "currency": "BRL",
                                    "our_price": [{"schedule": [{"value_with_tax": 19.9}]}]}]
    assert listings.current_price({}, MKT) == (None, None)
