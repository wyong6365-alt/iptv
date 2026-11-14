"""只读保护：原始招标清单、计算快照、审计日志在数据库层面拒绝 UPDATE 和 DELETE。

这层保护不依赖应用代码，直接执行 SQL 也无法改动。
"""
from sqlalchemy import text

PROTECTED = ["tender_boq_versions", "tender_boq_items", "calc_runs", "audit_log"]


def install(engine) -> None:
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            for table in PROTECTED:
                for op in ("UPDATE", "DELETE"):
                    conn.execute(text(
                        f"CREATE TRIGGER IF NOT EXISTS protect_{table}_{op.lower()} BEFORE {op} ON {table} "
                        f"BEGIN SELECT RAISE(ABORT, '{table} 为只读数据，禁止 {op}'); END"
                    ))
        elif dialect == "postgresql":
            conn.execute(text(
                "CREATE OR REPLACE FUNCTION gc_reject_change() RETURNS trigger AS $$ "
                "BEGIN RAISE EXCEPTION '% 为只读数据，禁止 %', TG_TABLE_NAME, TG_OP; END; $$ LANGUAGE plpgsql"
            ))
            for table in PROTECTED:
                conn.execute(text(f"DROP TRIGGER IF EXISTS protect_{table} ON {table}"))
                conn.execute(text(
                    f"CREATE TRIGGER protect_{table} BEFORE UPDATE OR DELETE ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION gc_reject_change()"
                ))
                conn.execute(text(f"DROP TRIGGER IF EXISTS protect_{table}_truncate ON {table}"))
                conn.execute(text(
                    f"CREATE TRIGGER protect_{table}_truncate BEFORE TRUNCATE ON {table} "
                    "FOR EACH STATEMENT EXECUTE FUNCTION gc_reject_change()"
                ))
        else:
            raise RuntimeError(f"不支持的数据库：{dialect}")
