import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from amazon_seller_mcp import files, server
from amazon_seller_mcp.client import SPAPIClient
from amazon_seller_mcp.config import Config

MKT = "A2Q3Y263D00KWC"


def _date(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")


ORDERS = "\n".join([
    "amazon-order-id\tpurchase-date\torder-status\tsku",
    f"701-0000001\t{_date(10)}\tShipped - Delivered to Buyer\tA",
    f"701-0000001\t{_date(10)}\tShipped - Delivered to Buyer\tB",  # mesmo pedido, 2 itens
    f"701-0000002\t{_date(12)}\tShipped\tA",
    f"701-0000003\t{_date(8)}\tShipped - Delivered to Buyer\tA",   # Amazon dirá que não é elegível
    f"701-0000004\t{_date(1)}\tShipped\tA",                         # recente demais
    f"701-0000005\t{_date(50)}\tShipped - Delivered to Buyer\tA",  # antigo demais
    f"701-0000006\t{_date(9)}\tCancelled\tA",
    f"701-0000007\t{_date(9)}\tShipped - Returned to Seller\tA",
]) + "\n"


class FakeSolicitations:
    def __init__(self, deny=False):
        self.deny = deny
        self.sent: list[str] = []
        self.checked: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.amazon.com":
            return httpx.Response(200, json={"access_token": "Atza|t", "expires_in": 3600})
        if self.deny:
            return httpx.Response(403, json={"errors": [{"code": "Unauthorized"}]})
        assert request.url.params["marketplaceIds"] == MKT
        parts = request.url.path.split("/")
        order = parts[4]
        if request.method == "GET":
            self.checked.append(order)
            actions = [] if order == "701-0000003" else [{
                "href": f"/solicitations/v1/orders/{order}/solicitations/productReviewAndSellerFeedback",
                "name": "productReviewAndSellerFeedback"}]
            return httpx.Response(200, json={"_links": {"actions": actions, "self": {"href": "x"}}})
        assert parts[-1] == "productReviewAndSellerFeedback"
        self.sent.append(order)
        return httpx.Response(201, content=b"")


@pytest.fixture
def setup(tmp_path, monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    (tmp_path / "pedidos.tsv").write_text(ORDERS, encoding="utf-8")

    def make(fake):
        config = Config("id", "secret", "refresh", "na", (MKT,), tmp_path)
        client = SPAPIClient(config, http=httpx.AsyncClient(transport=httpx.MockTransport(fake)))
        monkeypatch.setattr(server, "_client", client)
    return make


def test_previa_conta_elegiveis_sem_enviar(setup):
    fake = FakeSolicitations()
    setup(fake)
    r = asyncio.run(server.solicitar_avaliacoes(arquivo_pedidos="pedidos.tsv"))
    assert r["pedidos_encontrados"] == 3
    assert r["resultado"] == {"enviado": 0, "elegivel": 2, "nao_elegivel": 1}
    assert fake.sent == []


def test_envia_registra_e_nao_repete(setup, tmp_path):
    fake = FakeSolicitations()
    setup(fake)
    r = asyncio.run(server.solicitar_avaliacoes(arquivo_pedidos="pedidos.tsv", confirmar=True))
    assert r["resultado"]["enviado"] == 2
    assert sorted(fake.sent) == ["701-0000001", "701-0000002"]
    _, rows = files.load_rows(tmp_path / server.REVIEW_LOG)
    assert {row["pedido"] for row in rows} == {"701-0000001", "701-0000002"}

    fake2 = FakeSolicitations()
    setup(fake2)
    r = asyncio.run(server.solicitar_avaliacoes(arquivo_pedidos="pedidos.tsv", pedidos=["701-0000002"], confirmar=True))
    assert r["ja_solicitados_antes"] == 2
    assert fake2.sent == [] and fake2.checked == ["701-0000003"]


def test_limite_e_restantes(setup):
    setup(FakeSolicitations())
    r = asyncio.run(server.solicitar_avaliacoes(pedidos=["701-A", "701-B", "701-C"], limite=2))
    assert r["verificados_agora"] == 2 and r["faltam_verificar"] == 1


def test_sem_permissao(setup):
    setup(FakeSolicitations(deny=True))
    r = asyncio.run(server.solicitar_avaliacoes(pedidos=["701-A"]))
    assert "Buyer Solicitation" in r["dica"]


def test_entrada_obrigatoria(setup):
    setup(FakeSolicitations())
    with pytest.raises(ValueError):
        asyncio.run(server.solicitar_avaliacoes())
