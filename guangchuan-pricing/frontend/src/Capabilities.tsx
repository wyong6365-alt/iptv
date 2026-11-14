import { Fragment, useEffect, useState } from "react";
import { api } from "./api";

interface Row {
  profession: string;
  name: string;
  overall: string;
  capabilities: Record<string, { status: string; evidence: string }>;
}

const TONE: Record<string, string> = {
  可用: "ok", 已录入待复核: "warn", 未验证: "warn", 数据缺失: "bad", 不可用: "off", 未开发: "off",
};

export function Capabilities() {
  const [data, setData] = useState<{ columns: { key: string; name: string }[]; rows: Row[] } | null>(null);
  const [error, setError] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    api("GET", "/api/capabilities").then(setData).catch((e) => setError(e.message));
  }, []);
  if (error) return <div className="alert error">{error}</div>;
  if (!data) return <p className="muted">加载中…</p>;
  return (
    <>
      <h2>专业能力中心</h2>
      <p className="muted">
        地区：山东省。状态由系统根据已导入的数据和测试记录计算，不能手工改为“可用”。点击专业名称查看依据。
      </p>
      <div className="scroll">
        <table className="matrix">
          <thead>
            <tr>
              <th>专业</th>
              <th>总体状态</th>
              {data.columns.map((c) => <th key={c.key}>{c.name}</th>)}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <Fragment key={r.profession}>
                <tr>
                  <td><button className="link" onClick={() => setOpen(open === r.profession ? null : r.profession)}>{r.name}</button></td>
                  <td>{r.overall}</td>
                  {data.columns.map((c) => {
                    const cap = r.capabilities[c.key];
                    return <td key={c.key}><span className={`tag ${TONE[cap.status] ?? "off"}`} title={cap.evidence}>{cap.status}</span></td>;
                  })}
                </tr>
                {open === r.profession && (
                  <tr className="detail">
                    <td colSpan={data.columns.length + 2}>
                      <dl>
                        {data.columns.map((c) => (
                          <div key={c.key}><dt>{c.name}</dt><dd>{r.capabilities[c.key].status}{r.capabilities[c.key].evidence && `：${r.capabilities[c.key].evidence}`}</dd></div>
                        ))}
                      </dl>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
