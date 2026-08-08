import psycopg2
from psycopg2 import pool
from config import DB_CONFIG

_connection_pool = None


def get_pool():
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            **DB_CONFIG
        )
    return _connection_pool


def get_connection():
    return get_pool().getconn()


def release_connection(conn):
    get_pool().putconn(conn)


def execute_query(sql, params=None):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        release_connection(conn)


def execute_one(sql, params=None):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        release_connection(conn)


def execute_one_fresh(sql, params=None):
    """在全新连接上执行单条查询并立即关闭。

    用途: 规避同一后端会话内 GEOS (ST_Union/ST_Simplify) 重复执行退化问题
    (同一连接第 3 次起从 ~1.2s 退化到 ~5.5s, 换新连接始终 ~1.2s)。"""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def execute_query_fresh(sql, params=None):
    """在全新连接上执行多条查询并立即关闭。

    用途: 规避同一后端会话内 pgRouting (pgr_drivingDistance) 重复执行退化
    问题 (复用连接第 2 次起从 ~1.4s 退化到 ~6s, 换新连接始终 ~1.4s)。"""
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()
