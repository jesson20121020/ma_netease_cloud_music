# 安装指南

## 前置要求

### 1. 部署 netease_cloud_music_api

首先需要部署 `netease_cloud_music_api` 服务。推荐使用 Docker 部署：

```bash
# 拉取镜像
docker pull binaryify/netease_cloud_music_api

# 运行容器
docker run -d -p 3000:3000 --name netease_cloud_music_api binaryify/netease_cloud_music_api
```

验证服务是否正常运行：

```bash
curl http://localhost:3000
```

### 2. MusicAssistant 环境

确保您已经安装并运行了 MusicAssistant。可以参考 [MusicAssistant 官方文档](https://music-assistant.io/) 进行安装。

## 安装 Provider

### 方法一：作为 Python 包安装（推荐）

```bash
# 克隆或下载此仓库
git clone https://github.com/your-username/ma-netease-provider.git
cd ma-netease-provider

# 安装
pip install -e .

# 或者在 MusicAssistant 的虚拟环境中安装
cd /path/to/musicassistant
source .venv/bin/activate  # 或使用您的虚拟环境
pip install -e /path/to/ma-netease-provider
```

### 方法二：手动安装到 MusicAssistant 插件目录

1. 找到 MusicAssistant 的插件目录（通常位于 MusicAssistant 安装目录下的 `custom_components` 或 `providers` 目录）

2. 将 `netease_provider` 目录复制到插件目录：

```bash
cp -r netease_provider /path/to/musicassistant/custom_components/
```

3. 安装依赖：

```bash
pip install httpx>=0.24.0
```

### 方法三：通过 requirements.txt 安装依赖

```bash
pip install -r requirements.txt
```

## 配置 Provider

1. 启动 MusicAssistant

2. 在 MusicAssistant 的 Web 界面中，进入 **设置** > **Providers**（或 **设置** > **集成**）

3. 找到 **Netease Cloud Music** Provider，点击 **配置**

4. 填写配置项：
   - **API 地址**：输入您的 `netease_cloud_music_api` 服务地址
     - 本地部署：`http://localhost:3000`
     - 远程服务器：`http://your-server-ip:3000`
     - 使用域名：`https://your-domain.com`

5. 点击 **保存** 或 **应用**

6. MusicAssistant 会自动初始化 Provider，如果配置正确，Provider 状态会显示为 **已连接**

## 验证安装

1. 在 MusicAssistant 的搜索框中输入歌曲名称进行搜索

2. 如果能看到来自 "Netease Cloud Music" 的搜索结果，说明安装成功

3. 尝试播放搜索结果中的歌曲，确认播放功能正常

## 故障排查

### Provider 无法初始化

- 检查 API 地址是否正确
- 确认 netease_cloud_music_api 服务正在运行
- 检查网络连接（如果 API 在远程服务器）
- 查看 MusicAssistant 日志中的错误信息

### 搜索无结果

- 确认 API 服务可以正常访问
- 检查 API 接口是否正常工作：`curl http://localhost:3000/search?keywords=test&type=1`
- 查看 MusicAssistant 日志

### 无法播放

- 某些歌曲可能因版权限制无法获取播放链接
- 检查流媒体 URL 是否有效
- 确认 API 的 `/song/url/v1` 接口正常工作

## 卸载

如果需要卸载此 Provider：

```bash
# 如果使用 pip 安装
pip uninstall ma-netease-provider

# 如果手动安装，删除目录
rm -rf /path/to/musicassistant/custom_components/netease_provider
```

然后在 MusicAssistant 的设置中移除 Provider 配置。

