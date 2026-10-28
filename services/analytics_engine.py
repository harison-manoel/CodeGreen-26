"""
Motor de Análise Inteligente de Insumos Rurais (Explainable Analytics Engine).
Implementa regras de negócio verificáveis, cálculos determinísticos, detecção de
anomalias de consumo, risco de vencimento, previsão de falta e similaridade de produtos.
Todas as regras são transparentes e explicáveis em linguagem humana.
"""

import math
import hashlib
from datetime import datetime, date, timedelta
from difflib import SequenceMatcher
import unicodedata
from database.db import query_db


def normalize_text(text):
    """Remove acentos, pontuações e converte para minúsculas para comparações lexicais."""
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    return "".join(c for c in text.lower() if c.isalnum() or c.isspace()).strip()


def get_config(key, default_val):
    """Busca configuração do banco ou retorna valor padrão."""
    row = query_db("SELECT valor FROM configuracoes WHERE chave = ?", (key,), one=True)
    if row and row["valor"]:
        try:
            return float(row["valor"])
        except ValueError:
            return row["valor"]
    return default_val


class AnalyticsEngine:
    """Motor central de cálculos e análises explicáveis de estoque e insumos."""

    @staticmethod
    def calculate_consumption_stats(product_id, days_window=30):
        """
        Calcula o consumo médio diário (CMD) e estatísticas de saídas nos últimos N dias.
        Retorna dicionário com dados de consumo reais e indicação clara de confiabilidade.
        """
        now = datetime.now()
        start_date = (now - timedelta(days=days_window)).strftime("%Y-%m-%d 00:00:00")

        # Calibra janela efetiva caso o produto tenha sido cadastrado recentemente
        prod_row = query_db("SELECT data_cadastro FROM produtos WHERE id = ?", (product_id,), one=True)
        dias_efetivos = days_window
        if prod_row and prod_row.get("data_cadastro"):
            try:
                dt_cad = datetime.strptime(str(prod_row["data_cadastro"])[:10], "%Y-%m-%d").date()
                dias_desde_cad = (date.today() - dt_cad).days
                if 0 <= dias_desde_cad < days_window:
                    dias_efetivos = max(1, dias_desde_cad)
            except Exception:
                pass

        sql = """
            SELECT quantidade, data_movimentacao
            FROM movimentacoes
            WHERE produto_id = ? AND tipo = 'saida' AND estornada = 0
              AND data_movimentacao >= ?
            ORDER BY data_movimentacao ASC
        """
        movements = query_db(sql, (product_id, start_date))

        total_saidas = len(movements)
        total_quantidade_consumida = sum(float(m["quantidade"]) for m in movements)

        if total_saidas == 0:
            return {
                "periodo_dias": days_window,
                "dias_efetivos": dias_efetivos,
                "total_saidas": 0,
                "total_consumido": 0.0,
                "consumo_medio_diario": 0.0,
                "desvio_padrao": 0.0,
                "dados_suficientes": False,
                "confiabilidade": "insuficiente",
                "mensagem": "Não foram registradas saídas para este produto no período analisado."
            }

        # Consumo médio diário na janela analisada de dias
        consumo_medio_diario = total_quantidade_consumida / days_window

        # Cálculo do desvio padrão por movimentação individual
        quantidades = [float(m["quantidade"]) for m in movements]
        media_por_saida = sum(quantidades) / len(quantidades)
        variancia = sum((q - media_por_saida) ** 2 for q in quantidades) / len(quantidades)
        desvio_padrao = math.sqrt(variancia)

        # Confiabilidade estatística explícita
        if total_saidas >= 3:
            confiabilidade = "alta"
            dados_suficientes = True
            msg = f"Consumo médio de {consumo_medio_diario:.2f} unid/dia com base em {total_saidas} saídas nos últimos {days_window} dias (alta confiabilidade)."
        elif total_saidas == 2:
            confiabilidade = "media"
            dados_suficientes = True
            msg = f"Consumo médio de {consumo_medio_diario:.2f} unid/dia com base em {total_saidas} saídas (amostra inicial, confiabilidade média)."
        else:
            confiabilidade = "baixa"
            dados_suficientes = False
            msg = f"Apenas 1 saída registrada de {total_quantidade_consumida:g} unid. Histórico preliminar insuficiente para certeza estatística."

        return {
            "periodo_dias": days_window,
            "total_saidas": total_saidas,
            "total_consumido": round(total_quantidade_consumida, 2),
            "consumo_medio_diario": round(consumo_medio_diario, 4),
            "media_por_saida": round(media_por_saida, 2),
            "desvio_padrao": round(desvio_padrao, 2),
            "dados_suficientes": dados_suficientes,
            "confiabilidade": confiabilidade,
            "mensagem": msg
        }

    @staticmethod
    def analyze_critical_stock(product):
        """A. Análise de Estoque Crítico (saldo atual <= estoque mínimo) - Problema Confirmado."""
        qtd = float(product["quantidade_atual"])
        minimo = float(product["estoque_minimo"])
        unidade = product["unidade_medida"]

        if qtd <= minimo:
            nivel = "critico" if qtd <= (minimo * 0.5) or qtd == 0 else "alto"
            deficit = round(minimo - qtd, 2)
            return {
                "tipo": "estoque_critico",
                "prioridade": nivel,
                "natureza": "confirmado",
                "natureza_rotulo": "Problema Confirmado",
                "titulo": "Estoque Crítico / Abaixo do Mínimo",
                "dados_justificativa": {
                    "quantidade_atual": qtd,
                    "estoque_minimo": minimo,
                    "unidade_medida": unidade,
                    "deficit": deficit
                },
                "explicacao": (
                    f"O saldo atual é de {qtd:g} {unidade}, atingindo ou ficando abaixo do limite mínimo de "
                    f"segurança configurado ({minimo:g} {unidade}). O déficit atual para o nível seguro é de {deficit:g} {unidade}."
                ),
                "acao_recomendada": f"Emitir pedido de reposição de no mínimo {max(deficit, 1):g} {unidade} imediatamente para evitar parada de operações agrícolas."
            }
        return None

    @staticmethod
    def analyze_stockout_forecast(product, consumption_stats):
        """B. Previsão de Falta e Duração do Estoque - Risco Estimado."""
        qtd = float(product["quantidade_atual"])
        unidade = product["unidade_medida"]
        prazo_reposicao = product["prazo_reposicao_dias"]

        if not consumption_stats.get("dados_suficientes") or consumption_stats.get("consumo_medio_diario", 0) <= 0:
            return {
                "tipo": "previsao_falta",
                "prioridade": "baixo",
                "natureza": "estimado",
                "natureza_rotulo": "Risco Estimado",
                "titulo": "Previsão de Falta: Dados Insuficientes",
                "previsao_disponivel": False,
                "dados_justificativa": {
                    "quantidade_atual": qtd,
                    "consumo_medio_diario": 0,
                    "unidade_medida": unidade,
                    "confiabilidade": consumption_stats.get("confiabilidade", "insuficiente")
                },
                "explicacao": (
                    "Não há histórico suficiente de saídas registradas nos últimos "
                    f"{consumption_stats.get('periodo_dias', 30)} dias para estimar com segurança o ritmo de consumo deste insumo."
                ),
                "acao_recomendada": "Continue registrando as retiradas de campo regularmente para calibrar a taxa de consumo deste insumo."
            }

        cmd = consumption_stats["consumo_medio_diario"]
        dias_estimados = math.floor(qtd / cmd) if cmd > 0 else 9999

        # Comparação com o prazo de reposição quando disponível
        risco_reposicao = False
        prioridade = "baixo"
        if dias_estimados <= 7:
            prioridade = "critico"
        elif dias_estimados <= 15:
            prioridade = "alto"
        elif dias_estimados <= 30:
            prioridade = "medio"

        if prazo_reposicao is not None:
            if dias_estimados <= prazo_reposicao:
                risco_reposicao = True
                prioridade = "critico"

        if prioridade in ("critico", "alto", "medio"):
            explicacao = (
                f"O produto apresenta consumo médio de {cmd:.2f} {unidade}/dia nos últimos "
                f"{consumption_stats.get('dias_efetivos', consumption_stats['periodo_dias'])} dias e saldo atual de {qtd:g} {unidade}. "
                f"Mantido este ritmo, a estimativa de duração do estoque é de aproximadamente {dias_estimados} dia(s)."
            )
            if risco_reposicao:
                explicacao += (
                    f" ATENÇÃO: A duração estimada ({dias_estimados} dias) é menor ou igual ao prazo "
                    f"cadastrado para entrega pelo fornecedor ({prazo_reposicao} dias), configurando risco iminente de desabastecimento!"
                )

            return {
                "tipo": "previsao_falta",
                "prioridade": prioridade,
                "natureza": "estimado",
                "natureza_rotulo": "Risco Estimado",
                "titulo": "Risco de Falta de Estoque",
                "previsao_disponivel": True,
                "dados_justificativa": {
                    "quantidade_atual": qtd,
                    "consumo_medio_diario": cmd,
                    "dias_estimados": dias_estimados,
                    "prazo_reposicao_dias": prazo_reposicao,
                    "unidade_medida": unidade,
                    "confiabilidade": consumption_stats.get("confiabilidade", "media")
                },
                "explicacao": explicacao,
                "acao_recomendada": (
                    f"Programar pedido urgente com o fornecedor para entrega em até {max(1, dias_estimados - 2)} dias, "
                    f"assegurando a continuidade do cronograma agronômico."
                )
            }
        return None

    @staticmethod
    def analyze_expiration_risk(product, consumption_stats):
        """C. Risco de Vencimento e Perda por Expiração."""
        data_validade_str = product["data_validade"]
        if not data_validade_str:
            return None

        try:
            validade = datetime.strptime(str(data_validade_str)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

        hoje = date.today()
        dias_restantes = (validade - hoje).days
        qtd = float(product["quantidade_atual"])
        unidade = product["unidade_medida"]
        cmd = consumption_stats.get("consumo_medio_diario", 0.0)

        # Configuração de janela de alerta
        dias_alerta_config = int(get_config("dias_alerta_validade", 60))

        if dias_restantes < 0:
            return {
                "tipo": "risco_vencimento",
                "prioridade": "critico",
                "natureza": "confirmado",
                "natureza_rotulo": "Problema Confirmado",
                "titulo": "Produto Vencido em Estoque",
                "dados_justificativa": {
                    "data_validade": str(validade),
                    "dias_vencido": abs(dias_restantes),
                    "quantidade_atual": qtd,
                    "unidade_medida": unidade,
                    "lote": product["lote"]
                },
                "explicacao": (
                    f"O lote {product['lote'] or 'N/I'} venceu em {validade.strftime('%d/%m/%Y')} "
                    f"({abs(dias_restantes)} dias atrás) e ainda constam {qtd:g} {unidade} armazenadas."
                ),
                "acao_recomendada": "Segregar o produto imediatamente no depósito para evitar uso inadvertido na lavoura e avaliar procedimento de devolução ou descarte técnico adequado."
            }

        elif dias_restantes <= dias_alerta_config and qtd > 0:
            prioridade = "alto" if dias_restantes <= 30 else "medio"

            # Avaliar se o consumo previsto é suficiente para utilizar todo o estoque antes do vencimento
            alerta_sobra = ""
            if cmd > 0:
                consumo_estimado_ate_vencer = cmd * dias_restantes
                if consumo_estimado_ate_vencer < qtd:
                    sobra_prevista = round(qtd - consumo_estimado_ate_vencer, 2)
                    alerta_sobra = (
                        f" Com o consumo estimado ({cmd:.2f} {unidade}/dia), projeta-se utilizar apenas "
                        f"{consumo_estimado_ate_vencer:.1f} {unidade} até o vencimento, resultando em sobra estimada de "
                        f"{sobra_prevista:g} {unidade} com risco de descarte e perda financeira."
                    )

            return {
                "tipo": "risco_vencimento",
                "prioridade": prioridade,
                "natureza": "estimado",
                "natureza_rotulo": "Risco Estimado",
                "titulo": "Produto Próximo do Vencimento",
                "dados_justificativa": {
                    "data_validade": str(validade),
                    "dias_restantes": dias_restantes,
                    "quantidade_atual": qtd,
                    "unidade_medida": unidade,
                    "lote": product["lote"]
                },
                "explicacao": (
                    f"O produto tem validade próxima ({validade.strftime('%d/%m/%Y')}, restando {dias_restantes} dias) "
                    f"com saldo de {qtd:g} {unidade} no estoque.{alerta_sobra}"
                ),
                "acao_recomendada": "Priorizar a aplicação deste lote nas operações imediatas de campo (regra FEFO - First Expired, First Out) ou verificar permuta técnica com propriedades parceiras."
            }
        return None

    @staticmethod
    def analyze_overstock(product, consumption_stats):
        """D. Análise de Excesso de Estoque - Risco Estimado."""
        qtd = float(product["quantidade_atual"])
        minimo = float(product["estoque_minimo"])
        maximo = product["estoque_maximo"]
        unidade = product["unidade_medida"]
        cmd = consumption_stats.get("consumo_medio_diario", 0.0)

        # Regra 1: Estoque Máximo definido pelo produtor
        if maximo is not None and maximo > 0 and qtd > maximo:
            excesso = round(qtd - maximo, 2)
            return {
                "tipo": "excesso_estoque",
                "prioridade": "medio",
                "natureza": "estimado",
                "natureza_rotulo": "Risco Estimado",
                "titulo": "Excesso de Estoque (Acima da Capacidade Máxima)",
                "dados_justificativa": {
                    "quantidade_atual": qtd,
                    "estoque_maximo": maximo,
                    "excesso": excesso,
                    "unidade_medida": unidade
                },
                "explicacao": (
                    f"O saldo atual de {qtd:g} {unidade} ultrapassou o teto de estoque máximo estipulado "
                    f"({maximo:g} {unidade}) em {excesso:g} {unidade}."
                ),
                "acao_recomendada": "Suspender temporariamente novas compras deste insumo para liberar espaço físico no depósito e reduzir custos de armazenagem."
            }

        # Regra 2: Saldo superior a N vezes o estoque mínimo com consumo baixo/nulo
        multiplicador = float(get_config("multiplicador_excesso", 3.0))
        if minimo > 0 and qtd >= (minimo * multiplicador):
            if cmd == 0 or (cmd > 0 and (qtd / cmd) > 180): # Mais de 6 meses de suprimento
                dias_cobertura = math.floor(qtd / cmd) if cmd > 0 else "Indeterminado"
                return {
                    "tipo": "excesso_estoque",
                    "prioridade": "baixo",
                    "natureza": "estimado",
                    "natureza_rotulo": "Risco Estimado",
                    "titulo": "Estoque Elevado com Baixo Giro",
                    "dados_justificativa": {
                        "quantidade_atual": qtd,
                        "estoque_minimo": minimo,
                        "dias_cobertura": dias_cobertura,
                        "unidade_medida": unidade
                    },
                    "explicacao": (
                        f"O saldo atual ({qtd:g} {unidade}) é {qtd/minimo:.1f} vezes maior que a margem mínima de segurança "
                        f"({minimo:g} {unidade}), cobrindo mais de 180 dias de demanda no ritmo recente de saídas."
                    ),
                    "acao_recomendada": "Reavaliar o lote de compras para evitar capital imobilizado desnecessário na propriedade rural."
                }
        return None

    @staticmethod
    def analyze_consumption_anomalies(days_window=30):
        """
        E. Detecção de Consumo Fora do Padrão (Anomalias de Saída).
        Compara cada retirada individual com a média e desvio padrão histórico daquele insumo.
        Utiliza baseline robusto para evitar que a própria anomalia mascare o desvio em amostras pequenas.
        """
        now = datetime.now()
        start_date = (now - timedelta(days=days_window)).strftime("%Y-%m-%d 00:00:00")
        fator_anomalia = float(get_config("fator_anomalia_consumo", 2.0))

        sql = """
            SELECT m.*, p.nome as produto_nome, p.unidade_medida
            FROM movimentacoes m
            JOIN produtos p ON m.produto_id = p.id
            WHERE m.tipo = 'saida' AND m.estornada = 0 AND m.data_movimentacao >= ?
            ORDER BY m.data_movimentacao DESC
        """
        recent_movements = query_db(sql, (start_date,))

        anomalies = []
        # Buscar todo o histórico de saídas por produto para comparação
        all_movements_sql = """
            SELECT produto_id, quantidade, data_movimentacao
            FROM movimentacoes
            WHERE tipo = 'saida' AND estornada = 0
            ORDER BY data_movimentacao ASC
        """
        all_movs = query_db(all_movements_sql)
        by_prod_all = {}
        for m in all_movs:
            by_prod_all.setdefault(m["produto_id"], []).append(float(m["quantidade"]))

        for mov in recent_movements:
            pid = mov["produto_id"]
            history = by_prod_all.get(pid, [])
            if len(history) >= 3:
                qtd_mov = float(mov["quantidade"])
                # Baseline excluindo a própria movimentação quando possível (leave-one-out)
                other_quantities = [q for q in history]
                if qtd_mov in other_quantities and len(other_quantities) > 1:
                    other_quantities.remove(qtd_mov)

                media_baseline = sum(other_quantities) / len(other_quantities) if other_quantities else qtd_mov
                variancia = sum((q - media_baseline) ** 2 for q in other_quantities) / len(other_quantities) if len(other_quantities) > 1 else 0
                desvio = math.sqrt(variancia)

                limite_superior = media_baseline + (fator_anomalia * desvio) if desvio > 0 else (media_baseline * 2.0)

                # Se a retirada superar o limite superior e for pelo menos 70% maior que a média baseline
                if qtd_mov > limite_superior and (qtd_mov >= media_baseline * 1.7):
                    anomalies.append({
                        "movimentacao_id": mov["id"],
                        "produto_id": pid,
                        "produto_nome": mov["produto_nome"],
                        "quantidade": qtd_mov,
                        "unidade_medida": mov["unidade_medida"],
                        "media_padrao": round(media_baseline, 2),
                        "limite_esperado": round(limite_superior, 2),
                        "data_movimentacao": mov["data_movimentacao"],
                        "responsavel": mov["responsavel"],
                        "observacao": mov["observacao"] or "Sem observação",
                        "natureza": "verificacao_humana",
                        "natureza_rotulo": "Verificação Humana Requerida",
                        "explicacao": (
                            f"A retirada de {qtd_mov:g} {mov['unidade_medida']} em {mov['data_movimentacao'][:10]} por "
                            f"{mov['responsavel']} superou em {((qtd_mov/media_baseline)-1)*100:.0f}% a média histórica usual "
                            f"({media_baseline:.1f} {mov['unidade_medida']})."
                        ),
                        "acao_recomendada": "Verificar com o operador de campo o destino desta aplicação (possível vazamento, quebra ou lote extraordinário em talhão específico)."
                    })
        return anomalies

    @staticmethod
    def analyze_financial_valuation():
        """
        F. Valor Financeiro Armazenado e Capital Parado.
        Calcula valor estimado considerando estritamente produtos com preços válidos e quantidades válidas.
        Identifica produtos de alto valor com baixa movimentação nos últimos 60 dias.
        """
        sql = """
            SELECT p.*,
                   (SELECT COUNT(*) FROM movimentacoes m WHERE m.produto_id = p.id AND m.tipo = 'saida' AND m.estornada = 0 AND m.data_movimentacao >= date('now', '-60 day')) as saidas_recentes
            FROM produtos p
            WHERE p.ativo = 1
        """
        produtos = query_db(sql)

        total_valor_geral = 0.0
        produtos_valorizados = []
        capital_parado = []

        for p in produtos:
            qtd = float(p["quantidade_atual"])
            preco = p["preco_aquisicao_unitario"]

            if preco is not None and preco > 0 and qtd > 0:
                valor_total_item = round(qtd * float(preco), 2)
                total_valor_geral += valor_total_item

                item_info = {
                    "id": p["id"],
                    "nome": p["nome"],
                    "categoria": p["categoria"],
                    "quantidade": qtd,
                    "unidade_medida": p["unidade_medida"],
                    "preco_unitario": float(preco),
                    "valor_total": valor_total_item,
                    "saidas_recentes": p["saidas_recentes"]
                }
                produtos_valorizados.append(item_info)

                # Critério de Capital Parado: valor total significativo (> R$ 1.500) sem nenhuma saída recente
                if valor_total_item >= 1500.0 and p["saidas_recentes"] == 0:
                    capital_parado.append(item_info)

        produtos_valorizados.sort(key=lambda x: x["valor_total"], reverse=True)
        capital_parado.sort(key=lambda x: x["valor_total"], reverse=True)

        return {
            "total_valor_estoque": round(total_valor_geral, 2),
            "produtos_ranking": produtos_valorizados,
            "itens_capital_parado": capital_parado
        }

    @staticmethod
    def analyze_price_variations():
        """
        G. Variações de Preço de Aquisição.
        Compara entradas sucessivas do mesmo produto para identificar altas ou quedas relevantes no custo unitário.
        """
        sql = """
            SELECT m.produto_id, p.nome as produto_nome, p.unidade_medida,
                   m.preco_unitario, m.data_movimentacao, m.fornecedor_destino
            FROM movimentacoes m
            JOIN produtos p ON m.produto_id = p.id
            WHERE m.tipo = 'entrada' AND m.estornada = 0 AND m.preco_unitario IS NOT NULL AND m.preco_unitario > 0
            ORDER BY m.produto_id, m.data_movimentacao ASC
        """
        entradas = query_db(sql)

        by_product = {}
        for e in entradas:
            pid = e["produto_id"]
            if pid not in by_product:
                by_product[pid] = []
            by_product[pid].append(e)

        variations = []
        for pid, records in by_product.items():
            if len(records) >= 2:
                # Compara as duas aquisições mais recentes com preço
                anterior = records[-2]
                recente = records[-1]

                p_ant = float(anterior["preco_unitario"])
                p_rec = float(recente["preco_unitario"])

                if p_ant > 0:
                    diff_pct = round(((p_rec - p_ant) / p_ant) * 100, 1)
                    if abs(diff_pct) >= 10.0:  # Variação igual ou superior a 10%
                        variations.append({
                            "produto_id": pid,
                            "produto_nome": recente["produto_nome"],
                            "unidade_medida": recente["unidade_medida"],
                            "preco_anterior": p_ant,
                            "preco_recente": p_rec,
                            "variacao_percentual": diff_pct,
                            "data_anterior": anterior["data_movimentacao"],
                            "data_recente": recente["data_movimentacao"],
                            "fornecedor_recente": recente["fornecedor_destino"] or "Não informado",
                            "tipo_variacao": "alta" if diff_pct > 0 else "queda",
                            "natureza": "verificacao_humana",
                            "natureza_rotulo": "Verificação Humana Requerida",
                            "explicacao": (
                                f"O preço unitário passou de R$ {p_ant:.2f} para R$ {p_rec:.2f} "
                                f"({'+' if diff_pct > 0 else ''}{diff_pct}%) entre {anterior['data_movimentacao'][:10]} "
                                f"e {recente['data_movimentacao'][:10]}."
                            )
                        })

        variations.sort(key=lambda x: abs(x["variacao_percentual"]), reverse=True)
        return variations

    @staticmethod
    def detect_duplicate_products():
        """
        H. Detecção de Produtos Cadastrados com Grafias Diferentes / Possíveis Duplicidades.
        Utiliza algoritmo de similaridade combinando:
        1. SequenceMatcher clássico (ordem direta de caracteres).
        2. Token Sort Ratio (ordenação de palavras para captar permutações como 'Ureia 46% Agrícola' vs 'Ureia Agrícola 46%').
        3. Sobreposição de tokens-chave (Jaccard).
        Apresenta sugestões para revisão manual sem excluir nada automaticamente.
        """
        produtos = query_db("SELECT id, nome, categoria, unidade_medida, lote, quantidade_atual FROM produtos WHERE ativo = 1")
        duplicidades = []

        n = len(produtos)
        for i in range(n):
            for j in range(i + 1, n):
                p1 = produtos[i]
                p2 = produtos[j]

                norm1 = normalize_text(p1["nome"])
                norm2 = normalize_text(p2["nome"])

                if not norm1 or not norm2:
                    continue

                # 1. Razão clássica
                ratio_direct = SequenceMatcher(None, norm1, norm2).ratio()

                # 2. Token sort ratio (independência da ordem das palavras)
                words1 = norm1.split()
                words2 = norm2.split()
                sorted1 = " ".join(sorted(words1))
                sorted2 = " ".join(sorted(words2))
                ratio_sorted = SequenceMatcher(None, sorted1, sorted2).ratio()

                # 3. Jaccard token overlap
                set1 = set(words1)
                set2 = set(words2)
                intersection = set1.intersection(set2)
                union = set1.union(set2)
                jaccard = (len(intersection) / len(union)) if union else 0.0

                max_ratio = max(ratio_direct, ratio_sorted)
                is_sub = (norm1 in norm2 or norm2 in norm1) and min(len(norm1), len(norm2)) >= 5

                # Dispara se similaridade for expressiva (>= 75% ou tokens compartilhados significativos)
                if max_ratio >= 0.75 or (jaccard >= 0.60 and len(intersection) >= 2) or is_sub:
                    grau = round(max(max_ratio, jaccard) * 100, 1)
                    duplicidades.append({
                        "produto_1": {
                            "id": p1["id"],
                            "nome": p1["nome"],
                            "categoria": p1["categoria"],
                            "unidade": p1["unidade_medida"],
                            "saldo": p1["quantidade_atual"]
                        },
                        "produto_2": {
                            "id": p2["id"],
                            "nome": p2["nome"],
                            "categoria": p2["categoria"],
                            "unidade": p2["unidade_medida"],
                            "saldo": p2["quantidade_atual"]
                        },
                        "grau_similaridade": grau,
                        "mesma_categoria": p1["categoria"] == p2["categoria"],
                        "natureza": "verificacao_humana",
                        "natureza_rotulo": "Verificação Humana Requerida",
                        "explicacao": (
                            f"Os cadastros '{p1['nome']}' (ID #{p1['id']}) e '{p2['nome']}' (ID #{p2['id']}) "
                            f"apresentam grafia {grau}% similar e podem se referir ao mesmo insumo comercial."
                        ),
                        "acao_recomendada": "Revisar manualmente os registros cadastrais. Caso sejam o mesmo produto, unificar os saldos via inventário e inativar o registro duplicado."
                    })

        return duplicidades

    @staticmethod
    def analyze_capital_distribution(categoria=None):
        """
        I. Distribuição de Capital por Categoria e Insumos (Gráfico de Capital).
        Calcula o montante financeiro real alocado em estoque por categoria oficial e insumo.
        """
        sql = "SELECT id, nome, categoria, unidade_medida, quantidade_atual, preco_aquisicao_unitario FROM produtos WHERE ativo = 1"
        params = []
        if categoria:
            sql += " AND categoria = ?"
            params.append(categoria)

        produtos = query_db(sql, params)
        total_geral = 0.0
        por_categoria = {}
        itens = []

        for p in produtos:
            qtd = float(p["quantidade_atual"])
            preco = p["preco_aquisicao_unitario"]
            if preco is not None and preco > 0 and qtd > 0:
                val = round(qtd * float(preco), 2)
                total_geral += val
                cat = p["categoria"]
                if cat not in por_categoria:
                    por_categoria[cat] = {"valor": 0.0, "itens": 0}
                por_categoria[cat]["valor"] += val
                por_categoria[cat]["itens"] += 1
                itens.append({
                    "id": p["id"],
                    "nome": p["nome"],
                    "categoria": p["categoria"],
                    "valor_total": val,
                    "quantidade": qtd,
                    "unidade_medida": p["unidade_medida"]
                })

        # Ordenar categorias por valor total
        categorias_ranking = []
        for cat, info in sorted(por_categoria.items(), key=lambda x: x[1]["valor"], reverse=True):
            pct = round((info["valor"] / total_geral * 100), 1) if total_geral > 0 else 0
            categorias_ranking.append({
                "categoria": cat,
                "valor_total": round(info["valor"], 2),
                "total_itens": info["itens"],
                "percentual": pct
            })

        itens.sort(key=lambda x: x["valor_total"], reverse=True)

        return {
            "total_geral": round(total_geral, 2),
            "categorias": categorias_ranking,
            "top_itens": itens[:10]
        }

    @staticmethod
    def analyze_stock_duration(limit=10, categoria=None):
        """
        J. Estimativa de Duração do Estoque (Dias de Cobertura vs Prazo de Reposição).
        Calcula projeção de dias restantes para insumos ativos com consumo monitorado.
        """
        sql = "SELECT * FROM produtos WHERE ativo = 1"
        params = []
        if categoria:
            sql += " AND categoria = ?"
            params.append(categoria)

        produtos = query_db(sql, params)
        duracoes = []

        for p in produtos:
            stats = AnalyticsEngine.calculate_consumption_stats(p["id"], days_window=30)
            cmd = stats.get("consumo_medio_diario", 0.0)
            qtd = float(p["quantidade_atual"])
            prazo = p["prazo_reposicao_dias"]

            if cmd > 0 and qtd > 0:
                dias = math.floor(qtd / cmd)
                # Classificação de status da cobertura
                if prazo is not None and dias <= prazo:
                    situacao = "Crítico (Falta antes da reposição)"
                    status_cor = "critico"
                elif dias <= 7:
                    situacao = "Crítico (<= 7 dias)"
                    status_cor = "critico"
                elif dias <= 15:
                    situacao = "Alerta (8-15 dias)"
                    status_cor = "alto"
                elif dias <= 45:
                    situacao = "Adequado (16-45 dias)"
                    status_cor = "medio"
                else:
                    situacao = "Amplo / Seguro (> 45 dias)"
                    status_cor = "baixo"

                duracoes.append({
                    "id": p["id"],
                    "nome": p["nome"],
                    "categoria": p["categoria"],
                    "quantidade": qtd,
                    "unidade_medida": p["unidade_medida"],
                    "consumo_medio_diario": cmd,
                    "dias_estimados": dias,
                    "prazo_reposicao_dias": prazo or "N/I",
                    "situacao": situacao,
                    "status_cor": status_cor,
                    "confiabilidade": stats.get("confiabilidade", "media")
                })

        duracoes.sort(key=lambda x: x["dias_estimados"])
        return duracoes[:limit]
