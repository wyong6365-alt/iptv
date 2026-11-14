import { Fragment, useEffect, useMemo, useState } from "react";
import { api, BoqItem, CalcResult, Fee, Line, money } from "./api";

type Tab = "boq" | "pricing" | "params" | "result";
interface Named { name: string; amount: string; all_in?: boolean }
interface UnitInfo {
  id: number;
  name: string;
  project: { id: number; name: string };
  profession: { code: string; name: string };
  pricing_system: string;
  engine: string;
  grade: string | null;
  tender_requirements: Record<string, any>;
  pricing_params: Record<string, any>;
  reference: null | {
    rule_code: string; rule_name: string; reviewed: boolean; category_name: string; fee_base: string;
    management: string; profit: string; injury: string; vat: string;
    general_measures: { key: string; name: string; rate: string }[];
    safety: { key: string; name: string; floor: string }[];
    quality: Record<string, string>;
    service: { owner_material: string; subcontract: string };
  };
  has_boq: boolean;
  last_run: (CalcResult & { at: string; boq_version_id: number }) | null;
}
interface Boq {
  version_id: number; version_no: number; kind: string; source_file: string; note: string;
  content_hash: string; intact: boolean; items: BoqItem[];
}

const KIND: Record<string, string> = { original: "原始清单", addendum: "补遗", re_recognition: "重新识别" };

function BoqTable({ items, preview }: { items: BoqItem[]; preview?: boolean }) {
  return (
    <div className="scroll tall">
      <table>
        <thead>
          <tr><th>序号</th><th>项目编码</th><th>项目名称</th><th>项目特征</th><th>单位</th><th className="num">工程量</th><th>原件位置</th></tr>
        </thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={i} className={it.quantity === null ? "bad-row" : it.anomalies.length ? "warn-row" : ""}>
              <td>{it.seq ?? i + 1}</td>
              <td className="mono">{it.code}</td>
              <td>{it.name}<div className="muted small">{it.section}</div></td>
              <td className="pre">{it.features}
                {it.anomalies.map((a, k) => <div key={k} className="note">⚠ {a}</div>)}
              </td>
              <td>{it.unit}</td>
              <td className="num mono">{it.quantity ?? (preview ? "无法识别" : "")}</td>
              <td className="muted small">{it.source_ref}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BoqTab({ unit, boq, reload }: { unit: UnitInfo; boq: Boq | null; reload: () => void }) {
  const [preview, setPreview] = useState<any>(null);
  const [kind, setKind] = useState(boq ? "addendum" : "original");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [diff, setDiff] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  async function upload(file: File | undefined) {
    if (!file) return;
    setError(""); setPreview(null); setDiff(null); setBusy(true);
    try {
      setPreview(await api("POST", `/api/units/${unit.id}/boq/recognize?filename=${encodeURIComponent(file.name)}`, file));
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function confirm() {
    setError("");
    try {
      const r = await api("POST", `/api/units/${unit.id}/boq`, {
        kind: boq ? kind : "original", note, source_file: preview.source_file, items: preview.items,
      });
      setDiff(r.diff); setPreview(null); setNote("");
      reload();
    } catch (e: any) {
      setError(e.message);
    }
  }
  return (
    <>
      {boq && (
        <div className="card">
          <header>
            <h4>🔒 有效招标清单：第 {boq.version_no} 版（{KIND[boq.kind]}），共 {boq.items.length} 项</h4>
            <span className={`tag ${boq.intact ? "ok" : "bad"}`}>{boq.intact ? "完整性校验通过" : "完整性校验失败"}</span>
          </header>
          <p className="muted small">来源：{boq.source_file || "未记录"}　指纹：<span className="mono">{boq.content_hash.slice(0, 24)}…</span>{boq.note && `　依据：${boq.note}`}</p>
          <p className="muted">招标清单为只读数据，编码、名称、特征、单位、工程量均不能修改。</p>
          {diff && diff.length > 0 && (
            <div className="alert warn">
              本次导入与上一版相比有 {diff.length} 处变化，相关清单项的组价请复核：
              <ul>{diff.map((d, i) => (
                <li key={i}>{d.code} {d.change === "added" ? `新增：${d.name}` : d.change === "removed" ? `删除：${d.name}` :
                  Object.entries(d.fields).map(([f, v]: any) => `${f} ${v[0]} → ${v[1]}`).join("；")}</li>
              ))}</ul>
            </div>
          )}
          <BoqTable items={boq.items} />
        </div>
      )}
      <div className="card">
        <h4>{boq ? "导入补遗或重新识别（生成新版本，原版本保留）" : "上传招标工程量清单（Excel .xlsx）"}</h4>
        <input type="file" accept=".xlsx,.xlsm" onChange={(e) => upload(e.target.files?.[0])} />
        {busy && <p className="muted">正在识别…</p>}
        {error && <div className="alert error">{error}</div>}
        {preview && (
          <>
            <p>识别结果：共 {preview.items.length} 项，{preview.anomaly_rows} 项有提示，{preview.blocking_rows} 项无法导入。请对照原件核对后再确认。</p>
            <ul className="muted small">
              {preview.sheets.map((s: any) => <li key={s.sheet}>工作表“{s.sheet}”：{s.used ? `读取 ${s.items} 项` : `未读取（${s.reason}）`}</li>)}
            </ul>
            <BoqTable items={preview.items} preview />
            {preview.blocking_rows > 0 ? (
              <div className="alert error">有 {preview.blocking_rows} 项缺少编码、名称、单位或工程量（红色行）。系统不会猜测或跳过清单内容，请在原文件中核实后重新上传。</div>
            ) : (
              <div className="inline">
                {boq && (
                  <>
                    <select value={kind} onChange={(e) => setKind(e.target.value)}>
                      <option value="addendum">招标人补遗或变更</option>
                      <option value="re_recognition">纠正识别错误</option>
                    </select>
                    <input placeholder="依据（如：补遗第 1 号，2026-11-10）" value={note} onChange={(e) => setNote(e.target.value)} />
                  </>
                )}
                <button className="primary" onClick={confirm} disabled={preview.items.length === 0 || (!!boq && !note.trim())}>
                  已核对，确认导入
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </>
  );
}

const EMPTY_LINE: Line = { name: "", unit: "", content: "1", labor: "0", material: "0", machine: "0", basis_note: "" };

function PricingTab({ unit, boq, onSaved }: { unit: UnitInfo; boq: Boq; onSaved: () => void }) {
  const [all, setAll] = useState<Record<string, Line[]>>({});
  const [seq, setSeq] = useState<number>(boq.items[0]?.seq ?? 1);
  const [lines, setLines] = useState<Line[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const load = () => api("GET", `/api/units/${unit.id}/lines`).then(setAll);
  useEffect(() => { load(); }, []);
  useEffect(() => { setLines(all[seq] ? all[seq].map((l) => ({ ...l })) : []); }, [seq, all]);
  const item = boq.items.find((i) => i.seq === seq);
  const priced = useMemo(() => {
    const out: Record<number, string> = {};
    if (unit.last_run?.boq_version_id === boq.version_id) unit.last_run.items.forEach((r, i) => { out[boq.items[i]?.seq ?? -1] = r.unit_price; });
    return out;
  }, [unit.last_run, boq]);
  const set = (i: number, field: keyof Line, value: string) => setLines(lines.map((l, k) => (k === i ? { ...l, [field]: value } : l)));
  async function save() {
    setMsg(null);
    try {
      await api("PUT", `/api/units/${unit.id}/boq/${seq}/lines`, lines.map(({ quota_item_id, ...l }) => (quota_item_id ? { ...l, quota_item_id } : l)));
      await load();
      setMsg({ ok: true, text: "已保存。请到“计算结果”重新计算。" });
      onSaved();
    } catch (e: any) {
      setMsg({ ok: false, text: e.message });
    }
  }
  if (!item) return null;
  return (
    <div className="split">
      <div className="card list">
        {boq.items.map((it) => (
          <button key={it.seq} className={`row ${it.seq === seq ? "on" : ""}`} onClick={() => { setSeq(it.seq!); setMsg(null); }}>
            <span className="mono small">{it.code}</span>
            <span>{it.name}</span>
            <span className={`tag ${all[it.seq!]?.length ? "ok" : "off"}`}>{all[it.seq!]?.length ? `${all[it.seq!].length} 条子目` : "未组价"}</span>
          </button>
        ))}
      </div>
      <div className="card">
        <h4>🔒 {item.code}　{item.name}</h4>
        <p className="pre muted">{item.features}</p>
        <p>工程量：<b className="mono">{item.quantity}</b> {item.unit}
          {priced[seq] !== undefined && <>　上次计算综合单价：<b className="mono">{money(priced[seq])}</b></>}</p>
        <div className="alert info">定额库尚未导入，目前只能录入补充子目，并须填写依据。“含量”指每 1 个清单计量单位对应的子目工程量；人工、材料、机具为子目单位费用（元）。</div>
        <table className="edit">
          <thead><tr><th>子目名称</th><th>单位</th><th>含量</th><th>人工费</th><th>材料费</th><th>机具费</th><th>依据</th><th /></tr></thead>
          <tbody>
            {lines.map((l, i) => (
              <tr key={i}>
                <td><input value={l.name} onChange={(e) => set(i, "name", e.target.value)} /></td>
                <td><input className="narrow" value={l.unit} onChange={(e) => set(i, "unit", e.target.value)} /></td>
                {(["content", "labor", "material", "machine"] as const).map((f) => (
                  <td key={f}><input className="numin" inputMode="decimal" value={l[f]} onChange={(e) => set(i, f, e.target.value)} /></td>
                ))}
                <td><input value={l.basis_note} onChange={(e) => set(i, "basis_note", e.target.value)} placeholder="如：企业定额、询价" /></td>
                <td><button className="link" onClick={() => setLines(lines.filter((_, k) => k !== i))}>删除</button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="inline">
          <button onClick={() => setLines([...lines, { ...EMPTY_LINE }])}>添加子目</button>
          <button className="primary" onClick={save}>保存本项组价</button>
        </div>
        {msg && <div className={`alert ${msg.ok ? "ok" : "error"}`}>{msg.text}</div>}
      </div>
    </div>
  );
}

function NamedList({ rows, onChange, allIn }: { rows: Named[]; onChange: (r: Named[]) => void; allIn?: boolean }) {
  const set = (i: number, patch: Partial<Named>) => onChange(rows.map((r, k) => (k === i ? { ...r, ...patch } : r)));
  return (
    <div className="named">
      {rows.map((r, i) => (
        <div className="inline" key={i}>
          <input placeholder="名称" value={r.name} onChange={(e) => set(i, { name: e.target.value })} />
          <input className="numin" placeholder="金额" inputMode="decimal" value={r.amount} onChange={(e) => set(i, { amount: e.target.value })} />
          {allIn && <label className="check"><input type="checkbox" checked={!!r.all_in} onChange={(e) => set(i, { all_in: e.target.checked })} />含税全费用价</label>}
          <button className="link" onClick={() => onChange(rows.filter((_, k) => k !== i))}>删除</button>
        </div>
      ))}
      <button onClick={() => onChange([...rows, { name: "", amount: "" }])}>添加一行</button>
    </div>
  );
}

function clean(obj: Record<string, any>): Record<string, any> {
  const out: Record<string, any> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v === "" || v === null || v === undefined) continue;
    if (Array.isArray(v)) { const rows = v.filter((r) => r.name && r.amount !== ""); if (rows.length) out[k] = rows; continue; }
    if (typeof v === "object") { const c = clean(v); if (Object.keys(c).length) out[k] = c; continue; }
    out[k] = v;
  }
  return out;
}

function Num({ label, value, onChange, hint }: { label: string; value: string; onChange: (v: string) => void; hint?: string }) {
  return <label>{label}<input className="numin" inputMode="decimal" value={value ?? ""} placeholder={hint} onChange={(e) => onChange(e.target.value)} /></label>;
}

function ParamsTab({ unit, reload }: { unit: UnitInfo; reload: () => void }) {
  const sd = unit.engine === "sd_construction";
  const ref = unit.reference;
  const [t, setT] = useState<Record<string, any>>({ source_ref: "", tax_method: "general", tender_amounts: [], ...unit.tender_requirements });
  const [p, setP] = useState<Record<string, any>>({
    general_measure_rates: {}, safety_rates: {}, special_measures: [], measures: [], others: [], ...unit.pricing_params,
  });
  const [msg, setMsg] = useState<Record<string, { ok: boolean; text: string }>>({});
  const tset = (k: string, v: any) => setT({ ...t, [k]: v });
  const pset = (k: string, v: any) => setP({ ...p, [k]: v });
  async function save(which: "tender" | "params") {
    try {
      if (which === "tender") await api("PUT", `/api/units/${unit.id}/tender-requirements`, clean(t));
      else await api("PUT", `/api/units/${unit.id}/pricing-params`, clean(p));
      setMsg({ [which]: { ok: true, text: "已保存，修改已记入审计日志。" } });
      reload();
    } catch (e: any) {
      setMsg({ [which]: { ok: false, text: e.message } });
    }
  }
  return (
    <>
      <div className="card">
        <h4>🔒 招标文件规定的内容</h4>
        <p className="muted">这些内容由招标文件决定，投标人不得自行调整。保存时必须填写出处，每次修改都会记入审计日志。</p>
        <div className="grid">
          <label className="wide">出处（招标文件名称和页码）<input value={t.source_ref} onChange={(e) => tset("source_ref", e.target.value)} /></label>
          {sd ? (
            <>
              <label>计税方法
                <select value={t.tax_method} onChange={(e) => tset("tax_method", e.target.value)}>
                  <option value="general">一般计税</option><option value="simple">简易计税</option>
                </select>
              </label>
              <Num label="暂列金额（元）" value={t.provisional_sum} onChange={(v) => tset("provisional_sum", v)} />
              <Num label="专业工程暂估价（元，含税）" value={t.specialty_provisional} onChange={(v) => tset("specialty_provisional", v)} />
              <Num label="发包人提供的材料费（元）" value={t.owner_material} onChange={(v) => tset("owner_material", v)} />
              <label>优质优价创建目标
                <select value={t.quality_level ?? ""} onChange={(e) => tset("quality_level", e.target.value)}>
                  <option value="">招标文件未提出</option><option value="national">国家级</option>
                  <option value="provincial">省级</option><option value="municipal">市级</option>
                </select>
              </label>
            </>
          ) : (
            <Num label="税率（%）" value={t.tax_rate} onChange={(v) => tset("tax_rate", v)} />
          )}
        </div>
        {!sd && (<><h5>招标文件给定金额（暂列金额、暂估价等）</h5><NamedList rows={t.tender_amounts ?? []} onChange={(r) => tset("tender_amounts", r)} /></>)}
        <button className="primary" onClick={() => save("tender")}>保存招标规定</button>
        {msg.tender && <div className={`alert ${msg.tender.ok ? "ok" : "error"}`}>{msg.tender.text}</div>}
      </div>

      {sd && ref && (
        <div className="card">
          <h4>🔒 按规则锁定的费率</h4>
          <p className="muted">依据：{ref.rule_name}（{ref.rule_code}）　工程类别：{ref.category_name}{unit.grade && ` ${unit.grade} 类`}　计费基础：{ref.fee_base}</p>
          {!ref.reviewed && <div className="alert warn">该规则数据由程序从官方 PDF 转录，尚未经造价人员对照原件复核签字。</div>}
          <div className="grid">
            <label>建设项目工伤保险（%）<input disabled value={ref.injury} /></label>
            <label>增值税（%）<input disabled value={ref.vat} /></label>
          </div>
          <h5>安全文明措施费（费率不得低于规定值，留空按规定值）</h5>
          <div className="grid">
            {ref.safety.map((s) => (
              <Num key={s.key} label={`${s.name}（下限 ${s.floor}%）`} value={p.safety_rates[s.key]} hint={s.floor}
                onChange={(v) => pset("safety_rates", { ...p.safety_rates, [s.key]: v })} />
            ))}
          </div>
        </div>
      )}

      <div className="card">
        <h4>可竞争的费用参数</h4>
        {sd && ref ? (
          <>
            <p className="muted">规则中的费率仅供参考，留空即采用参考值（输入框中的灰色数字）。</p>
            <div className="grid">
              <Num label="企业管理费费率（%）" value={p.management_rate} hint={ref.management} onChange={(v) => pset("management_rate", v)} />
              <Num label="利润率（%）" value={p.profit_rate} hint={ref.profit} onChange={(v) => pset("profit_rate", v)} />
              {ref.general_measures.map((g) => (
                <Num key={g.key} label={`${g.name}（%）`} value={p.general_measure_rates[g.key]} hint={g.rate}
                  onChange={(v) => pset("general_measure_rates", { ...p.general_measure_rates, [g.key]: v })} />
              ))}
              <Num label="总承包服务费：发包人供材（%）" value={p.service_owner_material_rate} hint={ref.service.owner_material} onChange={(v) => pset("service_owner_material_rate", v)} />
              <Num label="总承包服务费：专业分包（%）" value={p.service_subcontract_rate} hint={ref.service.subcontract} onChange={(v) => pset("service_subcontract_rate", v)} />
              <Num label="总承包服务费：直接发包工程（元）" value={p.service_direct_lump} onChange={(v) => pset("service_direct_lump", v)} />
              <Num label="计日工（元）" value={p.daywork} onChange={(v) => pset("daywork", v)} />
              <Num label="其他（元）" value={p.other} onChange={(v) => pset("other", v)} />
            </div>
            <h5>专业措施项目（脚手架、垂直运输等，按金额录入）</h5>
            <NamedList rows={p.special_measures} onChange={(r) => pset("special_measures", r)} allIn />
          </>
        ) : (
          <>
            <div className="alert warn">该专业尚未录入计价规则，以下费率和费用全部由人工输入，计算结果会标注“非规则依据”。</div>
            <div className="grid">
              <label>管理费、利润的计费基础
                <select value={p.fee_base ?? "direct"} onChange={(e) => pset("fee_base", e.target.value)}>
                  <option value="direct">人工费+材料费+机具费</option><option value="labor_machine">人工费+机具费</option><option value="labor">人工费</option>
                </select>
              </label>
              <Num label="管理费费率（%）" value={p.management_rate} onChange={(v) => pset("management_rate", v)} />
              <Num label="利润率（%）" value={p.profit_rate} onChange={(v) => pset("profit_rate", v)} />
            </div>
            <h5>措施项目</h5><NamedList rows={p.measures} onChange={(r) => pset("measures", r)} />
            <h5>其他项目</h5><NamedList rows={p.others} onChange={(r) => pset("others", r)} />
          </>
        )}
        <button className="primary" onClick={() => save("params")}>保存费用参数</button>
        {msg.params && <div className={`alert ${msg.params.ok ? "ok" : "error"}`}>{msg.params.text}</div>}
      </div>
    </>
  );
}

function FeeRows({ fees, depth = 0 }: { fees: Fee[]; depth?: number }) {
  return (
    <>
      {fees.map((f) => (
        <Fragment key={f.code}>
          <tr className={depth === 0 ? "top" : ""}>
            <td className="mono">{/^[\dA-Z.]+$/.test(f.code) ? f.code : ""}</td>
            <td style={{ paddingLeft: 8 + depth * 18 }}>{f.locked && "🔒 "}{f.name}</td>
            <td className="muted small">{f.formula}{f.basis && <div>{f.basis}</div>}</td>
            <td className="num mono">{money(f.base)}</td>
            <td className="num mono">{f.rate && `${f.rate}%`}</td>
            <td className="num mono">{money(f.amount)}</td>
          </tr>
          <FeeRows fees={f.children} depth={depth + 1} />
        </Fragment>
      ))}
    </>
  );
}

function ResultTab({ unit, boq, reload }: { unit: UnitInfo; boq: Boq | null; reload: () => void }) {
  const [error, setError] = useState("");
  const run = unit.last_run;
  async function calc() {
    setError("");
    try {
      await api("POST", `/api/units/${unit.id}/calculate`);
      reload();
    } catch (e: any) {
      setError(e.message);
    }
  }
  const stale = run && boq && run.boq_version_id !== boq.version_id;
  return (
    <>
      <div className="inline">
        <button className="primary" onClick={calc} disabled={!boq}>重新计算</button>
        {run && <span className="muted">上次计算：{new Date(run.at).toLocaleString("zh-CN")}（计算快照 #{run.run_id}）</span>}
      </div>
      {error && <div className="alert error">{error}</div>}
      {!run && <p className="muted">尚未计算。所有金额由计价引擎计算得出。</p>}
      {run && (
        <>
          {stale && <div className="alert error">招标清单已更新为新版本，以下结果基于旧版清单，请重新计算。</div>}
          {run.warnings.map((w, i) => <div key={i} className="alert warn">{w}</div>)}
          <div className="card">
            <header><h4>费用汇总</h4><div className="total">合计 <b className="mono">{money(run.total)}</b> 元</div></header>
            <table>
              <thead><tr><th>序号</th><th>费用名称</th><th>计算方法与依据</th><th className="num">计算基数</th><th className="num">费率</th><th className="num">金额（元）</th></tr></thead>
              <tbody><FeeRows fees={run.fees} /></tbody>
            </table>
            <p className="muted small">🔒 表示不可竞争或招标文件给定的费用。</p>
          </div>
          {!stale && boq && (
            <div className="card">
              <h4>分部分项工程量清单计价</h4>
              <div className="scroll tall">
                <table>
                  <thead><tr><th>项目编码</th><th>项目名称</th><th>单位</th><th className="num">工程量</th><th className="num">人工</th><th className="num">材料</th><th className="num">机具</th><th className="num">管理费</th><th className="num">利润</th><th className="num">综合单价</th><th className="num">合价</th></tr></thead>
                  <tbody>
                    {run.items.map((r, i) => (
                      <tr key={i}>
                        <td className="mono">{boq.items[i]?.code}</td><td>{boq.items[i]?.name}</td><td>{boq.items[i]?.unit}</td>
                        {[r.quantity, r.labor, r.material, r.machine, r.management, r.profit, r.unit_price, r.amount].map((v, k) => (
                          <td key={k} className="num mono">{k === 0 ? v : money(v)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </>
  );
}

export function Unit({ id }: { id: number }) {
  const [unit, setUnit] = useState<UnitInfo | null>(null);
  const [boq, setBoq] = useState<Boq | null>(null);
  const [tab, setTab] = useState<Tab>("boq");
  const [error, setError] = useState("");
  async function load() {
    try {
      const u = await api<UnitInfo>("GET", `/api/units/${id}`);
      setUnit(u);
      setBoq(u.has_boq ? await api<Boq>("GET", `/api/units/${id}/boq`) : null);
    } catch (e: any) {
      setError(e.message);
    }
  }
  useEffect(() => { load(); }, [id]);
  if (error) return <div className="alert error">{error}</div>;
  if (!unit) return <p className="muted">加载中…</p>;
  const tabs: [Tab, string][] = [["boq", "招标清单"], ["pricing", "组价"], ["params", "费用参数"], ["result", "计算结果"]];
  return (
    <>
      <p className="muted small"><a href="#/projects">项目</a> / {unit.project.name}</p>
      <h2>{unit.name}</h2>
      <p className="muted">{unit.profession.name}　·　{unit.pricing_system}{unit.reference && `　·　${unit.reference.category_name}`}</p>
      <div className="tabs">
        {tabs.map(([k, label]) => <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{label}</button>)}
      </div>
      {tab === "boq" && <BoqTab unit={unit} boq={boq} reload={load} />}
      {tab === "pricing" && (boq ? <PricingTab unit={unit} boq={boq} onSaved={load} /> : <p className="muted">请先导入招标清单。</p>)}
      {tab === "params" && <ParamsTab unit={unit} reload={load} />}
      {tab === "result" && <ResultTab unit={unit} boq={boq} reload={load} />}
    </>
  );
}
