import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Cpu, Settings2 } from "lucide-react";
import { api } from "../api.js";

export const PROVIDER_COLORS = {
  ollama: "#0ea5e9", openai: "#10a37f", openrouter: "#8b5cf6", groq: "#f97316",
  together: "#2563eb", vllm: "#db2777", lmstudio: "#64748b", custom: "#475569",
};

export default function ModelSwitcher({ status, onChanged, compact }) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState("");
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    api.settings().then(setSettings).catch((e) => setError(e.message));
    const close = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const pick = async (id) => {
    try {
      await api.setActive(id);
      setOpen(false);
      onChanged?.();
    } catch (e) {
      setError(e.message);
    }
  };

  const model = status?.model;
  return (
    <div className="switcher" ref={ref}>
      <button className="switcher-btn" onClick={() => setOpen(!open)}>
        <span className="dot" style={{ background: PROVIDER_COLORS[model?.provider] || "#64748b" }} />
        <span className="switcher-label">{compact ? model?.model : model?.name || "Model"}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="menu">
          <div className="menu-title"><Cpu size={13} /> Answer with</div>
          {error && <p className="banner-error small">{error}</p>}
          {settings?.profiles.map((p) => (
            <button key={p.id} className="menu-item" onClick={() => pick(p.id)}>
              <span className="dot" style={{ background: PROVIDER_COLORS[p.provider] || "#64748b" }} />
              <span className="menu-text">
                <strong>{p.name}</strong>
                <small>{p.model} · {p.base_url.replace(/^https?:\/\//, "")}</small>
              </span>
              {p.id === settings.active_profile && <Check size={15} />}
            </button>
          ))}
          <a className="menu-item foot" href="/settings"><Settings2 size={14} /> Manage models</a>
        </div>
      )}
    </div>
  );
}
