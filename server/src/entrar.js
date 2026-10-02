// Página de login: o Diogo e a Cinthia, cada um com sua senha.

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export function paginaEntrar(res, aviso, cabecalhos) {
  res.writeHead(aviso ? 401 : 200, { ...cabecalhos, "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
  res.end(`<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Casa Nova · Entrar</title><link rel="icon" href="/icone.svg">
<style>
:root{--bg:#f6f1ea;--card:#fffdf9;--ink:#2b2420;--muted:#7a6e66;--line:#e5dbd0;--accent:#b4532a;--err:#a3321f}
@media (prefers-color-scheme:dark){:root{--bg:#1c1816;--card:#26201d;--ink:#f1e9e1;--muted:#b3a69b;--line:#3b322d;--accent:#e07a4f;--err:#f08a74}}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);
  font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:16px}
form{width:100%;max-width:340px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:28px 24px}
h1{margin:0 0 4px;font-size:26px}
p{margin:0 0 20px;color:var(--muted)}
label{display:block;font-weight:600;margin:14px 0 6px}
select,input{width:100%;font:inherit;padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:var(--bg);color:var(--ink)}
button{margin-top:22px;width:100%;font:inherit;font-weight:700;padding:12px;border:0;border-radius:10px;background:var(--accent);color:#fff;cursor:pointer}
.aviso{color:var(--err);margin:12px 0 0;font-weight:600}
</style></head><body>
<form method="post" action="/entrar">
  <h1>🏡 Casa Nova</h1>
  <p>A busca da casa do Diogo e da Cinthia.</p>
  <label for="u">Quem é você?</label>
  <select id="u" name="usuario"><option value="diogo">Diogo</option><option value="cinthia">Cinthia</option></select>
  <label for="s">Senha</label>
  <input id="s" name="senha" type="password" autocomplete="current-password" required autofocus>
  ${aviso ? `<div class="aviso" role="alert">${esc(aviso)}</div>` : ""}
  <button type="submit">Entrar</button>
</form>
</body></html>`);
}
