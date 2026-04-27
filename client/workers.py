import json
import base64
import threading
from threading import Lock
import websocket
import socket
import struct
import time
import paho.mqtt.client as mqtt
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
from common.config import (MQTT_BROKER, MQTT_TOPIC_DATA, VIDEO_WS_URL, 
                         VOICE_WS_URL, AUDIO_CHUNK, AUDIO_RATE)

# 尝试导入音频库，失败则禁用相关功能
try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False

try:
    from agora_rtc import RTC_ENGINE_CONTEXT, IRtcEngineEventHandler, RtcEngine
    AGORA_AVAILABLE = True
except ImportError:
    AGORA_AVAILABLE = False

class AgoraWorker(QThread):
    user_joined = Signal(int)
    user_left = Signal(int)
    volume_indication = Signal(list)
    error_occurred = Signal(str)

    def __init__(self, app_id):
        super().__init__()
        self.app_id = app_id
        self.engine = None
        self._active = False

    def run(self):
        if not AGORA_AVAILABLE:
            self.error_occurred.emit("声网 SDK 未安装")
            return
        
        try:
            context = RTC_ENGINE_CONTEXT()
            context.appId = self.app_id
            self.engine = RtcEngine.create_rtc_engine()
            self.engine.initialize(context)
            
            # 开启音量检测
            self.engine.enableAudioVolumeIndication(200, 3, True)
            self.engine.enableAudio()
            
            # 这里由于 Python SDK 的事件监听机制通常需要阻塞或轮询，
            # 我们假设 SDK 内部有自己的处理线程。
            self._active = True
            while self._active:
                self.msleep(100)
        except Exception as e:
            self.error_occurred.emit(f"声网初始化失败: {e}")

    def join_channel(self, token, channel_id, uid):
        if self.engine:
            self.engine.joinChannel(token, channel_id, "", uid)

    def leave_channel(self):
        if self.engine:
            self.engine.leaveChannel()

    def stop(self):
        self._active = False
        if self.engine:
            self.engine.release()
        self.wait()

class MQTTWorker(QThread):
    data_received = Signal(dict)
    def __init__(self):
        super().__init__()
        self._active = True

    def run(self):
        client = mqtt.Client()
        # 增加异常处理以防消息解析失败导致线程退出
        def on_message(c, u, m):
            try:
                self.data_received.emit(json.loads(m.payload.decode()))
            except: pass
        client.on_message = on_message
        try:
            client.connect(MQTT_BROKER, 1883, 60)
            client.subscribe(MQTT_TOPIC_DATA)
            while self._active:
                client.loop(0.1)
        except:
            pass

    def stop(self):
        self._active = False
        self.wait()

class DAQBridgeWorker(QThread):
    """
    内置的高性能采集桥接器
    监听本地或远程采集仪的 UDP 数据并转发至 MQTT
    """
    status_msg = Signal(str)

    def __init__(self, udp_ip="0.0.0.0", udp_port=19001, device_name="DTLinks-DAQ"):
        super().__init__()
        self.udp_ip = udp_ip
        self.udp_port = udp_port
        self.device_name = device_name
        self.running = False
        self.mqtt_client = mqtt.Client()
        self.data_buffer = {}
        self.buffer_lock = Lock()
        self.last_send_time = 0
        self.send_interval = 0.1

    def run(self):
        try:
            self.mqtt_client.connect(MQTT_BROKER, 1883, 60)
            self.mqtt_client.loop_start()
            self.status_msg.emit("✅ MQTT 已连接")
        except Exception as e:
            self.status_msg.emit(f"❌ MQTT 连接失败: {e}")
            return

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024*1024)
        try:
            sock.bind((self.udp_ip, self.udp_port))
            self.status_msg.emit(f"📡 正在监听端口 {self.udp_port}...")
        except Exception as e:
            self.status_msg.emit(f"❌ UDP 绑定失败: {e}")
            return

        self.running = True
        while self.running:
            try:
                # 设置超时以免阻塞无法退出
                sock.settimeout(1.0)
                data, addr = sock.recvfrom(8192)
                self._parse_packet(data)
                
                now = time.time()
                if now - self.last_send_time >= self.send_interval:
                    self._push_to_mqtt()
                    self.last_send_time = now
            except socket.timeout:
                continue
            except Exception as e:
                print(f"DAQ Bridge Loop Error: {e}")

        sock.close()
        self.mqtt_client.loop_stop()

    def _parse_packet(self, data):
        if len(data) < 16: return
        magic = struct.unpack('<I', data[0:4])[0]
        with self.buffer_lock:
            if magic == 0x52544853: # 单点
                count = data[10]
                for i in range(count):
                    val = struct.unpack('<f', data[16+i*4:20+i*4])[0]
                    ch = f"CH{i+1}"
                    if ch not in self.data_buffer: self.data_buffer[ch] = []
                    self.data_buffer[ch].append(val)
            elif magic == 0x52544842: # 批量
                sample_count = struct.unpack('<I', data[12:16])[0]
                channel_count = data[16]
                for s in range(sample_count):
                    offset = 32 + s * channel_count * 4
                    for i in range(channel_count):
                        val = struct.unpack('<f', data[offset + i*4 : offset + i*4 + 4])[0]
                        ch = f"CH{i+1}"
                        if ch not in self.data_buffer: self.data_buffer[ch] = []
                        self.data_buffer[ch].append(val)

    def _push_to_mqtt(self):
        with self.buffer_lock:
            if not self.data_buffer: return
            payload = {
                "timestamp": time.time(),
                "sensors": [{"name": self.device_name, "channels": self.data_buffer}]
            }
            self.data_buffer = {}
        try:
            self.mqtt_client.publish(MQTT_TOPIC_DATA, json.dumps(payload))
        except: pass

    def stop(self):
        self.running = False
        self.wait()

try:
    import cv2
    import numpy as np
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

class VideoWorker(QThread):
    frame_received = Signal(QImage)
    status_changed = Signal(str)

    def __init__(self, camera_id=0, url=None):
        super().__init__()
        self.camera_id = camera_id
        self.url = url  # 如果有 URL，则使用 URL (RTSP)，否则使用 camera_id (本地设备)
        self._active = False
        self.cap = None

    def set_source(self, url):
        self.url = url
        if self.cap:
            self.cap.release()
            self.cap = None

    def run(self):
        if not OPENCV_AVAILABLE:
            self.status_changed.emit("OpenCV 未安装")
            return

        self._active = True
        
        while self._active:
            # 如果没有 URL，则不进行采集，显示等待信号
            if not self.url:
                self.status_changed.emit("等待配置 RTSP...")
                self.msleep(2000)
                continue

            if not self.cap or not self.cap.isOpened():
                self.status_changed.emit(f"正在连接 CAM-{self.camera_id+1}...")
                self.cap = cv2.VideoCapture(self.url)
                
                if not self.cap.isOpened():
                    self.status_changed.emit("连接失败，重试中...")
                    self.msleep(5000)  # 5秒后重试
                    continue
                self.status_changed.emit(f"CAM-{self.camera_id+1} 已连接")

            ret, frame = self.cap.read()
            if ret:
                # 转换 OpenCV 的 BGR 到 RGB，再转成 QImage
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                h, w, ch = frame.shape
                bytes_per_line = ch * w
                qimage = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
                self.frame_received.emit(qimage.copy())
            else:
                self.status_changed.emit("信号丢失")
                self.cap.release()
                self.cap = None
                self.msleep(1000)

    def stop(self):
        self._active = False
        if self.cap:
            self.cap.release()
        self.wait()

class VoiceWorker(QThread):
    def __init__(self):
        super().__init__()
        self._active = False
        self.pa = None
        if PYAUDIO_AVAILABLE:
            try:
                self.pa = pyaudio.PyAudio()
            except:
                pass

    def run(self):
        if not PYAUDIO_AVAILABLE or not self.pa:
            print("语音功能不可用: 未检测到音频设备或库")
            return
            
        self._active = True
        try:
            ws = websocket.create_connection(VOICE_WS_URL)
            stream_in = self.pa.open(format=pyaudio.paInt16, channels=1, rate=AUDIO_RATE, 
                                   input=True, frames_per_buffer=AUDIO_CHUNK)
            stream_out = self.pa.open(format=pyaudio.paInt16, channels=1, rate=AUDIO_RATE, 
                                    output=True, frames_per_buffer=AUDIO_CHUNK)
            
            def receive():
                while self._active:
                    try:
                        data = ws.recv()
                        if isinstance(data, bytes):
                            stream_out.write(data)
                    except:
                        break
            
            t = threading.Thread(target=receive, daemon=True)
            t.start()

            while self._active:
                try:
                    data = stream_in.read(AUDIO_CHUNK, exception_on_overflow=False)
                    ws.send_binary(data)
                except:
                    break
            
            stream_in.stop_stream()
            stream_in.close()
            stream_out.stop_stream()
            stream_out.close()
            ws.close()
        except Exception as e:
            print(f"语音线程异常: {e}")
        finally:
            self._active = False

    def stop(self):
        self._active = False
        self.wait()
