# 在 Docker 容器中重启 MusicAssistant

当你已经将 Provider 放到容器内对应目录后，需要重启 MA 来加载新的 Provider。

## 方法一：重启整个容器（推荐）

这是最简单直接的方法：

### 使用 docker 命令

```bash
# 重启容器
docker restart music-assistant

# 或者使用容器 ID
docker restart <container-id>
```

### 使用 docker-compose

```bash
# 在 docker-compose.yml 所在目录
docker-compose restart music-assistant

# 或者重启所有服务
docker-compose restart
```

### 查看容器状态

```bash
# 查看容器是否正在运行
docker ps | grep music-assistant

# 查看容器日志，确认 MA 已启动
docker logs -f music-assistant
```

## 方法二：在容器内操作（如果需要）

如果你想在容器内部操作，可以：

### 1. 进入容器

```bash
docker exec -it music-assistant bash
# 或
docker exec -it music-assistant sh
```

### 2. 检查 Provider 文件

```bash
# 确认 Provider 文件已正确放置
ls -la /app/custom_components/netease_provider/

# 应该看到 __init__.py 和 provider.py
```

### 3. 检查依赖

```bash
# 检查 httpx 是否已安装
pip list | grep httpx

# 如果没有安装，安装它
pip install httpx>=0.24.0
```

### 4. 查找 MA 进程

```bash
# 查看运行中的进程
ps aux | grep -i music

# 或查看 Python 进程
ps aux | grep python
```

### 5. 重启 MA 服务（如果作为服务运行）

如果 MA 是作为 systemd 服务运行的（通常不是），可以：

```bash
# 在容器内（通常不适用）
systemctl restart music-assistant
```

**注意**：在 Docker 容器中，MA 通常直接作为主进程运行，不是 systemd 服务。

## 方法三：停止并重新启动容器

如果需要完全重新启动：

```bash
# 停止容器
docker stop music-assistant

# 启动容器
docker start music-assistant

# 或使用 docker-compose
docker-compose stop music-assistant
docker-compose start music-assistant
```

## 验证 Provider 是否加载成功

### 1. 查看日志

```bash
# 实时查看日志
docker logs -f music-assistant

# 搜索 Netease 相关日志
docker logs music-assistant | grep -i netease

# 查看最近的日志
docker logs --tail 100 music-assistant
```

### 2. 在 Web 界面验证

1. 访问 MusicAssistant Web 界面（通常是 `http://localhost:8095`）
2. 进入 **设置** > **Providers**
3. 查看是否出现 **Netease Cloud Music** Provider
4. 点击配置，填写 API 地址并保存

### 3. 测试搜索功能

在搜索框中输入歌曲名称，看是否能看到来自 "Netease Cloud Music" 的搜索结果。

## 常见问题

### Q: 重启后 Provider 仍然没有出现？

A: 检查以下几点：
- Provider 文件路径是否正确：`/app/custom_components/netease_provider/`
- 文件结构是否完整（需要 `__init__.py` 和 `provider.py`）
- 依赖是否已安装：`docker exec music-assistant pip list | grep httpx`
- 查看错误日志：`docker logs music-assistant | grep -i error`

### Q: 如何在容器重启后保持依赖？

A: 使用自定义镜像，参考 `INSTALL_DOCKER.md` 中的方法 B。

### Q: 如何查看容器内的文件系统？

A: 使用以下命令：
```bash
# 进入容器
docker exec -it music-assistant bash

# 查看文件
ls -la /app/custom_components/
cat /app/custom_components/netease_provider/__init__.py
```

### Q: 容器重启很慢？

A: 这是正常的，MA 需要时间初始化所有 Provider 和组件。查看日志确认进度：
```bash
docker logs -f music-assistant
```

## 快速命令参考

```bash
# 重启容器
docker restart music-assistant

# 查看日志
docker logs -f music-assistant

# 进入容器
docker exec -it music-assistant bash

# 检查 Provider 文件
docker exec music-assistant ls -la /app/custom_components/netease_provider/

# 安装依赖
docker exec music-assistant pip install httpx>=0.24.0

# 查看进程
docker exec music-assistant ps aux | grep python
```

