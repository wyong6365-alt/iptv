import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, getToken, setToken } from "./api";
import { Capabilities } from "./Capabilities";
import { Projects } from "./Projects";
import { Unit } from "./Unit";
import "./styles.css";

function useHash(): string {
  const [hash, setHash] = useState(location.hash || "#/projects");
  useEffect(() => {
    const on = () => setHash(location.hash || "#/projects");
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return hash;
}

function Login({ onDone }: { onDone: () => void }) {
  const [initialized, setInitialized] = useState<boolean | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    api("GET", "/api/auth/status").then((s) => setInitialized(s.initialized)).catch((e) => setError(e.message));
  }, []);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      const r = await api("POST", initialized ? "/api/auth/login" : "/api/auth/setup", { username, password });
      setToken(r.token);
      onDone();
    } catch (err: any) {
      setError(err.message);
    }
  }
  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <h1>广川AI智能组价平台</h1>
        <p className="muted">
          {initialized === false ? "首次使用，请创建管理员账号（密码不少于 8 位）" : "请登录"}
        </p>
        <label>用户名<input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus /></label>
        <label>密码<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <div className="alert error">{error}</div>}
        <button className="primary" disabled={initialized === null}>
          {initialized === false ? "创建管理员并进入" : "登录"}
        </button>
      </form>
    </div>
  );
}

function App() {
  const [authed, setAuthed] = useState(Boolean(getToken()));
  const hash = useHash();
  useEffect(() => {
    if (authed) api("GET", "/api/professions").catch((e) => e.status === 401 && logout());
  }, [authed]);
  function logout() {
    setToken("");
    setAuthed(false);
  }
  if (!authed) return <Login onDone={() => setAuthed(true)} />;
  const unit = hash.match(/^#\/unit\/(\d+)/);
  return (
    <div className="shell">
      <nav>
        <div className="brand">广川AI智能组价平台<small>V1.0 开发版</small></div>
        <a href="#/projects" className={hash.startsWith("#/projects") || unit ? "on" : ""}>项目</a>
        <a href="#/capabilities" className={hash.startsWith("#/capabilities") ? "on" : ""}>专业能力中心</a>
        <button className="link" onClick={logout}>退出登录</button>
      </nav>
      <main>
        {unit ? <Unit key={unit[1]} id={Number(unit[1])} /> : hash.startsWith("#/capabilities") ? <Capabilities /> : <Projects />}
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
