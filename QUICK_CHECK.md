# Provider 快速检查清单

如果 Provider 未出现在 MA 中，请按顺序检查以下项目：

## ✅ 快速检查步骤

### 1. 确认文件都在容器内正确位置

```bash
# 进入容器检查
docker exec -it music-assistant bash

# 应该看到以下文件
ls -la /app/custom_components/netease_provider/
# 应该显示：
# - __init__.py
# - provider.py  
# - manifest.json  ← 这个文件必须存在！
```

### 2. 如果 manifest.json 不存在，复制它

```bash
# 从项目目录复制到容器
docker cp manifest.json music-assistant:/app/custom_components/netease_provider/manifest.json
```

### 3. 安装依赖

```bash
docker exec music-assistant pip install httpx>=0.24.0
```

### 4. 测试导入（在容器内）

```bash
docker exec -it music-assistant python -c "import sys; sys.path.insert(0, '/app/custom_components'); from netease_provider import NeteaseProvider; print('成功!')"
```

如果这个命令成功，说明代码没问题。

### 5. 查看日志

```bash
# 查看所有错误
docker logs music-assistant | grep -i error

# 查看 netease 相关
docker logs music-assistant | grep -i netease

# 查看完整日志
docker logs music-assistant | tail -100
```

### 6. 完全重启容器

```bash
docker restart music-assistant
```

等待 30 秒后，再次检查日志。

## 🔍 使用自动检查脚本

运行提供的检查脚本：

```bash
./check_provider.sh music-assistant
```

这个脚本会自动检查所有常见问题。

## 📋 常见问题

| 问题 | 检查命令 | 解决方法 |
|------|---------|---------|
| 文件不存在 | `docker exec music-assistant ls /app/custom_components/netease_provider/` | 检查 volume 挂载 |
| manifest.json 缺失 | `docker exec music-assistant test -f /app/custom_components/netease_provider/manifest.json` | `docker cp manifest.json music-assistant:/app/custom_components/netease_provider/manifest.json` |
| 依赖未安装 | `docker exec music-assistant pip list \| grep httpx` | `docker exec music-assistant pip install httpx>=0.24.0` |
| 导入错误 | 见步骤 4 | 查看错误信息，通常是依赖或语法问题 |
| 没有日志 | `docker logs music-assistant \| tail -50` | 检查容器是否正常启动 |

## ⚠️ 重要提示

1. **manifest.json 必须在 netease_provider 目录中**
2. **所有文件必须有正确的权限（通常不是问题，除非手动修改过）**
3. **重启后等待 30-60 秒让 MA 完全加载**
4. **检查 MA 版本兼容性**

