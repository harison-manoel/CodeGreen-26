"""
Serviço de Gestão de Produtos e Movimentações de Estoque.
Implementa regras de negócio estritas de integridade, bloqueio de saldo negativo,
transações atômicas e rastreabilidade total (auditoria de estornos).
"""

from datetime import datetime
from database.db import get_db, query_db

CATEGORIAS_VALIDAS = [
    'Fertilizantes',
    'Corretivos',
    'Sementes',
    'Defensivos e produtos biológicos',
    'Combustíveis e lubrificantes',
    'Peças e manutenção',
    'Materiais de irrigação',
    'Equipamentos de proteção individual e materiais diversos'
]


def list_products(search=None, categoria=None, status=None, apenas_ativos=True, ordenar_por="nome"):
    """
    Lista produtos com filtros opcionais de busca, categoria, status de estoque e ordenação.
    Permite navegação direta a partir dos cards do Dashboard.
    """
    sql = """
        SELECT p.*,
               (SELECT COUNT(*) FROM movimentacoes m WHERE m.produto_id = p.id AND m.estornada = 0) as total_movimentacoes,
               (SELECT MAX(m.data_movimentacao) FROM movimentacoes m WHERE m.produto_id = p.id AND m.estornada = 0) as ultima_movimentacao
        FROM produtos p
        WHERE 1=1
    """
    params = []

    if apenas_ativos:
        sql += " AND p.ativo = 1"

    if categoria and categoria in CATEGORIAS_VALIDAS:
        sql += " AND p.categoria = ?"
        params.append(categoria)

    if status:
        status_norm = status.lower().strip()
        if status_norm == "critico":
            sql += " AND p.quantidade_atual <= p.estoque_minimo"
        elif status_norm == "urgente":
            sql += " AND (p.quantidade_atual <= (p.estoque_minimo * 0.5) OR p.quantidade_atual = 0)"
        elif status_norm == "vencendo":
            sql += " AND p.data_validade IS NOT NULL AND date(p.data_validade) <= date('now', '+60 day')"
        elif status_norm == "vencido":
            sql += " AND p.data_validade IS NOT NULL AND date(p.data_validade) < date('now')"
        elif status_norm == "excesso":
            sql += " AND ((p.estoque_maximo IS NOT NULL AND p.quantidade_atual > p.estoque_maximo) OR (p.estoque_minimo > 0 AND p.quantidade_atual >= p.estoque_minimo * 3.0))"
        elif status_norm == "seguro":
            sql += " AND p.quantidade_atual > p.estoque_minimo AND (p.estoque_maximo IS NULL OR p.quantidade_atual <= p.estoque_maximo)"

    if search:
        search_term = f"%{search.strip()}%"
        sql += " AND (p.nome LIKE ? OR p.fornecedor LIKE ? OR p.local_armazenamento LIKE ? OR p.lote LIKE ?)"
        params.extend([search_term, search_term, search_term, search_term])

    order_map = {
        "nome": "p.nome ASC",
        "quantidade": "p.quantidade_atual DESC",
        "preco": "p.preco_aquisicao_unitario DESC",
        "validade": "p.data_validade ASC",
        "categoria": "p.categoria ASC, p.nome ASC",
        "recentes": "p.data_cadastro DESC"
    }
    sql += f" ORDER BY {order_map.get(ordenar_por, 'p.nome ASC')}"

    return query_db(sql, params)


def get_product(product_id):
    """Busca um produto específico pelo ID."""
    sql = "SELECT * FROM produtos WHERE id = ?"
    return query_db(sql, (product_id,), one=True)


def create_product(data):
    """
    Cadastra um novo produto com validações estritas de negócio.
    Valida campos obrigatórios, tipos, limites numéricos e previne duplicidade.
    """
    nome = (data.get("nome") or "").strip()
    categoria = (data.get("categoria") or "").strip()
    unidade_medida = (data.get("unidade_medida") or "").strip()

    if not nome:
        raise ValueError("O nome do produto é obrigatório.")
    if not categoria or categoria not in CATEGORIAS_VALIDAS:
        raise ValueError(f"Categoria inválida. Categorias permitidas: {', '.join(CATEGORIAS_VALIDAS)}")
    if not unidade_medida:
        raise ValueError("A unidade de medida é obrigatória.")

    try:
        quantidade_atual = float(data.get("quantidade_atual", 0.0))
        if quantidade_atual < 0:
            raise ValueError("A quantidade inicial não pode ser negativa.")
    except (TypeError, ValueError):
        raise ValueError("Quantidade inicial inválida.")

    try:
        estoque_minimo = float(data.get("estoque_minimo", 0.0))
        if estoque_minimo < 0:
            raise ValueError("O estoque mínimo não pode ser negativo.")
    except (TypeError, ValueError):
        raise ValueError("Estoque mínimo inválido.")

    # Campos opcionais - tratar ausentes como NULL / desconhecidos (não como 0)
    estoque_maximo = None
    if data.get("estoque_maximo") not in (None, "", "null"):
        try:
            estoque_maximo = float(data["estoque_maximo"])
            if estoque_maximo < estoque_minimo:
                raise ValueError("O estoque máximo não pode ser menor que o estoque mínimo.")
        except (ValueError, TypeError):
            raise ValueError("Estoque máximo inválido.")

    prazo_reposicao = None
    if data.get("prazo_reposicao_dias") not in (None, "", "null"):
        try:
            prazo_reposicao = int(data["prazo_reposicao_dias"])
            if prazo_reposicao < 0:
                raise ValueError("O prazo de reposição não pode ser negativo.")
        except (ValueError, TypeError):
            raise ValueError("Prazo de reposição inválido.")

    preco_aquisicao = None
    if data.get("preco_aquisicao_unitario") not in (None, "", "null"):
        try:
            preco_aquisicao = float(data["preco_aquisicao_unitario"])
            if preco_aquisicao < 0:
                raise ValueError("O preço de aquisição não pode ser negativo.")
        except (ValueError, TypeError):
            raise ValueError("Preço unitário inválido.")

    data_validade = data.get("data_validade")
    if data_validade in (None, "", "null"):
        data_validade = None
    else:
        # Validar formato da data YYYY-MM-DD
        try:
            datetime.strptime(str(data_validade)[:10], "%Y-%m-%d")
            data_validade = str(data_validade)[:10]
        except ValueError:
            raise ValueError("Formato de data de validade inválido. Use AAAA-MM-DD.")

    lote = (data.get("lote") or "").strip() or None
    fornecedor = (data.get("fornecedor") or "").strip() or None
    local_armazenamento = (data.get("local_armazenamento") or "").strip() or None

    # Verificar possível produto idêntico já existente (mesmo nome, categoria e lote)
    duplicado = query_db(
        "SELECT id FROM produtos WHERE LOWER(nome) = LOWER(?) AND categoria = ? AND (lote = ? OR (lote IS NULL AND ? IS NULL)) AND ativo = 1",
        (nome, categoria, lote, lote),
        one=True
    )
    if duplicado:
        raise ValueError(f"Já existe um produto ativo com o mesmo nome ('{nome}'), categoria e lote.")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO produtos (
                nome, categoria, unidade_medida, quantidade_atual, estoque_minimo,
                estoque_maximo, prazo_reposicao_dias, preco_aquisicao_unitario,
                lote, data_validade, fornecedor, local_armazenamento, ativo
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            nome, categoria, unidade_medida, quantidade_atual, estoque_minimo,
            estoque_maximo, prazo_reposicao, preco_aquisicao,
            lote, data_validade, fornecedor, local_armazenamento
        ))
        novo_id = cursor.lastrowid

        # Se houver quantidade inicial > 0, registrar movimentação inicial de entrada
        if quantidade_atual > 0:
            cursor.execute("""
                INSERT INTO movimentacoes (
                    produto_id, tipo, quantidade, data_movimentacao,
                    preco_unitario, fornecedor_destino, responsavel, observacao, lote
                ) VALUES (?, 'entrada', ?, CURRENT_TIMESTAMP, ?, ?, ?, 'Saldo inicial de cadastro', ?)
            """, (
                novo_id, quantidade_atual, preco_aquisicao,
                fornecedor, "Sistema / Cadastro Inicial", lote
            ))
            mov_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO movimentacoes_auditoria (
                    movimentacao_id, tipo_operacao, quantidade_anterior, quantidade_nova,
                    saldo_anterior, saldo_novo, responsavel, justificativa
                ) VALUES (?, 'criacao', 0, ?, 0, ?, 'Sistema', 'Abertura de saldo no cadastro inicial do produto')
            """, (mov_id, quantidade_atual, quantidade_atual))

        return novo_id


def update_product(product_id, data):
    """Atualiza dados cadastrais de um produto existente (sem alterar saldo diretamente)."""
    produto = get_product(product_id)
    if not produto:
        raise ValueError("Produto não encontrado.")

    nome = (data.get("nome") or produto["nome"]).strip()
    categoria = (data.get("categoria") or produto["categoria"]).strip()
    unidade_medida = (data.get("unidade_medida") or produto["unidade_medida"]).strip()

    if not nome:
        raise ValueError("O nome do produto não pode ser vazio.")
    if categoria not in CATEGORIAS_VALIDAS:
        raise ValueError("Categoria inválida.")

    estoque_minimo = float(data.get("estoque_minimo", produto["estoque_minimo"]))
    if estoque_minimo < 0:
        raise ValueError("Estoque mínimo não pode ser negativo.")

    estoque_maximo = None
    if "estoque_maximo" in data:
        val = data.get("estoque_maximo")
        if val not in (None, "", "null"):
            estoque_maximo = float(val)
            if estoque_maximo < estoque_minimo:
                raise ValueError("Estoque máximo não pode ser menor que o estoque mínimo.")
    else:
        estoque_maximo = produto["estoque_maximo"]

    prazo_reposicao = None
    if "prazo_reposicao_dias" in data:
        val = data.get("prazo_reposicao_dias")
        if val not in (None, "", "null"):
            prazo_reposicao = int(val)
    else:
        prazo_reposicao = produto["prazo_reposicao_dias"]

    preco_aquisicao = None
    if "preco_aquisicao_unitario" in data:
        val = data.get("preco_aquisicao_unitario")
        if val not in (None, "", "null"):
            preco_aquisicao = float(val)
            if preco_aquisicao < 0:
                raise ValueError("Preço unitário não pode ser negativo.")
    else:
        preco_aquisicao = produto["preco_aquisicao_unitario"]

    data_validade = data.get("data_validade", produto["data_validade"])
    if data_validade in (None, "", "null"):
        data_validade = None

    lote = (data.get("lote") if "lote" in data else produto["lote"]) or None
    fornecedor = (data.get("fornecedor") if "fornecedor" in data else produto["fornecedor"]) or None
    local_armazenamento = (data.get("local_armazenamento") if "local_armazenamento" in data else produto["local_armazenamento"]) or None

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE produtos SET
                nome = ?,
                categoria = ?,
                unidade_medida = ?,
                estoque_minimo = ?,
                estoque_maximo = ?,
                prazo_reposicao_dias = ?,
                preco_aquisicao_unitario = ?,
                lote = ?,
                data_validade = ?,
                fornecedor = ?,
                local_armazenamento = ?,
                data_atualizacao = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (
            nome, categoria, unidade_medida, estoque_minimo,
            estoque_maximo, prazo_reposicao, preco_aquisicao,
            lote, data_validade, fornecedor, local_armazenamento,
            product_id
        ))
        return True


def delete_product(product_id):
    """
    Exclusão controlada de produto.
    Se o produto possui movimentações registradas, realiza soft-delete (ativo=0)
    para preservar a rastreabilidade e histórico contábil.
    Se não possui movimentações e saldo é zero, exclui fisicamente.
    """
    produto = get_product(product_id)
    if not produto:
        raise ValueError("Produto não encontrado.")

    if produto["quantidade_atual"] > 0:
        raise ValueError(
            f"Não é permitido excluir produto com saldo positivo em estoque "
            f"({produto['quantidade_atual']} {produto['unidade_medida']}). Efetue a baixa/saída antes."
        )

    movs = query_db("SELECT COUNT(*) as cnt FROM movimentacoes WHERE produto_id = ?", (product_id,), one=True)
    with get_db() as conn:
        cursor = conn.cursor()
        if movs["cnt"] > 0:
            # Preserva integridade de dados históricos
            cursor.execute("UPDATE produtos SET ativo = 0, data_atualizacao = CURRENT_TIMESTAMP WHERE id = ?", (product_id,))
            return {"status": "inativado", "mensagem": "Produto inativado para manter integridade das movimentações históricas."}
        else:
            cursor.execute("DELETE FROM produtos WHERE id = ?", (product_id,))
            return {"status": "excluido", "mensagem": "Produto removido com sucesso."}


def register_movement(product_id, tipo, quantidade, data_movimentacao=None,
                      preco_unitario=None, fornecedor_destino=None,
                      responsavel="Responsável Técnico", observacao=None, lote=None):
    """
    Registra uma movimentação (entrada ou saída) no estoque com validação atômica.
    Garante:
    1. Entrada aumenta o saldo.
    2. Saída diminui o saldo.
    3. Bloqueia estritamente saída acima do saldo disponível.
    4. Atualiza o preço unitário do produto na entrada se informado.
    5. Registra auditoria da operação.
    """
    if tipo not in ('entrada', 'saida'):
        raise ValueError("Tipo de movimentação inválido. Deve ser 'entrada' ou 'saida'.")

    try:
        qtd = float(quantidade)
        if qtd <= 0:
            raise ValueError("A quantidade movimentada deve ser maior que zero.")
    except (ValueError, TypeError):
        raise ValueError("Quantidade movimentada inválida.")

    if not responsavel or not str(responsavel).strip():
        raise ValueError("O nome do responsável pela movimentação é obrigatório.")

    preco_val = None
    if preco_unitario not in (None, "", "null"):
        try:
            preco_val = float(preco_unitario)
            if preco_val < 0:
                raise ValueError("Preço unitário não pode ser negativo.")
        except (ValueError, TypeError):
            raise ValueError("Preço unitário inválido.")

    data_mov = data_movimentacao
    if not data_mov:
        data_mov = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        cursor = conn.cursor()
        # Buscar produto com lock de leitura
        cursor.execute("SELECT * FROM produtos WHERE id = ? AND ativo = 1", (product_id,))
        produto = cursor.fetchone()
        if not produto:
            raise ValueError("Produto não encontrado ou inativo.")

        saldo_atual = float(produto["quantidade_atual"])

        if tipo == 'saida':
            if qtd > saldo_atual:
                raise ValueError(
                    f"Saldo insuficiente para retirada. Disponível: {saldo_atual:g} {produto['unidade_medida']}, "
                    f"Solicitado: {qtd:g} {produto['unidade_medida']}."
                )
            novo_saldo = saldo_atual - qtd
        else:
            novo_saldo = saldo_atual + qtd

        # Registrar movimentação
        cursor.execute("""
            INSERT INTO movimentacoes (
                produto_id, tipo, quantidade, data_movimentacao,
                preco_unitario, fornecedor_destino, responsavel, observacao, lote, estornada
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            product_id, tipo, qtd, data_mov,
            preco_val, fornecedor_destino, responsavel.strip(), observacao, lote or produto["lote"]
        ))
        mov_id = cursor.lastrowid

        # Atualizar saldo e, se entrada com preço, atualizar preço médio/último
        if tipo == 'entrada' and preco_val is not None:
            cursor.execute("""
                UPDATE produtos SET
                    quantidade_atual = ?,
                    preco_aquisicao_unitario = ?,
                    lote = COALESCE(?, lote),
                    data_atualizacao = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (novo_saldo, preco_val, lote, product_id))
        else:
            cursor.execute("""
                UPDATE produtos SET
                    quantidade_atual = ?,
                    data_atualizacao = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (novo_saldo, product_id))

        # Registrar auditoria
        cursor.execute("""
            INSERT INTO movimentacoes_auditoria (
                movimentacao_id, tipo_operacao, quantidade_anterior, quantidade_nova,
                saldo_anterior, saldo_novo, responsavel, justificativa
            ) VALUES (?, 'criacao', 0, ?, ?, ?, ?, ?)
        """, (
            mov_id, qtd, saldo_atual, novo_saldo,
            responsavel.strip(), f"Registro de {tipo} no estoque ({observacao or 'Sem observação'})"
        ))

        return {
            "movimentacao_id": mov_id,
            "produto_id": product_id,
            "tipo": tipo,
            "quantidade": qtd,
            "saldo_anterior": saldo_atual,
            "saldo_novo": novo_saldo
        }


def cancel_or_revert_movement(movimentacao_id, responsavel, justificativa):
    """
    Estorna uma movimentação anterior com recálculo correto do saldo e registro de auditoria.
    - Se estornar uma ENTRADA: diminui o saldo (bloqueia se o saldo atual for menor que a entrada).
    - Se estornar uma SAÍDA: devolve a quantidade ao saldo.
    - Marca a movimentação como estornada (estornada = 1).
    - Mantém a trilha de auditoria completa.
    """
    if not responsavel or not str(responsavel).strip():
        raise ValueError("O nome do responsável pelo estorno é obrigatório.")
    if not justificativa or len(justificativa.strip()) < 5:
        raise ValueError("A justificativa do estorno deve conter ao menos 5 caracteres.")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM movimentacoes WHERE id = ?", (movimentacao_id,))
        mov = cursor.fetchone()
        if not mov:
            raise ValueError("Movimentação não encontrada.")
        if mov["estornada"] == 1:
            raise ValueError("Esta movimentação já foi estornada anteriormente.")

        cursor.execute("SELECT * FROM produtos WHERE id = ?", (mov["produto_id"],))
        produto = cursor.fetchone()
        if not produto:
            raise ValueError("Produto relacionado não encontrado.")

        saldo_atual = float(produto["quantidade_atual"])
        qtd = float(mov["quantidade"])
        tipo = mov["tipo"]

        if tipo == 'entrada':
            # Estorno de entrada diminui o saldo
            if saldo_atual < qtd:
                raise ValueError(
                    f"Não é possível estornar esta entrada de {qtd:g} {produto['unidade_medida']}, "
                    f"pois o saldo atual ({saldo_atual:g}) ficaria negativo."
                )
            novo_saldo = saldo_atual - qtd
        else:
            # Estorno de saída devolve ao saldo
            novo_saldo = saldo_atual + qtd

        # Marcar movimentação como estornada
        cursor.execute("UPDATE movimentacoes SET estornada = 1 WHERE id = ?", (movimentacao_id,))

        # Atualizar saldo do produto
        cursor.execute("UPDATE produtos SET quantidade_atual = ?, data_atualizacao = CURRENT_TIMESTAMP WHERE id = ?", (novo_saldo, produto["id"]))

        # Inserir registro na tabela de auditoria
        cursor.execute("""
            INSERT INTO movimentacoes_auditoria (
                movimentacao_id, tipo_operacao, quantidade_anterior, quantidade_nova,
                saldo_anterior, saldo_novo, responsavel, justificativa
            ) VALUES (?, 'estorno', ?, 0, ?, ?, ?, ?)
        """, (
            movimentacao_id, qtd, saldo_atual, novo_saldo,
            responsavel.strip(), justificativa.strip()
        ))

        return {
            "sucesso": True,
            "movimentacao_id": movimentacao_id,
            "saldo_anterior": saldo_atual,
            "saldo_novo": novo_saldo,
            "tipo_estornado": tipo
        }


def list_movements(produto_id=None, tipo=None, data_inicio=None, data_fim=None, responsavel=None, limite=200):
    """Lista movimentações com filtros por produto, período, tipo e responsável."""
    sql = """
        SELECT m.*, p.nome as produto_nome, p.unidade_medida, p.categoria as produto_categoria
        FROM movimentacoes m
        JOIN produtos p ON m.produto_id = p.id
        WHERE 1=1
    """
    params = []

    if produto_id:
        sql += " AND m.produto_id = ?"
        params.append(produto_id)

    if tipo in ('entrada', 'saida'):
        sql += " AND m.tipo = ?"
        params.append(tipo)

    if data_inicio:
        sql += " AND date(m.data_movimentacao) >= date(?)"
        params.append(data_inicio)

    if data_fim:
        sql += " AND date(m.data_movimentacao) <= date(?)"
        params.append(data_fim)

    if responsavel:
        sql += " AND m.responsavel LIKE ?"
        params.append(f"%{responsavel.strip()}%")

    sql += " ORDER BY m.data_movimentacao DESC, m.id DESC LIMIT ?"
    params.append(limite)

    return query_db(sql, params)


def get_movement_audit(movimentacao_id):
    """Retorna os registros de auditoria de uma movimentação."""
    sql = "SELECT * FROM movimentacoes_auditoria WHERE movimentacao_id = ? ORDER BY data_operacao DESC"
    return query_db(sql, (movimentacao_id,))
