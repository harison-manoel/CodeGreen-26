"""
Módulo de Importação de Dados e Carga de Demonstração (Seed).
Atende às seções 6 e 7 do desafio Agrohack:
1. Permite carregar dados de teste demonstrativos com cenários realistas de Rondônia/Ariquemes.
2. Fornece importador estruturado para a base de dados oficial (CSV/JSON) que será fornecida pelo IFRO.
"""

import json
import csv
import io
from datetime import datetime, date, timedelta
from database.db import get_db, query_db, init_db
from services.inventory_service import create_product, register_movement, CATEGORIAS_VALIDAS


def load_demo_dataset():
    """
    Carrega conjunto rico de dados simulados que atende rigorosamente a todos
    os cenários obrigatórios do AGROHACK 2026/2.
    """
    # Reinicia o banco para garantir consistência dos exemplos
    init_db(force=True)

    hoje = date.today()

    # 1. Definição dos produtos simulados
    produtos_demo = [
        # Cenário 1: Abaixo do estoque mínimo (Calcário Dolomítico)
        {
            "nome": "Calcário Dolomítico PRNT 85%",
            "categoria": "Corretivos",
            "unidade_medida": "tonelada",
            "quantidade_atual": 4.0,
            "estoque_minimo": 15.0,
            "estoque_maximo": 40.0,
            "prazo_reposicao_dias": 10,
            "preco_aquisicao_unitario": 210.00,
            "lote": "L-CALC-2026",
            "data_validade": None,
            "fornecedor": "Calcário Vale do Jamari",
            "local_armazenamento": "Galpão Aberto 1"
        },
        # Cenário 2: Risco iminente de falta (Glifosato 480 SL com alto consumo diário)
        {
            "nome": "Herbicida Glifosato 480 SL",
            "categoria": "Defensivos e produtos biológicos",
            "unidade_medida": "litro",
            "quantidade_atual": 71.0, # 71L inicial - 36L (3 saídas de 12L) = 35L restantes
            "estoque_minimo": 50.0,
            "estoque_maximo": 200.0,
            "prazo_reposicao_dias": 7,
            "preco_aquisicao_unitario": 48.50,
            "lote": "L-GLI-883",
            "data_validade": (hoje + timedelta(days=300)).strftime("%Y-%m-%d"),
            "fornecedor": "AgroNorte Rondônia",
            "local_armazenamento": "Depósito de Químicos - Prateleira A"
        },
        # Cenário 3A: Produto próximo do vencimento com consumo insuficiente (Inoculante)
        {
            "nome": "Inoculante Biológico Bradyrhizobium Soja",
            "categoria": "Defensivos e produtos biológicos",
            "unidade_medida": "dose",
            "quantidade_atual": 85.0,
            "estoque_minimo": 20.0,
            "estoque_maximo": 100.0,
            "prazo_reposicao_dias": 5,
            "preco_aquisicao_unitario": 32.00,
            "lote": "L-BIO-091",
            "data_validade": (hoje + timedelta(days=18)).strftime("%Y-%m-%d"), # Vence em 18 dias!
            "fornecedor": "BioAgro Soluções Sustentáveis",
            "local_armazenamento": "Câmara Fria 2"
        },
        # Cenário 3B: Produto já vencido em estoque
        {
            "nome": "Fungicida Clorotalonil 720 SC",
            "categoria": "Defensivos e produtos biológicos",
            "unidade_medida": "litro",
            "quantidade_atual": 15.0,
            "estoque_minimo": 10.0,
            "estoque_maximo": 60.0,
            "prazo_reposicao_dias": 8,
            "preco_aquisicao_unitario": 95.00,
            "lote": "L-CLO-2024",
            "data_validade": (hoje - timedelta(days=22)).strftime("%Y-%m-%d"), # Vencido há 22 dias!
            "fornecedor": "Distribuidora Rural Jamari",
            "local_armazenamento": "Depósito Químico - Área de Quarentena"
        },
        # Cenário 4: Excesso de estoque (Bico de pulverizador muito acima do máximo)
        {
            "nome": "Bico de Pulverizador TeeJet TT11002",
            "categoria": "Peças e manutenção",
            "unidade_medida": "unidade",
            "quantidade_atual": 140.0,
            "estoque_minimo": 20.0,
            "estoque_maximo": 40.0, # Capacidade máxima 40, atual 140!
            "prazo_reposicao_dias": 15,
            "preco_aquisicao_unitario": 28.50,
            "lote": "L-TEE-501",
            "data_validade": None,
            "fornecedor": "TratorPeças Ariquemes",
            "local_armazenamento": "Almoxarifado Central - Gaveta B4"
        },
        # Cenário 5: Consumo atípico / anomalia de saída (Óleo Diesel S10)
        {
            "nome": "Óleo Diesel S10 Agrícola",
            "categoria": "Combustíveis e lubrificantes",
            "unidade_medida": "litro",
            "quantidade_atual": 1850.0,
            "estoque_minimo": 500.0,
            "estoque_maximo": 5000.0,
            "prazo_reposicao_dias": 3,
            "preco_aquisicao_unitario": 6.15,
            "lote": "L-DSL-0426",
            "data_validade": None,
            "fornecedor": "Posto & TRR Guaporé",
            "local_armazenamento": "Tanque Estacionário 1"
        },
        # Cenário 6: Produto de alto valor com capital imobilizado / baixa movimentação
        {
            "nome": "Fungicida Sistêmico Fox Xpro Galão 5L",
            "categoria": "Defensivos e produtos biológicos",
            "unidade_medida": "galão 5L",
            "quantidade_atual": 10.0,
            "estoque_minimo": 2.0,
            "estoque_maximo": 15.0,
            "prazo_reposicao_dias": 12,
            "preco_aquisicao_unitario": 2450.00, # R$ 24.500 parados!
            "lote": "L-FOX-99",
            "data_validade": (hoje + timedelta(days=340)).strftime("%Y-%m-%d"),
            "fornecedor": "Bayer Crop Science Distribuição",
            "local_armazenamento": "Depósito de Alta Segurança"
        },
        # Cenário 7: Variação de preço relevante (Adubo NPK 04-14-08)
        {
            "nome": "Adubo NPK 04-14-08 Granulado",
            "categoria": "Fertilizantes",
            "unidade_medida": "saca 50kg",
            "quantidade_atual": 120.0,
            "estoque_minimo": 50.0,
            "estoque_maximo": 300.0,
            "prazo_reposicao_dias": 10,
            "preco_aquisicao_unitario": 135.00, # Preço base inicial
            "lote": "L-NPK-01",
            "data_validade": (hoje + timedelta(days=700)).strftime("%Y-%m-%d"),
            "fornecedor": "Yara Fertilizantes Rondônia",
            "local_armazenamento": "Shed de Fertilizantes"
        },
        # Cenário 8: Possível duplicidade / grafias diferentes
        {
            "nome": "Cloreto de Potássio 60% K2O",
            "categoria": "Fertilizantes",
            "unidade_medida": "saca 50kg",
            "quantidade_atual": 45.0,
            "estoque_minimo": 20.0,
            "estoque_maximo": 100.0,
            "prazo_reposicao_dias": 8,
            "preco_aquisicao_unitario": 175.00,
            "lote": "L-KCL-A",
            "data_validade": None,
            "fornecedor": "NutriSolo Ariquemes",
            "local_armazenamento": "Shed de Fertilizantes"
        },
        {
            "nome": "Cloreto de Potassio (KCl) Granulado", # Nome similar para detecção léxica
            "categoria": "Fertilizantes",
            "unidade_medida": "saca 50kg",
            "quantidade_atual": 15.0,
            "estoque_minimo": 10.0,
            "estoque_maximo": 50.0,
            "prazo_reposicao_dias": 8,
            "preco_aquisicao_unitario": 178.00,
            "lote": "L-KCL-B",
            "data_validade": None,
            "fornecedor": "NutriSolo Ariquemes",
            "local_armazenamento": "Shed de Fertilizantes"
        },
        # Produto Adicional da Região: Sementes de Café Conilon BRS Ouro Preto
        {
            "nome": "Mudas Selecionadas Café Conilon BRS Ouro Preto",
            "categoria": "Sementes",
            "unidade_medida": "unidade",
            "quantidade_atual": 800.0,
            "estoque_minimo": 200.0,
            "estoque_maximo": 2000.0,
            "prazo_reposicao_dias": 20,
            "preco_aquisicao_unitario": 3.80,
            "lote": "L-EMBRAPA-2026",
            "data_validade": (hoje + timedelta(days=45)).strftime("%Y-%m-%d"),
            "fornecedor": "Viveiro Clonagem Rondônia",
            "local_armazenamento": "Viveiro Telado 3"
        },
        # Produto Adicional: Tubo de Gotejamento Irrigação
        {
            "nome": "Tubo Gotejador Drip 16mm Bobina 500m",
            "categoria": "Materiais de irrigação",
            "unidade_medida": "unidade",
            "quantidade_atual": 18.0,
            "estoque_minimo": 5.0,
            "estoque_maximo": 30.0,
            "prazo_reposicao_dias": 15,
            "preco_aquisicao_unitario": 340.00,
            "lote": "L-IRR-2026",
            "data_validade": None,
            "fornecedor": "IrigaRondônia Sistemas",
            "local_armazenamento": "Almoxarifado Central"
        },
        # Produto Adicional: EPI - Respirador e Filtro Químico
        {
            "nome": "Respirador Semifacial com Filtro para Vapores Orgânicos (EPI)",
            "categoria": "Equipamentos de proteção individual e materiais diversos",
            "unidade_medida": "unidade",
            "quantidade_atual": 24.0,
            "estoque_minimo": 10.0,
            "estoque_maximo": 50.0,
            "prazo_reposicao_dias": 10,
            "preco_aquisicao_unitario": 85.00,
            "lote": "L-EPI-3M",
            "data_validade": (hoje + timedelta(days=500)).strftime("%Y-%m-%d"),
            "fornecedor": "Protege Agro Segurança",
            "local_armazenamento": "Armário EPI 1"
        }
    ]

    p_ids = {}
    for prod in produtos_demo:
        pid = create_product(prod)
        p_ids[prod["nome"]] = pid

    # 2. Inserir histórico de movimentações para alimentar as regras analíticas
    # Movimentações do Glifosato (consumo diário alto -> previsão de falta para 3 dias)
    gli_id = p_ids["Herbicida Glifosato 480 SL"]
    for i in range(1, 4):
        dt = (datetime.now() - timedelta(days=i * 3)).strftime("%Y-%m-%d %H:%M:%S")
        register_movement(
            product_id=gli_id,
            tipo="saida",
            quantidade=12.0,
            data_movimentacao=dt,
            responsavel="João Silva (Tratorista)",
            fornecedor_destino="Talhão Café 04 - Dessecação pré-colheita",
            observacao="Aplicação de dessecação nas entrelinhas"
        )

    # Movimentações do Óleo Diesel S10 (saídas normais + 1 ANOMALIA ESTATÍSTICA de 450L)
    diesel_id = p_ids["Óleo Diesel S10 Agrícola"]
    # 5 saídas rotineiras de 50L a 70L
    for idx, dias_atras in enumerate([25, 20, 15, 10, 6]):
        dt = (datetime.now() - timedelta(days=dias_atras)).strftime("%Y-%m-%d 08:30:00")
        register_movement(
            product_id=diesel_id,
            tipo="saida",
            quantidade=60.0 + (idx * 2),
            data_movimentacao=dt,
            responsavel="Marcos Operador",
            fornecedor_destino="Trator John Deere 6110J",
            observacao="Abastecimento diário rotina de gradagem"
        )
    # ANOMALIA: Saída repentina de 450L nos últimos dias
    dt_anomalia = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d 17:45:00")
    register_movement(
        product_id=diesel_id,
        tipo="saida",
        quantidade=450.0,
        data_movimentacao=dt_anomalia,
        responsavel="Carlos Auxiliar",
        fornecedor_destino="Destino não especificado no formulário",
        observacao="Retirada emergencial registrada sem talhão identificado"
    )

    # Movimentação do Adubo NPK (Segunda entrada com AUMENTO de 37% no preço)
    npk_id = p_ids["Adubo NPK 04-14-08 Granulado"]
    dt_entrada_recente = (datetime.now() - timedelta(days=4)).strftime("%Y-%m-%d 10:15:00")
    register_movement(
        product_id=npk_id,
        tipo="entrada",
        quantidade=30.0,
        preco_unitario=185.00, # Subiu de 135 para 185!
        data_movimentacao=dt_entrada_recente,
        responsavel="Eng. Agrônomo Roberto",
        fornecedor_destino="Yara Fertilizantes Rondônia",
        observacao="Reposição de estoque para plantio de safra (reajuste de frete e dólar)"
    )

    # Movimentação do Inoculante (consumo baixo, não consome as 85 doses antes dos 18 dias restantes)
    inoc_id = p_ids["Inoculante Biológico Bradyrhizobium Soja"]
    dt_inoc = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d 09:00:00")
    register_movement(
        product_id=inoc_id,
        tipo="saida",
        quantidade=5.0,
        data_movimentacao=dt_inoc,
        responsavel="Técnico Lucas",
        fornecedor_destino="Talhão Soja Teste IFRO",
        observacao="Inoculação de sementes lote piloto"
    )

    return {
        "status": "sucesso",
        "total_produtos": len(produtos_demo),
        "mensagem": "Base de dados simulada para o AGROHACK 2026/2 carregada com sucesso!"
    }


def import_official_data(file_content, file_format="csv"):
    """
    Importador robusto para a base de dados oficial do IFRO.
    Aceita CSV (separado por vírgula ou ponto-e-vírgula) e JSON.
    Normaliza os campos e realiza validação rigorosa de dados.
    """
    imported_count = 0
    errors = []

    if file_format.lower() == "json":
        try:
            records = json.loads(file_content)
            if isinstance(records, dict):
                records = records.get("produtos") or records.get("dados") or [records]
        except Exception as e:
            return {"sucesso": False, "mensagem": f"Erro de formatação JSON: {str(e)}", "importados": 0, "erros": []}
    else:
        # Detectar delimitador de CSV (',' ou ';')
        try:
            sample = file_content[:2048]
            delimiter = ';' if ';' in sample and sample.count(';') >= sample.count(',') else ','
            reader = csv.DictReader(io.StringIO(file_content), delimiter=delimiter)
            records = list(reader)
        except Exception as e:
            return {"sucesso": False, "mensagem": f"Erro ao ler arquivo CSV: {str(e)}", "importados": 0, "erros": []}

    for idx, row in enumerate(records, start=1):
        # Mapeamento flexível de chaves para aceitar variações comuns em planilhas
        nome = (row.get("nome") or row.get("produto") or row.get("item") or "").strip()
        categoria = (row.get("categoria") or row.get("grupo") or "").strip()
        unidade = (row.get("unidade_medida") or row.get("unidade") or row.get("unid") or "unidade").strip()

        if not nome:
            errors.append(f"Linha {idx}: Nome do produto ausente.")
            continue

        # Normalização inteligente de categorias
        cat_match = None
        for c in CATEGORIAS_VALIDAS:
            if c.lower() in categoria.lower() or categoria.lower() in c.lower():
                cat_match = c
                break
        if not cat_match:
            cat_match = "Equipamentos de proteção individual e materiais diversos"

        try:
            raw_qtd = row.get("quantidade_atual") or row.get("quantidade") or row.get("saldo") or 0.0
            qtd = float(str(raw_qtd).replace(",", "."))
        except ValueError:
            qtd = 0.0

        try:
            raw_min = row.get("estoque_minimo") or row.get("minimo") or 0.0
            estoque_min = float(str(raw_min).replace(",", "."))
        except ValueError:
            estoque_min = 0.0

        estoque_max = None
        if row.get("estoque_maximo") or row.get("maximo"):
            try:
                estoque_max = float(str(row.get("estoque_maximo") or row.get("maximo")).replace(",", "."))
            except ValueError:
                estoque_max = None

        prazo_reposicao = None
        if row.get("prazo_reposicao_dias") or row.get("prazo_reposicao") or row.get("lead_time"):
            try:
                prazo_reposicao = int(row.get("prazo_reposicao_dias") or row.get("prazo_reposicao") or row.get("lead_time"))
            except ValueError:
                prazo_reposicao = None

        preco_unit = None
        if row.get("preco_aquisicao_unitario") or row.get("preco_unitario") or row.get("preco"):
            try:
                raw_preco = str(row.get("preco_aquisicao_unitario") or row.get("preco_unitario") or row.get("preco"))
                raw_preco = raw_preco.replace("R$", "").replace(" ", "").replace(",", ".")
                preco_unit = float(raw_preco)
            except ValueError:
                preco_unit = None

        data_validade = row.get("data_validade") or row.get("validade") or None
        if data_validade:
            data_validade = str(data_validade)[:10]

        lote = row.get("lote") or None
        fornecedor = row.get("fornecedor") or None
        local = row.get("local_armazenamento") or row.get("local") or None

        payload = {
            "nome": nome,
            "categoria": cat_match,
            "unidade_medida": unidade,
            "quantidade_atual": qtd,
            "estoque_minimo": estoque_min,
            "estoque_maximo": estoque_max,
            "prazo_reposicao_dias": prazo_reposicao,
            "preco_aquisicao_unitario": preco_unit,
            "data_validade": data_validade,
            "lote": lote,
            "fornecedor": fornecedor,
            "local_armazenamento": local
        }

        try:
            create_product(payload)
            imported_count += 1
        except Exception as ex:
            errors.append(f"Linha {idx} ({nome}): {str(ex)}")

    return {
        "sucesso": imported_count > 0,
        "importados": imported_count,
        "total_linhas": len(records),
        "erros": errors
    }
