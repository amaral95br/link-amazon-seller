"""Cliente HTTP da SP-API: autenticação LWA, tokens restritos (RDT), Reports API 2021-06-30 e Product Pricing v0."""

from __future__ import annotations

import asyncio
import gzip
import time
from typing import Any
from urllib.parse import quote

import httpx

from .config import Config

LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
REPORTS = "/reports/2021-06-30"
PRICING = "/products/pricing/v0"
LISTINGS = "/listings/2021-08-01"
SOLICITATIONS = "/solicitations/v1/orders"
REVIEW_ACTION = "productReviewAndSellerFeedback"
RETRY_STATUS = {429, 500, 502, 503, 504}


class SPAPIError(RuntimeError):
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        super().__init__(f"SP-API respondeu {status}: {body}")


class SPAPIClient:
    def __init__(self, config: Config, http: httpx.AsyncClient | None = None, max_retries: int = 5):
        self.config = config
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(60.0, read=300.0))
        self.max_retries = max_retries
        self._token: str | None = None
        self._token_expires = 0.0
        self._token_lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self.http.aclose()

    # --- autenticação -----------------------------------------------------

    async def access_token(self) -> str:
        async with self._token_lock:
            if self._token and time.monotonic() < self._token_expires - 60:
                return self._token
            resp = await self.http.post(
                LWA_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self.config.refresh_token,
                    "client_id": self.config.client_id,
                    "client_secret": self.config.client_secret,
                },
            )
            if resp.status_code != 200:
                raise SPAPIError(resp.status_code, _body(resp))
            data = resp.json()
            self._token = data["access_token"]
            self._token_expires = time.monotonic() + int(data.get("expires_in", 3600))
            return self._token

    async def restricted_data_token(self, path: str) -> str:
        """Token restrito (RDT) exigido para baixar relatórios com dados pessoais de compradores."""
        data = await self.request(
            "POST",
            "/tokens/2021-03-01/restrictedDataToken",
            json={"restrictedResources": [{"method": "GET", "path": path}]},
        )
        return data["restrictedDataToken"]

    # --- requisição genérica ----------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        token: str | None = None,
    ) -> Any:
        params = {k: _param(v) for k, v in (params or {}).items() if v is not None}
        for attempt in range(self.max_retries + 1):
            headers = {"x-amz-access-token": token or await self.access_token(), "accept": "application/json"}
            resp = await self.http.request(method, self.config.endpoint + path, params=params, json=json, headers=headers)
            if resp.status_code in RETRY_STATUS and attempt < self.max_retries:
                await asyncio.sleep(_retry_delay(resp, attempt))
                continue
            if resp.status_code >= 400:
                raise SPAPIError(resp.status_code, _body(resp))
            return resp.json() if resp.content else {}
        raise AssertionError("inalcançável")

    # --- Reports API --------------------------------------------------------

    async def create_report(self, report_type: str, marketplace_ids: list[str], data_start_time: str | None = None,
                            data_end_time: str | None = None, report_options: dict[str, str] | None = None) -> str:
        body: dict[str, Any] = {"reportType": report_type, "marketplaceIds": marketplace_ids}
        if data_start_time:
            body["dataStartTime"] = data_start_time
        if data_end_time:
            body["dataEndTime"] = data_end_time
        if report_options:
            body["reportOptions"] = report_options
        data = await self.request("POST", f"{REPORTS}/reports", json=body)
        return data["reportId"]

    async def get_reports(self, **params: Any) -> dict[str, Any]:
        return await self.request("GET", f"{REPORTS}/reports", params=params)

    async def get_report(self, report_id: str) -> dict[str, Any]:
        return await self.request("GET", f"{REPORTS}/reports/{report_id}")

    async def cancel_report(self, report_id: str) -> None:
        await self.request("DELETE", f"{REPORTS}/reports/{report_id}")

    async def get_report_schedules(self, report_types: list[str]) -> dict[str, Any]:
        return await self.request("GET", f"{REPORTS}/schedules", params={"reportTypes": report_types})

    async def get_report_document(self, document_id: str) -> dict[str, Any]:
        path = f"{REPORTS}/documents/{document_id}"
        try:
            return await self.request("GET", path)
        except SPAPIError as e:
            if e.status not in (400, 403):
                raise
            # Relatórios com dados pessoais (PII) só podem ser baixados com um token restrito.
            return await self.request("GET", path, token=await self.restricted_data_token(path))

    async def download_document(self, document: dict[str, Any]) -> tuple[bytes, str | None]:
        """Baixa o conteúdo do documento (URL pré-assinada), descompactando se necessário.

        Retorna os bytes e o charset informado pelo servidor, se houver.
        """
        resp = await self.http.get(document["url"])
        if resp.status_code != 200:
            raise SPAPIError(resp.status_code, resp.text[:500])
        content = resp.content
        if document.get("compressionAlgorithm") == "GZIP" or content[:2] == b"\x1f\x8b":
            content = gzip.decompress(content)
        return content, resp.charset_encoding

    # --- Product Pricing API v0 ------------------------------------------------------

    async def get_competitive_pricing(self, marketplace_id: str, asins: list[str]) -> list[dict[str, Any]]:
        """Buy Box, nº de ofertas e ranking de vendas de até 20 ASINs (de qualquer vendedor)."""
        data = await self.request("GET", f"{PRICING}/competitivePrice",
                                  params={"MarketplaceId": marketplace_id, "ItemType": "Asin", "Asins": asins})
        return data.get("payload") or []

    async def get_item_offers(self, marketplace_id: str, asin: str, condition: str = "New") -> dict[str, Any]:
        """Todas as ofertas de um ASIN (até 20), com resumo de Buy Box e menores preços."""
        data = await self.request("GET", f"{PRICING}/items/{asin}/offers",
                                  params={"MarketplaceId": marketplace_id, "ItemCondition": condition})
        return data.get("payload") or {}

    async def get_own_pricing(self, marketplace_id: str, skus: list[str]) -> list[dict[str, Any]]:
        """Preço atual das suas próprias ofertas, por SKU (até 20)."""
        data = await self.request("GET", f"{PRICING}/price",
                                  params={"MarketplaceId": marketplace_id, "ItemType": "Sku", "Skus": skus})
        return data.get("payload") or []

    # --- Listings Items API 2021-08-01 -------------------------------------------------

    async def get_listing(self, seller_id: str, sku: str, marketplace_id: str) -> dict[str, Any]:
        return await self.request("GET", f"{LISTINGS}/items/{quote(seller_id, safe='')}/{quote(sku, safe='')}",
                                  params={"marketplaceIds": marketplace_id,
                                          "includedData": ["summaries", "attributes", "issues"]})

    async def patch_listing(self, seller_id: str, sku: str, marketplace_id: str, product_type: str,
                            patches: list[dict[str, Any]]) -> dict[str, Any]:
        return await self.request("PATCH", f"{LISTINGS}/items/{quote(seller_id, safe='')}/{quote(sku, safe='')}",
                                  params={"marketplaceIds": marketplace_id},
                                  json={"productType": product_type, "patches": patches})

    # --- Solicitations API v1 -----------------------------------------------------------

    async def review_request_allowed(self, order_id: str, marketplace_id: str) -> bool:
        """True se a Amazon permite pedir avaliação para este pedido agora."""
        data = await self.request("GET", f"{SOLICITATIONS}/{quote(order_id, safe='')}",
                                  params={"marketplaceIds": marketplace_id})
        actions = ((data.get("_links") or {}).get("actions") or [])
        return any(REVIEW_ACTION in str(a.get("href", "")) or a.get("name") == REVIEW_ACTION for a in actions)

    async def request_review(self, order_id: str, marketplace_id: str) -> None:
        await self.request("POST", f"{SOLICITATIONS}/{quote(order_id, safe='')}/solicitations/{REVIEW_ACTION}",
                           params={"marketplaceIds": marketplace_id})

    async def wait_for_report(self, report_id: str, timeout: float, interval: float = 15.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while True:
            report = await self.get_report(report_id)
            if report.get("processingStatus") in ("DONE", "DONE_NO_DATA", "CANCELLED", "FATAL"):
                return report
            if time.monotonic() + interval > deadline:
                return report
            await asyncio.sleep(interval)


def _param(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return ",".join(str(v) for v in value)
    return value


def _body(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text[:1000]


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        try:
            return min(float(retry_after), 60.0)
        except ValueError:
            pass
    return min(2.0 ** attempt, 60.0)
