/**
 * 臺北樹蔭公平地圖（市政 debug 松 MVP）
 * 網頁 Index.html 與壓縮後的資料 shade_data.txt 都放在雲端硬碟資料夾「市政松練習」。
 * 網頁先開啟，再透過 getData() 讀取資料，避免一次傳送 6 MB 而卡住。
 * 更新網頁或資料時，只要替換資料夾裡的檔案，再執行一次 clearCache，不必重新部署。
 */
const FOLDER_ID = '1wsMXyRmkKBFFhefYksBViME_nhaQ5K5F';
const PAGE_FILE = 'Index.html';
const DATA_FILE = 'shade_data.txt';

function doGet() {
  return HtmlService.createHtmlOutput(readText_(PAGE_FILE))
    .setTitle('臺北樹蔭公平地圖')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

// 網頁呼叫：回傳 gzip 壓縮再 base64 編碼的資料（約 2.6 MB，純英數字）
function getData() {
  const cache = CacheService.getScriptCache();
  const n = Number(cache.get('shade_n') || 0);
  if (n) {
    const keys = Array.from({ length: n }, (_, i) => 'shade_' + i);
    const parts = cache.getAll(keys);
    if (Object.keys(parts).length === n) return keys.map(k => parts[k]).join('');
  }
  const text = readText_(DATA_FILE);
  try {
    const size = 95000, chunks = {};
    let k = 0;
    for (let i = 0; i < text.length; i += size) chunks['shade_' + (k++)] = text.slice(i, i + size);
    cache.putAll(chunks, 21600);
    cache.put('shade_n', String(k), 21600);
  } catch (e) {
    // 快取失敗不影響顯示
  }
  return text;
}

function readText_(name) {
  const it = DriveApp.getFolderById(FOLDER_ID).getFilesByName(name);
  if (!it.hasNext()) throw new Error('資料夾裡找不到 ' + name + '，請確認檔名完全相同');
  return it.next().getBlob().getDataAsString('UTF-8');
}

// 更新資料檔後執行一次，清掉舊快取
function clearCache() {
  const cache = CacheService.getScriptCache();
  const n = Number(cache.get('shade_n') || 0);
  cache.removeAll(Array.from({ length: n }, (_, i) => 'shade_' + i).concat(['shade_n']));
}
