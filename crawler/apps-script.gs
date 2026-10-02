/**
 * Casa Nova: copia o resultado do crawler (GitHub) para o seu Google Drive.
 *
 * O site do Casa Nova só consegue ler dados externos pelo conector do
 * Google Drive, então este script leva os arquivos do GitHub até o Drive:
 *   - casa-nova-casas.json   a lista de casas
 *   - casa-nova-fotos.json   o índice das fotos
 *   - pasta "Casa Nova - fotos"   as fotos (capas e galerias)
 *
 * Como instalar (uma vez só):
 *   1. Abra https://script.google.com e clique em "Novo projeto".
 *   2. Apague o que estiver no editor e cole este arquivo inteiro.
 *   3. Clique em Salvar (ícone de disquete) e dê o nome "Casa Nova".
 *   4. No menu de funções (ao lado de "Depurar"), escolha "instalar" e clique em Executar.
 *      O Google vai pedir permissão para acessar o Drive e a internet: autorize.
 *   Pronto. A função "copiar" passa a rodar sozinha a cada hora.
 */

var RAIZ = 'https://raw.githubusercontent.com/dgofreitas/casa_nova/';
var URL_DADOS = RAIZ + 'HEAD/data/casas.json';
var URL_FOTOS = RAIZ + 'fotos/';
var NOME_ARQUIVO = 'casa-nova-casas.json';
var NOME_INDICE_FOTOS = 'casa-nova-fotos.json';
var NOME_PASTA_FOTOS = 'Casa Nova - fotos';
var TEMPO_MAXIMO_MS = 4.5 * 60 * 1000; // o Google corta o script em 6 minutos

function copiar() {
  var inicio = Date.now();
  copiarCasas();
  copiarFotos(inicio);
}

function baixar(url) {
  var resp = UrlFetchApp.fetch(url + '?t=' + Date.now(), {muteHttpExceptions: true});
  if (resp.getResponseCode() !== 200) {
    console.warn(url + ' respondeu ' + resp.getResponseCode() + '; tento de novo na próxima hora.');
    return null;
  }
  return resp.getContentText('UTF-8');
}

function arquivoNaRaiz(nome) {
  var it = DriveApp.getFilesByName(nome);
  return it.hasNext() ? it.next() : null;
}

function gravar(nome, texto) {
  var arquivo = arquivoNaRaiz(nome);
  if (!arquivo) {
    DriveApp.createFile(nome, texto, 'application/json');
    return true;
  }
  if (arquivo.getBlob().getDataAsString('UTF-8') === texto) return false;
  arquivo.setContent(texto);
  return true;
}

function copiarCasas() {
  var texto = baixar(URL_DADOS);
  if (!texto) return;
  JSON.parse(texto); // se o arquivo vier quebrado, para aqui e não estraga o do Drive
  console.log(gravar(NOME_ARQUIVO, texto) ? 'Casas: Drive atualizado.' : 'Casas: nada mudou.');
}

function copiarFotos(inicio) {
  var texto = baixar(URL_FOTOS + 'indice.json');
  if (!texto) return;
  var indice = JSON.parse(texto);

  var pastas = DriveApp.getFoldersByName(NOME_PASTA_FOTOS);
  var pasta = pastas.hasNext() ? pastas.next() : DriveApp.createFolder(NOME_PASTA_FOTOS);

  // o que já está no Drive (nome do arquivo = caminho no GitHub com "__" no lugar de "/")
  var noDrive = {};
  var it = pasta.getFiles();
  while (it.hasNext()) {
    var f = it.next();
    noDrive[f.getName()] = f;
  }

  var precisa = {};
  Object.keys(indice.capas || {}).forEach(function (k) { precisa[indice.capas[k]] = true; });
  Object.keys(indice.galerias || {}).forEach(function (k) { precisa[indice.galerias[k]] = true; });

  var novos = 0, faltam = 0;
  Object.keys(precisa).forEach(function (caminho) {
    var nome = caminho.replace(/\//g, '__');
    if (noDrive[nome]) return;
    if (Date.now() - inicio > TEMPO_MAXIMO_MS) { faltam++; return; }
    var conteudo = baixar(URL_FOTOS + caminho);
    if (!conteudo) { faltam++; return; }
    noDrive[nome] = pasta.createFile(nome, conteudo, 'application/json');
    novos++;
  });

  // apaga o que o crawler não acompanha mais
  var apagados = 0;
  Object.keys(noDrive).forEach(function (nome) {
    if (!precisa[nome.replace(/__/g, '/')]) { noDrive[nome].setTrashed(true); delete noDrive[nome]; apagados++; }
  });

  // índice para o site: só aponta para arquivos que já estão no Drive
  var arquivos = {};
  Object.keys(precisa).forEach(function (caminho) {
    var f = noDrive[caminho.replace(/\//g, '__')];
    if (f) arquivos[caminho] = f.getId();
  });
  var filtra = function (mapa) {
    var out = {};
    Object.keys(mapa || {}).forEach(function (id) { if (arquivos[mapa[id]]) out[id] = mapa[id]; });
    return out;
  };
  var paraSite = {geradoEm: indice.geradoEm, arquivos: arquivos,
                  capas: filtra(indice.capas), galerias: filtra(indice.galerias)};
  gravar(NOME_INDICE_FOTOS, JSON.stringify(paraSite));
  console.log('Fotos: ' + novos + ' arquivos novos, ' + apagados + ' apagados' +
              (faltam ? ', ' + faltam + ' ficam para a próxima hora.' : '.'));
}

function instalar() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'copiar') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('copiar').timeBased().everyHours(1).create();
  copiar();
  console.log('Instalado: a cópia roda sozinha a cada hora.');
}
