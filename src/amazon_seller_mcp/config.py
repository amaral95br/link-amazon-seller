"""Leitura das configurações a partir de variáveis de ambiente (ou arquivo .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENDPOINTS = {
    "na": "https://sellingpartnerapi-na.amazon.com",
    "eu": "https://sellingpartnerapi-eu.amazon.com",
    "fe": "https://sellingpartnerapi-fe.amazon.com",
}
SANDBOX_ENDPOINTS = {
    "na": "https://sandbox.sellingpartnerapi-na.amazon.com",
    "eu": "https://sandbox.sellingpartnerapi-eu.amazon.com",
    "fe": "https://sandbox.sellingpartnerapi-fe.amazon.com",
}

MARKETPLACES = {
    "A2Q3Y263D00KWC": "Brasil",
    "ATVPDKIKX0DER": "Estados Unidos",
    "A2EUQ1WTGCTBG2": "Canadá",
    "A1AM78C64UM0Y8": "México",
    "A1RKKUPIHCS9HS": "Espanha",
    "A1F83G8C2ARO7P": "Reino Unido",
    "A13V1IB3VIYZZH": "França",
    "A1PA6795UKMFR9": "Alemanha",
    "APJ6JRA9NG5V4": "Itália",
    "A1805IZSGTT6HS": "Holanda",
    "A21TJRUUN4KGV": "Índia",
    "A1VC38T7YXB528": "Japão",
    "A39IBJ37TRP1C6": "Austrália",
}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    client_id: str
    client_secret: str
    refresh_token: str
    region: str
    marketplace_ids: tuple[str, ...]
    reports_dir: Path
    sandbox: bool = False
    seller_id: str | None = None

    @property
    def endpoint(self) -> str:
        return (SANDBOX_ENDPOINTS if self.sandbox else ENDPOINTS)[self.region]


def load_dotenv(path: Path) -> None:
    """Carrega um .env simples (CHAVE=valor) sem sobrescrever variáveis já definidas."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config() -> Config:
    load_dotenv(Path(os.environ.get("SPAPI_ENV_FILE", ".env")))

    missing = [k for k in ("SPAPI_CLIENT_ID", "SPAPI_CLIENT_SECRET", "SPAPI_REFRESH_TOKEN") if not os.environ.get(k)]
    if missing:
        raise ConfigError(f"Variáveis de ambiente ausentes: {', '.join(missing)}. Veja o README e o .env.example.")

    region = os.environ.get("SPAPI_REGION", "na").lower()
    if region not in ENDPOINTS:
        raise ConfigError(f"SPAPI_REGION inválida: {region!r}. Use na, eu ou fe.")

    marketplaces = tuple(m.strip() for m in os.environ.get("SPAPI_MARKETPLACE_IDS", "A2Q3Y263D00KWC").split(",") if m.strip())

    return Config(
        client_id=os.environ["SPAPI_CLIENT_ID"],
        client_secret=os.environ["SPAPI_CLIENT_SECRET"],
        refresh_token=os.environ["SPAPI_REFRESH_TOKEN"],
        region=region,
        marketplace_ids=marketplaces,
        reports_dir=Path(os.environ.get("SPAPI_REPORTS_DIR", "./relatorios")).expanduser().resolve(),
        sandbox=os.environ.get("SPAPI_SANDBOX", "false").lower() in ("1", "true", "yes", "sim"),
        seller_id=os.environ.get("SPAPI_SELLER_ID", "").strip() or None,
    )
