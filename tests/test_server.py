import asyncio
import gzip
import json

import httpx
import pytest

from amazon_seller_mcp import files, server
from amazon_seller_mcp.client import SPAPIClient
from amazon_seller_mcp.config import Config

ORDERS_TSV = (
    "amazon-order-id\tsku\tproduct-name\tquantity\titem-price\tpurchase-date\n"
    "111-1\tCAMISA-P\tCamisa \"básica\" P\t2\t1.234,50\t2026-09-02T10:00:00Z\n"
    "111-2\tCAMISA-M\tCamisa básica M\t1\t59,90\t2026-09-03T10:00:00Z\n"
    "111-3\tCAMISA-P\tCamisa \"básica\" P\t1\t617,25\t2026-09-05T10:00:00Z\n"
)


class FakeAmazon:
    def __init__(self, document: bytes, restricted: bool = False):
        self.document = document
        self.restricted = restricted
        self.polls = 0
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path))
        if request.url.host == "api.amazon.com":
            assert b"grant_type=refresh_token" in request.content
            return httpx.Response(200, json={"access_token": "Atza|token", "expires_in": 3600})
        if request.url.host == "s3.example.com":
            return httpx.Response(200, content=self.document)
        token = request.headers["x-amz-access-token"]
        if path == "/reports/2021-06-30/reports" and request.method == "POST":
            body = json.loads(request.content)
            assert body["marketplaceIds"] == ["A2Q3Y263D00KWC"]
            return httpx.Response(202, json={"reportId": "R1"})
        if path == "/reports/2021-06-30/reports/R1":
            self.polls += 1
            if self.polls == 1:
                return httpx.Response(429, headers={"retry-after": "0"}, json={"errors": []})
            status = "IN_PROGRESS" if self.polls == 2 else "DONE"
            return httpx.Response(200, json={
                "reportId": "R1", "reportType": "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL",
                "processingStatus": status, **({"reportDocumentId": "D1"} if status == "DONE" else {}),
            })
        if path == "/tokens/2021-03-01/restrictedDataToken":
            return httpx.Response(200, json={"restrictedDataToken": "Atz.rdt", "expiresIn": 3600})
        if path == "/reports/2021-06-30/documents/D1":
            if self.restricted and token != "Atz.rdt":
                return httpx.Response(403, json={"errors": [{"code": "Unauthorized"}]})
            return httpx.Response(200, json={"reportDocumentId": "D1", "url": "https://s3.example.com/doc",
                                             "compressionAlgorithm": "GZIP"})
        return httpx.Response(404, json={"path": path})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    def make(fake: FakeAmazon) -> SPAPIClient:
        config = Config("id", "secret", "refresh", "na", ("A2Q3Y263D00KWC",), tmp_path)
        client = SPAPIClient(config, http=httpx.AsyncClient(transport=httpx.MockTransport(fake)))
        monkeypatch.setattr(server, "_client", client)
        return client
    return make


def test_gerar_relatorio_fluxo_completo_com_token_restrito(setup, monkeypatch):
    fake = FakeAmazon(gzip.compress(ORDERS_TSV.encode("cp1252")), restricted=True)
    client = setup(fake)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    result = asyncio.run(server.gerar_relatorio("get_flat_file_all_orders_data_by_order_date_general",
                                                data_inicio="2026-09-01T00:00:00Z"))

    assert result["formato"] == "tsv"
    assert result["total_linhas"] == 3
    assert result["primeiras_linhas"][0]["product-name"] == 'Camisa "básica" P'
    assert ("POST", "/tokens/2021-03-01/restrictedDataToken") in fake.calls
    # o token LWA é reaproveitado entre chamadas
    assert sum(1 for c in fake.calls if c[1] == "/auth/o2/token") == 1
    assert client.config.reports_dir.joinpath(result["arquivo"]).is_file()

    lidos = server.ler_relatorio(result["arquivo"], filtros=["sku=camisa-p", "purchase-date>=2026-09-03"],
                                 colunas=["amazon-order-id", "quantity"])
    assert lidos["linhas"] == [{"amazon-order-id": "111-3", "quantity": "1"}]

    agregado = server.agregar_relatorio(result["arquivo"], agrupar_por=["sku"], somar=["quantity", "item-price"])
    assert agregado["grupos"][0] == {"sku": "CAMISA-P", "_linhas": 2, "quantity": 3.0, "item-price": 1851.75}


def test_relatorio_de_liquidacao_nao_pode_ser_solicitado(setup):
    setup(FakeAmazon(b""))
    with pytest.raises(ValueError, match="automaticamente"):
        asyncio.run(server.solicitar_relatorio("GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2"))


def test_json_achatado_e_caminho(tmp_path):
    data = {"salesAndTrafficByAsin": [
        {"parentAsin": "B01", "salesByAsin": {"unitsOrdered": 3, "orderedProductSales": {"amount": 30.5}}},
        {"parentAsin": "B02", "salesByAsin": {"unitsOrdered": 1, "orderedProductSales": {"amount": 9.5}}},
    ]}
    path, fmt = files.save_report(tmp_path, "GET_SALES_AND_TRAFFIC_REPORT", "R2", json.dumps(data))
    assert fmt == "json"
    columns, rows = files.load_rows(path, "salesAndTrafficByAsin")
    assert "salesByAsin.orderedProductSales.amount" in columns
    total = files.aggregate(rows, [], ["salesByAsin.orderedProductSales.amount"])
    assert total[0]["salesByAsin.orderedProductSales.amount"] == 40.0
    with pytest.raises(files.ReportFileError, match="salesAndTrafficByAsin"):
        files.load_rows(path, "naoExiste")


@pytest.mark.parametrize("raw,expected", [
    ("1.234,56", 1234.56), ("1,234.56", 1234.56), ("59,90", 59.9), ("1,234", 1234.0),
    ("R$ 10.00", 10.0), ("-3.5", -3.5), ("", None), ("abc", None),
])
def test_parse_number(raw, expected):
    assert files.parse_number(raw) == expected


def test_arquivo_fora_da_pasta_e_recusado(tmp_path):
    (tmp_path / "ok.tsv").write_text("a\n1\n")
    with pytest.raises(files.ReportFileError):
        files.resolve_file(tmp_path / "sub", "../ok.tsv")


async def _no_sleep(_seconds):
    return None
