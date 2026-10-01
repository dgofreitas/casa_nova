/**
 * Casa Nova: copia o resultado do crawler (GitHub) para o seu Google Drive.
 *
 * O site do Casa Nova só consegue ler dados externos pelo conector do
 * Google Drive, então este script leva o arquivo do GitHub até o Drive.
 *
 * Como instalar (uma vez só):
 *   1. Abra https://script.google.com e clique em "Novo projeto".
 *   2. Apague o que estiver no editor e cole este arquivo inteiro.
 *   3. Clique em Salvar (ícone de disquete) e dê o nome "Casa Nova".
 *   4. No menu de funções (ao lado de "Depurar"), escolha "instalar" e clique em Executar.
 *      O Google vai pedir permissão para acessar o Drive e a internet: autorize.
 *   Pronto. A função "copiar" passa a rodar sozinha a cada hora.
 */

var URL_DADOS = 'https://raw.githubusercontent.com/dgofreitas/casa_nova/HEAD/data/casas.json';
var NOME_ARQUIVO = 'casa-nova-casas.json';

function copiar() {
  var resp = UrlFetchApp.fetch(URL_DADOS + '?t=' + Date.now(), {muteHttpExceptions: true});
  if (resp.getResponseCode() !== 200) {
    console.warn('GitHub respondeu ' + resp.getResponseCode() + '; tento de novo na próxima hora.');
    return;
  }
  var texto = resp.getContentText('UTF-8');
  JSON.parse(texto); // se o arquivo vier quebrado, para aqui e não estraga o do Drive

  var arquivos = DriveApp.getFilesByName(NOME_ARQUIVO);
  var arquivo = arquivos.hasNext() ? arquivos.next() : null;
  if (!arquivo) {
    arquivo = DriveApp.createFile(NOME_ARQUIVO, texto, 'application/json');
    console.log('Arquivo criado no Drive: ' + arquivo.getUrl());
    return;
  }
  if (arquivo.getBlob().getDataAsString('UTF-8') === texto) {
    console.log('Nada mudou desde a última cópia.');
    return;
  }
  arquivo.setContent(texto);
  console.log('Drive atualizado.');
}

function instalar() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'copiar') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('copiar').timeBased().everyHours(1).create();
  copiar();
  console.log('Instalado: a cópia roda sozinha a cada hora.');
}
