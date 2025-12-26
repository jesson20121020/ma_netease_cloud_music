# 网易云音乐解锁 API 服务器

这是一个基于 UnblockNeteaseMusic 的 HTTP API 服务器，提供网易云音乐歌曲的音源获取服务。

## 功能特性

- 🚀 快速获取网易云音乐歌曲的音频 URL
- 🎵 支持多种音源：QQ音乐、酷狗音乐、酷我音乐、咪咕音乐、YouTube 等
- 📦 提供 Docker 镜像，便于快速部署
- 🌐 完整的 REST API 接口
- 📖 内置使用说明页面

## 快速开始

### 使用 Docker 部署（推荐）

1. **构建镜像**
```bash
cd umc_server
docker build -t netease-api-server .
```

2. **运行容器**
```bash
docker run -d -p 3000:3000 --name netease-api netease-api-server
```

3. **访问服务**
打开浏览器访问 http://localhost:3000 查看使用说明

### 本地开发部署

1. **安装依赖**
```bash
cd umc_server/server
npm install
```

2. **启动服务器**
```bash
cd umc_server
node api-server.js
```

服务器将在 http://localhost:3000 启动

## API 使用方法

### 获取歌曲音源

**基本用法：**
```
GET /match/{songId}
```

**指定音源：**
```
GET /match/{songId}?sources=qq,kugou,kuwo
```

**示例：**
```bash
curl "http://localhost:3000/match/418602084"
curl "http://localhost:3000/match/418602084?sources=qq,kugou,migu"
```

### 响应格式

**成功响应：**
```json
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
```

**失败响应：**
```json
{
  "success": false,
  "songId": "418602084",
  "error": "Song not found in any source"
}
```

## 支持的音源

- `qq` - QQ音乐
- `kugou` - 酷狗音乐
- `kuwo` - 酷我音乐
- `migu` - 咪咕音乐
- `ytdlp` - YouTube (需要安装 yt-dlp)
- `bilivideo` - B站音乐
- `joox` - JOOX音乐

## 浏览器测试

可以在浏览器地址栏直接输入 API URL 测试，或使用 JavaScript fetch：

```javascript
fetch('/match/418602084?sources=qq,kugou')
  .then(r => r.json())
  .then(data => console.log(data));
```

## 环境变量

服务器支持以下环境变量配置：

- `PORT` - 服务器端口 (默认: 3000)
- `ENABLE_LOCAL_VIP` - 启用本地VIP功能 (默认: true)
- `ENABLE_FLAC` - 启用FLAC无损音质 (默认: true)
- `SELECT_MAX_BR` - 选择最高码率 (默认: true)
- `FOLLOW_SOURCE_ORDER` - 按音源顺序选择 (默认: false)

## 部署到生产环境

### 使用 Docker Compose

创建 `docker-compose.yml`：

```yaml
version: '3.8'
services:
  netease-api:
    build: .
    ports:
      - "3000:3000"
    environment:
      - NODE_ENV=production
    restart: unless-stopped
```

然后运行：
```bash
docker-compose up -d
```

### 使用反向代理

推荐使用 Nginx 作为反向代理：

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

## 注意事项

- 部分音源可能需要额外的工具支持（如 yt-dlp）
- 服务器会自动选择可用的最高音质
- API 请求可能受到目标音源的限制

## 许可证

本项目基于 UnblockNeteaseMusic 项目，遵循 LGPL-3.0-only 许可证。
