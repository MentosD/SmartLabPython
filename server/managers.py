import asyncio
import cv2
import base64
import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

class VideoManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast_text(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

# 创建4个视频管理器实例
video_managers = [VideoManager() for _ in range(4)]
