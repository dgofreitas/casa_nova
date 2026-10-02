// Recria, sobre a API do servidor, as funções do Claude que a página usa:
// db (documentos e coleções ao vivo), assets (arquivos), user, downloads.
// IA (sample) e conectores (mcp) não existem aqui: a página já sabe viver sem eles.
(function () {
  "use strict";
  window.CASA_NOVA_SERVIDOR = true;

  function sair() { location.href = "/entrar"; }
  async function api(metodo, url, corpo, tipo) {
    const op = { method: metodo, headers: {}, credentials: "same-origin" };
    if (corpo !== undefined) {
      op.body = corpo;
      op.headers["Content-Type"] = tipo || "application/json";
    }
    let r;
    try { r = await fetch(url, op); } catch (e) { throw { code: "unavailable", message: "sem conexão" }; }
    if (r.status === 401) { sair(); throw { code: "revoked", message: "sessão expirou" }; }
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw { code: j.code || "internal", message: j.message || "erro " + r.status };
    return j;
  }

  // ---- avisos de mudança: um canal só para a página toda ----
  const assinaturas = new Map(); // coleção -> Set de funções que recarregam
  let canal = null;
  function abrirCanal() {
    if (canal) return;
    canal = new EventSource("/api/eventos");
    let caiu = false;
    canal.onmessage = (e) => {
      let m; try { m = JSON.parse(e.data); } catch (x) { return; }
      (assinaturas.get(m.c) || []).forEach((f) => f());
    };
    canal.onerror = () => { caiu = true; };
    // voltou depois de cair (celular dormiu, rede trocou): recarrega tudo
    canal.onopen = () => { if (caiu) { caiu = false; assinaturas.forEach((s) => s.forEach((f) => f())); } };
  }
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") assinaturas.forEach((s) => s.forEach((f) => f()));
  });

  const db = {
    doc(caminho) {
      const q = "/api/doc?p=" + encodeURIComponent(caminho);
      return {
        set: (data) => api("PUT", q, JSON.stringify(data)).then(() => undefined),
        get: async () => { const j = await api("GET", q); return { exists: j.exists, data: () => j.data }; },
        delete: () => api("DELETE", q).then(() => undefined),
      };
    },
    collection(coll) {
      return {
        onSnapshot(cb, onErr) {
          let ativo = true, versao = 0;
          const carregar = async () => {
            const v = ++versao;
            try {
              const j = await api("GET", "/api/colecao?c=" + encodeURIComponent(coll));
              if (!ativo || v !== versao) return;
              cb({ docs: j.docs.map((d) => ({ id: d.id, data: () => d.data })) });
            } catch (e) { if (ativo && onErr) onErr(e); }
          };
          if (!assinaturas.has(coll)) assinaturas.set(coll, new Set());
          assinaturas.get(coll).add(carregar);
          abrirCanal();
          carregar();
          return () => { ativo = false; assinaturas.get(coll).delete(carregar); };
        },
      };
    },
  };

  const assets = {
    async upload(arquivo) {
      const tipo = arquivo.type || "application/octet-stream";
      const r = await fetch("/api/arquivos", { method: "POST", body: arquivo, headers: { "Content-Type": tipo }, credentials: "same-origin" });
      if (r.status === 401) { sair(); throw { code: "revoked" }; }
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw { code: j.code || "internal", message: j.message };
      return j;
    },
    delete: (id) => api("DELETE", "/api/arquivos/" + encodeURIComponent(id)).then(() => undefined),
  };

  let eu = null;
  const quem = () => (eu = eu || api("GET", "/api/eu"));
  const user = {
    id: async () => (await quem()).id,
    can: async () => true,
    profiles: (ids) => api("GET", "/api/perfis?ids=" + encodeURIComponent([].concat(ids).join(","))),
  };

  const downloads = {
    async save({ filename, data }) {
      const b = data instanceof Blob ? data : new Blob([data], { type: "application/octet-stream" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(b);
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    },
  };

  const servidor = {
    buscarAgora: () => api("POST", "/api/buscar", "{}"),
    quem,
    importar: (corpo) => api("POST", "/api/importar", corpo),
  };

  const recursos = { db, assets, user, downloads, servidor };
  window.claude = {
    use: async (nome) => {
      if (recursos[nome]) return recursos[nome];
      throw { code: "not_granted" };
    },
  };
})();
