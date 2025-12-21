#!/bin/bash
# Provider 检查脚本
# 用法: ./check_provider.sh [容器名称]
# 默认容器名称: music-assistant

CONTAINER="${1:-music-assistant}"

echo "=========================================="
echo "MusicAssistant Netease Provider 检查脚本"
echo "=========================================="
echo "容器名称: $CONTAINER"
echo ""

# 检查容器是否运行
if ! docker ps | grep -q "$CONTAINER"; then
    echo "❌ 错误: 容器 '$CONTAINER' 未运行"
    echo "请先启动容器: docker start $CONTAINER"
    exit 1
fi

echo "✓ 容器正在运行"
echo ""

# 1. 检查 Provider 目录
echo "=== 1. 检查 Provider 目录 ==="
if docker exec $CONTAINER test -d /app/custom_components/netease_provider; then
    echo "✓ 目录存在: /app/custom_components/netease_provider"
    docker exec $CONTAINER ls -la /app/custom_components/netease_provider/
else
    echo "❌ 目录不存在: /app/custom_components/netease_provider"
    echo "   请检查 volume 挂载配置"
fi
echo ""

# 2. 检查必要文件
echo "=== 2. 检查必要文件 ==="
for file in __init__.py provider.py manifest.json; do
    if docker exec $CONTAINER test -f /app/custom_components/netease_provider/$file; then
        echo "✓ $file 存在"
    else
        echo "❌ $file 不存在"
    fi
done
echo ""

# 3. 检查文件内容
echo "=== 3. 检查 __init__.py 内容 ==="
docker exec $CONTAINER cat /app/custom_components/netease_provider/__init__.py 2>/dev/null || echo "❌ 无法读取文件"
echo ""

# 4. 检查 manifest.json
echo "=== 4. 检查 manifest.json ==="
if docker exec $CONTAINER test -f /app/custom_components/netease_provider/manifest.json; then
    docker exec $CONTAINER cat /app/custom_components/netease_provider/manifest.json
else
    echo "❌ manifest.json 不存在"
    echo "   建议复制 manifest.json 到容器内:"
    echo "   docker cp manifest.json $CONTAINER:/app/custom_components/netease_provider/manifest.json"
fi
echo ""

# 5. 检查依赖
echo "=== 5. 检查依赖 ==="
if docker exec $CONTAINER pip list 2>/dev/null | grep -q httpx; then
    echo "✓ httpx 已安装"
    docker exec $CONTAINER pip list | grep httpx
else
    echo "❌ httpx 未安装"
    echo "   请运行: docker exec $CONTAINER pip install httpx>=0.24.0"
fi
echo ""

# 6. 检查 Python 语法
echo "=== 6. 检查 Python 语法 ==="
echo "检查 __init__.py..."
if docker exec $CONTAINER python -m py_compile /app/custom_components/netease_provider/__init__.py 2>&1; then
    echo "✓ __init__.py 语法正确"
else
    echo "❌ __init__.py 有语法错误"
fi

echo "检查 provider.py..."
if docker exec $CONTAINER python -m py_compile /app/custom_components/netease_provider/provider.py 2>&1; then
    echo "✓ provider.py 语法正确"
else
    echo "❌ provider.py 有语法错误"
fi
echo ""

# 7. 测试导入
echo "=== 7. 测试导入 ==="
docker exec $CONTAINER python -c "
import sys
sys.path.insert(0, '/app/custom_components')
try:
    from netease_provider import NeteaseProvider
    print('✓ 导入成功')
    print('✓ NeteaseProvider 类:', NeteaseProvider)
    print('✓ domain 属性:', NeteaseProvider().domain if hasattr(NeteaseProvider(), 'domain') else 'N/A')
except Exception as e:
    print('❌ 导入失败:', str(e))
    import traceback
    traceback.print_exc()
" 2>&1
echo ""

# 8. 检查 MA 日志
echo "=== 8. 检查最近的日志（最后 30 行） ==="
docker logs --tail 30 $CONTAINER 2>&1 | grep -i -E "(error|exception|traceback|netease|provider)" || echo "没有找到相关日志"
echo ""

# 9. 检查 MA 版本
echo "=== 9. 检查 MusicAssistant 版本 ==="
docker exec $CONTAINER python -c "import music_assistant; print(f'MusicAssistant 版本: {music_assistant.__version__}')" 2>&1 || echo "无法获取版本信息"
echo ""

echo "=========================================="
echo "检查完成"
echo "=========================================="
echo ""
echo "如果 Provider 仍然未出现，请："
echo "1. 查看完整日志: docker logs $CONTAINER"
echo "2. 确认所有文件都在正确位置"
echo "3. 检查 TROUBLESHOOTING.md 获取更多帮助"

