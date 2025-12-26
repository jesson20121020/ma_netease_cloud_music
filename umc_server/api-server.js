// 设置开发模式，使用src目录而不是precompiled
process.env.DEVELOPMENT = 'true';

// 设置默认启用VIP、无损等最高音质
process.env.ENABLE_LOCAL_VIP = 'true';
process.env.ENABLE_FLAC = 'true';
process.env.SELECT_MAX_BR = 'true';
process.env.FOLLOW_SOURCE_ORDER = 'false'; // 选择最高码率而不是按顺序

const http = require('http');
const url = require('url');
const match = require('./server/src/provider/match');

const server = http.createServer((req, res) => {
    // 设置CORS头，允许浏览器跨域请求
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

    if (req.method === 'OPTIONS') {
        res.writeHead(200);
        res.end();
        return;
    }

    if (req.url.startsWith('/match/') && req.method === 'GET') {
        const parsedUrl = url.parse(req.url, true);
        const songId = parsedUrl.pathname.split('/match/')[1];
        const sources = parsedUrl.query.sources
            ? parsedUrl.query.sources.split(',')
            : ['qq', 'kugou', 'kuwo', 'migu', 'ytdlp'];

        console.log(`请求歌曲ID: ${songId}, 音源: ${sources.join(', ')}`);

        match(songId, sources)
            .then(result => {
                console.log(`成功获取音源: ${result.source} - ${result.url}`);
                res.writeHead(200, {'Content-Type': 'application/json'});
                res.end(JSON.stringify({
                    success: true,
                    songId: songId,
                    requestedSources: sources,
                    audioUrl: result.url,
                    bitrate: result.br,
                    size: result.size,
                    md5: result.md5,
                    source: result.source,
                    type: result.br === 999000 ? 'flac' : 'mp3'
                }, null, 2));
            })
            .catch(error => {
                const errorMessage = error?.message || 'Unknown error';
                console.error(`获取音源失败: ${errorMessage}`);
                res.writeHead(404, {'Content-Type': 'application/json'});
                res.end(JSON.stringify({
                    success: false,
                    songId: songId,
                    requestedSources: sources,
                    error: 'Song not found in any source',
                    details: errorMessage
                }, null, 2));
            });
    } else if (req.url === '/' && req.method === 'GET') {
        // 首页提供使用说明
        res.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'});
        res.end(`
<!DOCTYPE html>
<html>
<head>
    <title>UnblockNeteaseMusic API</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
        .example { background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 10px 0; }
        code { background: #e0e0e0; padding: 2px 4px; border-radius: 3px; }
    </style>
</head>
<body>
    <h1>网易云音乐解锁API</h1>
    <p>通过GET请求获取歌曲音源URL</p>

    <h2>使用方法</h2>
    <div class="example">
        <strong>基础用法:</strong><br>
        <code>GET /match/{songId}</code><br>
        <em>例如: /match/418602084</em>
    </div>

    <div class="example">
        <strong>指定音源:</strong><br>
        <code>GET /match/{songId}?sources=qq,kugou,kuwo</code><br>
        <em>例如: /match/418602084?sources=qq,kugou,migu</em>
    </div>

    <h2>支持的音源</h2>
    <ul>
        <li>qq - QQ音乐</li>
        <li>kugou - 酷狗音乐</li>
        <li>kuwo - 酷我音乐</li>
        <li>migu - 咪咕音乐</li>
        <li>ytdlp - YouTube (yt-dlp)</li>
        <li>bilivideo - B站音乐</li>
        <li>joox - JOOX音乐</li>
    </ul>

    <h2>响应格式</h2>
    <div class="example">
        <strong>成功响应:</strong><br>
        <pre>
{
  "success": true,
  "songId": "418602084",
  "requestedSources": ["qq", "kugou"],
  "audioUrl": "https://example.com/audio.mp3",
  "bitrate": 128000,
  "size": 4194304,
  "md5": "abc123...",
  "source": "qq",
  "type": "mp3"
}
        </pre>
    </div>

    <div class="example">
        <strong>失败响应:</strong><br>
        <pre>
{
  "success": false,
  "songId": "418602084",
  "error": "Song not found in any source"
}
        </pre>
    </div>

    <h2>浏览器测试</h2>
    <p>可以在浏览器地址栏直接输入API URL测试，或使用JavaScript fetch:</p>
    <div class="example">
        <code>
fetch('/match/418602084?sources=qq,kugou')<br>
  .then(r => r.json())<br>
  .then(data => console.log(data));
        </code>
    </div>
</body>
</html>
        `);
    } else {
        res.writeHead(404, {'Content-Type': 'application/json'});
        res.end(JSON.stringify({
            error: 'Not found',
            availableEndpoints: ['/', '/match/{songId}']
        }, null, 2));
    }
});

// 错误处理
server.on('error', (error) => {
    console.error('Server error:', error);
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => {
    console.log(`API Server running on http://localhost:${PORT}`);
    console.log(`访问 http://localhost:${PORT} 查看使用说明`);
});

module.exports = server;
