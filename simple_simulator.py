#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
DTLinksCore 简化模拟器 v1.0

使用高端口号避免Windows权限问题的简化版本
提供与DTLinksCore相同的WebSocket和UDP通信接口
"""

import json
import socket
import struct
import threading
import time
import math
from typing import List, Dict, Any

# 使用高端口号避免权限问题
WS_PORT = 18080  # WebSocket控制端口
UDP_PORT = 19001  # UDP数据流端口

class SignalGenerator:
    """信号生成器"""
    
    def __init__(self, sample_rate: int = 1000):
        self.sample_rate = sample_rate
        self.dt = 1.0 / sample_rate
        self.reset()
        
        # 4通道不同频率
        self.frequencies = [5.0, 10.0, 15.0, 20.0]  # Hz
        self.amplitudes = [1.0, 5.0, 6.0, 7.0]      # V
    
    def reset(self):
        """重置信号生成器时间"""
        self.start_real_time = time.time()  # 记录真实开始时间
        print(f"📡 信号生成器时间已重置为0.000000秒，开始真实时间: {self.start_real_time:.6f}")
        
    def generate_sample(self) -> tuple[List[float], float]:
        """生成一个采样点的4通道数据和时间戳"""
        # 使用真实经过的时间作为时间戳
        real_elapsed_time = time.time() - self.start_real_time
        
        channels = []
        for i, (freq, amp) in enumerate(zip(self.frequencies, self.amplitudes)):
            # 使用真实时间生成正弦波
            value = amp * math.sin(2 * math.pi * freq * real_elapsed_time)
            channels.append(value)
        
        return channels, real_elapsed_time


class WebSocketServer:
    """简化的WebSocket服务器"""
    
    def __init__(self, host: str = "localhost", port: int = 18080):
        self.host = host
        self.port = port
        self.socket = None
        self.running = False
        
    def start(self) -> bool:
        """启动WebSocket服务器"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind((self.host, self.port))
            self.socket.listen(5)
            
            self.running = True
            
            # 启动接受连接的线程
            thread = threading.Thread(target=self._accept_connections, daemon=True)
            thread.start()
            
            print(f"WebSocket控制服务器已启动: {self.host}:{self.port}")
            return True
            
        except Exception as e:
            print(f"WebSocket服务器启动失败: {e}")
            return False
    
    def stop(self):
        """停止服务器"""
        self.running = False
        if self.socket:
            self.socket.close()
    
    def _accept_connections(self):
        """接受客户端连接"""
        while self.running:
            try:
                client_socket, address = self.socket.accept()
                print(f"WebSocket客户端连接: {address}")
                
                # 简单的WebSocket握手响应
                thread = threading.Thread(
                    target=self._handle_client, 
                    args=(client_socket,), 
                    daemon=True
                )
                thread.start()
                
            except Exception as e:
                if self.running:
                    print(f"接受连接异常: {e}")
                break
    
    def _handle_client(self, client_socket):
        """处理客户端请求"""
        try:
            # 读取HTTP请求
            request = client_socket.recv(1024).decode('utf-8')
            
            if 'Upgrade: websocket' in request:
                # 执行WebSocket握手
                key = None
                for line in request.split('\n'):
                    if 'Sec-WebSocket-Key:' in line:
                        key = line.split(':')[1].strip()
                        break
                
                if key:
                    # 生成接受响应
                    import base64
                    import hashlib
                    magic_string = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
                    response_key = base64.b64encode(
                        hashlib.sha1((key + magic_string).encode()).digest()
                    ).decode()
                    
                    response = (
                        "HTTP/1.1 101 Switching Protocols\r\n"
                        "Upgrade: websocket\r\n"
                        "Connection: Upgrade\r\n"
                        f"Sec-WebSocket-Accept: {response_key}\r\n\r\n"
                    )
                    
                    client_socket.send(response.encode())
                    print("WebSocket握手完成")
                    
                    # 保持连接
                    while self.running:
                        time.sleep(1)
                        # 发送状态更新
                        status_msg = json.dumps({
                            "type": "status",
                            "data": {"status": "running", "timestamp": time.time()}
                        })
                        try:
                            # 简单的WebSocket帧格式
                            self._send_websocket_frame(client_socket, status_msg)
                        except:
                            break
                            
        except Exception as e:
            print(f"处理客户端异常: {e}")
        finally:
            client_socket.close()
    
    def _send_websocket_frame(self, socket, message: str):
        """发送WebSocket帧"""
        try:
            message_bytes = message.encode('utf-8')
            length = len(message_bytes)
            
            # 简单的文本帧
            frame = bytearray()
            frame.append(0x81)  # FIN=1, TEXT frame
            
            if length < 126:
                frame.append(length)
            elif length < 65536:
                frame.append(126)
                frame.extend(struct.pack('>H', length))
            else:
                frame.append(127)
                frame.extend(struct.pack('>Q', length))
            
            frame.extend(message_bytes)
            socket.send(frame)
            
        except Exception as e:
            print(f"发送WebSocket帧失败: {e}")


class UDPDataServer:
    """UDP数据流服务器"""
    
    def __init__(self, host: str = "localhost", port: int = 19001):
        self.host = host
        self.port = port
        self.socket = None
        self.running = False
        self.clients = []
        self.signal_generator = SignalGenerator()
        
    def start(self) -> bool:
        """启动UDP服务器"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            self.running = True
            
            # 重置信号生成器，确保时间从0开始
            self.signal_generator.reset()
            
            # 添加DAQ客户端地址（DAQ软件监听19001端口）
            self.clients.append(("localhost", 19001))
            
            # 启动数据发送线程
            thread = threading.Thread(target=self._send_data_loop, daemon=True)
            thread.start()
            
            print(f"📡 UDP数据服务器已启动，将发送数据到: localhost:19001")
            print(f"📊 数据格式: 时间戳从0.000000秒开始，采样率1000Hz")
            return True
            
        except Exception as e:
            print(f"❌ UDP服务器启动失败: {e}")
            return False
    
    def stop(self):
        """停止服务器"""
        self.running = False
        if self.socket:
            self.socket.close()
    
    def _send_data_loop(self):
        """数据发送循环"""
        sequence = 0
        target_interval = 0.001  # 目标1ms间隔 (1000Hz)
        
        print("📡 UDP数据发送线程已启动，使用真实时间戳")
        
        # 记录发送开始时间
        loop_start_time = time.time()
        next_send_time = loop_start_time
        
        while self.running:
            try:
                current_time = time.time()
                
                # 检查是否到了发送时间
                if current_time >= next_send_time:
                    # 生成数据和时间戳
                    channels, timestamp = self.signal_generator.generate_sample()
                    
                    # 将时间戳转换为微秒整数 (UDP包格式要求)
                    timestamp_us = int(timestamp * 1000000)  # 转换为微秒
                    
                    # 构建数据包
                    packet = self._build_udp_packet(timestamp_us, sequence, channels)
                    
                    # 发送给所有客户端
                    for client_host, client_port in self.clients:
                        try:
                            self.socket.sendto(packet, (client_host, client_port))
                        except Exception as e:
                            print(f"❌ 发送UDP数据失败 {client_host}:{client_port}: {e}")
                    
                    sequence = (sequence + 1) % 65536
                    
                    # 每1000个数据包输出一次调试信息
                    if sequence % 1000 == 0:
                        real_elapsed = current_time - loop_start_time
                        print(f"📊 已发送 {sequence} 个数据包，时间戳: {timestamp:.6f}s，真实耗时: {real_elapsed:.6f}s")
                    
                    # 计算下次发送时间
                    next_send_time += target_interval
                    
                    # 如果落后太多，重新同步
                    if next_send_time < current_time - 0.1:  # 落后超过100ms时重新同步
                        next_send_time = current_time + target_interval
                        print(f"⚠️ 发送时间重新同步，当前时间: {current_time:.6f}")
                
                else:
                    # 精确等待到下次发送时间
                    sleep_time = max(0, next_send_time - current_time)
                    if sleep_time > 0:
                        time.sleep(min(sleep_time, 0.001))  # 最多睡眠1ms
                        
            except Exception as e:
                if self.running:
                    print(f"❌ UDP数据发送异常: {e}")
                break
        
        print("📡 UDP数据发送线程已退出")
    
    def _build_udp_packet(self, timestamp: int, sequence: int, channels: List[float]) -> bytes:
        """构建UDP数据包"""
        # 数据包格式: magic(4) + timestamp(4) + sequence(2) + channel_count(1) + format(1) + reserved(4) + data + checksum(4)
        magic = 0x52544853  # "DTLinks"
        channel_count = len(channels)
        data_format = 0  # float32
        
        # 构建数据包
        packet = struct.pack('<IIHBB4x', magic, timestamp, sequence, channel_count, data_format)
        
        # 添加通道数据
        for value in channels:
            packet += struct.pack('<f', value)
        
        # 计算校验码
        import zlib
        checksum = zlib.crc32(packet) & 0xffffffff
        packet += struct.pack('<I', checksum)
        
        return packet


class DTLinksCoreSimulator:
    """DTLinksCore模拟器主类"""
    
    def __init__(self, ws_port: int = 18080, udp_port: int = 19001):
        self.ws_port = ws_port
        self.udp_port = udp_port
        
        self.websocket_server = WebSocketServer("localhost", ws_port)
        self.udp_server = UDPDataServer("localhost", udp_port)
        
        self.running = False
    
    def start(self) -> bool:
        """启动模拟器"""
        print("正在启动DTLinksCore模拟器...")
        
        # 启动WebSocket服务器
        if not self.websocket_server.start():
            return False
        
        # 启动UDP服务器
        if not self.udp_server.start():
            self.websocket_server.stop()
            return False
        
        self.running = True
        
        print("🎉 DTLinksCore模拟器启动成功！")
        print(f"📡 WebSocket控制端口: {self.ws_port}")
        print(f"📊 UDP数据流端口: {self.udp_port}")
        print("🌊 信号: 4通道 1kHz采样率")
        print("📈 频率: CH1=5Hz, CH2=10Hz, CH3=15Hz, CH4=20Hz")
        print("⚠️  注意: 使用了非默认端口")
        
        return True
    
    def stop(self):
        """停止模拟器"""
        print("正在停止模拟器...")
        self.running = False
        
        if hasattr(self, 'websocket_server'):
            self.websocket_server.stop()
        if hasattr(self, 'udp_server'):
            self.udp_server.stop()
        
        print("模拟器已停止")
    
    def run_console(self):
        """运行控制台"""
        print("\n" + "="*60)
        print("  DTLinksCore 模拟器控制台")
        print("="*60)
        print("命令:")
        print("  status  - 显示状态信息")
        print("  quit    - 退出程序")
        print("="*60)
        
        while self.running:
            try:
                command = input("\n> ").strip().lower()
                
                if command == "quit" or command == "q":
                    break
                elif command == "status":
                    self._show_status()
                elif command == "":
                    continue
                else:
                    print("未知命令，输入 'quit' 退出")
                    
            except KeyboardInterrupt:
                break
            except EOFError:
                break
    
    def _show_status(self):
        """显示状态信息"""
        print("\n📊 模拟器状态:")
        print(f"  运行状态: {'✅ 运行中' if self.running else '❌ 已停止'}")
        print(f"  WebSocket端口: {self.ws_port}")
        print(f"  UDP端口: {self.udp_port}")
        print(f"  信号生成: 4通道 1kHz")
        
        # 显示真实运行时间
        if hasattr(self.udp_server.signal_generator, 'start_real_time'):
            real_runtime = time.time() - self.udp_server.signal_generator.start_real_time
            print(f"  真实运行时间: {real_runtime:.1f}s")
        else:
            print(f"  运行时间: 未启动")


def main():
    """主函数"""
    print("🚀 DTLinksCore 简化模拟器 v1.0")
    print("使用高端口号避免权限问题")
    print(f"📡 WebSocket端口: {WS_PORT}")
    print(f"📊 UDP端口: {UDP_PORT}")
    print()
    
    # 创建模拟器
    simulator = DTLinksCoreSimulator(ws_port=WS_PORT, udp_port=UDP_PORT)
    
    try:
        # 启动模拟器
        if simulator.start():
            print(f"\n⚠️  重要提示:")
            print(f"请在DAQ软件中设置连接参数:")
            print(f"  主机地址: localhost")
            print(f"  WebSocket端口: {WS_PORT}")
            print(f"  UDP端口: {UDP_PORT}")
            print()
            
            # 运行控制台
            simulator.run_console()
        else:
            print("❌ 模拟器启动失败")
            
    except KeyboardInterrupt:
        print("\n收到中断信号，正在退出...")
    except Exception as e:
        print(f"❌ 程序异常: {e}")
        import traceback
        traceback.print_exc()
    finally:
        simulator.stop()
        print("👋 再见！")


if __name__ == "__main__":
    main()