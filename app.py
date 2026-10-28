"""
AGROHACK 2026/2 — Sistema Inteligente de Gestão de Insumos Rurais (AgroInsight IFRO)
Aplicação Web Principal construída com Flask, SQLite e Arquitetura Modular.
Transforma dados de estoque rural em inteligência agronômica acionável.
"""

import os
import io
from datetime import datetime, date, timedelta
from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, Response, send_file
)

from database.db import init_db, query_db, get_db
from services.inventory_service import (
    list_products, get_product, create_product, update_product,
    delete_product, register_movement, cancel_or_revert_movement,
    list_movements, get_movement_audit, CATEGORIAS_VALIDAS
)
from services.analytics_engine import AnalyticsEngine
from services.alert_service import (
    get_all_alerts, update_alert_status, get_alerts_summary
)
from services.report_service import (
    generate_stock_position_report, generate_critical_products_report,
    generate_expiration_report, generate_movements_report,
    generate_consumption_analysis_report, generate_financial_report,
    generate_alerts_report, export_to_csv
)
from services.data_importer import load_demo_dataset, import_official_data

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "agrohack-2026-ifro-ariquemes-secret-token")

# Inicialização automática do schema do banco caso ainda não exista
with app.app_context():
    init_db(force=False)


# -------------------------------------------------------------
# Filtros e Utilitários de Template (Jinja2)
# -------------------------------------------------------------
@app.template_filter('currency')
def currency_filter(val):
    """Formata valor como moeda brasileira R$ 1.250,00 ou N/I se ausente."""
    if val is None or val == "":
        return "N/I"
    try:
        return f"R$ {float(val):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (ValueError, TypeError):
        return "N/I"


@app.template_filter('format_date')
def format_date_filter(val):
    """Formata datas ISO para DD/MM/AAAA."""
    if not val:
        return "N/I"
    try:
        if isinstance(val, (datetime, date)):
            return val.strftime("%d/%m/%Y")
        return datetime.strptime(str(val)[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return str(val)[:10]


@app.template_filter('days_until')
def days_until_filter(val):
    """Calcula dias restantes até a data."""
    if not val:
        return None
    try:
        dt = datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
        return (dt - date.today()).days
    except Exception:
        return None


@app.context_processor
def inject_global_data():
    """Injeta categorias, resumo de alertas e produtos ativos para a sidebar e modais em todas as páginas."""
    try:
        alerts_summary = get_alerts_summary()
        produtos_ativos = list_products(apenas_ativos=True, ordenar_por="nome")
    except Exception:
        alerts_summary = {"total": 0, "pendentes": 0, "critico": 0, "alto": 0}
        produtos_ativos = []
    return {
        "categorias_oficiais": CATEGORIAS_VALIDAS,
        "global_alerts": alerts_summary,
        "produtos_ativos_global": produtos_ativos,
        "ano_atual": 2026,
        "evento_nome": "AGROHACK 2026/2 — IFRO Campus Ariquemes"
    }


# -------------------------------------------------------------
# 1. Rota do Dashboard Inteligente
# -------------------------------------------------------------
@app.route("/")
def dashboard():
    """
    Página inicial com indicadores reais calculados a partir dos dados do banco.
    Suporta filtros dinâmicos por categoria e período de análise.
    Nenhum valor simulado é fixado no HTML.
    """
    categoria = request.args.get("categoria")
    periodo = request.args.get("periodo", "30")
    try:
        days_window = int(periodo) if periodo and periodo.isdigit() else 30
    except ValueError:
        days_window = 30

    produtos = list_products(categoria=categoria, apenas_ativos=True)
    total_produtos = len(produtos)

    # 1. Indicadores calculados dinamicamente
    produtos_criticos = 0
    produtos_abaixo_minimo = 0
    produtos_proximos_vencimento = 0
    produtos_vencidos = 0
    produtos_risco_falta = 0
    produtos_excesso = 0

    hoje = date.today()

    for p in produtos:
        qtd = float(p["quantidade_atual"])
        minimo = float(p["estoque_minimo"])
        stats = AnalyticsEngine.calculate_consumption_stats(p["id"], days_window=days_window)

        # Abaixo ou igual ao estoque mínimo
        if qtd <= minimo:
            produtos_abaixo_minimo += 1
            if qtd <= (minimo * 0.5) or qtd == 0:
                produtos_criticos += 1

        # Previsão de falta
        falta = AnalyticsEngine.analyze_stockout_forecast(p, stats)
        if falta and falta.get("prioridade") in ("critico", "alto"):
            produtos_risco_falta += 1

        # Vencimentos
        if p["data_validade"]:
            try:
                dt_val = datetime.strptime(str(p["data_validade"])[:10], "%Y-%m-%d").date()
                dias = (dt_val - hoje).days
                if dias < 0:
                    produtos_vencidos += 1
                elif dias <= 60:
                    produtos_proximos_vencimento += 1
            except ValueError:
                pass

        # Excesso
        excesso = AnalyticsEngine.analyze_overstock(p, stats)
        if excesso:
            produtos_excesso += 1

    # 2. Resumo de Alertas (filtrado por categoria quando aplicável)
    alertas_pendentes = get_all_alerts(situacao_filtro="pendente", categoria_filtro=categoria)
    alertas_summary = get_alerts_summary()

    # 3. Valor financeiro do estoque e capital parado
    valuation = AnalyticsEngine.analyze_financial_valuation()
    if categoria:
        # Filtra o valuation pela categoria selecionada
        itens_cat = [it for it in valuation["produtos_ranking"] if it["categoria"] == categoria]
        valor_total_estoque = round(sum(it["valor_total"] for it in itens_cat), 2)
        capital_parado = [cp for cp in valuation["itens_capital_parado"] if cp["categoria"] == categoria]
    else:
        valor_total_estoque = valuation["total_valor_estoque"]
        capital_parado = valuation["itens_capital_parado"]

    # 4. Análise de Duração e Distribuição de Capital para os Gráficos
    duracao_estoque = AnalyticsEngine.analyze_stock_duration(limit=6, categoria=categoria)
    capital_dist = AnalyticsEngine.analyze_capital_distribution(categoria=categoria)

    # 5. Produtos com maior consumo recente (filtrados pelo período selecionado)
    consumption_report = generate_consumption_analysis_report()
    if categoria:
        produtos_maior_consumo = [
            it for it in consumption_report["items"] if it.get("categoria") == categoria
        ][:5]
    else:
        produtos_maior_consumo = consumption_report["items"][:5]

    # 6. Últimas movimentações
    ultimas_movimentacoes = list_movements(limite=8)

    # 7. Alertas mais urgentes (críticos e altos)
    top_alertas = [a for a in alertas_pendentes if a["prioridade"] in ("critico", "alto")][:6]

    # 8. Variações de preço recentes
    variacoes_preco = AnalyticsEngine.analyze_price_variations()[:3]

    # 9. Detecção de produtos duplicados/grafias
    duplicidades = AnalyticsEngine.detect_duplicate_products()[:3]

    return render_template(
        "dashboard.html",
        total_produtos=total_produtos,
        produtos_criticos=produtos_criticos,
        produtos_abaixo_minimo=produtos_abaixo_minimo,
        produtos_risco_falta=produtos_risco_falta,
        produtos_proximos_vencimento=produtos_proximos_vencimento,
        produtos_vencidos=produtos_vencidos,
        produtos_excesso=produtos_excesso,
        alertas_summary=alertas_summary,
        valor_total_estoque=valor_total_estoque,
        capital_parado=capital_parado[:4],
        produtos_maior_consumo=produtos_maior_consumo,
        ultimas_movimentacoes=ultimas_movimentacoes,
        top_alertas=top_alertas,
        variacoes_preco=variacoes_preco,
        duplicidades=duplicidades,
        duracao_estoque=duracao_estoque,
        capital_dist=capital_dist,
        categoria_atual=categoria,
        periodo_atual=periodo
    )


# -------------------------------------------------------------
# 2. Módulo de Produtos (CRUD e Detalhes)
# -------------------------------------------------------------
@app.route("/produtos")
def produtos_list():
    """Lista todos os produtos com pesquisa, filtro por categoria, status e ordenação."""
    categoria = request.args.get("categoria")
    status = request.args.get("status")
    search = request.args.get("q")
    ordenar = request.args.get("ordenar", "nome")

    produtos = list_products(search=search, categoria=categoria, status=status, ordenar_por=ordenar)

    # Métricas de resumo da listagem
    total_filtrado = len(produtos)
    criticos_count = sum(1 for p in produtos if float(p["quantidade_atual"]) <= float(p["estoque_minimo"]))

    return render_template(
        "produtos/index.html",
        produtos=produtos,
        categoria_atual=categoria,
        status_atual=status,
        search_atual=search,
        ordenar_atual=ordenar,
        total_filtrado=total_filtrado,
        criticos_count=criticos_count
    )


@app.route("/produtos/<int:product_id>")
def produto_detalhe(product_id):
    """Exibe visão detalhada do produto, movimentações históricas e análise preditiva."""
    produto = get_product(product_id)
    if not produto:
        flash("Produto não encontrado.", "erro")
        return redirect(url_for("produtos_list"))

    # Estatísticas de consumo e alertas deste produto
    stats_consumo = AnalyticsEngine.calculate_consumption_stats(product_id, days_window=30)
    alerta_critico = AnalyticsEngine.analyze_critical_stock(produto)
    alerta_falta = AnalyticsEngine.analyze_stockout_forecast(produto, stats_consumo)
    alerta_venc = AnalyticsEngine.analyze_expiration_risk(produto, stats_consumo)
    alerta_excesso = AnalyticsEngine.analyze_overstock(produto, stats_consumo)

    alertas_produto = [a for a in [alerta_critico, alerta_falta, alerta_venc, alerta_excesso] if a and a.get("prioridade") in ("critico", "alto", "medio")]

    movimentacoes = list_movements(produto_id=product_id, limite=50)

    # Cálculo do valor financeiro do lote
    valor_financeiro = None
    if produto["preco_aquisicao_unitario"] is not None and produto["quantidade_atual"] > 0:
        valor_financeiro = round(float(produto["quantidade_atual"]) * float(produto["preco_aquisicao_unitario"]), 2)

    return render_template(
        "produtos/detalhes.html",
        produto=produto,
        stats=stats_consumo,
        alertas=alertas_produto,
        movimentacoes=movimentacoes,
        valor_financeiro=valor_financeiro
    )


@app.route("/produtos/novo", methods=["POST"])
def produto_criar():
    """Cadastra novo produto no estoque via formulário."""
    try:
        data = request.form.to_dict()
        novo_id = create_product(data)
        flash(f"Produto '{data.get('nome')}' cadastrado com sucesso!", "sucesso")
        return redirect(url_for("produto_detalhe", product_id=novo_id))
    except ValueError as ex:
        flash(f"Erro ao cadastrar produto: {str(ex)}", "erro")
        return redirect(url_for("produtos_list"))
    except Exception as ex:
        flash(f"Erro inesperado no servidor: {str(ex)}", "erro")
        return redirect(url_for("produtos_list"))


@app.route("/produtos/<int:product_id>/editar", methods=["POST"])
def produto_editar(product_id):
    """Atualiza dados cadastrais de um produto."""
    try:
        data = request.form.to_dict()
        update_product(product_id, data)
        flash("Dados do produto atualizados com sucesso!", "sucesso")
    except ValueError as ex:
        flash(f"Erro na validação: {str(ex)}", "erro")
    except Exception as ex:
        flash(f"Erro ao atualizar: {str(ex)}", "erro")
    return redirect(url_for("produto_detalhe", product_id=product_id))


@app.route("/produtos/<int:product_id>/excluir", methods=["POST"])
def produto_excluir(product_id):
    """Exclusão controlada com preservação de integridade de histórico."""
    try:
        res = delete_product(product_id)
        flash(res["mensagem"], "info" if res["status"] == "inativado" else "sucesso")
    except ValueError as ex:
        flash(f"Impossível excluir produto: {str(ex)}", "erro")
    except Exception as ex:
        flash(f"Erro no servidor: {str(ex)}", "erro")
    return redirect(url_for("produtos_list"))


# -------------------------------------------------------------
# 3. Módulo de Movimentações (Entradas e Saídas)
# -------------------------------------------------------------
@app.route("/movimentacoes")
def movimentacoes_list():
    """Consulta histórico de movimentações com filtros por produto, período e tipo."""
    produto_id = request.args.get("produto_id", type=int)
    tipo = request.args.get("tipo")
    data_inicio = request.args.get("data_inicio")
    data_fim = request.args.get("data_fim")
    responsavel = request.args.get("responsavel")

    movs = list_movements(
        produto_id=produto_id,
        tipo=tipo,
        data_inicio=data_inicio,
        data_fim=data_fim,
        responsavel=responsavel,
        limite=300
    )

    produtos_ativos = list_products(apenas_ativos=True, ordenar_por="nome")

    return render_template(
        "movimentacoes/index.html",
        movimentacoes=movs,
        produtos=produtos_ativos,
        filtro_produto_id=produto_id,
        filtro_tipo=tipo,
        filtro_inicio=data_inicio,
        filtro_fim=data_fim,
        filtro_responsavel=responsavel
    )


@app.route("/movimentacoes/registrar", methods=["POST"])
def movimentacao_registrar():
    """Registra uma entrada ou saída de estoque com validação atômica de saldo."""
    try:
        produto_id = int(request.form.get("produto_id"))
        tipo = request.form.get("tipo")
        quantidade = float(request.form.get("quantidade"))
        responsavel = request.form.get("responsavel")
        fornecedor_destino = request.form.get("fornecedor_destino")
        preco_unitario = request.form.get("preco_unitario") or None
        data_mov = request.form.get("data_movimentacao") or None
        observacao = request.form.get("observacao") or None
        lote = request.form.get("lote") or None

        res = register_movement(
            product_id=produto_id,
            tipo=tipo,
            quantidade=quantidade,
            data_movimentacao=data_mov,
            preco_unitario=preco_unitario,
            fornecedor_destino=fornecedor_destino,
            responsavel=responsavel,
            observacao=observacao,
            lote=lote
        )

        flash(
            f"Movimentação de {tipo.upper()} de {quantidade:g} realizada com sucesso! "
            f"Novo saldo em estoque: {res['saldo_novo']:g}.",
            "sucesso"
        )
    except ValueError as ex:
        flash(f"Falha na movimentação: {str(ex)}", "erro")
    except Exception as ex:
        flash(f"Erro inesperado: {str(ex)}", "erro")

    next_url = request.form.get("redirect_to")
    if next_url and next_url.startswith("/"):
        return redirect(next_url)
    return redirect(url_for("movimentacoes_list"))


@app.route("/movimentacoes/<int:movimentacao_id>/estornar", methods=["POST"])
def movimentacao_estornar(movimentacao_id):
    """Estorna movimentação com recálculo do saldo e registro de auditoria."""
    responsavel = request.form.get("responsavel")
    justificativa = request.form.get("justificativa")

    try:
        res = cancel_or_revert_movement(movimentacao_id, responsavel, justificativa)
        flash(
            f"Movimentação #{movimentacao_id} estornada com sucesso! "
            f"Saldo atualizado de {res['saldo_anterior']:g} para {res['saldo_novo']:g}.",
            "sucesso"
        )
    except ValueError as ex:
        flash(f"Não foi possível estornar: {str(ex)}", "erro")
    except Exception as ex:
        flash(f"Erro no estorno: {str(ex)}", "erro")

    return redirect(url_for("movimentacoes_list"))


@app.route("/movimentacoes/<int:movimentacao_id>/auditoria")
def movimentacao_auditoria_view(movimentacao_id):
    """Retorna o histórico de auditoria de uma movimentação via JSON."""
    audit = get_movement_audit(movimentacao_id)
    return jsonify(audit)


# -------------------------------------------------------------
# 4. Central de Alertas e Prioridades
# -------------------------------------------------------------
@app.route("/alertas")
def alertas_hub():
    """Central de Alertas e Prioridades com filtros avançados e ações de resolução."""
    prioridade = request.args.get("prioridade")
    situacao = request.args.get("situacao", "pendente")
    tipo = request.args.get("tipo")
    categoria = request.args.get("categoria")
    produto_id = request.args.get("produto_id", type=int)
    natureza = request.args.get("natureza")
    search = request.args.get("q")

    # Se situacao for 'todos', passa None para trazer todas
    situacao_filtro = None if situacao == "todos" else situacao

    alertas = get_all_alerts(
        prioridade_filtro=prioridade,
        situacao_filtro=situacao_filtro,
        tipo_filtro=tipo,
        categoria_filtro=categoria,
        produto_id_filtro=produto_id,
        natureza_filtro=natureza,
        search=search
    )

    summary = get_alerts_summary()
    produtos_ativos = list_products(apenas_ativos=True, ordenar_por="nome")

    return render_template(
        "alertas/index.html",
        alertas=alertas,
        summary=summary,
        produtos_ativos=produtos_ativos,
        filtro_prioridade=prioridade,
        filtro_situacao=situacao,
        filtro_tipo=tipo,
        filtro_categoria=categoria,
        filtro_produto_id=produto_id,
        filtro_natureza=natureza,
        filtro_search=search
    )


@app.route("/alertas/<alerta_hash>/status", methods=["POST"])
def alerta_mudar_status(alerta_hash):
    """Atualiza o ciclo de vida do alerta (pendente / em_acompanhamento / resolvido)."""
    situacao = request.form.get("situacao")
    observacao = request.form.get("observacao")
    responsavel = request.form.get("responsavel")

    try:
        update_alert_status(alerta_hash, situacao, observacao, responsavel)
        flash(f"Situação do alerta atualizada para '{situacao.replace('_', ' ').capitalize()}'.", "sucesso")
    except Exception as ex:
        flash(f"Erro ao atualizar alerta: {str(ex)}", "erro")

    return redirect(request.referrer or url_for("alertas_hub"))


# -------------------------------------------------------------
# 5. Hub de Inteligência Agronômica e Análises Avançadas
# -------------------------------------------------------------
@app.route("/analises")
def analises_hub():
    """Painel de inteligência agronômica: anomalias, variações de preço, capital parado e duplicidades."""
    anomalias = AnalyticsEngine.analyze_consumption_anomalies(days_window=60)
    valuation = AnalyticsEngine.analyze_financial_valuation()
    variacoes_preco = AnalyticsEngine.analyze_price_variations()
    duplicidades = AnalyticsEngine.detect_duplicate_products()

    return render_template(
        "analises/index.html",
        anomalias=anomalias,
        capital_parado=valuation["itens_capital_parado"],
        ranking_financeiro=valuation["produtos_ranking"][:10],
        total_estoque_valor=valuation["total_valor_estoque"],
        variacoes_preco=variacoes_preco,
        duplicidades=duplicidades
    )


# -------------------------------------------------------------
# 6. Central de Relatórios e Exportação
# -------------------------------------------------------------
@app.route("/relatorios")
def relatorios_hub():
    """Visualização de relatórios operacionais e gerenciais."""
    tipo_relatorio = request.args.get("tipo", "posicao")
    categoria = request.args.get("categoria")
    data_inicio = request.args.get("data_inicio")
    data_fim = request.args.get("data_fim")
    prioridade = request.args.get("prioridade")

    dados_relatorio = {}
    if tipo_relatorio == "posicao":
        dados_relatorio = generate_stock_position_report(categoria=categoria)
    elif tipo_relatorio == "criticos":
        dados_relatorio = generate_critical_products_report()
    elif tipo_relatorio == "vencimentos":
        dados_relatorio = generate_expiration_report()
    elif tipo_relatorio == "movimentacoes":
        dados_relatorio = generate_movements_report(data_inicio=data_inicio, data_fim=data_fim)
    elif tipo_relatorio == "consumo":
        dados_relatorio = generate_consumption_analysis_report()
    elif tipo_relatorio == "financeiro":
        dados_relatorio = generate_financial_report()
    elif tipo_relatorio == "alertas":
        dados_relatorio = generate_alerts_report(prioridade=prioridade)

    return render_template(
        "relatorios/index.html",
        tipo_atual=tipo_relatorio,
        relatorio=dados_relatorio,
        filtro_categoria=categoria,
        filtro_inicio=data_inicio,
        filtro_fim=data_fim,
        filtro_prioridade=prioridade
    )


@app.route("/relatorios/exportar-csv")
def relatorios_exportar_csv():
    """Gera e faz o download de arquivo CSV estruturado do relatório selecionado."""
    tipo_relatorio = request.args.get("tipo", "posicao")
    categoria = request.args.get("categoria")
    data_inicio = request.args.get("data_inicio")
    data_fim = request.args.get("data_fim")
    prioridade = request.args.get("prioridade")

    if tipo_relatorio == "posicao":
        dados = generate_stock_position_report(categoria=categoria)
    elif tipo_relatorio == "criticos":
        dados = generate_critical_products_report()
    elif tipo_relatorio == "vencimentos":
        dados = generate_expiration_report()
    elif tipo_relatorio == "movimentacoes":
        dados = generate_movements_report(data_inicio=data_inicio, data_fim=data_fim)
    elif tipo_relatorio == "consumo":
        dados = generate_consumption_analysis_report()
    elif tipo_relatorio == "financeiro":
        dados = generate_financial_report()
    elif tipo_relatorio == "alertas":
        dados = generate_alerts_report(prioridade=prioridade)
    else:
        dados = generate_stock_position_report()

    csv_content = export_to_csv(dados, tipo_relatorio)

    filename = f"agrohack_relatorio_{tipo_relatorio}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        csv_content.encode("utf-8-sig"),  # utf-8-sig para compatibilidade com Microsoft Excel em PT-BR
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# -------------------------------------------------------------
# 7. Importador de Dados e Dados Simulados (Desafio Oficial)
# -------------------------------------------------------------
@app.route("/importar")
def importar_view():
    """Página de importação da base de dados oficial e carga dos dados simulados."""
    total_produtos = query_db("SELECT COUNT(*) as cnt FROM produtos", one=True)["cnt"]
    total_movs = query_db("SELECT COUNT(*) as cnt FROM movimentacoes", one=True)["cnt"]

    return render_template(
        "importar.html",
        total_produtos=total_produtos,
        total_movimentacoes=total_movs
    )


@app.route("/importar/oficial", methods=["POST"])
def importar_oficial_upload():
    """Recebe e processa arquivo CSV ou JSON da organização do AGROHACK."""
    if "arquivo" not in request.files:
        flash("Nenhum arquivo enviado.", "erro")
        return redirect(url_for("importar_view"))

    file = request.files["arquivo"]
    if file.filename == "":
        flash("Selecione um arquivo válido para importar.", "erro")
        return redirect(url_for("importar_view"))

    filename = file.filename.lower()
    ext = "json" if filename.endswith(".json") else "csv"

    try:
        content = file.read().decode("utf-8", errors="ignore")
        resultado = import_official_data(content, file_format=ext)

        if resultado["sucesso"]:
            flash(
                f"Importação concluída com sucesso! {resultado['importados']} produtos foram cadastrados no sistema.",
                "sucesso"
            )
        else:
            flash(f"Falha na importação: {resultado.get('mensagem', 'Nenhum registro válido.')}", "erro")

        if resultado.get("erros"):
            for err in resultado["erros"][:5]:
                flash(err, "aviso")

    except Exception as ex:
        flash(f"Erro ao processar arquivo: {str(ex)}", "erro")

    return redirect(url_for("produtos_list"))


@app.route("/importar/demo", methods=["POST"])
def importar_demo_action():
    """Carrega instantaneamente o conjunto rico de dados simulados do AGROHACK 2026/2."""
    try:
        res = load_demo_dataset()
        flash(res["mensagem"], "sucesso")
        flash(
            "Cenários demonstrativos carregados: produtos críticos, risco de falta, lote vencendo, "
            "excesso de estoque, anomalia de saída de combustível, variação de preço e cadastros duplicados.",
            "info"
        )
    except Exception as ex:
        flash(f"Erro ao carregar dados simulados: {str(ex)}", "erro")

    return redirect(url_for("dashboard"))


# -------------------------------------------------------------
# 8. Rota Sobre / Documentação do Projeto
# -------------------------------------------------------------
@app.route("/sobre")
def sobre_view():
    """Página institucional do projeto, alinhada com os critérios do IFRO Campus Ariquemes."""
    return render_template("sobre.html")


# -------------------------------------------------------------
# 9. API REST para Atualização Dinâmica de Gráficos (Dashboard)
# -------------------------------------------------------------
@app.route("/api/dashboard-charts")
def api_dashboard_charts():
    """
    Retorna dados reais formatados em JSON para renderização dos gráficos do Chart.js.
    Totalmente dinâmico, calculado sobre as movimentações e produtos persistidos.
    Suporta filtros por categoria e período.
    """
    categoria = request.args.get("categoria")
    periodo = request.args.get("periodo", "30")

    # 1. Distribuição de produtos por categoria
    cat_sql = """
        SELECT categoria, COUNT(*) as total_itens, SUM(quantidade_atual) as soma_quantidade
        FROM produtos WHERE ativo = 1
    """
    cat_params = []
    if categoria:
        cat_sql += " AND categoria = ?"
        cat_params.append(categoria)
    cat_sql += " GROUP BY categoria ORDER BY total_itens DESC"
    cat_rows = query_db(cat_sql, cat_params)

    categorias_labels = [r["categoria"] for r in cat_rows]
    categorias_counts = [r["total_itens"] for r in cat_rows]

    # 2. Movimentações por mês (entradas vs saídas) - ordenadas cronologicamente
    mov_sql = """
        SELECT strftime('%Y-%m', m.data_movimentacao) as ano_mes,
               m.tipo,
               COUNT(*) as total_operacoes,
               SUM(m.quantidade) as volume
        FROM movimentacoes m
        JOIN produtos p ON m.produto_id = p.id
        WHERE m.estornada = 0
    """
    mov_params = []
    if categoria:
        mov_sql += " AND p.categoria = ?"
        mov_params.append(categoria)
    mov_sql += """
        GROUP BY ano_mes, m.tipo
        ORDER BY ano_mes ASC
    """
    mov_rows = query_db(mov_sql, mov_params)

    meses_set = []
    for r in mov_rows:
        if r["ano_mes"] and r["ano_mes"] not in meses_set:
            meses_set.append(r["ano_mes"])

    if not meses_set:
        meses_set = [datetime.now().strftime("%Y-%m")]

    entradas_by_mes = {m: 0 for m in meses_set}
    saidas_by_mes = {m: 0 for m in meses_set}

    for r in mov_rows:
        am = r["ano_mes"]
        if r["tipo"] == 'entrada':
            entradas_by_mes[am] = round(r["volume"], 1)
        elif r["tipo"] == 'saida':
            saidas_by_mes[am] = round(r["volume"], 1)

    formatted_meses = []
    for am in meses_set:
        try:
            dt = datetime.strptime(am, "%Y-%m")
            formatted_meses.append(dt.strftime("%m/%Y"))
        except Exception:
            formatted_meses.append(am)

    # 3. Distribuição de Capital Armazenado por Categoria (Gráfico Financeiro)
    capital_data = AnalyticsEngine.analyze_capital_distribution(categoria=categoria)
    capital_labels = [c["categoria"] for c in capital_data["categorias"]]
    capital_values = [c["valor_total"] for c in capital_data["categorias"]]
    capital_formatted = [
        f"R$ {c['valor_total']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        for c in capital_data["categorias"]
    ]

    # 4. Estimativa de Duração do Estoque (Dias de Cobertura vs Prazo de Reposição)
    duracao_data = AnalyticsEngine.analyze_stock_duration(limit=8, categoria=categoria)
    duracao_labels = [d["nome"] for d in duracao_data]
    duracao_dias = [d["dias_estimados"] for d in duracao_data]
    duracao_prazos = [
        d["prazo_reposicao_dias"] if isinstance(d["prazo_reposicao_dias"], (int, float)) else 0
        for d in duracao_data
    ]
    duracao_unidades = [d["unidade_medida"] for d in duracao_data]
    duracao_cores = [
        '#dc2626' if d["status_cor"] == "critico" else ('#ea580c' if d["status_cor"] == "alto" else ('#d97706' if d["status_cor"] == "medio" else '#52b788'))
        for d in duracao_data
    ]
    duracao_tooltips = [
        f"Saldo: {d['quantidade']:g} {d['unidade_medida']} | Consumo: {d['consumo_medio_diario']:.2f} {d['unidade_medida']}/dia | Lead time: {d['prazo_reposicao_dias']}d"
        for d in duracao_data
    ]

    # 5. Top produtos com maior consumo
    consumption_data = generate_consumption_analysis_report()
    top_consumo = [
        it for it in consumption_data["items"]
        if (not categoria or it.get("categoria") == categoria)
    ][:6]
    top_consumo_labels = [it["nome"] for it in top_consumo]
    top_consumo_values = [it["total_consumido_30d"] for it in top_consumo]
    top_consumo_unidades = [it.get("unidade", "") for it in top_consumo]

    return jsonify({
        "categorias": {
            "labels": categorias_labels,
            "data": categorias_counts
        },
        "fluxo_mensal": {
            "labels": formatted_meses,
            "entradas": [entradas_by_mes.get(m, 0) for m in meses_set],
            "saidas": [saidas_by_mes.get(m, 0) for m in meses_set]
        },
        "capital_categoria": {
            "labels": capital_labels,
            "data": capital_values,
            "formatted": capital_formatted,
            "total_geral": capital_data["total_geral"]
        },
        "duracao_estoque": {
            "labels": duracao_labels,
            "dias": duracao_dias,
            "prazos_reposicao": duracao_prazos,
            "unidades": duracao_unidades,
            "cores": duracao_cores,
            "detalhes": duracao_tooltips
        },
        "top_consumo": {
            "labels": top_consumo_labels,
            "data": top_consumo_values,
            "unidades": top_consumo_unidades
        }
    })


if __name__ == "__main__":
    # Permite executar diretamente com 'python app.py'
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
