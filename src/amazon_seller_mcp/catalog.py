"""Catálogo dos tipos de relatório da SP-API (Reports API) disponíveis para vendedores.

Não é uma lista fechada: qualquer `reportType` aceito pela Amazon pode ser solicitado.
Referência: https://developer-docs.amazon.com/sp-api/docs/report-type-values
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReportType:
    code: str
    category: str
    description: str
    notes: str = ""
    requestable: bool = True  # False = gerado automaticamente pela Amazon; só dá para listar e baixar
    restricted: bool = False  # contém dados pessoais (PII); exige papel restrito no app


def _r(code: str, category: str, description: str, notes: str = "", *, requestable: bool = True,
       restricted: bool = False) -> ReportType:
    return ReportType(code, category, description, notes, requestable, restricted)


REPORT_TYPES: list[ReportType] = [
    # --- Vendas e tráfego / Brand Analytics -----------------------------------
    _r("GET_SALES_AND_TRAFFIC_REPORT", "vendas_trafego",
       "Vendas, sessões, visualizações de página, Buy Box e conversão por data e por ASIN/SKU (JSON).",
       'Opções: {"dateGranularity": "DAY|WEEK|MONTH", "asinGranularity": "PARENT|CHILD|SKU"}.'),
    _r("GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT", "brand_analytics",
       "Termos de busca mais frequentes e os 3 ASINs mais clicados de cada um (JSON).",
       'Exige Brand Registry. Opções: {"reportPeriod": "DAY|WEEK|MONTH|QUARTER"}.'),
    _r("GET_BRAND_ANALYTICS_SEARCH_QUERY_PERFORMANCE_REPORT", "brand_analytics",
       "Desempenho das consultas de busca (impressões, cliques, carrinho, compras) para seus ASINs (JSON).",
       'Exige Brand Registry. Opções: {"reportPeriod": "WEEK|MONTH|QUARTER", "asin": "ASIN1 ASIN2"}.'),
    _r("GET_BRAND_ANALYTICS_SEARCH_CATALOG_PERFORMANCE_REPORT", "brand_analytics",
       "Funil de busca do catálogo (impressões, cliques, carrinho, compras) por ASIN (JSON).",
       'Exige Brand Registry. Opções: {"reportPeriod": "WEEK|MONTH|QUARTER"}.'),
    _r("GET_BRAND_ANALYTICS_MARKET_BASKET_REPORT", "brand_analytics",
       "Produtos comprados junto com os seus (JSON).",
       'Exige Brand Registry. Opções: {"reportPeriod": "DAY|WEEK|MONTH|QUARTER"}.'),
    _r("GET_BRAND_ANALYTICS_REPEAT_PURCHASE_REPORT", "brand_analytics",
       "Recompra: pedidos e clientes recorrentes por ASIN (JSON).",
       'Exige Brand Registry. Opções: {"reportPeriod": "WEEK|MONTH|QUARTER"}.'),

    # --- Anúncios / inventário próprio ------------------------------------------
    _r("GET_MERCHANT_LISTINGS_ALL_DATA", "anuncios", "Todos os anúncios (ativos e inativos) com preço, quantidade e status."),
    _r("GET_MERCHANT_LISTINGS_DATA", "anuncios", "Anúncios ativos."),
    _r("GET_MERCHANT_LISTINGS_INACTIVE_DATA", "anuncios", "Anúncios inativos."),
    _r("GET_MERCHANT_LISTINGS_DATA_LITE", "anuncios", "Anúncios ativos, versão resumida (SKU, quantidade, preço, ASIN)."),
    _r("GET_MERCHANT_LISTINGS_DATA_LITER", "anuncios", "Anúncios ativos, versão mínima (SKU e quantidade)."),
    _r("GET_MERCHANT_LISTINGS_DATA_BACK_COMPAT", "anuncios", "Anúncios ativos, formato legado."),
    _r("GET_MERCHANT_CANCELLED_LISTINGS_DATA", "anuncios", "Anúncios cancelados."),
    _r("GET_FLAT_FILE_OPEN_LISTINGS_DATA", "anuncios", "Inventário aberto (SKU, ASIN, preço, quantidade)."),
    _r("GET_MERCHANTS_LISTINGS_FYP_REPORT", "anuncios", "Anúncios suprimidos/com problemas e o motivo."),
    _r("GET_REFERRAL_FEE_PREVIEW_REPORT", "anuncios", "Prévia da comissão (referral fee) por anúncio."),
    _r("GET_PAN_EU_OFFER_STATUS", "anuncios", "Status de elegibilidade Pan-European FBA (somente Europa)."),

    # --- Pedidos ---------------------------------------------------------------
    _r("GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL", "pedidos",
       "Todos os pedidos por data do pedido (até 30 dias por relatório).", "Use dataStartTime/dataEndTime."),
    _r("GET_FLAT_FILE_ALL_ORDERS_DATA_BY_LAST_UPDATE_GENERAL", "pedidos",
       "Todos os pedidos por data da última atualização.", "Use dataStartTime/dataEndTime."),
    _r("GET_XML_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL", "pedidos", "Todos os pedidos por data do pedido (XML)."),
    _r("GET_XML_ALL_ORDERS_DATA_BY_LAST_UPDATE_GENERAL", "pedidos", "Todos os pedidos por última atualização (XML)."),
    _r("GET_FLAT_FILE_ARCHIVED_ORDERS_DATA_BY_ORDER_DATE", "pedidos", "Pedidos arquivados (mais antigos que 18 meses)."),
    _r("GET_FLAT_FILE_PENDING_ORDERS_DATA", "pedidos", "Pedidos pendentes."),
    _r("GET_PENDING_ORDERS_DATA", "pedidos", "Pedidos pendentes (XML)."),
    _r("GET_CONVERGED_FLAT_FILE_PENDING_ORDERS_DATA", "pedidos", "Pedidos pendentes, formato unificado."),
    _r("GET_FLAT_FILE_ACTIONABLE_ORDER_DATA_SHIPPING", "pedidos",
       "Pedidos não enviados que exigem ação (FBM), com dados de envio.", restricted=True),
    _r("GET_ORDER_REPORT_DATA_INVOICING", "pedidos", "Pedidos com dados de faturamento (XML).", restricted=True),
    _r("GET_ORDER_REPORT_DATA_TAX", "pedidos", "Pedidos com dados de imposto (XML).", restricted=True),
    _r("GET_ORDER_REPORT_DATA_SHIPPING", "pedidos", "Pedidos com dados de envio (XML).", restricted=True),
    _r("GET_FLAT_FILE_ORDER_REPORT_DATA_INVOICING", "pedidos", "Pedidos com dados de faturamento.", restricted=True),
    _r("GET_FLAT_FILE_ORDER_REPORT_DATA_SHIPPING", "pedidos", "Pedidos com dados de envio.", restricted=True),
    _r("GET_FLAT_FILE_ORDER_REPORT_DATA_TAX", "pedidos", "Pedidos com dados de imposto.", restricted=True),

    # --- Devoluções ------------------------------------------------------------
    _r("GET_FLAT_FILE_RETURNS_DATA_BY_RETURN_DATE", "devolucoes", "Devoluções de pedidos FBM por data de devolução."),
    _r("GET_XML_RETURNS_DATA_BY_RETURN_DATE", "devolucoes", "Devoluções de pedidos FBM por data de devolução (XML)."),
    _r("GET_CSV_MFN_PRIME_RETURNS_REPORT", "devolucoes", "Devoluções de pedidos Prime enviados pelo vendedor."),
    _r("GET_XML_MFN_PRIME_RETURNS_REPORT", "devolucoes", "Devoluções de pedidos Prime enviados pelo vendedor (XML)."),
    _r("GET_FLAT_FILE_MFN_SKU_RETURN_ATTRIBUTES_REPORT", "devolucoes", "Atributos de devolução por SKU (FBM)."),
    _r("GET_XML_MFN_SKU_RETURN_ATTRIBUTES_REPORT", "devolucoes", "Atributos de devolução por SKU (FBM, XML)."),

    # --- Desempenho da conta ---------------------------------------------------
    _r("GET_V2_SELLER_PERFORMANCE_REPORT", "desempenho", "Saúde da conta: métricas de desempenho e violações de política (JSON)."),
    _r("GET_V1_SELLER_PERFORMANCE_REPORT", "desempenho", "Desempenho do vendedor, formato legado (XML)."),
    _r("GET_SELLER_FEEDBACK_DATA", "desempenho", "Avaliações (feedback) de compradores sobre o vendedor."),
    _r("GET_PROMOTION_PERFORMANCE_REPORT", "desempenho", "Desempenho de promoções (JSON).",
       'Opções: {"promotionStartDateFrom": "...", "promotionStartDateTo": "..."}.'),
    _r("GET_COUPON_PERFORMANCE_REPORT", "desempenho", "Desempenho de cupons (JSON).",
       'Opções: {"campaignStartDateFrom": "...", "campaignStartDateTo": "..."}.'),

    # --- Financeiro / liquidação -----------------------------------------------
    _r("GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2", "financeiro",
       "Relatório de liquidação (repasses): vendas, taxas, reembolsos e ajustes de cada período de pagamento.",
       "Gerado automaticamente pela Amazon a cada repasse; use listar_relatorios para encontrar.", requestable=False),
    _r("GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE", "financeiro", "Relatório de liquidação, formato legado.",
       "Gerado automaticamente pela Amazon.", requestable=False),
    _r("GET_V2_SETTLEMENT_REPORT_DATA_XML", "financeiro", "Relatório de liquidação (XML).",
       "Gerado automaticamente pela Amazon.", requestable=False),

    # --- FBA: vendas e envios ----------------------------------------------------
    _r("GET_AMAZON_FULFILLED_SHIPMENTS_DATA_GENERAL", "fba_vendas", "Envios feitos pela Amazon (FBA), por item.", restricted=True),
    _r("GET_AMAZON_FULFILLED_SHIPMENTS_DATA_INVOICING", "fba_vendas", "Envios FBA com dados de faturamento.", restricted=True),
    _r("GET_AMAZON_FULFILLED_SHIPMENTS_DATA_TAX", "fba_vendas", "Envios FBA com dados de imposto.", restricted=True),
    _r("GET_FBA_FULFILLMENT_CUSTOMER_SHIPMENT_SALES_DATA", "fba_vendas", "Vendas FBA por envio ao cliente."),
    _r("GET_FBA_FULFILLMENT_CUSTOMER_SHIPMENT_PROMOTION_DATA", "fba_vendas", "Promoções aplicadas em envios FBA."),
    _r("GET_FBA_FULFILLMENT_CUSTOMER_TAXES_DATA", "fba_vendas", "Impostos de envios FBA."),
    _r("GET_REMOTE_FULFILLMENT_ELIGIBILITY", "fba_vendas", "Elegibilidade para Remote Fulfillment."),

    # --- FBA: estoque --------------------------------------------------------------
    _r("GET_FBA_MYI_ALL_INVENTORY_DATA", "fba_estoque", "Estoque FBA completo (inclusive anúncios arquivados)."),
    _r("GET_FBA_MYI_UNSUPPRESSED_INVENTORY_DATA", "fba_estoque", "Estoque FBA de anúncios não suprimidos."),
    _r("GET_AFN_INVENTORY_DATA", "fba_estoque", "Quantidade disponível em centros de distribuição FBA."),
    _r("GET_AFN_INVENTORY_DATA_BY_COUNTRY", "fba_estoque", "Estoque FBA por país."),
    _r("GET_RESERVED_INVENTORY_DATA", "fba_estoque", "Estoque reservado (em transferência, processamento etc.)."),
    _r("GET_FBA_INVENTORY_PLANNING_DATA", "fba_estoque", "Planejamento de estoque: idade, excesso, custos de armazenagem, sell-through."),
    _r("GET_RESTOCK_INVENTORY_RECOMMENDATIONS_REPORT", "fba_estoque", "Recomendações de reposição de estoque."),
    _r("GET_STRANDED_INVENTORY_UI_DATA", "fba_estoque", "Estoque encalhado (sem anúncio ativo)."),
    _r("GET_STRANDED_INVENTORY_LOADER_DATA", "fba_estoque", "Estoque encalhado, formato para reenvio em massa."),
    _r("GET_LEDGER_SUMMARY_VIEW_DATA", "fba_estoque", "Razão de estoque resumido: saldo inicial, entradas, saídas e saldo final.",
       'Opções: {"aggregateByLocation": "COUNTRY|FC", "aggregatedByTimePeriod": "DAILY|WEEKLY|MONTHLY"}.'),
    _r("GET_LEDGER_DETAIL_VIEW_DATA", "fba_estoque", "Razão de estoque detalhado: cada movimentação de unidade."),
    _r("GET_FBA_FULFILLMENT_INBOUND_NONCOMPLIANCE_DATA", "fba_estoque", "Problemas em remessas de entrada (inbound)."),
    _r("GET_FBA_UNO_INVENTORY_DATA", "fba_estoque", "Estoque do programa Small and Light."),
    _r("GET_FBA_SNS_FORECAST_DATA", "fba_estoque", "Previsão do Subscribe & Save."),
    _r("GET_FBA_SNS_PERFORMANCE_DATA", "fba_estoque", "Desempenho do Subscribe & Save."),

    # --- FBA: taxas e reembolsos -------------------------------------------------------
    _r("GET_FBA_ESTIMATED_FBA_FEES_TXT_DATA", "fba_taxas", "Estimativa de taxas FBA por SKU."),
    _r("GET_FBA_STORAGE_FEE_CHARGES_DATA", "fba_taxas", "Taxas de armazenagem mensais por ASIN."),
    _r("GET_FBA_FULFILLMENT_LONGTERM_STORAGE_FEE_CHARGES_DATA", "fba_taxas", "Taxas de armazenagem de longo prazo."),
    _r("GET_FBA_OVERAGE_FEE_CHARGES_DATA", "fba_taxas", "Taxas por excesso de capacidade de armazenagem."),
    _r("GET_FBA_REIMBURSEMENTS_DATA", "fba_taxas", "Reembolsos pagos pela Amazon (itens perdidos, danificados etc.)."),

    # --- FBA: devoluções, remoções e trocas -------------------------------------------
    _r("GET_FBA_FULFILLMENT_CUSTOMER_RETURNS_DATA", "fba_devolucoes", "Devoluções de clientes de pedidos FBA, com motivo e condição."),
    _r("GET_FBA_FULFILLMENT_CUSTOMER_SHIPMENT_REPLACEMENT_DATA", "fba_devolucoes", "Substituições enviadas a clientes."),
    _r("GET_PRODUCT_EXCHANGE_DATA", "fba_devolucoes", "Trocas de produto."),
    _r("GET_FBA_RECOMMENDED_REMOVAL_DATA", "fba_devolucoes", "Remoções recomendadas de estoque."),
    _r("GET_FBA_FULFILLMENT_REMOVAL_ORDER_DETAIL_DATA", "fba_devolucoes", "Pedidos de remoção (detalhe)."),
    _r("GET_FBA_FULFILLMENT_REMOVAL_SHIPMENT_DETAIL_DATA", "fba_devolucoes", "Envios de remoção (detalhe)."),

    # --- Impostos ------------------------------------------------------------------------
    _r("GET_FLAT_FILE_SALES_TAX_DATA", "impostos", "Imposto sobre vendas (EUA)."),
    _r("SC_VAT_TAX_REPORT", "impostos", "Cálculo de VAT (Europa)."),
    _r("GET_VAT_TRANSACTION_DATA", "impostos", "Transações de VAT (Europa)."),

    # --- B2B ----------------------------------------------------------------------------
    _r("GET_B2B_PRODUCT_OPPORTUNITIES_RECOMMENDED_FOR_YOU", "b2b", "Oportunidades de produto B2B recomendadas."),
    _r("GET_B2B_PRODUCT_OPPORTUNITIES_NOT_YET_ON_AMAZON", "b2b", "Produtos B2B procurados que ainda não estão na Amazon."),
]

BY_CODE = {r.code: r for r in REPORT_TYPES}
CATEGORIES = sorted({r.category for r in REPORT_TYPES})
