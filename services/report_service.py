"""
Serviço de Relatórios e Exportação Estruturada de Dados (CSV e Visualização para Impressão/PDF).
Permite filtragem dinâmica por categoria, período, produto e prioridade.
Gera relatórios conforme especificado na Seção 4.7 do desafio.
"""

import csv
import io
from datetime import datetime, date
from database.db import query_db
from services.inventory_service import list_products, list_movements
from services.analytics_engine import AnalyticsEngine
from services.alert_service import get_all_alerts


def generate_stock_position_report(categoria=None):
    """Relatório 1: Posição Atual do Estoque."""
    produtos = list_products(categoria=categoria, apenas_ativos=True, ordenar_por="nome")
    items = []
    total_itens = len(produtos)
    total_valor = 0.0

    for p in produtos:
        qtd = float(p["quantidade_atual"])
        preco = p["preco_aquisicao_unitario"]
        valor_item = round(qtd * float(preco), 2) if (preco is not None and preco > 0) else None
        if valor_item:
            total_valor += valor_item

        situacao_estoque = "Normal"
        if qtd <= float(p["estoque_minimo"]):
            situacao_estoque = "Crítico (Abaixo do Mínimo)"
        elif p["estoque_maximo"] and qtd > float(p["estoque_maximo"]):
            situacao_estoque = "Excesso"

        items.append({
            "id": p["id"],
            "nome": p["nome"],
            "categoria": p["categoria"],
            "unidade": p["unidade_medida"],
            "saldo_atual": qtd,
            "estoque_minimo": float(p["estoque_minimo"]),
            "estoque_maximo": p["estoque_maximo"],
            "preco_unitario": preco,
            "valor_total": valor_item,
            "situacao": situacao_estoque,
            "local": p["local_armazenamento"] or "Geral",
            "lote": p["lote"] or "N/I"
        })

    return {
        "titulo": "Relatório de Posição do Estoque",
        "data_geracao": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total_itens": total_itens,
        "valor_total_estimado": round(total_valor, 2),
        "items": items
    }


def generate_critical_products_report():
    """Relatório 2: Produtos Críticos e em Risco de Falta."""
    produtos = list_products(apenas_ativos=True)
    items = []

    for p in produtos:
        pid = p["id"]
        stats = AnalyticsEngine.calculate_consumption_stats(pid, days_window=30)
        critico = AnalyticsEngine.analyze_critical_stock(p)
        falta = AnalyticsEngine.analyze_stockout_forecast(p, stats)

        if critico or (falta and falta.get("prioridade") in ("critico", "alto")):
            cmd = stats.get("consumo_medio_diario", 0.0)
            dias_estimados = math_floor = int(float(p["quantidade_atual"]) / cmd) if cmd > 0 else "N/D"

            items.append({
                "id": p["id"],
                "nome": p["nome"],
                "categoria": p["categoria"],
                "saldo_atual": float(p["quantidade_atual"]),
                "estoque_minimo": float(p["estoque_minimo"]),
                "unidade": p["unidade_medida"],
                "consumo_diario": round(cmd, 2),
                "dias_estimados": dias_estimados,
                "prazo_reposicao": p["prazo_reposicao_dias"] or "Não informado",
                "diagnostico": critico["explicacao"] if critico else falta["explicacao"],
                "recomendacao": critico["acao_recomendada"] if critico else falta["acao_recomendada"]
            })

    return {
        "titulo": "Relatório de Produtos Críticos e Risco de Falta",
        "data_geracao": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total_itens": len(items),
        "items": items
    }


def generate_expiration_report():
    """Relatório 3: Vencimentos e Lotes."""
    produtos = list_products(apenas_ativos=True, ordenar_por="validade")
    hoje = date.today()
    items = []

    for p in produtos:
        if p["data_validade"]:
            try:
                dt_val = datetime.strptime(str(p["data_validade"])[:10], "%Y-%m-%d").date()
                dias = (dt_val - hoje).days

                status = "Vencido" if dias < 0 else ("Crítico (<=30d)" if dias <= 30 else ("Alerta (<=60d)" if dias <= 60 else "No Prazo"))

                items.append({
                    "id": p["id"],
                    "nome": p["nome"],
                    "categoria": p["categoria"],
                    "lote": p["lote"] or "N/I",
                    "data_validade": dt_val.strftime("%d/%m/%Y"),
                    "dias_restantes": dias,
                    "saldo_atual": float(p["quantidade_atual"]),
                    "unidade": p["unidade_medida"],
                    "status": status,
                    "local": p["local_armazenamento"] or "Geral"
                })
            except ValueError:
                pass

    items.sort(key=lambda x: x["dias_restantes"])
    return {
        "titulo": "Relatório de Vencimentos e Lotes",
        "data_geracao": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total_itens": len(items),
        "items": items
    }


def generate_movements_report(data_inicio=None, data_fim=None, tipo=None, produto_id=None):
    """Relatório 4: Histórico de Movimentações (Auditoria de Entradas e Saídas)."""
    movs = list_movements(produto_id=produto_id, tipo=tipo, data_inicio=data_inicio, data_fim=data_fim, limite=1000)

    total_entradas = sum(m["quantidade"] for m in movs if m["tipo"] == 'entrada' and m["estornada"] == 0)
    total_saidas = sum(m["quantidade"] for m in movs if m["tipo"] == 'saida' and m["estornada"] == 0)

    return {
        "titulo": "Relatório de Movimentações de Estoque",
        "data_geracao": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total_registros": len(movs),
        "total_entradas": round(total_entradas, 2),
        "total_saidas": round(total_saidas, 2),
        "filtros": {
            "periodo": f"{data_inicio or 'Início'} até {data_fim or 'Hoje'}",
            "tipo": tipo or "Todos"
        },
        "items": movs
    }


def generate_consumption_analysis_report():
    """Relatório 5: Análise de Consumo e Projeções."""
    produtos = list_products(apenas_ativos=True)
    items = []

    for p in produtos:
        stats = AnalyticsEngine.calculate_consumption_stats(p["id"], days_window=30)
        if stats["total_saidas"] > 0:
            cmd = stats["consumo_medio_diario"]
            saldo = float(p["quantidade_atual"])
            duracao = round(saldo / cmd, 1) if cmd > 0 else "Indeterminado"

            items.append({
                "id": p["id"],
                "nome": p["nome"],
                "categoria": p["categoria"],
                "unidade": p["unidade_medida"],
                "total_consumido_30d": stats["total_consumido"],
                "total_saidas_30d": stats["total_saidas"],
                "consumo_medio_diario": round(cmd, 3),
                "saldo_atual": saldo,
                "duracao_dias": duracao,
                "desvio_padrao": stats["desvio_padrao"]
            })

    items.sort(key=lambda x: x["total_consumido_30d"], reverse=True)
    return {
        "titulo": "Relatório de Consumo e Projeções Agronômicas",
        "data_geracao": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total_itens": len(items),
        "items": items
    }


def generate_financial_report():
    """Relatório 6: Valor Financeiro e Capital Alocado."""
    valuation = AnalyticsEngine.analyze_financial_valuation()
    variacoes = AnalyticsEngine.analyze_price_variations()

    return {
        "titulo": "Relatório de Valor Financeiro e Capital Imobilizado",
        "data_geracao": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total_valor_estoque": valuation["total_valor_estoque"],
        "total_itens_avaliados": len(valuation["produtos_ranking"]),
        "ranking": valuation["produtos_ranking"],
        "capital_parado": valuation["itens_capital_parado"],
        "variacoes_precos": variacoes
    }


def generate_alerts_report(prioridade=None, situacao=None):
    """Relatório 7: Alertas Gerados e Recomendações."""
    alertas = get_all_alerts(prioridade_filtro=prioridade, situacao_filtro=situacao)
    return {
        "titulo": "Relatório da Central de Alertas e Recomendações",
        "data_geracao": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "total_alertas": len(alertas),
        "items": alertas
    }


def export_to_csv(data_dict, report_type):
    """Converte o relatório em string CSV com cabeçalhos estruturados."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)

    # Cabeçalho padrão de identificação
    writer.writerow(["AGROHACK 2026/2 - SISTEMA INTELIGENTE DE GESTAO DE INSUMOS"])
    writer.writerow([data_dict.get("titulo", "Relatório de Estoque")])
    writer.writerow([f"Gerado em: {data_dict.get('data_geracao', '')}"])
    writer.writerow([])

    if report_type == "posicao":
        writer.writerow(["ID", "Produto", "Categoria", "Unidade", "Saldo Atual", "Estoque Mínimo", "Estoque Máximo", "Preço Unitário (R$)", "Valor Total (R$)", "Situação", "Lote", "Local"])
        for it in data_dict.get("items", []):
            writer.writerow([
                it["id"], it["nome"], it["categoria"], it["unidade"],
                f"{it['saldo_atual']}".replace(".", ","),
                f"{it['estoque_minimo']}".replace(".", ","),
                f"{it['estoque_maximo'] or ''}".replace(".", ","),
                f"{it['preco_unitario']:.2f}".replace(".", ",") if it["preco_unitario"] is not None else "N/I",
                f"{it['valor_total']:.2f}".replace(".", ",") if it["valor_total"] is not None else "N/I",
                it["situacao"], it["lote"], it["local"]
            ])

    elif report_type == "criticos":
        writer.writerow(["ID", "Produto", "Categoria", "Saldo Atual", "Unidade", "Estoque Mínimo", "Consumo Diário", "Dias Estimados", "Prazo Reposição (dias)", "Diagnóstico", "Recomendação"])
        for it in data_dict.get("items", []):
            writer.writerow([
                it["id"], it["nome"], it["categoria"],
                f"{it['saldo_atual']}".replace(".", ","),
                it["unidade"],
                f"{it['estoque_minimo']}".replace(".", ","),
                f"{it['consumo_diario']}".replace(".", ","),
                it["dias_estimados"], it["prazo_reposicao"],
                it["diagnostico"], it["recomendacao"]
            ])

    elif report_type == "vencimentos":
        writer.writerow(["ID", "Produto", "Categoria", "Lote", "Data de Validade", "Dias Restantes", "Saldo Atual", "Unidade", "Status", "Local"])
        for it in data_dict.get("items", []):
            writer.writerow([
                it["id"], it["nome"], it["categoria"], it["lote"],
                it["data_validade"], it["dias_restantes"],
                f"{it['saldo_atual']}".replace(".", ","),
                it["unidade"], it["status"], it["local"]
            ])

    elif report_type == "movimentacoes":
        writer.writerow(["ID", "Data", "Tipo", "Produto", "Categoria", "Quantidade", "Unidade", "Preço Unit.", "Fornecedor / Destino", "Responsável", "Estornada", "Observação"])
        for it in data_dict.get("items", []):
            writer.writerow([
                it["id"], it["data_movimentacao"], it["tipo"].upper(), it["produto_nome"],
                it.get("produto_categoria", ""),
                f"{it['quantidade']}".replace(".", ","),
                it["unidade_medida"],
                f"{it['preco_unitario']:.2f}".replace(".", ",") if it.get("preco_unitario") else "",
                it.get("fornecedor_destino", ""), it["responsavel"],
                "SIM" if it.get("estornada") == 1 else "NÃO",
                it.get("observacao", "")
            ])

    elif report_type == "consumo":
        writer.writerow(["ID", "Produto", "Categoria", "Unidade", "Consumido 30d", "Saídas 30d", "Consumo Médio Diário", "Saldo Atual", "Duração Estimada (Dias)"])
        for it in data_dict.get("items", []):
            writer.writerow([
                it["id"], it["nome"], it["categoria"], it["unidade"],
                f"{it['total_consumido_30d']}".replace(".", ","),
                it["total_saidas_30d"],
                f"{it['consumo_medio_diario']}".replace(".", ","),
                f"{it['saldo_atual']}".replace(".", ","),
                it["duracao_dias"]
            ])

    elif report_type == "financeiro":
        writer.writerow(["ID", "Produto", "Categoria", "Quantidade", "Unidade", "Preço Unitário (R$)", "Valor Imobilizado (R$)", "Saídas Recentes (60d)"])
        for it in data_dict.get("ranking", []):
            writer.writerow([
                it["id"], it["nome"], it["categoria"],
                f"{it['quantidade']}".replace(".", ","),
                it["unidade"],
                f"{it['preco_unitario']:.2f}".replace(".", ","),
                f"{it['valor_total']:.2f}".replace(".", ","),
                it["saidas_recentes"]
            ])

    elif report_type == "alertas":
        writer.writerow(["Hash", "Produto", "Categoria", "Tipo", "Prioridade", "Situação", "Justificativa / Diagnóstico", "Ação Recomendada", "Data Identificação"])
        for it in data_dict.get("items", []):
            writer.writerow([
                it.get("hash", ""), it.get("produto_nome", ""), it.get("produto_categoria", ""),
                it.get("titulo", ""), it.get("prioridade", "").upper(), it.get("situacao", "").upper(),
                it.get("explicacao", ""), it.get("acao_recomendada", ""),
                it.get("data_criacao", "")
            ])

    return output.getvalue()
