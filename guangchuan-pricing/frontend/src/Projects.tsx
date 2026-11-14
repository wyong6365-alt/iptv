import { useEffect, useState } from "react";
import { api, Profession } from "./api";

interface Project { id: number; name: string; units: { id: number; name: string; pricing_system: string }[] }

function NewUnit({ projectId, professions, onDone }: { projectId: number; professions: Profession[]; onDone: () => void }) {
  const [name, setName] = useState("");
  const [profession, setProfession] = useState(professions[0].code);
  const [subcategory, setSubcategory] = useState("");
  const [category, setCategory] = useState("");
  const [grade, setGrade] = useState("");
  const [error, setError] = useState("");
  const prof = professions.find((p) => p.code === profession)!;
  const cat = prof.fee_categories.find((c) => c.code === category);
  const manual = prof.pricing_system.engine === "manual";
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const unit = await api("POST", `/api/projects/${projectId}/units`, {
        name, profession, subcategory: subcategory || null,
        fee_category: manual ? null : category || null, grade: cat?.graded ? grade || null : null,
      });
      onDone();
      location.hash = `#/unit/${unit.id}`;
    } catch (err: any) {
      setError(err.message);
    }
  }
  return (
    <form className="card form" onSubmit={submit}>
      <h4>新建单位工程</h4>
      <div className="grid">
        <label>单位工程名称<input value={name} onChange={(e) => setName(e.target.value)} required /></label>
        <label>专业
          <select value={profession} onChange={(e) => { setProfession(e.target.value); setSubcategory(""); setCategory(""); setGrade(""); }}>
            {professions.map((p) => <option key={p.code} value={p.code}>{p.name}</option>)}
          </select>
        </label>
        <label>子专业（可选）
          <select value={subcategory} onChange={(e) => setSubcategory(e.target.value)}>
            <option value="">不指定</option>
            {prof.subcategories.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
          </select>
        </label>
        {!manual && (
          <label>费用规则工程类别
            <select value={category} onChange={(e) => setCategory(e.target.value)} required>
              <option value="">请选择</option>
              {prof.fee_categories.map((c) => <option key={c.code} value={c.code}>{c.name}</option>)}
            </select>
          </label>
        )}
        {cat?.graded && (
          <label>工程类别
            <select value={grade} onChange={(e) => setGrade(e.target.value)} required>
              <option value="">请选择</option><option>I</option><option>II</option><option>III</option>
            </select>
          </label>
        )}
      </div>
      <p className="muted">计价体系：{prof.pricing_system.name}</p>
      {manual && <div className="alert warn">该计价体系的计价规则和定额尚未录入。本单位工程只能人工组价，费率由人工输入，结果会标注“非规则依据”。</div>}
      {error && <div className="alert error">{error}</div>}
      <button className="primary">创建</button>
    </form>
  );
}

export function Projects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [professions, setProfessions] = useState<Profession[]>([]);
  const [name, setName] = useState("");
  const [adding, setAdding] = useState<number | null>(null);
  const [error, setError] = useState("");
  const load = () => api("GET", "/api/projects").then(setProjects).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    api("GET", "/api/professions").then(setProfessions).catch(() => {});
  }, []);
  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await api("POST", "/api/projects", { name });
      setName("");
      load();
    } catch (err: any) {
      setError(err.message);
    }
  }
  return (
    <>
      <h2>项目</h2>
      <form className="inline" onSubmit={create}>
        <input placeholder="新项目名称" value={name} onChange={(e) => setName(e.target.value)} required />
        <button className="primary">新建项目</button>
      </form>
      {error && <div className="alert error">{error}</div>}
      {projects.length === 0 && <p className="muted">还没有项目。先新建项目，再在项目下按专业建立单位工程。</p>}
      {projects.map((p) => (
        <section className="card" key={p.id}>
          <header>
            <h3>{p.name}</h3>
            <button onClick={() => setAdding(adding === p.id ? null : p.id)}>{adding === p.id ? "取消" : "添加单位工程"}</button>
          </header>
          {p.units.length === 0 && adding !== p.id && <p className="muted">暂无单位工程</p>}
          <ul className="units">
            {p.units.map((u) => (
              <li key={u.id}><a href={`#/unit/${u.id}`}>{u.name}</a><span className="muted">{u.pricing_system}</span></li>
            ))}
          </ul>
          {adding === p.id && professions.length > 0 && (
            <NewUnit projectId={p.id} professions={professions} onDone={() => { setAdding(null); load(); }} />
          )}
        </section>
      ))}
    </>
  );
}
