import os
import requests
from PySide6.QtWidgets import QWidget, QVBoxLayout, QFrame, QLineEdit, QPushButton, QHBoxLayout, QLabel, QMessageBox
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtCore import QUrl
from common.config import SERVER_URL

class ConferencePage(QWidget):
    def __init__(self, user_info, parent=None):
        super().__init__(parent)
        self.user_info = user_info
        self.is_joining = False
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        top_bar = QFrame()
        top_bar.setFixedHeight(60)
        top_bar.setStyleSheet("background: white; border-bottom: 1px solid #ddd;")
        top_layout = QHBoxLayout(top_bar)
        
        self.room_input = QLineEdit()
        self.room_input.setPlaceholderText("房间号...")
        self.room_input.setText("SmartLab_Default")
        self.room_input.setFixedWidth(200)
        
        self.join_btn = QPushButton("进入会议")
        self.join_btn.setStyleSheet("background: #27AE60; color: white; padding: 8px 20px; font-weight: bold;")
        self.join_btn.clicked.connect(self.handle_join)
        
        top_layout.addWidget(QLabel("<b>会议房间:</b>"))
        top_layout.addWidget(self.room_input)
        top_layout.addWidget(self.join_btn)
        top_layout.addStretch()
        layout.addWidget(top_bar)

        self.browser = QWebEngineView()
        
        # --- 深度权限开启 ---
        settings = self.browser.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.AllowRunningInsecureContent, True)
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        # 必须开启这个，屏幕共享按钮才会生效
        settings.setAttribute(QWebEngineSettings.ScreenCaptureEnabled, True)
        
        self.browser.page().featurePermissionRequested.connect(self.handle_permission)
        
        # 屏幕捕获信号处理
        if hasattr(self.browser.page(), 'desktopVideoCaptureRequested'):
            self.browser.page().desktopVideoCaptureRequested.connect(lambda r: r.accept())

        html_path = os.path.join(os.path.dirname(__file__), "conference.html")
        self.browser.setUrl(QUrl.fromLocalFile(html_path))
        layout.addWidget(self.browser)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

    def handle_permission(self, url, feature):
        print(f"DEBUG: 收到权限请求 -> {feature}")
        # 只要涉及媒体采集，一律授权
        f_str = str(feature).lower()
        if any(x in f_str for x in ["audio", "video", "capture"]):
            print(f"DEBUG: 自动授予权限")
            self.browser.page().setFeaturePermission(url, feature, QWebEnginePage.PermissionGrantedByUser)

    def handle_join(self):
        if self.is_joining: return
        
        if self.join_btn.text() == "进入会议":
            room_id = self.room_input.text()
            if not room_id: return
            self.is_joining = True
            self.join_btn.setEnabled(False) 
            self.start_conference(room_id)
        else:
            self.leave_conference()

    def start_conference(self, channel):
        uid = hash(self.user_info['username']) & 0x7FFFFFFF
        try:
            res_obj = requests.get(f"{SERVER_URL}/auth/agora_token", params={"channelName": channel, "uid": uid})
            if res_obj.status_code != 200:
                self.is_joining = False
                self.join_btn.setEnabled(True)
                return
            
            res = res_obj.json()
            # 发送到 JS
            js_code = f"join('{res['appId']}', '{channel}', '{res['token']}', {uid}, '{self.user_info['username']}')"
            self.browser.page().runJavaScript(js_code)
            
            self.join_btn.setText("离开会议")
            self.join_btn.setStyleSheet("background: #E74C3C; color: white; padding: 8px 20px; font-weight: bold;")
            self.join_btn.setEnabled(True)
            self.is_joining = False
        except Exception as e:
            print(f"ERROR: {e}")
            self.is_joining = False
            self.join_btn.setEnabled(True)

    def leave_conference(self):
        self.browser.page().runJavaScript("leaveChannel()")
        self.join_btn.setText("进入会议")
        self.join_btn.setStyleSheet("background: #27AE60; color: white; padding: 8px 20px; font-weight: bold;")
        self.is_joining = False
