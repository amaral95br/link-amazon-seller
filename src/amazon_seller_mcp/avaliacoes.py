"""Comando para automatizar o pedido de avaliação, sem precisar do Claude.

Gera o relatório de pedidos do período, separa os pedidos enviados/entregues, consulta a elegibilidade
de cada um na Amazon e (com --enviar) pede avaliação + feedback. Pedidos já solicitados ficam registrados
em avaliacoes_solicitadas.csv e nunca são repetidos. Feito para rodar uma vez por dia (cron, Agendador de
Tarefas do Windows ou GitHub Actions).

Uso:
    amazon-seller-avaliacoes            # só mostra quantos pedidos estão elegíveis
    amazon-seller-avaliacoes --enviar   # envia os pedidos de avaliação
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone

from . import files, reviews
from .client import SPAPIClient, SPAPIError
from .config import ConfigError, load_config

ORDERS_REPORT = "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL"
MAX_PERIODO_DIAS = 30  # limite da Amazon para esse relatório


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="amazon-seller-avaliacoes", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--enviar", action="store_true", help="envia os pedidos de avaliação (sem isso, só simula)")
    p.add_argument("--dias-min", type=int, default=4, help="ignora compras mais recentes que isso (padrão 4)")
    p.add_argument("--dias-max", type=int, default=34, help="ignora compras mais antigas que isso (padrão 34)")
    p.add_argument("--limite", type=int, default=0, help="máximo de pedidos verificados nesta execução (0 = todos)")
    p.add_argument("--marketplace", help="ID do marketplace (padrão: o primeiro de SPAPI_MARKETPLACE_IDS)")
    p.add_argument("--espera-max", type=int, default=1800, help="segundos para esperar o relatório (padrão 1800)")
    p.add_argument("--detalhes", action="store_true", help="mostra os números dos pedidos com erro")
    args = p.parse_args(argv)
    if args.dias_min < 0 or args.dias_max <= args.dias_min:
        p.error("--dias-max precisa ser maior que --dias-min.")
    if args.dias_max - args.dias_min > MAX_PERIODO_DIAS:
        p.error(f"O período (--dias-max menos --dias-min) pode ter no máximo {MAX_PERIODO_DIAS} dias.")
    return args


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


async def run(args: argparse.Namespace, client: SPAPIClient | None = None) -> int:
    try:
        cliente = client or SPAPIClient(load_config())
    except ConfigError as e:
        log(f"ERRO de configuração: {e}")
        return 2
    cfg = cliente.config
    mkt = args.marketplace or cfg.marketplace_ids[0]
    try:
        agora = datetime.now(timezone.utc)
        inicio, fim = agora - timedelta(days=args.dias_max), agora - timedelta(days=args.dias_min)
        log(f"Gerando relatório de pedidos de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y} (marketplace {mkt})...")
        report_id = await cliente.create_report(ORDERS_REPORT, [mkt], _iso(inicio), _iso(fim))
        report = await cliente.wait_for_report(report_id, timeout=args.espera_max, interval=30)
        status = report.get("processingStatus")
        if status == "DONE_NO_DATA" or (status == "DONE" and not report.get("reportDocumentId")):
            log("Nenhum pedido no período. Nada a fazer.")
            return 0
        if status != "DONE":
            log(f"ERRO: o relatório terminou com status {status} (reportId {report_id}).")
            return 1

        document = await cliente.get_report_document(report["reportDocumentId"])
        content, charset = await cliente.download_document(document)
        path, _ = files.save_report(cfg.reports_dir, ORDERS_REPORT, report_id, files.decode(content, charset))
        columns, rows = files.load_rows(path)
        pedidos = reviews.orders_from_rows(columns, rows, args.dias_min, args.dias_max, "relatório")

        ja = reviews.already_requested(cfg.reports_dir)
        pendentes = [p for p in pedidos if p not in ja]
        lote = pendentes[:args.limite] if args.limite > 0 else pendentes
        log(f"{len(pedidos)} pedidos enviados/entregues no período; {len(pedidos) - len(pendentes)} já solicitados "
            f"antes; verificando {len(lote)} (cerca de {round(len(lote) * 2.2 / 60) or 1} min).")

        contagem, detalhes, negado = await reviews.check_and_send(cliente, lote, mkt, cfg.reports_dir, args.enviar)
        if negado:
            log(f"ERRO {negado.status}: {reviews.DICA_PERMISSAO}")
            return 2

        if args.enviar:
            log(f"Pedidos de avaliação enviados: {contagem['enviado']}. Não elegíveis agora: {contagem['nao_elegivel']}. "
                f"Erros: {contagem['erro']}.")
        else:
            log(f"SIMULAÇÃO (nada foi enviado): {contagem['elegivel']} elegíveis, {contagem['nao_elegivel']} não "
                f"elegíveis agora, {contagem['erro']} erros. Use --enviar para enviar.")
        if len(pendentes) > len(lote):
            log(f"Ficaram {len(pendentes) - len(lote)} pedidos para a próxima execução (--limite).")
        if args.detalhes:
            for d in detalhes:
                log(f"  pedido {d['pedido']}: erro {d['erro']} {d['detalhes']}")
        return 1 if contagem["erro"] and not (contagem["enviado"] or contagem["elegivel"] or contagem["nao_elegivel"]) else 0
    except SPAPIError as e:
        log(f"ERRO da SP-API ({e.status}): {str(e.body)[:300]}")
        return 1
    finally:
        if client is None:
            await cliente.aclose()


def main(argv: list[str] | None = None) -> None:
    sys.exit(asyncio.run(run(parse_args(argv))))


if __name__ == "__main__":
    main()
