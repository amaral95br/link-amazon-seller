# link-amazon-seller

Servidor **MCP** que dá ao Claude acesso aos **relatórios da sua conta Amazon Seller** pela
[Selling Partner API (SP-API)](https://developer-docs.amazon.com/sp-api/), usando a Reports API, e aos
**preços de qualquer produto** do marketplace pela Product Pricing API.

Com ele você pode pedir ao Claude coisas como:

- "Gere o relatório de pedidos de setembro e me diga os 10 SKUs que mais venderam."
- "Baixe o último relatório de liquidação e some as taxas por tipo."
- "Quais produtos FBA estão com estoque encalhado ou vão acabar nas próximas semanas?"
- "Quanto a Amazon me reembolsou por itens perdidos este ano?"
- "Qual o preço da Buy Box dos 3 produtos mais clicados em 'planner semanal'? E o meu?"

## O que ele faz

| Ferramenta | Descrição |
|---|---|
| `listar_tipos_relatorio` | Catálogo de ~85 tipos de relatório (pedidos, vendas e tráfego, estoque FBA, taxas, liquidação, devoluções, desempenho, Brand Analytics…) |
| `gerar_relatorio` | Solicita, espera ficar pronto e baixa, tudo em uma chamada |
| `solicitar_relatorio` / `status_relatorio` / `baixar_relatorio` | O mesmo fluxo em etapas, para relatórios demorados |
| `listar_relatorios` | Relatórios já existentes na conta, inclusive os automáticos (liquidação/repasse) |
| `cancelar_relatorio`, `listar_agendamentos` | Gestão de relatórios na fila e agendados |
| `relatorios_baixados` | Arquivos já salvos localmente |
| `ler_relatorio` | Lê linhas com paginação, filtros (`=`, `!=`, `~`, `>`, `<`…) e seleção de colunas |
| `agregar_relatorio` | Soma colunas agrupando por outras (ex.: vendas por SKU) |
| `ler_relatorio_bruto` | Conteúdo bruto (XML/texto) em trechos |
| `configuracao_atual` | Região, marketplaces e pasta configurados |
| `precos_asins` | Preço da Buy Box, nº de ofertas e ranking de vendas de até 200 ASINs, inclusive de concorrentes |
| `ofertas_asin` | Todas as ofertas de um ASIN: preço, frete, FBA/Prime, quem ganha a Buy Box |
| `meus_precos` | Preço atual das suas ofertas, por SKU |

Qualquer `reportType` válido da SP-API é aceito, mesmo que não esteja no catálogo.
Os relatórios são salvos em `./relatorios` (TSV, CSV, JSON ou XML), e o Claude os lê aos poucos,
sem precisar carregar arquivos enormes de uma vez.

As ferramentas de preço exigem o papel **Pricing** no app e mostram o preço do momento da consulta
(a API não tem histórico).

O servidor é **somente leitura**: não altera preços, anúncios nem pedidos.

## 1. Obter as credenciais da SP-API

1. Tenha uma conta de vendedor **Professional**.
2. No Seller Central, acesse **Apps e Serviços → Desenvolver aplicativos** e registre-se como
   desenvolvedor (perfil de desenvolvedor *privado*, para usar apenas na sua conta).
   - Selecione os papéis (roles) de dados que você quer acessar. Para relatórios, os mais comuns são:
     *Inventory and Order Tracking*, *Finance and Accounting*, *Selling Partner Insights*,
     *Pricing*, *Amazon Fulfillment* e, se tiver Brand Registry, *Brand Analytics*.
   - Relatórios com dados pessoais de compradores (endereço, nome) exigem papéis restritos, que
     passam por uma análise adicional da Amazon. O servidor já usa o token restrito (RDT)
     automaticamente quando necessário.
3. Depois da aprovação, crie um **app** em *Desenvolver aplicativos* e anote o **Client ID** e o
   **Client Secret** (credenciais LWA).
4. No mesmo app, clique em **Autorizar aplicativo** para gerar o **Refresh Token** da sua conta.

## 2. Instalar

Requer Python 3.10+.

```bash
git clone https://github.com/amaral95br/link-amazon-seller.git
cd link-amazon-seller
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env             # e preencha com suas credenciais
```

Variáveis do `.env`:

| Variável | Descrição |
|---|---|
| `SPAPI_CLIENT_ID`, `SPAPI_CLIENT_SECRET` | Credenciais LWA do app |
| `SPAPI_REFRESH_TOKEN` | Token gerado ao autorizar o app na sua conta |
| `SPAPI_REGION` | `na` (Brasil, EUA, Canadá, México), `eu` ou `fe` |
| `SPAPI_MARKETPLACE_IDS` | Marketplaces padrão, separados por vírgula. Brasil = `A2Q3Y263D00KWC` |
| `SPAPI_REPORTS_DIR` | Pasta dos relatórios baixados (padrão `./relatorios`) |
| `SPAPI_SANDBOX` | `true` para usar o sandbox da Amazon |

> O `.env` está no `.gitignore`. **Nunca** faça commit das suas credenciais.

## 3. Conectar ao Claude

### Claude Desktop

Edite o arquivo de configuração (`Settings → Developer → Edit Config`) e adicione, ajustando os caminhos:

```json
{
  "mcpServers": {
    "amazon-seller": {
      "command": "/caminho/para/link-amazon-seller/.venv/bin/amazon-seller-mcp",
      "env": {
        "SPAPI_ENV_FILE": "/caminho/para/link-amazon-seller/.env",
        "SPAPI_REPORTS_DIR": "/caminho/para/link-amazon-seller/relatorios"
      }
    }
  }
}
```

No Windows, o comando fica em `...\link-amazon-seller\.venv\Scripts\amazon-seller-mcp.exe`.
Reinicie o Claude Desktop depois de salvar.

### Claude Code

Dentro da pasta do projeto:

```bash
claude mcp add amazon-seller -- .venv/bin/amazon-seller-mcp
```

## Dicas de uso

- **Relatórios de liquidação** (repasses, taxas e reembolsos) são gerados pela própria Amazon a cada
  pagamento e não podem ser solicitados. Peça ao Claude para *listar* os relatórios
  `GET_V2_SETTLEMENT_REPORT_DATA_FLAT_FILE_V2` e baixar o que quiser.
- **Pedidos**: cada relatório cobre no máximo 30 dias; para períodos maiores, o Claude gera vários.
- **Vendas e tráfego** (`GET_SALES_AND_TRAFFIC_REPORT`) vem em JSON; use `caminho_json`
  `salesAndTrafficByDate` ou `salesAndTrafficByAsin` ao ler.
- A Amazon limita a frequência: cerca de 1 solicitação de relatório por minuto (rajadas de até 15).
  O servidor repete automaticamente quando recebe erro 429.
- **Anúncios patrocinados (Amazon Ads)** usam outra API e não fazem parte deste servidor.

## Desenvolvimento

```bash
pip install -e '.[dev]'
pytest
```

Os testes simulam a SP-API e não precisam de credenciais.
