# Netease Cloud Music Provider for MusicAssistant

这是一个 MusicAssistant 的自定义 Provider，用于集成您自己部署的 `netease_cloud_music_api`，提供音乐、电台和有声读物等服务。

## 功能特性

- ✅ 搜索音乐、专辑、艺术家
- ✅ 搜索电台和有声读物
- ✅ 获取歌曲、专辑、艺术家、电台的详细信息
- ✅ 获取流媒体播放 URL
- ✅ 支持自定义 API 地址配置

## 前置要求

1. **部署 netease_cloud_music_api**
   
   确保您已经部署了 `netease_cloud_music_api` 服务。可以使用 Docker 快速部署：

   ```bash
   docker pull binaryify/netease_cloud_music_api
   docker run -d -p 3000:3000 --name netease_cloud_music_api binaryify/netease_cloud_music_api
   ```

   服务默认运行在 `http://localhost:3000`。

2. **MusicAssistant 环境**
   
   确保您已经安装并运行了 MusicAssistant。

## 安装方法

### 方法一：通过 pip 安装（推荐）

```bash
# 克隆或下载此仓库
git clone https://github.com/your-username/ma-netease-provider.git
cd ma-netease-provider

# 安装依赖
pip install -e .
```

### 方法二：手动安装

1. 将 `netease_provider` 目录复制到 MusicAssistant 的插件目录
2. 安装依赖：`pip install httpx>=0.24.0`

## 配置

1. 在 MusicAssistant 的配置界面中找到 "Netease Cloud Music" Provider
2. 配置 API 地址：
   - 如果 API 部署在本地：`http://localhost:3000`
   - 如果 API 部署在远程服务器：`http://your-server-ip:3000`
   - 如果使用了域名：`https://your-domain.com`

3. 保存配置后，MusicAssistant 会自动初始化 Provider

## 使用说明

配置完成后，您可以在 MusicAssistant 中：

- **搜索音乐**：在搜索框中输入歌曲名称、艺术家名称或专辑名称
- **播放音乐**：点击搜索结果中的歌曲即可播放
- **浏览电台**：搜索并播放电台节目
- **有声读物**：搜索和播放有声读物内容

## API 接口说明

此 Provider 使用以下 netease_cloud_music_api 接口：

- `GET /search` - 搜索（支持歌曲、专辑、艺术家、电台）
- `GET /song/detail` - 获取歌曲详情
- `GET /song/url/v1` - 获取歌曲播放 URL
- `GET /album` - 获取专辑详情
- `GET /artist/detail` - 获取艺术家详情
- `GET /dj/detail` - 获取电台详情

## 开发

### 项目结构

```
ma-netease-provider/
├── netease_provider/
│   ├── __init__.py
│   └── provider.py          # Provider 主实现文件
├── pyproject.toml           # 项目配置文件
├── manifest.json            # Provider 清单文件
└── README.md                # 说明文档
```

### 本地开发

1. 克隆仓库
2. 安装开发依赖：
   ```bash
   pip install -e ".[dev]"
   ```
3. 运行测试（如果有）：
   ```bash
   pytest
   ```

## 故障排查

### Provider 无法初始化

- 检查 API 地址是否正确
- 确认 netease_cloud_music_api 服务正在运行
- 检查网络连接（如果 API 在远程服务器）

### 搜索无结果

- 检查 API 服务是否正常响应
- 查看 MusicAssistant 日志中的错误信息
- 确认 API 接口是否正常工作

### 无法播放

- 检查流媒体 URL 是否可用
- 某些歌曲可能因为版权问题无法获取播放链接

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 参考资源

- [MusicAssistant 官方文档](https://music-assistant.io/)
- [netease_cloud_music_api 项目](https://github.com/Binaryify/NeteaseCloudMusicApi)
- [MusicAssistant DemoProvider](https://github.com/music-assistant/demo-provider)

