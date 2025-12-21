# Provider 未加载问题排查指南

如果重启 MA 后 Provider 没有出现，请按照以下步骤逐一检查：

## 1. 检查文件位置和结构

### 进入容器检查

```bash
# 进入容器
docker exec -it music-assistant bash

# 检查 Provider 目录是否存在
ls -la /app/custom_components/

# 检查 netease_provider 目录
ls -la /app/custom_components/netease_provider/

# 应该看到以下文件：
# __init__.py
# provider.py
```

### 正确的目录结构

```
/app/custom_components/netease_provider/
├── __init__.py       # 必须存在
└── provider.py       # 必须存在
```

如果缺少文件，说明挂载有问题。

## 2. 检查 manifest.json 位置

根据 MusicAssistant 的规范，manifest.json 可能需要放在特定位置。尝试以下位置：

### 方式 A：在 netease_provider 目录下（推荐）

```bash
# 检查 manifest.json 是否在目录中
docker exec music-assistant ls -la /app/custom_components/netease_provider/

# 如果不存在，需要复制过去
docker cp manifest.json music-assistant:/app/custom_components/netease_provider/manifest.json
```

### 方式 B：检查是否需要放在其他位置

```bash
# 检查 MA 的配置目录
docker exec music-assistant ls -la /data/
docker exec music-assistant ls -la /config/
```

## 3. 检查文件内容

### 检查 __init__.py

```bash
docker exec music-assistant cat /app/custom_components/netease_provider/__init__.py
```

应该看到：
```python
"""Netease Cloud Music Provider for MusicAssistant."""

from .provider import NeteaseProvider

__all__ = ["NeteaseProvider"]
```

### 检查 provider.py 开头

```bash
docker exec music-assistant head -30 /app/custom_components/netease_provider/provider.py
```

### 检查 manifest.json

```bash
docker exec music-assistant cat /app/custom_components/netease_provider/manifest.json
```

## 4. 检查依赖

```bash
# 检查 httpx 是否安装
docker exec music-assistant pip list | grep httpx

# 如果没有安装，安装它
docker exec music-assistant pip install httpx>=0.24.0
```

## 5. 检查 Python 语法错误

```bash
# 检查 Python 语法
docker exec music-assistant python -m py_compile /app/custom_components/netease_provider/__init__.py
docker exec music-assistant python -m py_compile /app/custom_components/netease_provider/provider.py

# 如果没有错误，命令应该成功执行
```

## 6. 检查导入是否正确

```bash
# 在容器内测试导入
docker exec music-assistant python -c "import sys; sys.path.insert(0, '/app/custom_components'); from netease_provider import NeteaseProvider; print('导入成功')"
```

如果导入失败，会显示错误信息。

## 7. 查看 MA 日志

```bash
# 查看所有日志
docker logs music-assistant

# 搜索错误信息
docker logs music-assistant | grep -i error

# 搜索 netease 相关
docker logs music-assistant | grep -i netease

# 搜索 provider 相关
docker logs music-assistant | grep -i provider

# 查看最近的日志
docker logs --tail 100 music-assistant
```

## 8. 检查 MA 版本兼容性

```bash
# 查看 MA 版本
docker exec music-assistant python -c "import music_assistant; print(music_assistant.__version__)"
```

确保 Provider 代码与 MA 版本兼容。

## 9. 常见问题和解决方案

### 问题 1：文件不存在

**症状**：`ls` 命令显示目录为空或不存在

**解决**：
- 检查 volume 挂载配置是否正确
- 确认本地文件路径正确
- 重新挂载 volume

### 问题 2：导入错误

**症状**：测试导入时显示 `ModuleNotFoundError` 或 `ImportError`

**可能原因**：
- 依赖未安装（httpx, music_assistant 等）
- Python 路径问题
- 代码中有语法错误

**解决**：
- 安装缺失的依赖
- 检查代码语法
- 确认 MA 的 Python 环境

### 问题 3：manifest.json 找不到

**症状**：MA 无法识别 Provider

**解决**：
- 将 manifest.json 复制到 netease_provider 目录
- 确认 manifest.json 格式正确（JSON 格式）

### 问题 4：Provider 类未正确导出

**症状**：导入成功但 MA 不识别

**解决**：
- 确认 `__init__.py` 中正确导出了 `NeteaseProvider`
- 确认类名正确

## 10. 完整检查脚本

运行以下脚本进行完整检查：

```bash
#!/bin/bash
CONTAINER="music-assistant"

echo "=== 检查 Provider 目录 ==="
docker exec $CONTAINER ls -la /app/custom_components/netease_provider/ 2>&1

echo -e "\n=== 检查文件内容 ==="
echo "--- __init__.py ---"
docker exec $CONTAINER cat /app/custom_components/netease_provider/__init__.py 2>&1

echo -e "\n--- manifest.json ---"
docker exec $CONTAINER cat /app/custom_components/netease_provider/manifest.json 2>&1

echo -e "\n=== 检查依赖 ==="
docker exec $CONTAINER pip list | grep httpx

echo -e "\n=== 检查 Python 语法 ==="
docker exec $CONTAINER python -m py_compile /app/custom_components/netease_provider/__init__.py 2>&1
docker exec $CONTAINER python -m py_compile /app/custom_components/netease_provider/provider.py 2>&1

echo -e "\n=== 测试导入 ==="
docker exec $CONTAINER python -c "import sys; sys.path.insert(0, '/app/custom_components'); from netease_provider import NeteaseProvider; print('✓ 导入成功')" 2>&1

echo -e "\n=== 查看错误日志 ==="
docker logs $CONTAINER 2>&1 | tail -50 | grep -i -E "(error|exception|traceback|netease)" || echo "没有找到相关错误"
```

保存为 `check_provider.sh`，然后运行：

```bash
chmod +x check_provider.sh
./check_provider.sh
```

## 11. 如果仍然无法解决

1. **查看完整日志**：
   ```bash
   docker logs music-assistant > ma_logs.txt
   ```
   然后查看日志文件，搜索错误信息

2. **检查 MA 官方文档**：
   - 查看是否有 Provider 开发的更新要求
   - 检查是否有新的 API 变化

3. **简化测试**：
   - 创建一个最简单的 Provider 测试是否能加载
   - 逐步添加功能定位问题

4. **社区求助**：
   - 在 MusicAssistant 的 GitHub Issues 或 Discord 中提问
   - 提供完整的错误日志和检查结果

