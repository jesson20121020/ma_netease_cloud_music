# 🎵 Netease Cloud Music Integration for MusicAssistant

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

网易云音乐与 MusicAssistant 的完整集成解决方案，提供高品质音乐播放体验！

## 📁 项目结构

本项目包含两个主要组件：

### 🎯 [ma_provider/](ma_provider/) - MusicAssistant Provider
MusicAssistant 的网易云音乐 Provider，实现完整的音乐服务集成。

- ✅ 智能搜索：音乐、专辑、艺术家、电台、有声读物
- ✅ 高品质播放：支持 FLAC 无损音质和多种音源
- ✅ 解锁 API：可选的无版权限制音源支持
- ✅ 自动回退：音源获取失败时智能切换

### 🚀 [umc_server/](umc_server/) - 网易云音乐解锁 API 服务器
基于 [UnblockNeteaseMusic/server](https://github.com/UnblockNeteaseMusic/server) 的增强版 API 服务器。

- ✅ RESTful API 接口
- ✅ 多音源支持：QQ音乐、酷狗音乐、酷我音乐等
- ✅ Docker 一键部署
- ✅ 完整的音源解锁功能

## 🏗️ 系统架构

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  MusicAssistant │────│  Netease Provider │────│ NeteaseCloudAPI │
│   (Port 8095)   │    │                  │    │   (Port 3000)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │   Unblock API    │
                       │   (Port 3001)    │
                       │   Optional       │
                       └──────────────────┘
```

## 🚀 快速开始

### 1. 部署 MusicAssistant

```bash
# 使用 Docker 快速部署 MusicAssistant
docker run -d \
  --name musicassistant \
  -p 8095:8095 \
  -v /path/to/config:/config \
  ghcr.io/music-assistant/server:latest
```

访问 `http://localhost:8095` 进入 MusicAssistant Web 界面。

### 2. 部署网易云音乐 API

```bash
# 部署网易云音乐 API 服务
docker run -d \
  --name netease-cloud-api \
  -p 3000:3000 \
  binaryify/netease_cloud_music_api
```

### 3. 可选：部署解锁 API（推荐）

```bash
# 进入 umc_server 目录
cd umc_server

# 构建并运行解锁 API
docker build -t netease-unblock-api .
docker run -d \
  --name netease-unblock-api \
  -p 3001:3000 \
  netease-unblock-api
```

### 4. 安装并配置 Provider

新版 MusicAssistant 通过把 Provider 目录挂载进容器来加载外部 Provider：

```bash
docker run -d \
  --name musicassistant \
  -p 8095:8095 \
  -v /path/to/config:/data \
  -v /path/to/ma_netease_cloud_music/ma_provider/netease_provider:/app/venv/lib/python3.14/site-packages/music_assistant/providers/netease_provider \
  ghcr.io/music-assistant/server:latest
```

在 MusicAssistant 的「设置 → 提供商 → 添加提供商」中选择 **Netease Cloud provider**，添加向导会要求填写：
- **API 地址**（必填）: `http://localhost:3000`
- **解锁 API 地址**（可选）: `http://localhost:3001`
- **登录 Cookie**（可选，推荐）: 登录网易云后的 cookie，可大幅提高接口配额（避免「操作频繁」405）并访问自己账号的歌单

向导会立即探测地址是否为可用的 NeteaseCloudMusicApi 服务，填错会提示重新输入；之后修改地址请使用提供商的「重新配置」。

## ✨ 功能特性

### 🎶 音乐播放
- **海量音乐库**：网易云音乐全库支持
- **高品质音质**：FLAC 无损、320Kbps 等
- **智能音源**：自动选择最佳播放源
- **版权解锁**：突破地域限制

### 📻 电台内容
- **电台节目**：各类音乐电台
- **有声读物**：丰富的有声内容
- **节目浏览**：完整的节目列表

### 🔧 高级功能
- **Docker 部署**：一键部署所有服务
- **灵活配置**：自定义 API 地址
- **故障回退**：多重保障机制
- **社区支持**：活跃的开源社区

## 📋 部署要求

### 必需组件
- ✅ **Docker & Docker Compose**
- ✅ **MusicAssistant** (推荐最新版本)
- ✅ **网易云音乐 API** (Docker 镜像)

### 系统要求
- **内存**: 至少 1GB 可用内存
- **存储**: 至少 5GB 可用存储空间
- **网络**: 稳定的互联网连接

## 🔧 故障排查

### 常见问题

**MusicAssistant 无法启动**
```bash
# 检查 Docker 容器状态
docker ps | grep musicassistant
docker logs musicassistant
```

**网易云 API 无响应**
```bash
# 测试 API 连接（/cloudsearch 没有被网易限流，/search 可能返回 405）
curl "http://localhost:3000/cloudsearch?keywords=测试&type=1&limit=2"
curl http://localhost:3000/login/status
```

**Provider 无法初始化**
- 检查 API 地址配置是否正确
- 确认所有服务都在运行
- 查看 MusicAssistant 日志
- 若日志出现 `ValueError: API URL is required`，说明 Provider 版本过旧：新版 MusicAssistant 要求提供实例级 `get_config_entries()` 与 `setup_flow.py`，请更新到本仓库最新代码后重启 MusicAssistant

**搜索不到任何歌曲 / 日志出现 HTTP 405**
- 日志形如 `Unexpected error while requesting http://.../search: 405, message='Method Not Allowed'`，网易云 API 容器日志里是 `{ msg: '操作频繁，请稍候再试', code: 405 }`：这是网易对旧版 `/search` 接口的限流（大量刷新媒体库时最容易触发），而不是配置错误
- Provider 使用 `/cloudsearch` 搜索，串行化请求并内置退避（首次 15 秒、逐次翻倍、上限 120 秒）与自动重试，请更新到本仓库最新代码；旧代码调用 `/search`，一旦被限流就会一直搜不到
- 若日志出现 `'coroutine' object has no attribute 'get'` 或 `RuntimeWarning: coroutine 'MassClientResponse.json' was never awaited`，说明 Provider 把 MusicAssistant 的 aiohttp 会话当成 httpx 使用，同样更新到最新代码即可
- 若日志出现 `Netease API rate limit reached (...): pausing requests for Ns`：这是 Provider 正在自动退避，通常无需干预；频繁出现说明当前是**匿名会话**（配额很低），登录后填入 cookie 即可解决

**搜索「不刷新」/ 某个关键词一直搜不到（已修复，2026-11-14）**
- 现象：某个关键词搜一次没结果，之后再搜同一个词始终是空的；换个词才有结果；重启 Music Assistant 或等很久才恢复
- 根因链（三层叠加）：
  1. 匿名会话配额低，刷新媒体库时 `/cloudsearch` 会被网易回 `405 操作频繁`
  2. 旧版 Provider 收到 405 后**在锁里睡满 15s→120s 的退避**，而 Music Assistant 只等 provider **8s**（`SEARCH_PROVIDER_SOFT_TIMEOUT`），于是这次搜索不带网易云结果
  3. 旧版 Provider 把「全部类型都失败」**当成成功返回空结果**；Music Assistant 对 streaming provider 的搜索结果会缓存 **24 小时**，前端 `useProgressiveSearch` 还会把空结果按 provider 记在页面上。于是一个空结果被缓存住，同一个词怎么搜都是空
- 现在的行为（本仓库最新代码）：
  - 剩余退避时间 > 3s 时**立即**抛 `ResourceTemporarilyUnavailable`（不等满），Music Assistant 按「暂时不可用」处理并稍后重试，前端 7s 后自动重试（最多 3 次）
  - 只有**真正拿到数据**才返回；四类搜索全失败时抛异常而不是返回空 → 不会再把空结果缓存 24 小时
  - 单曲详情补图失败不再丢掉已搜到的单曲（降级返回）
  - 限流日志一轮只报一次 WARNING，其余降到 DEBUG；逐曲 INFO 日志改为 DEBUG
- 注意：这不是根治。根治仍然是**登录后填 cookie**（见下一条），匿名会话配额低，刷新大媒体库时依然会被限流，只是不再「粘住」。

**频繁限流（操作频繁）—— 登录后填入 cookie**
```bash
# 1) 手机号+密码登录，返回 JSON 里带一个很长的 cookie 字段
curl -X POST "http://192.168.31.1:3001/login/cellphone?phone=手机号&password=密码"
# 2) 把返回 JSON 里的 cookie 值填到 Provider 的「登录 Cookie（可选，推荐）」里（重新配置流程）
# 3) 验证：data.account 存在且 anonimousUser 不为 true 即表示已登录
curl "http://192.168.31.1:3001/login/status?cookie=粘贴的cookie"
```
登录后可显著提高接口配额（避免 405 操作频繁），并能访问自己账号的歌单；留空则使用匿名会话，配额较低。

## 📚 相关链接

### 官方资源
- [MusicAssistant 官方文档](https://music-assistant.io/)
- [网易云音乐 API 项目](https://github.com/Binaryify/NeteaseCloudMusicApi)
- [UnblockNeteaseMusic 项目](https://github.com/UnblockNeteaseMusic/server)

### 社区支持
- [MusicAssistant Discord](https://discord.gg/musicassistant)
- [GitHub Issues](https://github.com/jesson20121020/ma_netease_cloud_music/issues)

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

[MIT License](LICENSE)

---

<div align="center">

**Made with ❤️ for MusicAssistant community**

**享受无版权限制的高品质音乐！**

</div>
