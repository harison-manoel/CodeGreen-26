"""
Suíte de Testes Automatizados para o AGROHACK 2026/2.
Cobre rigorosamente as 12 regras de validação exigidas na Seção 9 do desafio:
1. Cadastro e edição de produtos
2. Entrada e saída de estoque
3. Bloqueio de saída acima do saldo disponível
4. Cálculo do estoque mínimo
5. Cálculo de consumo médio e duração estimada
6. Identificação de produtos próximos do vencimento
7. Cálculo do valor financeiro
8. Detecção de movimentações fora do padrão
9. Atualização dos alertas após movimentações
10. Tratamento de campos ausentes
11. Atualização e cancelamento/estorno de movimentações
12. Persistência dos dados no SQLite
"""

import os
import unittest
import tempfile
from datetime import datetime, date, timedelta

# Configura banco temporário isolado para os testes
temp_db_fd, temp_db_path = tempfile.mkstemp(suffix="_test_agro.db")
os.environ["DATABASE_PATH"] = temp_db_path

from database.db import init_db, query_db, get_db
from services.inventory_service import (
    create_product, update_product, get_product, list_products,
    register_movement, cancel_or_revert_movement, list_movements
)
from services.analytics_engine import AnalyticsEngine
from services.alert_service import get_all_alerts, get_alerts_summary, update_alert_status


class AgrohackSystemTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        init_db(force=True)

    def setUp(self):
        # Limpa dados entre testes
        with get_db() as conn:
            conn.execute("DELETE FROM movimentacoes_auditoria;")
            conn.execute("DELETE FROM alertas_status;")
            conn.execute("DELETE FROM movimentacoes;")
            conn.execute("DELETE FROM produtos;")

    # -------------------------------------------------------------
    # 1. Cadastro e Edição de Produtos
    # -------------------------------------------------------------
    def test_01_create_and_edit_product(self):
        """Valida criação e edição com verificação de campos e regras."""
        p_data = {
            "nome": "Adubo NPK 20-00-20",
            "categoria": "Fertilizantes",
            "unidade_medida": "saca 50kg",
            "quantidade_atual": 10.0,
            "estoque_minimo": 5.0,
            "estoque_maximo": 50.0,
            "preco_aquisicao_unitario": 160.0,
            "lote": "L-NPK-TESTE",
            "fornecedor": "AgroRondônia"
        }
        pid = create_product(p_data)
        self.assertIsNotNone(pid)

        prod = get_product(pid)
        self.assertEqual(prod["nome"], "Adubo NPK 20-00-20")
        self.assertEqual(prod["quantidade_atual"], 10.0)

        # Atualização cadastral
        update_product(pid, {
            "nome": "Adubo NPK 20-00-20 Especial",
            "estoque_minimo": 8.0,
            "fornecedor": "AgroRondônia Matriz"
        })
        prod_updated = get_product(pid)
        self.assertEqual(prod_updated["nome"], "Adubo NPK 20-00-20 Especial")
        self.assertEqual(prod_updated["estoque_minimo"], 8.0)
        self.assertEqual(prod_updated["fornecedor"], "AgroRondônia Matriz")

    # -------------------------------------------------------------
    # 2. Entrada e Saída de Estoque
    # -------------------------------------------------------------
    def test_02_in_and_out_movements(self):
        """Valida que entradas aumentam e saídas diminuem o saldo corretamente."""
        pid = create_product({
            "nome": "Calcário Agrícola",
            "categoria": "Corretivos",
            "unidade_medida": "tonelada",
            "quantidade_atual": 0.0,
            "estoque_minimo": 5.0
        })

        # Entrada de 20 toneladas
        res_in = register_movement(
            product_id=pid,
            tipo="entrada",
            quantidade=20.0,
            preco_unitario=220.0,
            responsavel="Eng. Agrônomo",
            observacao="Carga recebida"
        )
        self.assertEqual(res_in["saldo_novo"], 20.0)
        self.assertEqual(get_product(pid)["quantidade_atual"], 20.0)

        # Saída de 8 toneladas
        res_out = register_movement(
            product_id=pid,
            tipo="saida",
            quantidade=8.0,
            responsavel="Tratorista",
            fornecedor_destino="Talhão Café 1"
        )
        self.assertEqual(res_out["saldo_novo"], 12.0)
        self.assertEqual(get_product(pid)["quantidade_atual"], 12.0)

    # -------------------------------------------------------------
    # 3. Bloqueio de Saída Acima do Saldo Disponível
    # -------------------------------------------------------------
    def test_03_block_output_exceeding_stock(self):
        """Garante bloqueio estrito de saídas superiores ao saldo com exceção clara."""
        pid = create_product({
            "nome": "Herbicida Seletivo",
            "categoria": "Defensivos e produtos biológicos",
            "unidade_medida": "litro",
            "quantidade_atual": 15.0,
            "estoque_minimo": 5.0
        })

        # Tentar retirar 20 litros tendo apenas 15
        with self.assertRaises(ValueError) as context:
            register_movement(
                product_id=pid,
                tipo="saida",
                quantidade=20.0,
                responsavel="Operador"
            )

        self.assertIn("Saldo insuficiente", str(context.exception))
        # Saldo deve permanecer inalterado em 15.0
        self.assertEqual(get_product(pid)["quantidade_atual"], 15.0)

    # -------------------------------------------------------------
    # 4. Cálculo do Estoque Mínimo e Alerta de Nível Crítico
    # -------------------------------------------------------------
    def test_04_critical_stock_detection(self):
        """Identifica produto com saldo <= estoque mínimo."""
        pid = create_product({
            "nome": "Semente de Milho BRS",
            "categoria": "Sementes",
            "unidade_medida": "saca 20kg",
            "quantidade_atual": 4.0,
            "estoque_minimo": 10.0
        })

        prod = get_product(pid)
        alert = AnalyticsEngine.analyze_critical_stock(prod)
        self.assertIsNotNone(alert)
        self.assertEqual(alert["tipo"], "estoque_critico")
        self.assertEqual(alert["prioridade"], "critico")
        self.assertEqual(alert["dados_justificativa"]["deficit"], 6.0)

    # -------------------------------------------------------------
    # 5. Cálculo de Consumo Médio e Duração Estimada
    # -------------------------------------------------------------
    def test_05_consumption_and_stockout_forecast(self):
        """Calcula consumo médio diário e previsão de dias até desabastecimento."""
        pid = create_product({
            "nome": "Óleo 2T Motosserra",
            "categoria": "Combustíveis e lubrificantes",
            "unidade_medida": "litro",
            "quantidade_atual": 30.0,
            "estoque_minimo": 10.0,
            "prazo_reposicao_dias": 5
        })

        # Registra 3 saídas nos últimos dias: total 15 litros em 30 dias
        for i in [10, 5, 2]:
            register_movement(
                product_id=pid,
                tipo="saida",
                quantidade=5.0,
                data_movimentacao=(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d %H:%M:%S"),
                responsavel="Mecânico"
            )

        stats = AnalyticsEngine.calculate_consumption_stats(pid, days_window=30)
        self.assertTrue(stats["dados_suficientes"])
        self.assertEqual(stats["total_consumido"], 15.0)
        # Consumo diário = 15 / 30 = 0.5 litro/dia
        self.assertAlmostEqual(stats["consumo_medio_diario"], 0.5, places=2)

        prod = get_product(pid)
        # Saldo remanescente = 30.0 inicial - 15.0 saídas = 15.0 litros
        self.assertEqual(prod["quantidade_atual"], 15.0)

        forecast = AnalyticsEngine.analyze_stockout_forecast(prod, stats)
        # 15 litros restantes / 0.5 litros/dia = 30 dias de duração estimada
        self.assertEqual(forecast["dados_justificativa"]["dias_estimados"], 30)

    # -------------------------------------------------------------
    # 6. Identificação de Produtos Próximos do Vencimento e Vencidos
    # -------------------------------------------------------------
    def test_06_expiration_risk(self):
        """Detecta produtos vencidos e com vencimento próximo configurável."""
        hoje = date.today()

        # Produto A: Vencido
        pid_vencido = create_product({
            "nome": "Biológico Trichoderma Antigo",
            "categoria": "Defensivos e produtos biológicos",
            "unidade_medida": "kg",
            "quantidade_atual": 8.0,
            "estoque_minimo": 2.0,
            "data_validade": (hoje - timedelta(days=10)).strftime("%Y-%m-%d"),
            "lote": "L-EXP-01"
        })

        p_vencido = get_product(pid_vencido)
        alert_venc = AnalyticsEngine.analyze_expiration_risk(p_vencido, {})
        self.assertEqual(alert_venc["prioridade"], "critico")
        self.assertIn("venceu em", alert_venc["explicacao"])

        # Produto B: Vence em 20 dias (próximo)
        pid_proximo = create_product({
            "nome": "Inoculante Feijão",
            "categoria": "Defensivos e produtos biológicos",
            "unidade_medida": "dose",
            "quantidade_atual": 50.0,
            "estoque_minimo": 10.0,
            "data_validade": (hoje + timedelta(days=20)).strftime("%Y-%m-%d"),
            "lote": "L-EXP-02"
        })
        p_prox = get_product(pid_proximo)
        alert_prox = AnalyticsEngine.analyze_expiration_risk(p_prox, {})
        self.assertEqual(alert_prox["prioridade"], "alto")

    # -------------------------------------------------------------
    # 7. Cálculo do Valor Financeiro do Estoque
    # -------------------------------------------------------------
    def test_07_financial_valuation(self):
        """Calcula o valor financeiro total considerando apenas preços e saldos válidos."""
        # Item 1: 10 unidades a R$ 50,00 = R$ 500,00
        create_product({
            "nome": "Filtro de Ar Trator",
            "categoria": "Peças e manutenção",
            "unidade_medida": "unidade",
            "quantidade_atual": 10.0,
            "estoque_minimo": 2.0,
            "preco_aquisicao_unitario": 50.0
        })

        # Item 2: 5 unidades a R$ 200,00 = R$ 1.000,00
        create_product({
            "nome": "Óleo Hidráulico 68",
            "categoria": "Combustíveis e lubrificantes",
            "unidade_medida": "galão 20L",
            "quantidade_atual": 5.0,
            "estoque_minimo": 2.0,
            "preco_aquisicao_unitario": 200.0
        })

        # Item 3: Preço nulo (não deve somar nem quebrar o cálculo)
        create_product({
            "nome": "Mudas Doação Comunitária",
            "categoria": "Sementes",
            "unidade_medida": "unidade",
            "quantidade_atual": 100.0,
            "estoque_minimo": 10.0,
            "preco_aquisicao_unitario": None
        })

        valuation = AnalyticsEngine.analyze_financial_valuation()
        self.assertEqual(valuation["total_valor_estoque"], 1500.0)

    # -------------------------------------------------------------
    # 8. Detecção de Movimentações Fora do Padrão (Anomalias)
    # -------------------------------------------------------------
    def test_08_consumption_anomalies(self):
        """Identifica retiradas significativamente superiores à média histórica do insumo."""
        pid = create_product({
            "nome": "Gasolina Comum",
            "categoria": "Combustíveis e lubrificantes",
            "unidade_medida": "litro",
            "quantidade_atual": 500.0,
            "estoque_minimo": 50.0
        })

        # 4 saídas normais de 10 litros
        for d in [20, 15, 10, 5]:
            register_movement(
                product_id=pid,
                tipo="saida",
                quantidade=10.0,
                data_movimentacao=(datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d %H:%M:%S"),
                responsavel="Operador"
            )

        # 1 saída anômala de 80 litros (8x a média)
        register_movement(
            product_id=pid,
            tipo="saida",
            quantidade=80.0,
            data_movimentacao=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
            responsavel="Auxiliar",
            observacao="Retirada grande sem nota"
        )

        anomalias = AnalyticsEngine.analyze_consumption_anomalies(days_window=30)
        self.assertTrue(len(anomalias) >= 1)
        self.assertEqual(anomalias[0]["produto_id"], pid)
        self.assertEqual(anomalias[0]["quantidade"], 80.0)

    # -------------------------------------------------------------
    # 9. Atualização dos Alertas Após Movimentações
    # -------------------------------------------------------------
    def test_09_alert_update_after_movement(self):
        """Verifica que novos alertas são gerados e cessam após reposição de estoque."""
        pid = create_product({
            "nome": "Adubo Foliar Zinco",
            "categoria": "Fertilizantes",
            "unidade_medida": "litro",
            "quantidade_atual": 20.0,
            "estoque_minimo": 15.0
        })

        # Inicialmente sem alerta crítico
        critico_antes = AnalyticsEngine.analyze_critical_stock(get_product(pid))
        self.assertIsNone(critico_antes)

        # Saída de 10 litros: saldo cai para 10 (abaixo do mínimo de 15)
        register_movement(pid, "saida", 10.0, responsavel="Agrônomo")
        critico_depois = AnalyticsEngine.analyze_critical_stock(get_product(pid))
        self.assertIsNotNone(critico_depois)
        self.assertEqual(critico_depois["prioridade"], "alto")

        # Entrada de reposição de 25 litros: saldo sobe para 35 (acima do mínimo)
        register_movement(pid, "entrada", 25.0, responsavel="Almoxarife")
        critico_resolvido = AnalyticsEngine.analyze_critical_stock(get_product(pid))
        self.assertIsNone(critico_resolvido)

    # -------------------------------------------------------------
    # 10. Tratamento de Campos Opcionais e Ausentes
    # -------------------------------------------------------------
    def test_10_missing_optional_fields(self):
        """Garante que preço e validade ausentes não são gravados como 0 e não causam erros."""
        pid = create_product({
            "nome": "Enxada Cabo de Madeira",
            "categoria": "Equipamentos de proteção individual e materiais diversos",
            "unidade_medida": "unidade",
            "quantidade_atual": 5.0,
            "estoque_minimo": 2.0,
            "preco_aquisicao_unitario": None,
            "data_validade": None
        })

        prod = get_product(pid)
        self.assertIsNone(prod["preco_aquisicao_unitario"])
        self.assertIsNone(prod["data_validade"])

        # Teste de análise de vencimento sem quebrar
        exp = AnalyticsEngine.analyze_expiration_risk(prod, {})
        self.assertIsNone(exp)

    # -------------------------------------------------------------
    # 11. Atualização e Cancelamento/Estorno de Movimentações
    # -------------------------------------------------------------
    def test_11_movement_reversal_and_audit(self):
        """Testa estorno de movimentação com recálculo do saldo e trilha de auditoria."""
        pid = create_product({
            "nome": "Graxa para Tratores",
            "categoria": "Combustíveis e lubrificantes",
            "unidade_medida": "balde 20kg",
            "quantidade_atual": 10.0,
            "estoque_minimo": 3.0
        })

        # Saída incorreta de 4 baldes -> saldo vai para 6
        mov_res = register_movement(pid, "saida", 4.0, responsavel="Operador")
        mov_id = mov_res["movimentacao_id"]
        self.assertEqual(get_product(pid)["quantidade_atual"], 6.0)

        # Estorno da saída com justificativa
        revert_res = cancel_or_revert_movement(
            movimentacao_id=mov_id,
            responsavel="Gerente de Operações",
            justificativa="Digitação errônea de talhão e quantidade cancelada em campo"
        )
        self.assertTrue(revert_res["sucesso"])
        # Saldo deve retornar para 10.0
        self.assertEqual(get_product(pid)["quantidade_atual"], 10.0)

        # Verificar se auditoria foi gravada
        audit = query_db("SELECT * FROM movimentacoes_auditoria WHERE movimentacao_id = ? AND tipo_operacao = 'estorno'", (mov_id,))
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["responsavel"], "Gerente de Operações")

    # -------------------------------------------------------------
    # 12. Persistência dos Dados no SQLite
    # -------------------------------------------------------------
    def test_12_persistence_in_sqlite(self):
        """Valida que registros persistem em conexões independentes do SQLite."""
        pid = create_product({
            "nome": "Mangueira de Irrigação 1 Pol",
            "categoria": "Materiais de irrigação",
            "unidade_medida": "metro",
            "quantidade_atual": 250.0,
            "estoque_minimo": 50.0
        })

        # Consulta independente via SELECT puro
        row = query_db("SELECT * FROM produtos WHERE id = ?", (pid,), one=True)
        self.assertIsNotNone(row)
        self.assertEqual(row["nome"], "Mangueira de Irrigação 1 Pol")
        self.assertEqual(row["quantidade_atual"], 250.0)

    # -------------------------------------------------------------
    # 13. Detecção de Produtos com Grafias Similares / Duplicidades
    # -------------------------------------------------------------
    def test_13_duplicate_product_detection(self):
        """Verifica se o algoritmo de similaridade identifica produtos com grafias parecidas."""
        create_product({
            "nome": "Ureia 46% N Agrícola",
            "categoria": "Fertilizantes",
            "unidade_medida": "saca 50kg",
            "quantidade_atual": 10.0,
            "estoque_minimo": 2.0
        })
        create_product({
            "nome": "Ureia Agrícola 46% Granulada",
            "categoria": "Fertilizantes",
            "unidade_medida": "saca 50kg",
            "quantidade_atual": 5.0,
            "estoque_minimo": 2.0
        })

        dups = AnalyticsEngine.detect_duplicate_products()
        self.assertTrue(len(dups) >= 1)
        self.assertIn("Ureia", dups[0]["produto_1"]["nome"])
        self.assertIn("Ureia", dups[0]["produto_2"]["nome"])


if __name__ == "__main__":
    unittest.main()
