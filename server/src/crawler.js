// Transforma o que o crawler grava (casas.json e fotos.json) nos documentos que a
// página lê da coleção "crawler": feed, fotos e textos-<imobiliária>.

const CAMPOS = ["id", "grupo", "fonte", "codigo", "link", "tipo", "preco", "condominio", "iptu", "area",
  "areaTerreno", "quartos", "suites", "banheiros", "vagas", "endereco", "bairro", "cidade", "status",
  "primeiroVisto", "historicoPreco", "temFotos", "anunciante"];

export function feedDe(j) {
  const nomes = {};
  for (const [k, v] of Object.entries(j.fontes || {})) nomes[k] = v.nome || k;
  const imoveis = Object.values(j.imoveis || {}).map((a) => {
    const o = {};
    for (const k of CAMPOS) if (a[k] != null && a[k] !== "") o[k] = a[k];
    o.fonteNome = nomes[a.fonte] || a.fonte;
    if (o.historicoPreco) o.historicoPreco = o.historicoPreco.slice(-6);
    return o;
  });
  const fontes = {};
  for (const [k, v] of Object.entries(j.fontes || {}))
    fontes[k] = { nome: v.nome, ok: v.ok, erro: v.erro || null, casas: v.casas || 0, quando: v.quando || null };
  return { ultimaRodada: j.ultimaRodada || null, rodadas: j.rodadas || 0, fontes, imoveis };
}

// a galeria é do grupo (a mesma casa em várias imobiliárias); cada anúncio aponta para ela
export function fotosDe(j, indice) {
  const capas = {}, galerias = {};
  const g = (indice && indice.galerias) || {};
  for (const [id, a] of Object.entries(j.imoveis || {})) {
    const lista = g[a.grupo || id];
    if (!lista || !lista.length) continue;
    capas[id] = "c/" + lista[0];
    galerias[id] = lista.map((n) => "f/" + n);
  }
  return { capas, galerias, geradoEm: (indice && indice.geradoEm) || null };
}

export function textosDe(j) {
  const por = {};
  for (const a of Object.values(j.imoveis || {}))
    if (a.descricao && a.status !== "saiu") (por[a.fonte] = por[a.fonte] || {})[a.id] = a.descricao;
  return por;
}
