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
| `solicitar_avaliacoes` | Pede avaliação + feedback (botão "Solicitar uma avaliação") para pedidos elegíveis, sem repetir pedidos; exige o papel **Buyer Solicitation** |
| `alterar_precos` | Altera o preço de anúncios seus: mostra uma prévia, só aplica com confirmação, bloqueia variações acima de 25% e registra tudo em `alteracoes_preco.csv` |

Qualquer `reportType` válido da SP-API é aceito, mesmo que não esteja no catálogo.
Os relatórios são salvos em `./relatorios` (TSV, CSV, JSON ou XML), e o Claude os lê aos poucos,
sem precisar carregar arquivos enormes de uma vez.

As ferramentas de preço exigem o papel **Pricing** no app e mostram o preço do momento da consulta
(a API não tem histórico).

A única escrita é `alterar_precos`, que exige o papel **Product Listing** e a variável `SPAPI_SELLER_ID`
(o Token de comerciante da conta). Ela mantém preço promocional e preço mínimo/máximo já cadastrados.
O servidor não altera anúncios, estoque nem pedidos.

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

## 4. Pedir avaliações automaticamente (opcional)

O comando `amazon-seller-avaliacoes` faz sozinho, sem o Claude, o mesmo que o botão
"Solicitar uma avaliação": gera o relatório de pedidos das compras feitas entre 4 e 34 dias atrás,
pergunta à Amazon quais pedidos estão elegíveis (entregues há 5 a 30 dias e ainda não solicitados)
e envia o pedido de avaliação + feedback. Os pedidos enviados ficam em
`relatorios/avaliacoes_solicitadas.csv` e nunca são repetidos.

Exige o papel **Buyer Solicitation** no app da SP-API. Se você adicionar o papel agora, gere um
Refresh Token novo.

```bash
amazon-seller-avaliacoes            # simulação: só mostra quantos estão elegíveis
amazon-seller-avaliacoes --enviar   # envia de verdade
```

Outras opções: `--limite N` (verifica no máximo N pedidos por execução), `--dias-min`/`--dias-max`,
`--marketplace` e `--detalhes`. A Amazon permite cerca de 1 chamada por segundo, então cada pedido
leva uns 2 segundos.

Rode **uma vez por dia**, de uma das formas abaixo.

### Opção A: GitHub Actions (na nuvem, sem deixar o computador ligado)

O workflow `.github/workflows/avaliacoes.yml` já está pronto e roda todo dia às 09:17 (horário de Brasília).

1. No GitHub, abra o repositório e vá em **Settings → Secrets and variables → Actions**.
2. Na aba **Secrets**, crie `SPAPI_CLIENT_ID`, `SPAPI_CLIENT_SECRET` e `SPAPI_REFRESH_TOKEN`.
   Os Secrets ficam criptografados e não aparecem nos logs.
3. Teste em **Actions → Pedir avaliações → Run workflow**, deixando "Enviar de verdade" desmarcado.
   O log mostra quantos pedidos estão elegíveis.
4. Para ligar o envio automático, crie na aba **Variables** a variável `AVALIACOES_ENVIAR` com o valor `true`.
   Sem ela, a execução diária só simula.

Os logs mostram apenas contagens, nunca números de pedido, porque o repositório é público.

### Opção B: no seu computador

**Mac/Linux (cron)**: rode `crontab -e` e adicione, ajustando o caminho:

```
17 9 * * * cd /caminho/para/link-amazon-seller && .venv/bin/amazon-seller-avaliacoes --enviar >> relatorios/avaliacoes.log 2>&1
```

**Windows (Agendador de Tarefas)**: crie uma tarefa básica diária com:
- Programa: `C:\caminho\para\link-amazon-seller\.venv\Scripts\amazon-seller-avaliacoes.exe`
- Argumentos: `--enviar`
- Iniciar em: `C:\caminho\para\link-amazon-seller`

O computador precisa estar ligado no horário agendado.

> Use só uma das opções. Se usar as duas, cada uma tem seu próprio registro. A Amazon recusa um
> segundo pedido para o mesmo pedido, então não há envio duplicado, mas são chamadas desperdiçadas.

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
