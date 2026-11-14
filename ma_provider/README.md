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
- **扫码登录（推荐，默认勾选）**: 下一步直接显示二维码，用网易云音乐 App 扫码并在手机上确认即可登录，cookie 自动保存（提高配额、避免 405 限流、可访问账号歌单）；二维码 120 秒过期会自动换新的
- **登录 Cookie**（可选，仅在不方便扫码时手填）: 登录后的 cookie，留空则由扫码登录或匿名会话处理

向导会立即探测该地址是否为可用的 NeteaseCloudMusicApi 服务，地址填错时会提示重新填写。添加完成后如需修改地址或重新登录，在提供商页面使用「重新配置」即可（同样会出二维码）。不勾选扫码、也不填 cookie 时使用匿名会话（配额较低）。

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
- **登录（扫码，推荐）**: 配置向导里勾选「扫码登录」，用**网易云音乐 App → 扫一扫**扫描向导显示的二维码并确认
  - 走的是 NeteaseCloudMusicApi 的 `/login/qr/key` → `/login/qr/create` → `/login/qr/check`（801 等待扫码 / 802 待确认 / 803 成功 / 800 过期自动换码）
  - 登录后接口配额显著提高（匿名会话配额很低，容易被限流返回 405「操作频繁」），并可访问自己账号的歌单
- **登录 Cookie（备用）**: 已拿到 cookie 时可直接粘贴（匿名会话配额很低）
  - 获取: `curl -X POST 'http://localhost:3000/login/cellphone?phone=手机号&password=密码'`，取返回 JSON 的 `cookie` 字段

### 📚 媒体库同步（登录后走账号数据）

登录（配置了 cookie）后，`ma_provider` 的库同步改用账号自己的数据，而不是热门榜单：

| 媒体类型 | 登录后数据源 | 匿名时（旧行为） |
|---|---|---|
| 歌单 | `/user/playlist` 账号自己创建 + 收藏的歌单（含「我喜欢的音乐」、年度歌单） | `/top/playlist/highquality` 热门歌单 |
| 曲目 | `/likelist` 我喜欢的音乐 | 热门歌单里抽若干首 |
| 歌手 | 关注的歌手（`/artist/sublist`）**+ 热门歌手**（`/top/artists`，数量由 `hot_artists` 控制，默认 50） | 热门歌手 |
| 专辑 | 收藏的专辑（`/album/sublist`）**+ 新碟上架**（`/album/new?area=ALL`，数量由 `hot_albums` 控制，默认 50） | 新碟上架 |
| 榜单 | `/toplist` 里按配置挑的榜单歌单（默认 飙升榜/新歌榜/热歌榜/原创榜） | 同左（榜单是公开数据） |

榜单歌单在 Provider 设置里的「同步的榜单歌单」一栏配置（逗号分隔，留空不同步）。名字取自
<https://music.163.com/#/discover/toplist>，例如：
`飙升榜,新歌榜,热歌榜,原创榜,网易云摇滚榜,网易云国风榜,网易云ACG动画榜,网易云民谣榜`。
支持部分名（如 `ACG`，前提是只匹配到一个），匹配不到的会在日志里列出可用名字。
也可以直接填 `ALL`（等价于 `*` / `全部`）一次同步**全部榜单**——当前是 65 个（官方榜 + 云音乐特色榜 +
全球榜 + 合作/车友榜），日志会打印 `Netease library charts: syncing all 65 chart playlist(s)`。

热门歌手/热门专辑的数量在 Provider 设置里配：`同步热门歌手数量`、`同步热门专辑数量`（0 = 不同步，
默认都是 50；登录后会额外叠加关注歌手 / 收藏专辑并去重）。

同步时日志会打印数量，例如：

```
Netease library artists: 10 followed artist(s)
Netease library playlists: 22 playlist(s) of account 249697856
Netease library tracks: 420 liked song(s)
```

注意：`/song/detail`、`/playlist/detail`、`/likelist` 返回的字段是 `ar`/`al`，而 `/cloudsearch`
返回的是 `artists`/`album`，解析器两种都认（否则同步会报 `Track is missing artist(s)` 而整条丢弃）。

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

### 🔁 某个关键词一直搜不到 / 搜索「不刷新」（2026-11-14 已修复）

现象：第一次搜某个词没结果，之后同一个词怎么搜都是空，换个词才有结果。

三层原因：

1. 匿名会话配额低，媒体库刷新时 `/cloudsearch` 被网易回 `405 操作频繁`；
2. 旧代码收到 405 后在请求锁里**睡满 15s→120s 的退避**，而 Music Assistant 只等
   provider **8 秒**（`SEARCH_PROVIDER_SOFT_TIMEOUT`），这次搜索就不带网易云结果；
3. 旧代码把「所有类型都失败」当成成功、返回**空结果**，Music Assistant 会把这个空结果
   按 streaming provider 缓存 **24 小时**，前端也会按 provider 记住空结果
   （`useProgressiveSearch`）——于是同一个词被「粘住」。

现在：剩余退避 > 3s 立即抛 `ResourceTemporarilyUnavailable`（不睡满）、只有拿到数据才返回
（全失败抛异常 → 不会被缓存成空）、补图失败不再丢单曲。**根治仍建议填登录 cookie**提高配额。


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
   # Provider 使用 /cloudsearch 搜索；旧版 /search 会被网易限流并返回 405
   curl "http://localhost:3000/cloudsearch?keywords=稻香&type=1&limit=2"
   curl "http://localhost:3000/search?keywords=稻香&type=1&limit=2"
   ```

2. **检查 MusicAssistant 日志**
   ```bash
   # 查看 MA 日志中的错误信息
   docker logs musicassistant 2>&1 | grep -i error
   ```

3. **验证 API 服务状态**
   - 访问 `http://localhost:3000` 查看服务状态

4. **日志出现 HTTP 405 / 「操作频繁」**
   - 形如 `405, message='Method Not Allowed', url='.../search?...'`，网易云 API 容器日志里为 `{ msg: '操作频繁，请稍候再试', code: 405 }`
   - 这是网易对旧版 `/search` 接口的限流（刷新媒体库触发大量搜索时最常见），与 API 地址配置无关；更新到本仓库最新代码（改用 `/cloudsearch`，串行化 + 退避 15s 起、翻倍、上限 120s，并自动重试）后重启 MusicAssistant
   - 被限流的请求现在会重试并在仍失败时抛出 `ResourceTemporarilyUnavailable`（可被 MA 重试），不会再被误判成「歌曲/歌手不存在」

5. **日志出现 `Netease API rate limit reached (...): pausing requests for Ns`**
   - Provider 正在自动退避，通常无需干预；反复出现说明当前是**匿名会话**（配额很低）

6. **验证 cookie 是否真的生效**（2026-11-14 新增）

   启动日志里会打印一行身份核对，例如：

   ```
   Netease login verified: 小远和南方 (uid 249697856, vipType 11, cookie=full, backend=logged-in)
   ```

   - `cookie=full|minimal`：用的是完整 cookie 还是被裁剪成 `MUSIC_U+__csrf`（浏览器 cookie 里那些
     访客 cookie 有时会让后端保持匿名，Provider 会自动降级重试）
   - `backend=logged-in`：**这一项才是关键**——它验证「后端把 cookie 带上后，普通搜索走的是登录配额」
   - 若出现 `Netease cookie is NOT logged in ...` 说明 cookie 已失效（会打印 MUSIC_U 长度，便于判断是不是
     复制时被截断），重新登录后再贴一次
   - 注意：单看后端 `/login/status` 会误报匿名（实测 cookie 有效时它仍回 anonimousUser），所以 Provider
     会用 Netease 直连 + 一次 `/user/playlist` 交叉验证

6. **登录以提升配额**

   > ⚠️ 2026-11-14 实测：网易云已封禁服务端扫码登录。手机能扫到（服务端 `802`），但 1～2 秒后
   > 返回 `8821 请切换其他登录方式或升级新版本再试`，手机端一直转圈。type=3（后端 `/login/qr/*`）
   > 报「设备环境异常」，type=1（官方网页通道）报 8821，两条都不通。因此向导里的「扫码登录」默认关闭。

   **推荐：手机号+密码换 cookie**（最快）
   ```bash
   curl -X POST "http://localhost:3000/login/cellphone?phone=手机号&password=密码"
   # 取返回 JSON 的 cookie 字段，填进向导的「登录 Cookie」
   ```

   **或短信验证码**
   ```bash
   curl "http://localhost:3000/captcha/sent?phone=手机号&ctcode=86"      # 收短信验证码
   curl "http://localhost:3000/login/cellphone?phone=手机号&captcha=验证码"
   ```

   历史上扫码流程（保留供参考，当前基本不可用）
   - MusicAssistant 后台 → 设置 → 提供商 → **Netease Cloud provider** → 「重新配置」
   - 保持「扫码登录（推荐）」勾选 → 下一步显示二维码 → 手机网易云音乐 App 扫一扫 → 手机上确认
   - 确认后向导自动完成并把 cookie 写入该实例；日志出现 `login cookie: yes` 即已登录
   ```bash
   # 命令行等价流程（type=1 = 官方网页登录通道，绕开 API 固定的 type=3 风控）
   curl -X POST 'https://music.163.com/api/login/qrcode/unikey' -d 'type=1&noCheckToken=true'
   curl "http://localhost:3000/login/qr/create?key=<unikey>&qrimg=true"        # 仅本地编码图片
   curl -X POST 'https://music.163.com/api/login/qrcode/client/login' \
     -H 'X-loginMethod: qr_code' -d 'key=<unikey>&type=1&noCheckToken=true'   # 803 后 Set-Cookie 带 MUSIC_U
   ```

   > 手机提示「检测到当前设备环境异常，本次操作已拦截」= 网易云风控。Provider 已改用官方网页的
   > `type=1` 通道；若仍被拦截，先在 App 里完成一次安全验证，或用官方网页登录一次再回来扫码。
   备用（不方便扫码时）：`curl -X POST "http://localhost:3000/login/cellphone?phone=手机号&password=密码"` 取 cookie 填到「登录 Cookie」，再用 `curl "http://localhost:3000/login/status?cookie=粘贴的cookie"` 验证 `anonimousUser` 不为 `true`。

7. **日志出现 `'coroutine' object has no attribute 'get'`**
   - 说明 Provider 把 MusicAssistant 共享的 aiohttp 会话当作 httpx 使用（`MassClientResponse.json` 是协程）；更新到最新代码即可（Provider 使用自己的 `httpx.AsyncClient`）

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
