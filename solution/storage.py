"""SQLite 持久化：保存每次 plan/diagnose 运行的结果，支持 history 查询。

持久状态只增不改；同一份逻辑输入（case_json 的规范化哈希）与同一命令
重复执行会得到相同的结果内容（自增序号除外）。
"""

import hashlib
import json
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    seq           INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id       TEXT NOT NULL,
    case_hash     TEXT NOT NULL,
    command       TEXT NOT NULL,
    status        TEXT NOT NULL,
    result_json   TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def case_hash(raw: dict) -> str:
    """逻辑输入的稳定哈希：键排序、无多余空白，保证同输入同哈希。"""
    blob = json.dumps(raw, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class Storage:
    def __init__(self, path: str):
        # check_same_thread=False 仅为兼容潜在调用方式；CLI 单线程使用
        self.conn = sqlite3.connect(path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.commit()
        self.conn.close()

    def save_run(self, case_id, chash, command, status, result: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (case_id, case_hash, command, status, result_json)"
            " VALUES (?, ?, ?, ?, ?)",
            (case_id, chash, command, status,
             json.dumps(result, ensure_ascii=False, sort_keys=True)),
        )
        self.conn.commit()
        return cur.lastrowid

    def list_runs(self, case_id=None, chash=None) -> list:
        sql = ("SELECT seq, case_id, case_hash, command, status, result_json,"
               " created_at FROM runs WHERE 1=1")
        args = []
        if case_id is not None:
            sql += " AND case_id = ?"
            args.append(case_id)
        if chash is not None:
            sql += " AND case_hash = ?"
            args.append(chash)
        sql += " ORDER BY seq ASC"
        rows = self.conn.execute(sql, args).fetchall()
        return [
            {
                "seq": r[0], "case_id": r[1], "case_hash": r[2],
                "command": r[3], "status": r[4],
                "result": json.loads(r[5]), "created_at": r[6],
            }
            for r in rows
        ]
