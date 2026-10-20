"""Servidor MCP que expõe os relatórios da Amazon Seller (SP-API Reports API) ao Claude."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import files, listings, pricing, reviews
from .catalog import BY_CODE, CATEGORIES, REPORT_TYPES
from .client import SPAPIClient, SPAPIError
from .config import MARKETPLACES, Config, load_config

INSTRUCTIONS = """\
Acesso aos relatórios da conta Amazon Seller via SP-API.

Fluxo típico:
1. listar_tipos_relatorio para escolher o tipo (qualquer reportType da Amazon é aceito, mesmo fora do catálogo).
2. gerar_relatorio (solicita, espera e baixa) — ou solicitar_relatorio + status_relatorio + baixar_relatorio
   para relatórios demorados.
3. Relatórios de liquidação/repasse (GET_V2_SETTLEMENT_REPORT_DATA_*) não podem ser solicitados: use
   listar_relatorios com o tipo e baixar_relatorio.
4. Os arquivos ficam salvos localmente; use ler_relatorio (paginado, com filtros) e agregar_relatorio
   (somas agrupadas) em vez de ler tudo de uma vez.

Datas em ISO 8601 (ex.: 2026-09-01T00:00:00Z). A Amazon limita a frequência de solicitações
(cerca de 1 relatório por minuto, com rajadas de até 15).

Preços (Product Pricing API, exige o papel Pricing no app):
- precos_asins: Buy Box, nº de ofertas e ranking de vendas de qualquer ASIN, inclusive de concorrentes
  (ex.: os 3 mais clicados de cada termo do Brand Analytics). Até 200 ASINs por chamada.
- ofertas_asin: todas as ofertas de um ASIN (preço, frete, FBA/Prime, quem tem a Buy Box).
- meus_precos: preço atual das suas próprias ofertas, por SKU.
Os preços são do momento da consulta (não há histórico).

Alterar preços (Listings Items API, exige o papel Product Listing e SPAPI_SELLER_ID no .env):
- alterar_precos SEMPRE primeiro com confirmar=false para mostrar a prévia ao usuário; só repita com
  confirmar=true depois que ele aprovar explicitamente aquela prévia.
- Variações acima de 25% são bloqueadas, a menos que o usuário peça permitir_variacao_grande=true.
- Toda alteração enviada fica registrada em alteracoes_preco.csv na pasta de relatórios.
"""

mcp = MCPServer("amazon-seller", instructions=INSTRUCTIONS)

_client: SPAPIClient | None = None


def client() -> SPAPIClient:
    global _client
    if _client is None:
        _client = SPAPIClient(load_config())
    return _client


def config() -> Config:
    return client().config


def _preview(path, fmt: str, linhas: int = 5) -> dict[str, Any]:
    info: dict[str, Any] = {"arquivo": path.name, "formato": fmt, "tamanho_bytes": path.stat().st_size}
    if fmt in ("tsv", "csv"):
        columns, rows = files.load_rows(path)
        info.update(total_linhas=len(rows), colunas=columns, primeiras_linhas=rows[:linhas])
    elif fmt == "json":
        info["estrutura"] = files.json_outline(json.loads(path.read_text(encoding="utf-8")))
        info["dica"] = "Use ler_relatorio com caminho_json apontando para a lista desejada."
    else:
        info["inicio"] = path.read_text(encoding="utf-8")[:2000]
    return info


async def _download(report: dict[str, Any]) -> dict[str, Any]:
    status = report.get("processingStatus")
    doc_id = report.get("reportDocumentId")
    if status == "DONE_NO_DATA" or (status == "DONE" and not doc_id):
        return {"relatorio": report, "mensagem": "Relatório concluído, mas sem dados para o período/filtros."}
    if status not in ("DONE", "FATAL") or not doc_id:
        return {"relatorio": report, "mensagem": f"Relatório ainda não está pronto (status {status})."}

    document = await client().get_report_document(doc_id)
    content, charset = await client().download_document(document)
    text = files.decode(content, charset)
    path, fmt = files.save_report(config().reports_dir, report.get("reportType", "REPORT"), report["reportId"], text)
    result = {"relatorio": report, **_preview(path, fmt)}
    if status == "FATAL":
        result["mensagem"] = "A Amazon não conseguiu gerar o relatório; o arquivo contém o motivo do erro."
    return result


# --- catálogo --------------------------------------------------------------------------


@mcp.tool()
def listar_tipos_relatorio(categoria: str | None = None, busca: str | None = None) -> dict[str, Any]:
    """Lista os tipos de relatório da Amazon Seller, com descrição e opções.

    Args:
        categoria: filtra por categoria (vendas_trafego, brand_analytics, anuncios, pedidos, devolucoes,
            desempenho, financeiro, fba_vendas, fba_estoque, fba_taxas, fba_devolucoes, impostos, b2b).
        busca: texto para procurar no código ou na descrição (ex.: "estoque", "taxa", "SETTLEMENT").
    """
    tipos = REPORT_TYPES
    if categoria:
        tipos = [t for t in tipos if t.category == categoria]
    if busca:
        b = busca.casefold()
        tipos = [t for t in tipos if b in t.code.casefold() or b in t.description.casefold() or b in t.category]
    return {
        "categorias": CATEGORIES,
        "tipos": [
            {
                "codigo": t.code,
                "categoria": t.category,
                "descricao": t.description,
                **({"observacoes": t.notes} if t.notes else {}),
                **({"pode_solicitar": False} if not t.requestable else {}),
                **({"dados_pessoais": True} if t.restricted else {}),
            }
            for t in tipos
        ],
        "observacao": "Qualquer outro reportType válido da SP-API também pode ser usado.",
    }


@mcp.tool()
def configuracao_atual() -> dict[str, Any]:
    """Mostra região, marketplaces padrão e pasta de relatórios configurados (sem expor credenciais)."""
    c = config()
    return {
        "regiao": c.region,
        "endpoint": c.endpoint,
        "sandbox": c.sandbox,
        "marketplaces_padrao": {m: MARKETPLACES.get(m, "?") for m in c.marketplace_ids},
        "pasta_relatorios": str(c.reports_dir),
        "marketplaces_conhecidos": MARKETPLACES,
    }


# --- Reports API -----------------------------------------------------------------------


@mcp.tool()
async def solicitar_relatorio(
    tipo: str,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    marketplaces: list[str] | None = None,
    opcoes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Solicita a geração de um relatório e devolve o reportId (não espera ficar pronto).

    Args:
        tipo: código do relatório, ex. GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL.
        data_inicio: início do período em ISO 8601, ex. 2026-09-01T00:00:00Z.
        data_fim: fim do período em ISO 8601.
        marketplaces: IDs de marketplace; se omitido, usa os configurados.
        opcoes: reportOptions específicas do tipo (veja listar_tipos_relatorio).
    """
    tipo = tipo.strip().upper()
    info = BY_CODE.get(tipo)
    if info and not info.requestable:
        raise ValueError(f"{tipo} é gerado automaticamente pela Amazon; use listar_relatorios e baixar_relatorio.")
    report_id = await client().create_report(tipo, marketplaces or list(config().marketplace_ids), data_inicio, data_fim, opcoes)
    return {"reportId": report_id, "tipo": tipo, "proximo_passo": "Use status_relatorio ou baixar_relatorio com este reportId."}


@mcp.tool()
async def status_relatorio(report_id: str) -> dict[str, Any]:
    """Consulta o status de um relatório (IN_QUEUE, IN_PROGRESS, DONE, DONE_NO_DATA, CANCELLED, FATAL)."""
    return await client().get_report(report_id)


@mcp.tool()
async def listar_relatorios(
    tipos: list[str] | None = None,
    status: list[str] | None = None,
    criados_desde: str | None = None,
    criados_ate: str | None = None,
    marketplaces: list[str] | None = None,
    quantidade: int = 20,
    next_token: str | None = None,
) -> dict[str, Any]:
    """Lista relatórios já gerados na conta (inclusive os automáticos, como os de liquidação/repasse).

    Args:
        tipos: códigos de relatório (obrigatório, exceto ao usar next_token). Ex.: ["GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2"].
        status: filtra por processingStatus, ex. ["DONE"].
        criados_desde: ISO 8601; a Amazon guarda até 90 dias (padrão: últimos 90 dias).
        criados_ate: ISO 8601.
        marketplaces: IDs de marketplace.
        quantidade: 1 a 100.
        next_token: token de paginação devolvido na chamada anterior.
    """
    if next_token:
        return await client().get_reports(nextToken=next_token)
    if not tipos:
        raise ValueError("Informe ao menos um tipo de relatório em 'tipos'.")
    return await client().get_reports(
        reportTypes=[t.strip().upper() for t in tipos],
        processingStatuses=status,
        createdSince=criados_desde,
        createdUntil=criados_ate,
        marketplaceIds=marketplaces,
        pageSize=max(1, min(quantidade, 100)),
    )


@mcp.tool()
async def baixar_relatorio(report_id: str) -> dict[str, Any]:
    """Baixa um relatório pronto, salva localmente e mostra colunas e primeiras linhas."""
    return await _download(await client().get_report(report_id))


@mcp.tool()
async def gerar_relatorio(
    tipo: str,
    data_inicio: str | None = None,
    data_fim: str | None = None,
    marketplaces: list[str] | None = None,
    opcoes: dict[str, str] | None = None,
    espera_max_segundos: int = 600,
) -> dict[str, Any]:
    """Solicita um relatório, aguarda ficar pronto e já baixa (atalho para solicitar + status + baixar).

    Se o tempo de espera acabar, devolve o reportId para baixar depois com baixar_relatorio.
    Os argumentos são os mesmos de solicitar_relatorio.
    """
    pedido = await solicitar_relatorio(tipo, data_inicio, data_fim, marketplaces, opcoes)
    report = await client().wait_for_report(pedido["reportId"], timeout=max(espera_max_segundos, 0))
    return await _download(report)


@mcp.tool()
async def cancelar_relatorio(report_id: str) -> dict[str, Any]:
    """Cancela um relatório que ainda está na fila (IN_QUEUE)."""
    await client().cancel_report(report_id)
    return {"reportId": report_id, "cancelado": True}


@mcp.tool()
async def listar_agendamentos(tipos: list[str]) -> dict[str, Any]:
    """Lista os agendamentos de relatórios recorrentes configurados para os tipos informados."""
    return await client().get_report_schedules([t.strip().upper() for t in tipos])


# --- Product Pricing API ----------------------------------------------------------------------

LOTE_PRECOS = 20
MAX_ASINS = 200


def _codes(values: list[str], nome: str, maximo: int) -> list[str]:
    codes = list(dict.fromkeys(v.strip().upper() for v in values or [] if v and v.strip()))
    if not codes:
        raise ValueError(f"Informe ao menos um {nome}.")
    if len(codes) > maximo:
        raise ValueError(f"Máximo de {maximo} {nome}s por chamada (recebidos {len(codes)}).")
    return codes


def _pricing_error(e: SPAPIError) -> dict[str, Any]:
    erro: dict[str, Any] = {"erro": f"A Amazon respondeu {e.status}", "detalhes": e.body}
    if e.status in (401, 403):
        erro["dica"] = ("Acesso negado. Confira se o papel 'Pricing' está marcado no aplicativo da Central de "
                        "desenvolvedores e se o Refresh Token no .env foi gerado depois disso (e não é de sandbox).")
    return erro


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


@mcp.tool()
async def precos_asins(asins: list[str], marketplace: str | None = None) -> dict[str, Any]:
    """Preço da Buy Box, nº de ofertas e ranking de vendas de ASINs (seus ou de concorrentes).

    Bom para montar uma base de preços por palavra-chave: passe os ASINs mais clicados de cada termo
    do relatório de Principais termos de pesquisa.

    Args:
        asins: lista de ASINs (até 200; consultados em lotes de 20).
        marketplace: ID do marketplace; se omitido, usa o primeiro configurado (Brasil).
    """
    codes = _codes(asins, "ASIN", MAX_ASINS)
    mkt = marketplace or config().marketplace_ids[0]
    itens: list[dict[str, Any]] = []
    try:
        for lote in _chunks(codes, LOTE_PRECOS):
            itens.extend(pricing.competitive_item(i) for i in await client().get_competitive_pricing(mkt, lote))
    except SPAPIError as e:
        return {**_pricing_error(e), "marketplace": mkt, "itens_ja_consultados": itens}
    encontrados = {i.get("asin") for i in itens}
    faltando = [a for a in codes if a not in encontrados]
    return {
        "marketplace": mkt,
        "total": len(itens),
        "itens": itens,
        **({"sem_resposta": faltando} if faltando else {}),
        "observacao": "Preços do momento da consulta. ranking_vendas: menor número = mais vendido na categoria.",
    }


@mcp.tool()
async def ofertas_asin(asin: str, marketplace: str | None = None, condicao: str = "New",
                       limite: int = 10) -> dict[str, Any]:
    """Todas as ofertas de um ASIN: preço, frete, FBA/Prime, quem ganha a Buy Box e menores preços por canal.

    Args:
        asin: o ASIN.
        marketplace: ID do marketplace; se omitido, usa o primeiro configurado (Brasil).
        condicao: New, Used, Collectible, Refurbished ou Club.
        limite: quantas ofertas devolver, das mais baratas para as mais caras.
    """
    code = _codes([asin], "ASIN", 1)[0]
    mkt = marketplace or config().marketplace_ids[0]
    try:
        payload = await client().get_item_offers(mkt, code, condicao)
    except SPAPIError as e:
        return {**_pricing_error(e), "asin": code, "marketplace": mkt}
    return {"marketplace": mkt, **pricing.item_offers(payload, limite)}


@mcp.tool()
async def meus_precos(skus: list[str], marketplace: str | None = None) -> dict[str, Any]:
    """Preço atual das suas próprias ofertas, por SKU (até 200; em lotes de 20).

    Args:
        skus: lista de SKUs seus.
        marketplace: ID do marketplace; se omitido, usa o primeiro configurado (Brasil).
    """
    codes = list(dict.fromkeys(s.strip() for s in skus or [] if s and s.strip()))
    if not codes:
        raise ValueError("Informe ao menos um SKU.")
    if len(codes) > MAX_ASINS:
        raise ValueError(f"Máximo de {MAX_ASINS} SKUs por chamada (recebidos {len(codes)}).")
    mkt = marketplace or config().marketplace_ids[0]
    itens: list[dict[str, Any]] = []
    try:
        for lote in _chunks(codes, LOTE_PRECOS):
            itens.extend(pricing.own_price_item(i) for i in await client().get_own_pricing(mkt, lote))
    except SPAPIError as e:
        return {**_pricing_error(e), "marketplace": mkt, "itens_ja_consultados": itens}
    return {"marketplace": mkt, "total": len(itens), "itens": itens}


# --- alteração de preço (Listings Items API) ----------------------------------------------------

MAX_ALTERACOES = 20
VARIACAO_MAXIMA = 0.25


async def _prepare_change(seller_id: str, mkt: str, sku: str, novo: float) -> dict[str, Any]:
    item = await client().get_listing(seller_id, sku, mkt)
    resumo = listings.summary(item, mkt)
    attributes = item.get("attributes") or {}
    atual, moeda = listings.current_price(attributes, mkt)
    info: dict[str, Any] = {
        "sku": sku,
        "asin": resumo.get("asin"),
        "titulo": (resumo.get("itemName") or "")[:90],
        "preco_atual": atual,
        "preco_novo": round(novo, 2),
        "variacao_pct": round((novo / atual - 1) * 100, 1) if atual else None,
        "_product_type": resumo.get("productType") or item.get("productType"),
        "_attributes": attributes,
        "_moeda": moeda or "BRL",
    }
    return info


@mcp.tool()
async def alterar_precos(
    alteracoes: list[dict[str, Any]],
    confirmar: bool = False,
    permitir_variacao_grande: bool = False,
    marketplace: str | None = None,
) -> dict[str, Any]:
    """Altera o preço de venda de anúncios seus, por SKU. Primeiro mostra uma prévia; só aplica com confirmar=true.

    Sempre chame com confirmar=false, mostre a prévia ao usuário e só repita com confirmar=true depois
    que ele aprovar. Mantém preço promocional e preço mínimo/máximo já cadastrados.

    Args:
        alteracoes: lista de {"sku": "...", "preco": 53.8} (até 20). O preço é o valor final com impostos.
        confirmar: false = só prévia (nada muda); true = envia as alterações à Amazon.
        permitir_variacao_grande: libera mudanças acima de 25% em relação ao preço atual.
        marketplace: ID do marketplace; se omitido, usa o primeiro configurado (Brasil).
    """
    seller_id = config().seller_id
    if not seller_id:
        return {"erro": "SPAPI_SELLER_ID não configurado.",
                "dica": "Adicione ao .env a linha SPAPI_SELLER_ID=<seu Token de comerciante> (Seller Central > "
                        "Configurações > Informações da conta > Informações do vendedor) e reinicie o Claude."}
    if not alteracoes:
        raise ValueError("Informe ao menos uma alteração.")
    if len(alteracoes) > MAX_ALTERACOES:
        raise ValueError(f"Máximo de {MAX_ALTERACOES} alterações por vez.")
    pedidos: list[tuple[str, float]] = []
    for a in alteracoes:
        sku = str(a.get("sku", "")).strip()
        try:
            preco = float(str(a.get("preco")).replace(",", "."))
        except (TypeError, ValueError):
            raise ValueError(f"Preço inválido para {sku or a}: {a.get('preco')!r}") from None
        if not sku or preco <= 0:
            raise ValueError(f"Alteração inválida: {a}")
        pedidos.append((sku, preco))
    if len({s for s, _ in pedidos}) != len(pedidos):
        raise ValueError("Há SKUs repetidos na lista.")

    mkt = marketplace or config().marketplace_ids[0]
    resultados: list[dict[str, Any]] = []
    for sku, novo in pedidos:
        try:
            info = await _prepare_change(seller_id, mkt, sku, novo)
        except SPAPIError as e:
            erro = _pricing_error(e)
            if e.status in (401, 403):
                erro["dica"] = ("Acesso negado. Confira se o papel 'Product Listing' está marcado no aplicativo e se o "
                                "Refresh Token foi gerado depois disso; confira também o SPAPI_SELLER_ID.")
            elif e.status == 404:
                erro["dica"] = "SKU não encontrado nesta conta/marketplace (ou SPAPI_SELLER_ID incorreto)."
            resultados.append({"sku": sku, "preco_novo": novo, "situacao": "erro", **erro})
            continue

        bloqueio = None
        if not info["_product_type"]:
            bloqueio = "Não foi possível descobrir o tipo de produto do anúncio."
        elif info["preco_atual"] is None:
            bloqueio = "Preço atual não encontrado no anúncio; altere este na Seller Central."
        elif abs(info["variacao_pct"]) > VARIACAO_MAXIMA * 100 and not permitir_variacao_grande:
            bloqueio = f"Variação de {info['variacao_pct']}% acima do limite de {int(VARIACAO_MAXIMA * 100)}%."
        elif info["preco_atual"] == info["preco_novo"]:
            bloqueio = "O preço novo é igual ao atual."

        publico = {k: v for k, v in info.items() if not k.startswith("_")}
        if bloqueio:
            resultados.append({**publico, "situacao": "bloqueado", "motivo": bloqueio})
            continue
        if not confirmar:
            resultados.append({**publico, "situacao": "previa"})
            continue

        patches = listings.price_patch(info["_attributes"], mkt, info["preco_novo"], info["_moeda"])
        try:
            resp = await client().patch_listing(seller_id, sku, mkt, info["_product_type"], patches)
            status = resp.get("status", "?")
            problemas = listings.issues_text(resp.get("issues"))
            submission = resp.get("submissionId", "")
        except SPAPIError as e:
            status, problemas, submission = f"ERRO {e.status}", [str(e.body)[:300]], ""
        listings.append_log(config().reports_dir, {
            "data_hora": listings.now(), "sku": sku, "asin": info["asin"], "marketplace": mkt,
            "preco_anterior": info["preco_atual"], "preco_novo": info["preco_novo"],
            "variacao_pct": info["variacao_pct"], "status": status, "submission_id": submission,
            "problemas": " | ".join(problemas),
        })
        resultados.append({**publico, "situacao": "enviado" if status == "ACCEPTED" else "recusado",
                           "status_amazon": status, **({"problemas": problemas} if problemas else {})})

    resumo: dict[str, int] = {}
    for r in resultados:
        resumo[r["situacao"]] = resumo.get(r["situacao"], 0) + 1
    out: dict[str, Any] = {"marketplace": mkt, "confirmar": confirmar, "resumo": resumo, "itens": resultados}
    if not confirmar:
        out["proximo_passo"] = "Nada foi alterado. Mostre a prévia ao usuário e, se ele aprovar, repita com confirmar=true."
    else:
        out["observacao"] = ("Alterações aceitas levam de alguns minutos a 1 hora para aparecer no site. "
                             f"Registro salvo em {listings.LOG_NAME} na pasta de relatórios.")
    return out


# --- pedido de avaliação (Solicitations API) -------------------------------------------------------

REVIEW_LOG = reviews.REVIEW_LOG


def _orders_from_report(arquivo: str, dias_min: int, dias_max: int) -> list[str]:
    path = files.resolve_file(config().reports_dir, arquivo)
    columns, rows = files.load_rows(path)
    return reviews.orders_from_rows(columns, rows, dias_min, dias_max, f"arquivo {arquivo}")


@mcp.tool()
async def solicitar_avaliacoes(
    pedidos: list[str] | None = None,
    arquivo_pedidos: str | None = None,
    confirmar: bool = False,
    limite: int = 40,
    marketplace: str | None = None,
) -> dict[str, Any]:
    """Pede avaliação do produto + feedback do vendedor (o botão "Solicitar uma avaliação" da Seller Central).

    A Amazon só aceita pedidos entregues há 5 a 30 dias e uma única solicitação por pedido; a ferramenta
    consulta a elegibilidade de cada pedido, pula os já solicitados (registro em avaliacoes_solicitadas.csv)
    e só envia com confirmar=true. Exige o papel Buyer Solicitation.

    Args:
        pedidos: IDs de pedido (ex.: 702-1234567-1234567). Alternativa: arquivo_pedidos.
        arquivo_pedidos: relatório de pedidos baixado (GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL);
            usa os pedidos enviados/entregues com compra entre 4 e 35 dias atrás.
        confirmar: false = só verifica quantos são elegíveis (nada é enviado); true = envia.
        limite: máximo de pedidos verificados nesta chamada (até 60; ~1 segundo por pedido).
        marketplace: ID do marketplace; se omitido, usa o primeiro configurado (Brasil).
    """
    if not pedidos and not arquivo_pedidos:
        raise ValueError("Informe 'pedidos' ou 'arquivo_pedidos'.")
    lista = [p.strip() for p in (pedidos or []) if p and p.strip()]
    if arquivo_pedidos:
        lista += [p for p in _orders_from_report(arquivo_pedidos, 4, 35) if p not in lista]
    mkt = marketplace or config().marketplace_ids[0]
    folder = config().reports_dir
    ja = reviews.already_requested(folder)
    pendentes = [p for p in lista if p not in ja]
    limite = max(1, min(limite, 60))
    lote, restantes = pendentes[:limite], pendentes[limite:]

    contagem, detalhes, negado = await reviews.check_and_send(client(), lote, mkt, folder, confirmar)
    if negado:
        return {"erro": f"A Amazon respondeu {negado.status}", "detalhes": negado.body, "dica": reviews.DICA_PERMISSAO}

    out: dict[str, Any] = {
        "marketplace": mkt,
        "confirmar": confirmar,
        "pedidos_encontrados": len(lista),
        "ja_solicitados_antes": len(lista) - len(pendentes),
        "verificados_agora": len(lote),
        "resultado": {k: v for k, v in contagem.items() if v or k in ("enviado", "elegivel")},
        "faltam_verificar": len(restantes),
    }
    if detalhes:
        out["erros"] = detalhes[:10]
    if not confirmar:
        out["proximo_passo"] = "Nada foi enviado. Se o usuário aprovar, repita com confirmar=true."
    elif restantes:
        out["proximo_passo"] = "Repita a mesma chamada para processar os pedidos restantes."
    return out


# --- arquivos locais -------------------------------------------------------------------------


@mcp.tool()
def relatorios_baixados() -> dict[str, Any]:
    """Lista os relatórios já baixados na pasta local (mais recentes primeiro)."""
    return {
        "pasta": str(config().reports_dir),
        "arquivos": [{"arquivo": p.name, "tamanho_bytes": p.stat().st_size} for p in files.list_files(config().reports_dir)],
    }


@mcp.tool()
def ler_relatorio(
    arquivo: str,
    inicio: int = 0,
    limite: int = 50,
    filtros: list[str] | None = None,
    colunas: list[str] | None = None,
    caminho_json: str | None = None,
) -> dict[str, Any]:
    """Lê linhas de um relatório baixado (TSV, CSV ou lista JSON), com paginação e filtros.

    Args:
        arquivo: nome do arquivo (veja relatorios_baixados).
        inicio: índice da primeira linha (após filtros).
        limite: máximo de linhas a devolver (até 500).
        filtros: condições combinadas com E. Operadores: = (igual), != (diferente), ~ (contém),
            >, <, >=, <= (numérico ou texto, ex. datas ISO). Ex.: ["sku~CAMISA", "quantity>=2"].
        colunas: devolve só estas colunas.
        caminho_json: para JSON, caminho até a lista com pontos, ex. "salesAndTrafficByAsin".
    """
    path = files.resolve_file(config().reports_dir, arquivo)
    all_columns, rows = files.load_rows(path, caminho_json)
    conds = files.parse_filters(filtros, all_columns)
    files.check_columns(colunas or [], all_columns)
    selected = [r for r in rows if files.matches(r, conds)]
    limite = max(1, min(limite, 500))
    page = selected[inicio:inicio + limite]
    return {
        "arquivo": path.name,
        "colunas": all_columns,
        "total_linhas": len(rows),
        "linhas_apos_filtros": len(selected),
        "inicio": inicio,
        "linhas": [files.select(r, colunas) for r in page],
        "tem_mais": inicio + limite < len(selected),
    }


@mcp.tool()
def agregar_relatorio(
    arquivo: str,
    agrupar_por: list[str] | None = None,
    somar: list[str] | None = None,
    filtros: list[str] | None = None,
    caminho_json: str | None = None,
    limite: int = 100,
) -> dict[str, Any]:
    """Agrupa as linhas de um relatório e soma colunas numéricas (ex.: vendas por SKU, taxas por tipo).

    Args:
        arquivo: nome do arquivo baixado.
        agrupar_por: colunas de agrupamento; vazio = total geral.
        somar: colunas numéricas a somar (aceita 1.234,56 e 1,234.56). A coluna _linhas conta as linhas.
        filtros: mesmos filtros de ler_relatorio.
        caminho_json: para JSON, caminho até a lista.
        limite: máximo de grupos devolvidos (ordenados pela primeira coluna somada, decrescente).
    """
    path = files.resolve_file(config().reports_dir, arquivo)
    all_columns, rows = files.load_rows(path, caminho_json)
    agrupar_por, somar = agrupar_por or [], somar or []
    files.check_columns(agrupar_por + somar, all_columns)
    conds = files.parse_filters(filtros, all_columns)
    result = files.aggregate([r for r in rows if files.matches(r, conds)], agrupar_por, somar)
    return {"arquivo": path.name, "total_grupos": len(result), "grupos": result[:max(1, limite)]}


@mcp.tool()
def ler_relatorio_bruto(arquivo: str, inicio: int = 0, caracteres: int = 20000) -> dict[str, Any]:
    """Lê o conteúdo bruto de um relatório (útil para XML ou texto), em trechos de caracteres."""
    path = files.resolve_file(config().reports_dir, arquivo)
    text = path.read_text(encoding="utf-8")
    caracteres = max(1, min(caracteres, 100000))
    return {
        "arquivo": path.name,
        "total_caracteres": len(text),
        "inicio": inicio,
        "conteudo": text[inicio:inicio + caracteres],
        "tem_mais": inicio + caracteres < len(text),
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
