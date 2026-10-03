// Casa Nova: servidor do site.
//
// Serve a página (site/casa-nova.html), guarda os dados num SQLite e entrega o que
// o crawler deixa na pasta de dados (casas.json, fotos.json e as fotos).
// A página foi feita para rodar dentro do Claude; o arquivo public/shim.js
// recria as funções que ela usa de lá (banco, arquivos, usuário, download)
// chamando a API daqui.
//
// Variáveis de ambiente:
//   PORT            porta HTTP (padrão 3000)
//   CASA_NOVA_DADOS pasta de dados, compartilhada com o crawler (padrão /dados)
//   SENHA_DIOGO, SENHA_CINTHIA   senhas de cada um (usuário sem senha não entra)
//   SEGREDO_SESSAO  chave das sessões (se faltar, é gerada e guardada nos dados)

import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { feedDe, fotosDe, textosDe } from "./crawler.js";
import { paginaEntrar } from "./entrar.js";

const AQUI = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.PORT || 3000);
const DADOS = process.env.CASA_NOVA_DADOS || "/dados";
const SITE = process.env.CASA_NOVA_SITE_HTML || path.join(AQUI, "..", "..", "site", "casa-nova.html");
const PUBLICO = path.join(AQUI, "..", "public");
const ARQUIVOS = path.join(DADOS, "arquivos");
const FOTOS = path.join(DADOS, "fotos");
const GUARDADAS = path.join(DADOS, "guardadas"); // fotos do crawler usadas em Imóveis
const PEDIDO = path.join(DADOS, "pedido-busca");

const USUARIOS = {
  diogo: { nome: "Diogo", senha: process.env.SENHA_DIOGO || "" },
  cinthia: { nome: "Cinthia", senha: process.env.SENHA_CINTHIA || "" },
};
const ADMIN = "diogo";
const SESSAO_DIAS = 180;
const MAX_DOC = 2 * 1024 * 1024;
const MAX_ARQUIVO = 25 * 1024 * 1024;
const TIPOS_ARQUIVO = {
  "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif",
  "image/heic": ".heic", "image/heif": ".heif", "application/pdf": ".pdf",
};

for (const p of [DADOS, ARQUIVOS, GUARDADAS, path.join(GUARDADAS, "c")]) fs.mkdirSync(p, { recursive: true });

// ---------- sessão ----------
function segredo() {
  if (process.env.SEGREDO_SESSAO) return process.env.SEGREDO_SESSAO;
  const arq = path.join(DADOS, "segredo-sessao");
  if (!fs.existsSync(arq)) fs.writeFileSync(arq, crypto.randomBytes(32).toString("hex"), { mode: 0o600 });
  return fs.readFileSync(arq, "utf8").trim();
}
const SEGREDO = segredo();
const assinar = (s) => crypto.createHmac("sha256", SEGREDO).update(s).digest("base64url");
function cookieSessao(usuario) {
  const corpo = Buffer.from(`${usuario}|${Date.now() + SESSAO_DIAS * 864e5}`).toString("base64url");
  return `${corpo}.${assinar(corpo)}`;
}
function quemE(req) {
  const m = /(?:^|;\s*)cn=([^;]+)/.exec(req.headers.cookie || "");
  if (!m) return null;
  const [corpo, ass] = m[1].split(".");
  if (!corpo || !ass) return null;
  const a = Buffer.from(ass), b = Buffer.from(assinar(corpo));
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  const [usuario, exp] = Buffer.from(corpo, "base64url").toString().split("|");
  if (!USUARIOS[usuario] || !USUARIOS[usuario].senha || Number(exp) < Date.now()) return null;
  return usuario;
}
function senhaConfere(usuario, senha) {
  const u = USUARIOS[usuario];
  if (!u || !u.senha) return false;
  const a = crypto.createHash("sha256").update(String(senha)).digest();
  const b = crypto.createHash("sha256").update(u.senha).digest();
  return crypto.timingSafeEqual(a, b);
}
const tentativas = new Map(); // ip -> [horários das tentativas erradas]
function bloqueado(ip) {
  const t = (tentativas.get(ip) || []).filter((x) => x > Date.now() - 15 * 60e3);
  tentativas.set(ip, t);
  return t.length >= 8;
}

// ---------- banco ----------
const db = new DatabaseSync(path.join(DADOS, "casa-nova.db"));
db.exec(`PRAGMA journal_mode = WAL;
  CREATE TABLE IF NOT EXISTS docs (coll TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL,
    atualizado TEXT NOT NULL, por TEXT, PRIMARY KEY (coll, id));
  CREATE TABLE IF NOT EXISTS arquivos (id TEXT PRIMARY KEY, tipo TEXT NOT NULL, tamanho INTEGER NOT NULL,
    criado TEXT NOT NULL, por TEXT);`);
const sql = {
  lista: db.prepare("SELECT id, data FROM docs WHERE coll = ?"),
  um: db.prepare("SELECT data FROM docs WHERE coll = ? AND id = ?"),
  grava: db.prepare(`INSERT INTO docs (coll, id, data, atualizado, por) VALUES (?, ?, ?, ?, ?)
    ON CONFLICT (coll, id) DO UPDATE SET data = excluded.data, atualizado = excluded.atualizado, por = excluded.por`),
  apaga: db.prepare("DELETE FROM docs WHERE coll = ? AND id = ?"),
  arquivo: db.prepare("SELECT tipo FROM arquivos WHERE id = ?"),
  novoArquivo: db.prepare("INSERT OR REPLACE INTO arquivos (id, tipo, tamanho, criado, por) VALUES (?, ?, ?, ?, ?)"),
  apagaArquivo: db.prepare("DELETE FROM arquivos WHERE id = ?"),
};

// caminho "a/b/c" -> coleção "a/b", id "c" (igual ao banco do Claude)
function separar(p) {
  const partes = String(p || "").split("/").filter(Boolean);
  if (partes.length < 2 || partes.some((x) => x === "." || x === ".." || x.length > 200)) return null;
  return { coll: partes.slice(0, -1).join("/"), id: partes.at(-1) };
}

// ---------- o que vem do crawler (coleção "crawler", só leitura) ----------
const cache = new Map();
function lerJSON(nome) {
  const arq = path.join(DADOS, nome);
  let st;
  try { st = fs.statSync(arq); } catch { return null; }
  const c = cache.get(nome);
  if (c && c.mtime === st.mtimeMs) return c.valor;
  try {
    const valor = JSON.parse(fs.readFileSync(arq, "utf8"));
    cache.set(nome, { mtime: st.mtimeMs, valor });
    return valor;
  } catch { return c ? c.valor : null; }
}
function docsCrawler() {
  const casas = lerJSON("casas.json");
  const docs = {};
  const status = lerJSON("crawler-status.json");
  if (status) docs.status = status;
  if (!casas) return docs;
  docs.feed = feedDe(casas);
  docs.fotos = fotosDe(casas, lerJSON("fotos.json"));
  for (const [fonte, textos] of Object.entries(textosDe(casas))) docs["textos-" + fonte] = { textos, rodada: casas.ultimaRodada || null };
  return docs;
}

// ---------- avisos em tempo real (SSE) ----------
const ouvintes = new Set();
function avisar(coll) {
  const msg = `data: ${JSON.stringify({ c: coll })}\n\n`;
  for (const res of ouvintes) res.write(msg);
}
// mudou só um documento: a página busca só ele
function avisarDoc(coll, id) {
  const msg = `data: ${JSON.stringify({ c: coll, id })}\n\n`;
  for (const res of ouvintes) res.write(msg);
}
// fotos dos anúncios dos imóveis, lidas pelo crawler (crawler/fotos_imoveis.py): junta no imóvel
let marcaFotosImoveis = 0;
function aplicarFotosImoveis() {
  let st;
  try { st = fs.statSync(path.join(DADOS, "fotos-imoveis.json")); } catch { return; }
  if (st.mtimeMs === marcaFotosImoveis) return;
  marcaFotosImoveis = st.mtimeMs;
  let r;
  try { r = JSON.parse(fs.readFileSync(path.join(DADOS, "fotos-imoveis.json"), "utf8")); } catch { return; }
  let mudou = false;
  for (const [id, res] of Object.entries(r.resultados || {})) {
    const x = sql.um.get("imoveis", id);
    if (!x) continue;
    const d = JSON.parse(x.data);
    if ((d.link || "").trim() !== res.link) continue; // o link mudou depois: o crawler lê de novo
    if (d.fotosAnuncio && d.fotosAnuncio.link === res.link) continue; // já aplicado
    const atuais = Array.isArray(d.fotos) ? d.fotos : [];
    d.fotos = atuais.concat((res.novas || []).filter((f) => !atuais.includes(f)));
    if (res.texto && !d.anuncioTexto) d.anuncioTexto = String(res.texto).slice(0, 20000);
    d.fotosAnuncio = { link: res.link, em: res.em, novas: (res.novas || []).length, ...(res.erro ? { erro: res.erro } : {}) };
    sql.grava.run("imoveis", id, JSON.stringify(d), new Date().toISOString(), "crawler");
    mudou = true;
  }
  if (mudou) avisar("imoveis");
}
setInterval(aplicarFotosImoveis, 5000);

// o que o crawler grava: lista e fotos mudam pouco; o andamento muda a cada poucos segundos
// e vai num aviso só dele, para a página não baixar a lista inteira de novo
const marca = (n) => { try { return fs.statSync(path.join(DADOS, n)).mtimeMs; } catch { return 0; } };
let marcaCrawler = null, marcaStatus = null;
setInterval(() => {
  const m = marca("casas.json") + "," + marca("fotos.json"), st = marca("crawler-status.json");
  if (marcaCrawler !== null && m !== marcaCrawler) avisar("crawler");
  else if (marcaStatus !== null && st !== marcaStatus) avisarDoc("crawler", "status");
  marcaCrawler = m; marcaStatus = st;
}, 3000);
setInterval(() => { for (const res of ouvintes) res.write(": ping\n\n"); }, 15000);

// ---------- respostas ----------
const SEGURANCA = { "X-Content-Type-Options": "nosniff", "Referrer-Policy": "same-origin", "X-Frame-Options": "DENY" };
function json(res, status, corpo) {
  res.writeHead(status, { ...SEGURANCA, "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" });
  res.end(JSON.stringify(corpo));
}
function erro(res, status, code, message) { json(res, status, { code, message }); }
function lerCorpo(req, limite) {
  return new Promise((ok, falha) => {
    const partes = []; let n = 0;
    req.on("data", (c) => { n += c.length; if (n > limite) { falha({ status: 413 }); req.destroy(); } else partes.push(c); });
    req.on("end", () => ok(Buffer.concat(partes)));
    req.on("error", falha);
  });
}
function arquivoEstatico(res, arq, tipo, extra = {}) {
  fs.stat(arq, (e, st) => {
    if (e || !st.isFile()) { res.writeHead(404, SEGURANCA); return res.end(); }
    res.writeHead(200, { ...SEGURANCA, "Content-Type": tipo, "Content-Length": st.size, ...extra });
    fs.createReadStream(arq).pipe(res);
  });
}

let paginaCache = { mtime: 0, html: "" };
function pagina() {
  const st = fs.statSync(SITE);
  if (st.mtimeMs !== paginaCache.mtime) {
    const corpo = fs.readFileSync(SITE, "utf8");
    paginaCache = { mtime: st.mtimeMs, html: `<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="/icone.svg"><script src="/shim.js"></script></head><body>
${corpo}
</body></html>` };
  }
  return paginaCache.html;
}

// imóvel que usa foto do crawler: guarda uma cópia, para ela não sumir quando o anúncio sair do ar
function guardarFotos(data) {
  for (const f of (data && Array.isArray(data.fotos) ? data.fotos : [])) {
    const m = /^f\/([0-9a-f]{20})$/.exec(f);
    if (!m) continue;
    for (const sub of ["", "c"]) {
      const de = path.join(FOTOS, sub, m[1] + ".jpg"), para = path.join(GUARDADAS, sub, m[1] + ".jpg");
      if (!fs.existsSync(para) && fs.existsSync(de)) fs.copyFileSync(de, para);
    }
  }
}

// ---------- rotas ----------
async function api(req, res, url, usuario) {
  const r = url.pathname;
  if (r === "/api/eu") return json(res, 200, { id: usuario, nome: USUARIOS[usuario].nome, admin: usuario === ADMIN });
  if (r === "/api/perfis") {
    const ids = (url.searchParams.get("ids") || "").split(",").filter(Boolean);
    return json(res, 200, Object.fromEntries(ids.map((id) => [id, USUARIOS[id] ? { id, name: USUARIOS[id].nome, isMe: id === usuario } : null])));
  }
  if (r === "/api/colecao" && req.method === "GET") {
    const c = url.searchParams.get("c") || "";
    if (c === "crawler") return json(res, 200, { docs: Object.entries(docsCrawler()).map(([id, data]) => ({ id, data })) });
    return json(res, 200, { docs: sql.lista.all(c).map((x) => ({ id: x.id, data: JSON.parse(x.data) })) });
  }
  if (r === "/api/doc") {
    const p = separar(url.searchParams.get("p"));
    if (!p) return erro(res, 400, "invalid_argument", "caminho inválido");
    if (p.coll === "crawler") {
      if (req.method === "GET") { const d = docsCrawler()[p.id]; return json(res, 200, { exists: !!d, data: d || null }); }
      return json(res, 200, { ok: true }); // o que vem do crawler não se edita pelo site
    }
    if (req.method === "GET") { const x = sql.um.get(p.coll, p.id); return json(res, 200, { exists: !!x, data: x ? JSON.parse(x.data) : null }); }
    if (req.method === "PUT") {
      let data;
      try { data = JSON.parse((await lerCorpo(req, MAX_DOC)).toString("utf8")); }
      catch (e) { return e && e.status === 413 ? erro(res, 413, "too_large", "documento grande demais") : erro(res, 400, "invalid_argument", "JSON inválido"); }
      if (p.coll === "imoveis") guardarFotos(data);
      sql.grava.run(p.coll, p.id, JSON.stringify(data), new Date().toISOString(), usuario);
      avisar(p.coll);
      return json(res, 200, { ok: true });
    }
    if (req.method === "DELETE") { sql.apaga.run(p.coll, p.id); avisar(p.coll); return json(res, 200, { ok: true }); }
  }
  if (r === "/api/eventos") {
    res.writeHead(200, { ...SEGURANCA, "Content-Type": "text/event-stream", "Cache-Control": "no-store", "X-Accel-Buffering": "no" });
    res.write(": oi\n\n");
    ouvintes.add(res);
    req.on("close", () => ouvintes.delete(res));
    return;
  }
  if (r === "/api/arquivos" && req.method === "POST") {
    const tipo = String(req.headers["content-type"] || "").split(";")[0].trim().toLowerCase();
    if (!TIPOS_ARQUIVO[tipo]) return erro(res, 415, "unsupported_type", "formato não aceito");
    let corpo;
    try { corpo = await lerCorpo(req, MAX_ARQUIVO); } catch { return erro(res, 413, "too_large", "arquivo grande demais"); }
    const id = crypto.randomBytes(16).toString("hex");
    fs.writeFileSync(path.join(ARQUIVOS, id), corpo);
    sql.novoArquivo.run(id, tipo, corpo.length, new Date().toISOString(), usuario);
    return json(res, 200, { id, url: "/_blob/" + id });
  }
  const mArq = /^\/api\/arquivos\/([0-9a-f]{32})$/.exec(r);
  if (mArq && req.method === "DELETE") {
    fs.rmSync(path.join(ARQUIVOS, mArq[1]), { force: true });
    sql.apagaArquivo.run(mArq[1]);
    return json(res, 200, { ok: true });
  }
  if (r === "/api/buscar" && req.method === "POST") {
    fs.writeFileSync(PEDIDO, new Date().toISOString());
    return json(res, 200, { ok: true });
  }
  if (r === "/api/importar" && req.method === "POST") {
    if (usuario !== ADMIN) return erro(res, 403, "not_granted", "só o Diogo pode importar");
    let b;
    try { b = JSON.parse((await lerCorpo(req, 400 * 1024 * 1024)).toString("utf8")); }
    catch { return erro(res, 400, "invalid_argument", "arquivo de importação inválido"); }
    return json(res, 200, importar(b, usuario));
  }
  return erro(res, 404, "not_found", "rota desconhecida");
}

// backup do site antigo: {docs: {"coll/id": data}, arquivos: {id: {tipo, b64}}, usuarios: {uidAntigo: "diogo"}}
function importar(b, usuario) {
  const troca = b.usuarios || {};
  const trocar = (s) => Object.entries(troca).reduce((t, [de, para]) => t.split(de).join(para), s);
  let docs = 0, arquivos = 0;
  db.exec("BEGIN");
  try {
    for (const [caminho, data] of Object.entries(b.docs || {})) {
      const p = separar(trocar(caminho));
      if (!p || p.coll === "crawler") continue;
      sql.grava.run(p.coll, p.id, trocar(JSON.stringify(data)), new Date().toISOString(), usuario);
      docs++;
    }
    for (const [id, a] of Object.entries(b.arquivos || {})) {
      if (!/^[0-9a-f]{32}$/.test(id) || !TIPOS_ARQUIVO[a.tipo]) continue;
      const bytes = Buffer.from(a.b64, "base64");
      fs.writeFileSync(path.join(ARQUIVOS, id), bytes);
      sql.novoArquivo.run(id, a.tipo, bytes.length, new Date().toISOString(), usuario);
      arquivos++;
    }
    db.exec("COMMIT");
  } catch (e) { db.exec("ROLLBACK"); throw e; }
  for (const c of new Set(Object.keys(b.docs || {}).map((k) => (separar(trocar(k)) || {}).coll))) if (c) avisar(c);
  return { ok: true, docs, arquivos };
}

function blob(res, id) {
  const m = /^(f|c)\/([0-9a-f]{20})$/.exec(id);
  const cache = { "Cache-Control": "private, max-age=31536000, immutable" };
  if (m) {
    const sub = m[1] === "c" ? "c" : "";
    const arq = path.join(FOTOS, sub, m[2] + ".jpg");
    return arquivoEstatico(res, fs.existsSync(arq) ? arq : path.join(GUARDADAS, sub, m[2] + ".jpg"), "image/jpeg", cache);
  }
  if (!/^[0-9a-f]{32}$/.test(id)) { res.writeHead(404, SEGURANCA); return res.end(); }
  const x = sql.arquivo.get(id);
  if (!x) { res.writeHead(404, SEGURANCA); return res.end(); }
  // arquivo enviado por alguém: nunca roda como página
  arquivoEstatico(res, path.join(ARQUIVOS, id), x.tipo, { ...cache, "Content-Security-Policy": "sandbox" });
}

const servidor = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://x");
    const r = url.pathname;
    if (r === "/saude") return json(res, 200, { ok: true });
    if (r === "/icone.svg") return arquivoEstatico(res, path.join(PUBLICO, "icone.svg"), "image/svg+xml", { "Cache-Control": "public, max-age=86400" });
    const https = req.headers["x-forwarded-proto"] === "https";
    if (r === "/entrar") {
      const ip = String(req.headers["x-forwarded-for"] || req.socket.remoteAddress || "").split(",")[0].trim();
      if (req.method === "POST") {
        const f = new URLSearchParams((await lerCorpo(req, 10000)).toString());
        const usuario = String(f.get("usuario") || "").toLowerCase();
        if (bloqueado(ip)) return paginaEntrar(res, "Muitas tentativas. Espere 15 minutos.", SEGURANCA);
        if (!senhaConfere(usuario, f.get("senha") || "")) {
          tentativas.get(ip).push(Date.now());
          return paginaEntrar(res, "Usuário ou senha errados.", SEGURANCA);
        }
        res.writeHead(303, { ...SEGURANCA, Location: "/", "Set-Cookie":
          `cn=${cookieSessao(usuario)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${SESSAO_DIAS * 86400}${https ? "; Secure" : ""}` });
        return res.end();
      }
      return paginaEntrar(res, "", SEGURANCA);
    }
    if (r === "/sair") {
      res.writeHead(303, { ...SEGURANCA, Location: "/entrar", "Set-Cookie": "cn=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" });
      return res.end();
    }
    const usuario = quemE(req);
    if (!usuario) {
      if (r.startsWith("/api/") || r.startsWith("/_blob/")) return erro(res, 401, "revoked", "faça login de novo");
      res.writeHead(303, { ...SEGURANCA, Location: "/entrar" });
      return res.end();
    }
    if (r.startsWith("/api/")) {
      // pedidos que mudam dados só valem vindos do próprio site
      if (req.method !== "GET" && req.headers["sec-fetch-site"] && req.headers["sec-fetch-site"] !== "same-origin")
        return erro(res, 403, "not_granted", "origem não permitida");
      return await api(req, res, url, usuario);
    }
    if (r.startsWith("/_blob/")) return blob(res, r.slice(7));
    if (r === "/shim.js") return arquivoEstatico(res, path.join(PUBLICO, "shim.js"), "text/javascript; charset=utf-8", { "Cache-Control": "no-cache" });
    if (r === "/" || r === "/index.html") {
      res.writeHead(200, { ...SEGURANCA, "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-cache" });
      return res.end(pagina());
    }
    res.writeHead(404, SEGURANCA); res.end();
  } catch (e) {
    console.error(e);
    if (!res.headersSent) erro(res, 500, "internal", "erro no servidor");
    else res.end();
  }
});
servidor.requestTimeout = 0; // envios grandes e o canal de avisos ficam abertos
servidor.listen(PORT, () => {
  const sem = Object.entries(USUARIOS).filter(([, u]) => !u.senha).map(([k]) => k);
  console.log(`Casa Nova na porta ${PORT}, dados em ${DADOS}` + (sem.length ? ` (sem senha, não entram: ${sem.join(", ")})` : ""));
});
