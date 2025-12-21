# 自定义 MusicAssistant 镜像，包含 Netease Provider 依赖
# 使用方法：
#   docker build -f Dockerfile.ma -t music-assistant-custom:latest .

FROM ghcr.io/music-assistant/server:latest

# 安装 Provider 所需依赖
RUN pip install httpx>=0.24.0

