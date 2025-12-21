# Docker 部署安装指南

本指南说明如何将 Netease Cloud Music Provider 添加到通过 Docker 部署的 MusicAssistant 中。

## 方法一：通过 Volume 挂载（推荐）

这是最简单直接的方法，直接将 Provider 代码挂载到容器的 custom_components 目录。

### 步骤 1：准备 Provider 代码

确保你的 Provider 代码在本地的某个目录，例如：
```bash
/path/to/ma_netease_cloud_music
```

### 步骤 2：修改 docker-compose.yml

找到你的 MusicAssistant docker-compose.yml 文件，添加 volume 挂载：

```yaml
version: '3'

services:
  music-assistant:
    image: ghcr.io/music-assistant/server:latest
    container_name: music-assistant
    restart: unless-stopped
    network_mode: host
    volumes:
      - /path/to/ma/data:/data           # 数据目录（已有）
      - /path/to/ma/media:/media         # 媒体目录（已有）
      - /path/to/ma_netease_cloud_music/netease_provider:/app/custom_components/netease_provider  # 添加这行
    environment:
      - LOG_LEVEL=info
```

**重要说明：**
- `/path/to/ma_netease_cloud_music` 替换为你实际的 Provider 代码路径
- 挂载路径必须是 `netease_provider` 目录，不是整个项目目录
- 容器内路径：`/app/custom_components/netease_provider`

### 步骤 3：安装依赖

由于容器中需要安装 `httpx` 依赖，有两种方式：

#### 方式 A：在容器内安装（临时，重启后会丢失）

```bash
# 进入容器
docker exec -it music-assistant bash

# 安装依赖
pip install httpx>=0.24.0

# 退出容器
exit
```

#### 方式 B：通过构建自定义镜像（推荐，持久化）

创建 `Dockerfile.ma`：

```dockerfile
FROM ghcr.io/music-assistant/server:latest

# 安装 Provider 依赖
RUN pip install httpx>=0.24.0
```

构建自定义镜像：

```bash
docker build -f Dockerfile.ma -t music-assistant-custom:latest .
```

然后修改 docker-compose.yml，使用自定义镜像：

```yaml
services:
  music-assistant:
    image: music-assistant-custom:latest  # 改为自定义镜像
    # ... 其他配置保持不变
```

### 步骤 4：重启容器

```bash
# 如果使用 docker-compose
docker-compose restart music-assistant

# 或使用 docker 命令
docker restart music-assistant
```

### 步骤 5：在 MA 中配置 Provider

1. 访问 MusicAssistant Web 界面（通常是 `http://localhost:8095`）
2. 进入 **设置** > **Providers**（或 **设置** > **集成**）
3. 找到 **Netease Cloud Music** Provider，点击 **配置**
4. 填写 API 地址（例如：`http://host.docker.internal:3000` 或 `http://你的服务器IP:3000`）
5. 保存配置

## 方法二：通过 pip 在容器内安装

如果 Provider 已经打包为 Python 包（有 setup.py 和 pyproject.toml），可以在容器内直接安装。

### 步骤 1：将代码复制到容器或通过 volume 挂载

```yaml
volumes:
  - /path/to/ma_netease_cloud_music:/tmp/netease-provider
```

### 步骤 2：在容器内安装

```bash
# 进入容器
docker exec -it music-assistant bash

# 安装 Provider
pip install -e /tmp/netease-provider

# 退出容器
exit
```

**注意：** 这种方式在容器重启后会丢失，需要每次重启后重新安装，或使用自定义镜像。

## 方法三：使用自定义 Dockerfile 构建完整镜像

创建一个包含 Provider 的自定义 MusicAssistant 镜像。

### 步骤 1：创建 Dockerfile

在项目根目录创建 `Dockerfile`：

```dockerfile
FROM ghcr.io/music-assistant/server:latest

# 复制 Provider 代码
COPY netease_provider /app/custom_components/netease_provider

# 安装依赖
RUN pip install httpx>=0.24.0

# 设置工作目录（如果需要）
WORKDIR /app
```

### 步骤 2：构建镜像

```bash
cd /path/to/ma_netease_cloud_music
docker build -t music-assistant-with-netease:latest .
```

### 步骤 3：修改 docker-compose.yml

```yaml
services:
  music-assistant:
    image: music-assistant-with-netease:latest  # 使用自定义镜像
    # ... 其他配置保持不变
```

### 步骤 4：启动容器

```bash
docker-compose up -d
```

## 网络配置注意事项

由于 MusicAssistant 和 netease_cloud_music_api 都运行在 Docker 中，需要注意网络配置：

### 场景 1：两个容器在同一 docker-compose 中

如果两个服务在同一个 docker-compose.yml 中：

```yaml
services:
  music-assistant:
    # ... 配置
    depends_on:
      - netease-api
    # 使用服务名访问
    # API 地址配置为: http://netease-api:3000

  netease-api:
    image: binaryify/netease_cloud_music_api
    container_name: netease-api
    ports:
      - "3000:3000"
```

在 Provider 配置中，API 地址填写：`http://netease-api:3000`

### 场景 2：两个容器独立运行

如果使用 `network_mode: host`：

```yaml
services:
  music-assistant:
    network_mode: host
    # API 地址配置为: http://localhost:3000 或 http://127.0.0.1:3000
```

如果使用默认 bridge 网络：

```yaml
services:
  music-assistant:
    # 不使用 network_mode: host
    # 需要使用 host.docker.internal（Linux 需要额外配置）
    # 或使用服务器的实际 IP 地址
    # API 地址配置为: http://host.docker.internal:3000
    # 或: http://你的服务器IP:3000
```

**Linux 系统启用 host.docker.internal：**

在 docker-compose.yml 中添加：

```yaml
services:
  music-assistant:
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

## 验证安装

1. 查看容器日志，确认 Provider 已加载：

```bash
docker logs music-assistant | grep -i netease
```

2. 在 MusicAssistant Web 界面中：
   - 进入 **设置** > **Providers**
   - 查看 **Netease Cloud Music** Provider 状态
   - 应该显示为 **已连接** 或 **可用**

3. 测试搜索功能：
   - 在搜索框中输入歌曲名称
   - 应该能看到来自 "Netease Cloud Music" 的搜索结果

## 故障排查

### Provider 未出现在列表中

- 检查 volume 挂载路径是否正确
- 确认 `netease_provider` 目录结构完整（包含 `__init__.py` 和 `provider.py`）
- 查看容器日志：`docker logs music-assistant`

### Provider 无法连接

- 检查 API 地址配置是否正确
- 确认 netease_cloud_music_api 容器正在运行：`docker ps | grep netease`
- 测试 API 是否可访问：
  ```bash
  docker exec music-assistant curl http://your-api-url:3000
  ```

### 依赖安装失败

- 确认容器内有 pip 和网络访问权限
- 尝试手动进入容器安装：`docker exec -it music-assistant pip install httpx`

### 容器重启后 Provider 丢失

- 使用自定义镜像方式（方法三），而不是在容器内临时安装
- 或者使用 volume 挂载 + 自定义镜像安装依赖（方法一 + 方式 B）

## 推荐配置示例

完整的 docker-compose.yml 示例：

```yaml
version: '3'

services:
  music-assistant:
    image: ghcr.io/music-assistant/server:latest
    container_name: music-assistant
    restart: unless-stopped
    network_mode: host
    volumes:
      - /path/to/ma/data:/data
      - /path/to/ma/media:/media
      - /path/to/ma_netease_cloud_music/netease_provider:/app/custom_components/netease_provider
    environment:
      - LOG_LEVEL=info
    # 如果需要自定义镜像（已安装依赖）
    # image: music-assistant-custom:latest

  netease-api:
    image: binaryify/netease_cloud_music_api
    container_name: netease-api
    restart: unless-stopped
    ports:
      - "3000:3000"
```

在 Provider 配置中，API 地址填写：`http://localhost:3000`（因为使用了 `network_mode: host`）

