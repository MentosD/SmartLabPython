import sys
import os
import json
import time
import socket
import struct
import paho.mqtt.client as mqtt
from threading import Thread, Lock

# 配置信息 (优先使用环境变量或默认值)
MQTT_BROKER = "broker.emqx.io" 
MQTT_TOPIC = "smartlab/sensors/data"
UDP_IP = "0.0.0.0" # 监听所有网卡
UDP_PORT = 19001 

class DAQBridge:
    def __init__(self):
        self.mqtt_client = mqtt.Client()
        self.running = False
        self.last_send_time = 0
        self.send_interval = 0.1 # 10Hz
        self.data_buffer = {}
        self.buffer_lock = Lock()
        self.device_name = "DTLinks-DAQ"
        self.total_points_received = 0

    def start(self):
        try:
            print(f"正在连接 MQTT Broker: {MQTT_BROKER}...")
            self.mqtt_client.connect(MQTT_BROKER, 1883, 60)
            self.mqtt_client.loop_start()
            print("✅ MQTT 连接成功")
        except Exception as e:
            print(f"❌ MQTT 连接失败: {e}")
            print("💡 请确保已安装并启动了 MQTT Broker (如 Mosquitto) 或者将 config.py 里的地址改回公网地址。")
            return

        self.running = True
        self.udp_thread = Thread(target=self._udp_listen_loop, daemon=True)
        self.udp_thread.start()
        
        print(f"🚀 高性能采集桥接器已启动...")
        print(f"📡 监听 UDP {UDP_IP}:{UDP_PORT} | 📤 推送 MQTT {MQTT_TOPIC}")

        packet_count = 0
        try:
            while self.running:
                now = time.time()
                if now - self.last_send_time >= self.send_interval:
                    if self._push_to_mqtt():
                        packet_count += 1
                        if packet_count % 20 == 0:
                            print(f"📊 已推送 {packet_count} 批数据，当前缓冲区处理点数: {self.total_points_received}")
                    self.last_send_time = now
                time.sleep(0.01)
        except KeyboardInterrupt:
            self.stop()

    def _udp_listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024*1024) # 1MB 缓冲区
        try:
            sock.bind((UDP_IP, UDP_PORT))
            print(f"✅ UDP 端口 {UDP_PORT} 绑定成功")
        except Exception as e:
            print(f"❌ UDP Bind 失败: {e}"); return

        while self.running:
            try:
                data, addr = sock.recvfrom(8192)
                self._parse_packet(data)
            except Exception as e:
                if self.running:
                    print(f"UDP Recv Error: {e}")

    def _parse_packet(self, data):
        if len(data) < 16: return
        magic = struct.unpack('<I', data[0:4])[0]
        
        with self.buffer_lock:
            if magic == 0x52544853: # 单点包
                count = data[10]
                if len(data) < 16 + count * 4: return
                for i in range(count):
                    val = struct.unpack('<f', data[16+i*4:20+i*4])[0]
                    ch_key = f"CH{i+1}"
                    if ch_key not in self.data_buffer: self.data_buffer[ch_key] = []
                    self.data_buffer[ch_key].append(val)
                    self.total_points_received += 1
            
            elif magic == 0x52544842: # 批量包
                if len(data) < 32: return
                sample_count = struct.unpack('<I', data[12:16])[0]
                channel_count = data[16]
                if len(data) >= 32 + sample_count * channel_count * 4:
                    for s in range(sample_count):
                        offset = 32 + s * channel_count * 4
                        for i in range(channel_count):
                            val = struct.unpack('<f', data[offset + i*4 : offset + i*4 + 4])[0]
                            ch_key = f"CH{i+1}"
                            if ch_key not in self.data_buffer: self.data_buffer[ch_key] = []
                            self.data_buffer[ch_key].append(val)
                            self.total_points_received += 1

    def _push_to_mqtt(self):
        with self.buffer_lock:
            if not self.data_buffer: return False
            payload = {
                "timestamp": time.time(),
                "sensors": [{"name": self.device_name, "channels": self.data_buffer}]
            }
            self.data_buffer = {}
            # 这里不需要重置 total_points_received，让它一直增加作为计数器
            
        try:
            self.mqtt_client.publish(MQTT_TOPIC, json.dumps(payload))
            return True
        except Exception as e:
            print(f"MQTT Publish Error: {e}")
            return False

    def stop(self):
        self.running = False
        self.mqtt_client.loop_stop()
        print("🛑 桥接器已停止")

if __name__ == "__main__":
    bridge = DAQBridge(); bridge.start()
