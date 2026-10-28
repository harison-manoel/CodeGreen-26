"""
Serviço da Central de Alertas e Prioridades.
Consolida as análises do AnalyticsEngine, gerencia o ciclo de vida dos alertas
(Pendente -> Em Acompanhamento -> Resolvido), impede duplicações
e garante rastreabilidade das ações de gestão rural.
"""

import hashlib
import json
from datetime import datetime
from database.db import get_db, query_db
from services.analytics_engine import AnalyticsEngine
from services.inventory_service import list_products


def generate_alert_hash(product_id, alert_type, key_identifier=""):
    """Gera um hash único e determinístico para o alerta."""
    raw = f"{product_id}_{alert_type}_{key_identifier}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def get_all_alerts(prioridade_filtro=None, situacao_filtro=None, tipo_filtro=None,
                   categoria_filtro=None, produto_id_filtro=None, natureza_filtro=None, search=None):
    """
    Executa a varredura completa das regras de análise em todos os produtos ativos,
    sincroniza os estados na tabela alertas_status e retorna a lista consolidada.
    Suporta filtros por prioridade, situação, tipo, categoria, produto, natureza e busca textual.
    """
    produtos = list_products(apenas_ativos=True)

    raw_alerts = []

    # 1. Análise por produto (Estoque crítico, Previsão de falta, Vencimento, Excesso)
    for p in produtos:
        pid = p["id"]
        stats = AnalyticsEngine.calculate_consumption_stats(pid, days_window=30)

        # A. Estoque crítico (Problema Confirmado)
        alerta_critico = AnalyticsEngine.analyze_critical_stock(p)
        if alerta_critico:
            raw_alerts.append({
                **alerta_critico,
                "produto_id": pid,
                "produto_nome": p["nome"],
                "produto_categoria": p["categoria"],
                "produto_unidade": p["unidade_medida"],
                "hash": generate_alert_hash(pid, "estoque_critico")
            })

        # B. Previsão de falta (Risco Estimado)
        alerta_falta = AnalyticsEngine.analyze_stockout_forecast(p, stats)
        if alerta_falta and alerta_falta.get("previsao_disponivel"):
            raw_alerts.append({
                **alerta_falta,
                "produto_id": pid,
                "produto_nome": p["nome"],
                "produto_categoria": p["categoria"],
                "produto_unidade": p["unidade_medida"],
                "hash": generate_alert_hash(pid, "previsao_falta")
            })

        # C. Risco de vencimento (Confirmado se vencido, Estimado se a vencer)
        alerta_venc = AnalyticsEngine.analyze_expiration_risk(p, stats)
        if alerta_venc:
            raw_alerts.append({
                **alerta_venc,
                "produto_id": pid,
                "produto_nome": p["nome"],
                "produto_categoria": p["categoria"],
                "produto_unidade": p["unidade_medida"],
                "hash": generate_alert_hash(pid, "risco_vencimento", str(p["data_validade"]))
            })

        # D. Excesso de estoque (Risco Estimado)
        alerta_excesso = AnalyticsEngine.analyze_overstock(p, stats)
        if alerta_excesso:
            raw_alerts.append({
                **alerta_excesso,
                "produto_id": pid,
                "produto_nome": p["nome"],
                "produto_categoria": p["categoria"],
                "produto_unidade": p["unidade_medida"],
                "hash": generate_alert_hash(pid, "excesso_estoque")
            })

    # 2. Análise de anomalias de consumo (Verificação Humana Requerida)
    anomalias = AnalyticsEngine.analyze_consumption_anomalies(days_window=30)
    for anom in anomalias:
        raw_alerts.append({
            "tipo": "consumo_anomalo",
            "prioridade": "alto",
            "natureza": "verificacao_humana",
            "natureza_rotulo": "Verificação Humana Requerida",
            "titulo": "Consumo Fora do Padrão Detectado",
            "produto_id": anom["produto_id"],
            "produto_nome": anom["produto_nome"],
            "produto_categoria": "Movimentação",
            "produto_unidade": anom["unidade_medida"],
            "dados_justificativa": {
                "quantidade_saida": anom["quantidade"],
                "media_padrao": anom["media_padrao"],
                "limite_esperado": anom["limite_esperado"],
                "data_movimentacao": anom["data_movimentacao"],
                "responsavel": anom["responsavel"]
            },
            "explicacao": anom["explicacao"],
            "acao_recomendada": anom["acao_recomendada"],
            "hash": generate_alert_hash(anom["produto_id"], "consumo_anomalo", str(anom["movimentacao_id"]))
        })

    # 3. Análise de variações bruscas de preço (Verificação Humana Requerida)
    variacoes = AnalyticsEngine.analyze_price_variations()
    for var in variacoes:
        if abs(var["variacao_percentual"]) >= 20.0: # Acima de 20% gera alerta
            raw_alerts.append({
                "tipo": "variacao_preco",
                "prioridade": "medio" if var["variacao_percentual"] > 0 else "baixo",
                "natureza": "verificacao_humana",
                "natureza_rotulo": "Verificação Humana Requerida",
                "titulo": f"Variação no Preço de Aquisição ({'+' if var['variacao_percentual'] > 0 else ''}{var['variacao_percentual']}%)",
                "produto_id": var["produto_id"],
                "produto_nome": var["produto_nome"],
                "produto_categoria": "Custo de Aquisição",
                "produto_unidade": var["unidade_medida"],
                "dados_justificativa": var,
                "explicacao": var["explicacao"],
                "acao_recomendada": "Cotar com distribuidores alternativos da região ou negociar condições de compra em maior escala.",
                "hash": generate_alert_hash(var["produto_id"], "variacao_preco", str(var["data_recente"]))
            })

    # 4. Análise de duplicidades cadastrais (Verificação Humana Requerida)
    duplicidades = AnalyticsEngine.detect_duplicate_products()
    for dup in duplicidades:
        if dup["grau_similaridade"] >= 80.0:
            raw_alerts.append({
                "tipo": "duplicidade_cadastro",
                "prioridade": "medio",
                "natureza": "verificacao_humana",
                "natureza_rotulo": "Verificação Humana Requerida",
                "titulo": f"Suspeita de Insumo Duplicado ({dup['grau_similaridade']}% similar)",
                "produto_id": dup["produto_1"]["id"],
                "produto_nome": dup["produto_1"]["nome"],
                "produto_categoria": dup["produto_1"]["categoria"],
                "produto_unidade": dup["produto_1"]["unidade"],
                "dados_justificativa": dup,
                "explicacao": dup["explicacao"],
                "acao_recomendada": dup["acao_recomendada"],
                "hash": generate_alert_hash(dup["produto_1"]["id"], "duplicidade_cadastro", str(dup["produto_2"]["id"]))
            })

    # Sincronizar com a tabela de status no banco (manter observações e status de resolução)
    hashes_existentes = {
        row["alerta_hash"]: row
        for row in query_db("SELECT * FROM alertas_status")
    }

    alerts_consolidated = []
    with get_db() as conn:
        cursor = conn.cursor()
        for a in raw_alerts:
            h = a["hash"]
            if h in hashes_existentes:
                db_record = hashes_existentes[h]
                situacao = db_record["situacao"]
                resolucao = db_record["observacao_resolucao"]
                responsavel = db_record["responsavel"]
                data_criacao = db_record["data_criacao"]
            else:
                situacao = "pendente"
                resolucao = None
                responsavel = None
                data_criacao = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Registrar novo alerta no banco
                cursor.execute("""
                    INSERT OR IGNORE INTO alertas_status (
                        alerta_hash, produto_id, tipo_alerta, prioridade, situacao, data_criacao
                    ) VALUES (?, ?, ?, ?, 'pendente', ?)
                """, (h, a["produto_id"], a["tipo"], a["prioridade"], data_criacao))

            item = {
                **a,
                "situacao": situacao,
                "observacao_resolucao": resolucao,
                "responsavel_resolucao": responsavel,
                "data_criacao": data_criacao
            }
            alerts_consolidated.append(item)

    # Filtragem
    if prioridade_filtro:
        alerts_consolidated = [a for a in alerts_consolidated if a["prioridade"] == prioridade_filtro]
    if situacao_filtro:
        alerts_consolidated = [a for a in alerts_consolidated if a["situacao"] == situacao_filtro]
    if tipo_filtro:
        alerts_consolidated = [a for a in alerts_consolidated if a["tipo"] == tipo_filtro]
    if categoria_filtro:
        alerts_consolidated = [a for a in alerts_consolidated if a.get("produto_categoria") == categoria_filtro]
    if produto_id_filtro:
        try:
            pid_int = int(produto_id_filtro)
            alerts_consolidated = [a for a in alerts_consolidated if a.get("produto_id") == pid_int]
        except (ValueError, TypeError):
            pass
    if natureza_filtro:
        alerts_consolidated = [a for a in alerts_consolidated if a.get("natureza") == natureza_filtro]
    if search:
        s = search.lower().strip()
        alerts_consolidated = [
            a for a in alerts_consolidated
            if s in a.get("produto_nome", "").lower()
            or s in a.get("titulo", "").lower()
            or s in a.get("explicacao", "").lower()
        ]

    # Ordenação por prioridade: critico > alto > medio > baixo
    priority_order = {"critico": 0, "alto": 1, "medio": 2, "baixo": 3}
    alerts_consolidated.sort(key=lambda x: (
        0 if x["situacao"] == "pendente" else (1 if x["situacao"] == "em_acompanhamento" else 2),
        priority_order.get(x["prioridade"], 4),
        x.get("produto_nome", "")
    ))

    return alerts_consolidated


def update_alert_status(alerta_hash, situacao, observacao=None, responsavel=None):
    """Atualiza o status de um alerta (ex: marcar como resolvido ou em acompanhamento)."""
    if situacao not in ('pendente', 'em_acompanhamento', 'resolvido'):
        raise ValueError("Situação inválida. Permitido: pendente, em_acompanhamento, resolvido.")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE alertas_status SET
                situacao = ?,
                observacao_resolucao = COALESCE(?, observacao_resolucao),
                responsavel = COALESCE(?, responsavel),
                data_atualizacao = CURRENT_TIMESTAMP
            WHERE alerta_hash = ?
        """, (situacao, observacao, responsavel, alerta_hash))
        return cursor.rowcount > 0


def get_alerts_summary():
    """Retorna o resumo quantitativo de alertas para o dashboard."""
    alerts = get_all_alerts()
    summary = {
        "total": len(alerts),
        "pendentes": 0,
        "em_acompanhamento": 0,
        "resolvidos": 0,
        "critico": 0,
        "alto": 0,
        "medio": 0,
        "baixo": 0,
        "confirmado": 0,
        "estimado": 0,
        "verificacao_humana": 0,
        "por_tipo": {}
    }

    for a in alerts:
        if a["situacao"] == "pendente":
            summary["pendentes"] += 1
            summary[a["prioridade"]] = summary.get(a["prioridade"], 0) + 1
            nat = a.get("natureza", "confirmado")
            summary[nat] = summary.get(nat, 0) + 1
        elif a["situacao"] == "em_acompanhamento":
            summary["em_acompanhamento"] += 1
            summary[a["prioridade"]] = summary.get(a["prioridade"], 0) + 1
            nat = a.get("natureza", "confirmado")
            summary[nat] = summary.get(nat, 0) + 1
        elif a["situacao"] == "resolvido":
            summary["resolvidos"] += 1

        tipo = a["tipo"]
        summary["por_tipo"][tipo] = summary["por_tipo"].get(tipo, 0) + 1

    return summary
