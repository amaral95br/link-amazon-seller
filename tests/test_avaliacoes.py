import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from amazon_seller_mcp import avaliacoes, files, reviews
from amazon_seller_mcp.client import SPAPIClient
from amazon_seller_mcp.config import Config

MKT = "A2Q3Y263D00KWC"


def _date(days_ago):
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S+00:00")


ORDERS = "\n".join([
    "amazon-order-id\tpurchase-date\torder-status\tsku",
    f"701-0000001\t{_date(10)}\tShipped - Delivered to Buyer\tA",
    f"701-0000002\t{_date(12)}\tShipped\tA",
    f"701-0000003\t{_date(8)}\tShipped - Delivered to Buyer\tA",  # Amazon dirá que não é elegível
    f"701-0000006\t{_date(9)}\tCancelled\tA",
]) + "\n"


class FakeAmazon:
    def __init__(self, orders=ORDERS, report_status="DONE", deny=False):
        self.orders = orders
        self.report_status = report_status
        self.deny = deny
        self.report_request: dict | None = None
        self.sent: list[str] = []
        self.checked: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "api.amazon.com":
            return httpx.Response(200, json={"access_token": "Atza|t", "expires_in": 3600})
        if request.url.host == "s3.example.com":
            return httpx.Response(200, content=self.orders.encode())
        if path == "/reports/2021-06-30/reports":
            self.report_request = json.loads(request.content)
            return httpx.Response(202, json={"reportId": "R9"})
        if path == "/reports/2021-06-30/reports/R9":
            extra = {"reportDocumentId": "D9"} if self.report_status == "DONE" else {}
            return httpx.Response(200, json={"reportId": "R9", "processingStatus": self.report_status, **extra})
        if path == "/reports/2021-06-30/documents/D9":
            return httpx.Response(200, json={"reportDocumentId": "D9", "url": "https://s3.example.com/d"})
        if path.startswith("/solicitations/v1/orders/"):
            if self.deny:
                return httpx.Response(403, json={"errors": [{"code": "Unauthorized"}]})
            order = path.split("/")[4]
            if request.method == "GET":
                self.checked.append(order)
                actions = [] if order == "701-0000003" else [{"name": "productReviewAndSellerFeedback", "href": "x"}]
                return httpx.Response(200, json={"_links": {"actions": actions}})
            self.sent.append(order)
            return httpx.Response(201, content=b"")
        return httpx.Response(404, json={"path": path})


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    async def no_sleep(_):
        return None
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    def make(fake):
        config = Config("id", "secret", "refresh", "na", (MKT,), tmp_path)
        return SPAPIClient(config, http=httpx.AsyncClient(transport=httpx.MockTransport(fake)))
    return make


def run(argv, client):
    return asyncio.run(avaliacoes.run(avaliacoes.parse_args(argv), client))


def test_simulacao_nao_envia(make_client, capsys):
    fake = FakeAmazon()
    assert run([], make_client(fake)) == 0
    assert fake.sent == []
    assert sorted(fake.checked) == ["701-0000001", "701-0000002", "701-0000003"]
    assert fake.report_request["reportType"] == avaliacoes.ORDERS_REPORT
    assert fake.report_request["marketplaceIds"] == [MKT]
    saida = capsys.readouterr().out
    assert "SIMULAÇÃO" in saida and "2 elegíveis" in saida
    assert "701-" not in saida  # números de pedido não aparecem nos logs


def test_envia_e_na_execucao_seguinte_nao_repete(make_client, tmp_path):
    fake = FakeAmazon()
    assert run(["--enviar"], make_client(fake)) == 0
    assert sorted(fake.sent) == ["701-0000001", "701-0000002"]
    assert reviews.already_requested(tmp_path) == {"701-0000001", "701-0000002"}

    fake2 = FakeAmazon()
    assert run(["--enviar"], make_client(fake2)) == 0
    assert fake2.sent == [] and fake2.checked == ["701-0000003"]


def test_limite_deixa_restante_para_depois(make_client, capsys):
    fake = FakeAmazon()
    assert run(["--enviar", "--limite", "1"], make_client(fake)) == 0
    assert len(fake.checked) == 1
    assert "Ficaram 2 pedidos" in capsys.readouterr().out


def test_sem_pedidos_no_periodo(make_client, capsys):
    fake = FakeAmazon(report_status="DONE_NO_DATA")
    assert run(["--enviar"], make_client(fake)) == 0
    assert fake.checked == []
    assert "Nenhum pedido" in capsys.readouterr().out


def test_relatorio_com_falha(make_client):
    assert run([], make_client(FakeAmazon(report_status="FATAL"))) == 1


def test_sem_papel_buyer_solicitation(make_client, capsys):
    assert run(["--enviar"], make_client(FakeAmazon(deny=True))) == 2
    assert "Buyer Solicitation" in capsys.readouterr().out


def test_periodo_maximo_de_30_dias():
    with pytest.raises(SystemExit):
        avaliacoes.parse_args(["--dias-min", "1", "--dias-max", "40"])


def test_relatorio_salvo_na_pasta(make_client, tmp_path):
    run([], make_client(FakeAmazon()))
    assert any(p.name.startswith(avaliacoes.ORDERS_REPORT) for p in files.list_files(tmp_path))
