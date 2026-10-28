-- ============================================================
-- AGROHACK 2026/2 - IFRO Campus Ariquemes
-- Sistema Inteligente de Gestão de Insumos Rurais (AgroInsight)
-- Schema do Banco de Dados Relacional (SQLite com Foreign Keys e Auditoria)
-- ============================================================

PRAGMA foreign_keys = ON;

-- 1. Tabela de Categorias Oficiais do Desafio
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT UNIQUE NOT NULL,
    descricao TEXT
);

-- Inserção das categorias oficiais do regulamento
INSERT OR IGNORE INTO categorias (nome, descricao) VALUES
('Fertilizantes', 'Adubos químicos, orgânicos, formulados NPK e micronutrientes'),
('Corretivos', 'Calcário, gesso agrícola e condicionadores de solo'),
('Sementes', 'Cultivares de soja, milho, café, pastagem e hortaliças'),
('Defensivos e produtos biológicos', 'Herbicidas, fungicidas, inseticidas e agentes biológicos'),
('Combustíveis e lubrificantes', 'Óleo diesel S10, gasolina, óleos lubrificantes e graxas'),
('Peças e manutenção', 'Peças de tratores, implementos, filtros, correias e bicos'),
('Materiais de irrigação', 'Tubos, conexões, gotejadores, aspersores e motobombas'),
('Equipamentos de proteção individual e materiais diversos', 'EPIs agrícolas, ferramentas, telas, sacarias e embalagens');

-- 2. Tabela de Produtos
CREATE TABLE IF NOT EXISTS produtos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    categoria TEXT NOT NULL,
    unidade_medida TEXT NOT NULL,
    quantidade_atual REAL NOT NULL DEFAULT 0.0 CHECK (quantidade_atual >= 0),
    estoque_minimo REAL NOT NULL DEFAULT 0.0 CHECK (estoque_minimo >= 0),
    estoque_maximo REAL DEFAULT NULL CHECK (estoque_maximo IS NULL OR estoque_maximo >= 0),
    prazo_reposicao_dias INTEGER DEFAULT NULL CHECK (prazo_reposicao_dias IS NULL OR prazo_reposicao_dias >= 0),
    preco_aquisicao_unitario REAL DEFAULT NULL CHECK (preco_aquisicao_unitario IS NULL OR preco_aquisicao_unitario >= 0),
    lote TEXT DEFAULT NULL,
    data_validade DATE DEFAULT NULL,
    fornecedor TEXT DEFAULT NULL,
    local_armazenamento TEXT DEFAULT NULL,
    ativo INTEGER NOT NULL DEFAULT 1 CHECK (ativo IN (0, 1)),
    data_cadastro TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    data_atualizacao TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Índices para otimização de consultas
CREATE INDEX IF NOT EXISTS idx_produtos_categoria ON produtos(categoria);
CREATE INDEX IF NOT EXISTS idx_produtos_validade ON produtos(data_validade);
CREATE INDEX IF NOT EXISTS idx_produtos_ativo ON produtos(ativo);

-- 3. Tabela de Movimentações de Estoque (Entradas e Saídas)
CREATE TABLE IF NOT EXISTS movimentacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    produto_id INTEGER NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('entrada', 'saida')),
    quantidade REAL NOT NULL CHECK (quantidade > 0),
    data_movimentacao TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    preco_unitario REAL DEFAULT NULL CHECK (preco_unitario IS NULL OR preco_unitario >= 0),
    fornecedor_destino TEXT DEFAULT NULL,
    responsavel TEXT NOT NULL,
    observacao TEXT DEFAULT NULL,
    lote TEXT DEFAULT NULL,
    estornada INTEGER NOT NULL DEFAULT 0 CHECK (estornada IN (0, 1)),
    data_criacao TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (produto_id) REFERENCES produtos(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_movimentacoes_produto ON movimentacoes(produto_id);
CREATE INDEX IF NOT EXISTS idx_movimentacoes_data ON movimentacoes(data_movimentacao);
CREATE INDEX IF NOT EXISTS idx_movimentacoes_tipo ON movimentacoes(tipo);

-- 4. Tabela de Auditoria de Movimentações (Rastreabilidade e Estornos)
CREATE TABLE IF NOT EXISTS movimentacoes_auditoria (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    movimentacao_id INTEGER NOT NULL,
    tipo_operacao TEXT NOT NULL CHECK (tipo_operacao IN ('criacao', 'edicao', 'estorno', 'cancelamento')),
    quantidade_anterior REAL,
    quantidade_nova REAL,
    saldo_anterior REAL,
    saldo_novo REAL,
    responsavel TEXT NOT NULL,
    justificativa TEXT NOT NULL,
    data_operacao TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (movimentacao_id) REFERENCES movimentacoes(id) ON DELETE CASCADE
);

-- 5. Tabela de Status e Resolução de Alertas
-- Permite que gestores acompanhem e resolvam alertas gerados dinamicamente
CREATE TABLE IF NOT EXISTS alertas_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alerta_hash TEXT UNIQUE NOT NULL, -- Hash único do alerta (produto_id + tipo_alerta + data_referencia)
    produto_id INTEGER NOT NULL,
    tipo_alerta TEXT NOT NULL,
    prioridade TEXT NOT NULL,
    situacao TEXT NOT NULL DEFAULT 'pendente' CHECK (situacao IN ('pendente', 'em_acompanhamento', 'resolvido')),
    observacao_resolucao TEXT DEFAULT NULL,
    responsavel TEXT DEFAULT NULL,
    data_criacao TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    data_atualizacao TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (produto_id) REFERENCES produtos(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alertas_hash ON alertas_status(alerta_hash);
CREATE INDEX IF NOT EXISTS idx_alertas_situacao ON alertas_status(situacao);

-- 6. Tabela de Configurações do Sistema
CREATE TABLE IF NOT EXISTS configuracoes (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL,
    descricao TEXT
);

INSERT OR IGNORE INTO configuracoes (chave, valor, descricao) VALUES
('dias_alerta_validade', '60', 'Dias de antecedência para alertar sobre validade próxima'),
('fator_anomalia_consumo', '2.5', 'Multiplicador de desvio da média para acusar consumo atípico'),
('periodo_analise_dias', '30', 'Janela de dias recente para cálculo de consumo médio diário'),
('multiplicador_excesso', '3.0', 'Multiplicador sobre estoque mínimo para apontar excesso de estoque'),
('nome_propriedade', 'Fazenda Modelo IFRO Ariquemes', 'Nome da propriedade rural para relatórios');
