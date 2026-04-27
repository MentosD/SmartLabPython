import asyncio
import socket
import struct
import json
import time
import paho.mqtt.client as mqtt
import cv2
import base64
import numpy as np
from common.config import MQTT_BROKER, MQTT_TOPIC_DATA
from server.managers import video_managers

# 全局变量用于控制服务器端的采集任务
daq_task_running = False
daq_config = {"udp_ip": "0.0.0.0", "udp_port": 19001, "device_name": "DTLinks-DAQ"}

async def daq_udp_receiver():
    """服务器端 UDP 接收器：监听采集仪数据并分发"""
    global daq_task_running
    
    # 建立本地 MQTT 客户端用于分发数据
    client = mqtt.Client()
    try:
        client.connect(MQTT_BROKER, 1883, 60)
        client.loop_start()
    except Exception as e:
        print(f"Server DAQ Error: MQTT connection failed: {e}")
        return

    # 创建 UDP Socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False) # 异步非阻塞
    try:
        sock.bind((daq_config["udp_ip"], daq_config["udp_port"]))
        print(f"🚀 服务器采集引擎已启动: 监听 {daq_config['udp_ip']}:{daq_config['udp_port']}")
    except Exception as e:
        print(f"Server DAQ Error: UDP Bind failed: {e}")
        return

    loop = asyncio.get_event_loop()
    data_buffer = {}
    last_send_time = time.time()
    send_interval = 0.1 # 10Hz 批量转发
    
    daq_task_running = True
    try:
        while daq_task_running:
            try:
                # 尝试读取数据
                data, addr = await loop.sock_recvfrom(sock, 8192)
                
                # 解析逻辑
                if len(data) >= 16:
                    magic = struct.unpack('<I', data[0:4])[0]
                    if magic == 0x52544853: # 单点
                        count = data[10]
                        for i in range(count):
                            val = struct.unpack('<f', data[16+i*4:20+i*4])[0]
                            ch = f"CH{i+1}"
                            if ch not in data_buffer: data_buffer[ch] = []
                            data_buffer[ch].append(val)
                    elif magic == 0x52544842: # 批量
                        sample_count = struct.unpack('<I', data[12:16])[0]
                        channel_count = data[16]
                        for s in range(sample_count):
                            offset = 32 + s * channel_count * 4
                            for i in range(channel_count):
                                val = struct.unpack('<f', data[offset + i*4 : offset + i*4 + 4])[0]
                                ch = f"CH{i+1}"
                                if ch not in data_buffer: data_buffer[ch] = []
                                data_buffer[ch].append(val)
            except BlockingIOError:
                await asyncio.sleep(0.001)
                continue
            except Exception as e:
                print(f"UDP Receive error: {e}")

            # 定时分发数据给所有客户端
            now = time.time()
            if now - last_send_time >= send_interval:
                if data_buffer:
                    payload = {
                        "timestamp": now,
                        "sensors": [{"name": daq_config["device_name"], "channels": data_buffer}]
                    }
                    client.publish(MQTT_TOPIC_DATA, json.dumps(payload))
                    data_buffer = {}
                last_send_time = now
                
    finally:
        daq_task_running = False
        sock.close()
        client.loop_stop()
        print("🛑 服务器采集引擎已停止")

async def video_streamer(cam_id: int, rtsp_url: str = None):
    """针对特定通道的视频流采集"""
    source = rtsp_url if rtsp_url and rtsp_url.strip() else 0
    if source == 0 and cam_id > 0: source = -1
        
    cap = cv2.VideoCapture(source)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    manager = video_managers[cam_id]
    
    while True:
        ret, frame = cap.read()
        if not ret:
            frame = np.zeros((240, 320, 3), dtype=np.uint8)
            cv2.putText(frame, f"CAM {cam_id+1} OFFLINE", (50, 120), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 1)
            await asyncio.sleep(1)
            if rtsp_url: cap.open(source)
        else:
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 50])
            jpg_text = base64.b64encode(buffer).decode('utf-8')
            await manager.broadcast_text(jpg_text)
            await asyncio.sleep(0.05)
