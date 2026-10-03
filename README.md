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
- Provider 使用 `/cloudsearch` 搜索并内置了 20 秒退避，请更新到本仓库最新代码；旧代码调用 `/search`，一旦被限流就会一直搜不到
- 若日志出现 `'coroutine' object has no attribute 'get'` 或 `RuntimeWarning: coroutine 'MassClientResponse.json' was never awaited`，说明 Provider 把 MusicAssistant 的 aiohttp 会话当成 httpx 使用，同样更新到最新代码即可

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
