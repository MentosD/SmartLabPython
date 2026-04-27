import os

# 基础路径
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAS_DIR = os.path.join(BASE_DIR, "uploads", "nas")

# 网络配置
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8000
SERVER_URL = f"http://localhost:{SERVER_PORT}"
VOICE_WS_URL = f"ws://localhost:{SERVER_PORT}/voice"
VIDEO_WS_URL = f"ws://localhost:{SERVER_PORT}/video"

# MQTT 配置
MQTT_BROKER = "broker.emqx.io"
MQTT_TOPIC_DATA = "smartlab/sensors/data"

# 音频配置
AUDIO_CHUNK = 1024
AUDIO_RATE = 44100

# 数据库配置
DATABASE_URL = "sqlite:///./smart_lab.db"
