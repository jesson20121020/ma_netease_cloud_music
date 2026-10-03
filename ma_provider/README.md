# 🎵 Netease Cloud Music Provider for MusicAssistant

[![MIT License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

网易云音乐 MusicAssistant Provider - 让您的 MusicAssistant 支持网易云音乐的完整功能！

## ✨ 功能特性

### 🎶 核心功能
- 🔍 **智能搜索** - 搜索音乐、专辑、艺术家、电台、有声读物
- 🎵 **高品质播放** - 支持 FLAC 无损音质和多种音源
- 📻 **电台支持** - 完整的电台节目浏览和播放
- 🎧 **有声读物** - 支持有声读物内容
- 🌐 **多源播放** - 自动选择最佳音源，提升播放成功率

### 🔧 高级特性
- 🚀 **解锁 API** - 可选的无版权限制音源支持
- ⚙️ **灵活配置** - 自定义 API 地址和参数
- 📱 **响应式设计** - 适配各种 MusicAssistant 界面
- 🔄 **自动回退** - 音源获取失败时自动切换备用方案

## 🏗️ 系统架构

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  MusicAssistant │────│  Netease Provider │────│ NeteaseCloudAPI │
│                 │    │                  │    │   (Port 3000)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │   Unblock API    │
                       │   (Port 3001)    │
                       │   Optional       │
                       └──────────────────┘
```

## 📋 前置要求

### 必需组件
- ✅ **MusicAssistant** - 已安装并运行
- ✅ **NeteaseCloudMusicApi** - 网易云音乐 API 服务

### 可选组件
- 🔄 **Unblock API** - 无版权限制音源服务（推荐）

## 🚀 快速开始

### 1. 部署网易云音乐 API

```bash
# 使用 Docker 快速部署
docker run -d \
  --name netease-cloud-api \
  -p 3000:3000 \
  binaryify/netease_cloud_music_api
```

### 2. 可选：部署解锁 API（推荐）

```bash
# 进入 umc_server 目录
cd ../umc_server

# 构建并运行解锁 API
docker build -t netease-unblock-api .
docker run -d \
  --name netease-unblock-api \
  -p 3001:3000 \
  netease-unblock-api
```

### 3. 安装 Provider

新版 MusicAssistant 通过把 Provider 目录挂载进容器来加载外部 Provider：

```bash
docker run -d \
  --name musicassistant \
  -p 8095:8095 \
  -v /path/to/config:/data \
  -v /path/to/ma_netease_cloud_music/ma_provider/netease_provider:/app/venv/lib/python3.14/site-packages/music_assistant/providers/netease_provider \
  ghcr.io/music-assistant/server:latest
```

> 也可以直接把 `netease_provider` 目录复制到 MusicAssistant 的 providers 目录。

### 4. 配置 Provider

在 MusicAssistant 的「设置 → 提供商 → 添加提供商」中选择 **Netease Cloud provider**，添加向导会要求填写：

- **API 地址**（必填）: `http://localhost:3000`
- **解锁 API 地址**（可选）: `http://localhost:3001`

向导会立即探测该地址是否为可用的 NeteaseCloudMusicApi 服务，地址填错时会提示重新填写。添加完成后如需修改地址，在提供商页面使用「重新配置」即可。

## 📖 使用指南

### 🎵 播放音乐
配置完成后，您可以：

- **🔍 搜索内容**：输入歌曲、艺术家、专辑或电台名称
- **▶️ 播放音乐**：点击搜索结果直接播放
- **📻 收听电台**：浏览和播放各类电台节目
- **🎧 听有声读物**：享受有声读物内容

### ⚙️ 配置说明

#### 必需配置
- **API 地址**: 网易云音乐 API 服务地址
  - 本地部署: `http://localhost:3000`
  - 远程服务器: `http://your-server:3000`

#### 可选配置
- **解锁 API 地址**: 无版权限制音源服务
  - 启用后可获得更高质量的音源
  - 地址示例: `http://localhost:3001`

## 🔌 技术规格

### API 接口使用
Provider 通过以下接口获取数据：

| 接口 | 功能 | 说明 |
|------|------|------|
| `/search` | 搜索 | 支持多类型内容搜索 |
| `/song/detail` | 歌曲详情 | 获取歌曲详细信息 |
| `/song/url/v1` | 播放地址 | 获取音频流地址 |
| `/album` | 专辑详情 | 获取专辑信息 |
| `/artist/detail` | 艺术家详情 | 获取艺术家信息 |
| `/dj/detail` | 电台详情 | 获取电台节目信息 |

## 开发

### 项目结构

```
ma-netease-provider/
├── netease_provider/
│   ├── __init__.py          # Provider 主实现文件
│   ├── setup_flow.py        # 添加/重配置向导（收集并校验 API 地址）
│   └── manifest.json        # Provider 清单文件
└── README.md                # 说明文档
```



## 🔧 故障排查

### 🚫 Provider 初始化失败

**可能原因及解决方案：**

- **❌ API 地址错误**
  ```bash
  # 检查服务是否运行
  curl http://localhost:3000/search?keywords=测试
  ```

- **❌ 新版 MusicAssistant 报错 `ValueError: API URL is required`**
  - 说明部署的是旧版 Provider：新版 MusicAssistant 不再调用旧式的
    `get_config_entries(mass, instance_id, action, values)` 钩子，改为在 Provider
    实例上调用 `get_config_entries()`，并通过 `setup_flow.py` 收集地址
  - 更新 `__init__.py` 的同时必须一起部署 `setup_flow.py`，否则无法添加新的 Provider 实例
  - 更新后重启 MusicAssistant，日志中应出现
    `Netease Provider initialized with API URL: ...` 与 `Loaded music provider Netease Cloud provider`

- **🌐 网络连接问题**
  - 检查防火墙设置
  - 确认端口未被占用：`netstat -tlnp | grep 3000`

- **🐳 Docker 容器问题**
  ```bash
  # 检查容器状态
  docker ps | grep netease
  docker logs netease-cloud-api
  ```

### 🔍 搜索无结果

**排查步骤：**
1. **测试 API 响应**
   ```bash
   curl "http://localhost:3000/search?keywords=稻香&type=song"
   ```

2. **检查 MusicAssistant 日志**
   ```bash
   # 查看 MA 日志中的错误信息
   docker logs musicassistant 2>&1 | grep -i error
   ```

3. **验证 API 服务状态**
   - 访问 `http://localhost:3000` 查看服务状态

### 🎵 无法播放音乐

**常见解决方案：**

- **版权限制**: 某些歌曲因版权问题无法播放
- **音源不可用**: 尝试启用解锁 API 获取更多音源
- **网络问题**: 检查网络连接和代理设置

**启用解锁 API 提升播放成功率：**
```bash
# 部署解锁 API 服务
cd ../umc_server
docker build -t netease-unblock .
docker run -d -p 3001:3000 netease-unblock
```

然后在 Provider 配置中设置：
- **解锁 API 地址**: `http://localhost:3001`

## 🤝 贡献与支持

### 🐛 报告问题
如果您遇到问题或有功能建议：

1. **检查现有 Issue** - 避免重复报告
2. **提供详细信息** - 包含错误日志、配置信息和重现步骤
3. **使用 Issue 模板** - 遵循项目的 Issue 模板

### 🛠️ 贡献代码
欢迎贡献代码！请：

1. Fork 此仓库
2. 创建功能分支：`git checkout -b feature/amazing-feature`
3. 提交更改：`git commit -m 'Add amazing feature'`
4. 推送分支：`git push origin feature/amazing-feature`
5. 提交 Pull Request

### 📝 开发规范
- 遵循 PEP 8 代码风格
- 添加必要的测试用例
- 更新相关文档
- 确保向后兼容性

## 📚 参考资源

### 官方文档
- 📖 [MusicAssistant 官方文档](https://music-assistant.io/)
- 🎵 [网易云音乐 API 项目](https://github.com/Binaryify/NeteaseCloudMusicApi)

### 相关项目
- 🎯 [MusicAssistant Demo Provider](https://github.com/music-assistant/server/tree/dev/music_assistant/providers/test)
- 🚀 [UnblockNeteaseMusic Server](https://github.com/UnblockNeteaseMusic/server)

### 社区支持
- 💬 [MusicAssistant Discord](https://discord.gg/musicassistant)
- 📧 [GitHub Discussions](https://github.com/music-assistant/core/discussions)

---

<div align="center">

**如果这个项目对你有帮助，请给它一个 ⭐ Star！**

Made with ❤️ for MusicAssistant community

</div>
</div>
