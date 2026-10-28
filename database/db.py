"""
Módulo de conexão e gerenciamento do Banco de Dados SQLite.
Garante integridade referencial (foreign keys ON), modo WAL para concorrência
e transações atômicas seguras.
"""

import os
import sqlite3
from contextlib import contextmanager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(BASE_DIR, "agro_estoque.db"))
SCHEMA_PATH = os.path.join(BASE_DIR, "database", "schema.sql")


def get_db_connection():
    """Retorna uma nova conexão configurada com row_factory e foreign keys ativadas."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


@contextmanager
def get_db():
    """Context manager para operações de banco de dados com commit/rollback automático."""
    conn = get_db_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(force=False):
    """Inicializa o banco de dados a partir do arquivo schema.sql."""
    if force and os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except Exception:
            pass

    with get_db() as conn:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
    return True


def query_db(query, args=(), one=False):
    """Executa consultas SELECT retornando dicionários."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(query, args)
        rv = cur.fetchall()
        cur.close()
        if one:
            return dict(rv[0]) if rv else None
        return [dict(row) for row in rv]


def execute_db(query, args=()):
    """Executa comandos INSERT/UPDATE/DELETE e retorna o lastrowid."""
    with get_db() as conn:
        cur = conn.cursor()
        cur.execute(query, args)
        last_id = cur.lastrowid
        cur.close()
        return last_id
