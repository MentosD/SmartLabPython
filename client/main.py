import sys
import os
import requests
import base64
import cv2
import json
import numpy as np
import websockets
import asyncio
import threading
import pyqtgraph as pg
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QStackedWidget, QLabel, 
                             QTableWidget, QTableWidgetItem, QPushButton, QFileDialog, 
                             QMessageBox, QSplitter, QTreeWidget, QTreeWidgetItem, QFrame,
                             QGridLayout, QDialog, QLineEdit, QFormLayout, QComboBox,
                             QMenu, QInputDialog, QGraphicsDropShadowEffect,
                             QRadioButton, QButtonGroup, QCheckBox, QListWidget, QAbstractItemView, QHeaderView, QCompleter,
                             QDialogButtonBox)
from PySide6.QtCore import Qt, QTimer, Slot, QThread, Signal, QPoint, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap, QIcon, QImage, QFont, QAction, QColor

# 路径修复
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common.config import SERVER_URL
from client.workers import MQTTWorker, VoiceWorker
from client.conference_widget import ConferencePage

# 全局样式表
STYLE_SHEET = """
QMainWindow { background-color: #F8F9F9; }
QLabel { font-size: 14px; color: #2C3E50; }
QTreeWidget { background-color: white; border: 1px solid #D5DBDB; border-radius: 4px; font-size: 13px; outline: 0; }
QTreeWidget::item { height: 35px; border-bottom: 1px solid #F2F4F4; }
QTreeWidget::item:selected { background-color: #EBF5FB; color: #2980B9; }
QPushButton#NavButton { background-color: transparent; border: none; color: #BDC3C7; text-align: left; padding-left: 18px; font-size: 15px; font-weight: bold; height: 60px; }
QPushButton#NavButton:hover { background-color: #34495E; color: white; }
QPushButton#NavButton[active="true"] { background-color: #3498DB; color: white; border-left: 4px solid #AED6F1; }
QFrame#Sidebar { background-color: #2C3E50; }
QFrame#ContentCard { background-color: white; border-radius: 8px; border: 1px solid #E5E8E8; }
QComboBox { padding: 5px; border: 1px solid #D5DBDB; border-radius: 4px; min-width: 100px; }
"""

class VideoWorker(QThread):
    frame_received = Signal(int, QImage)
    def __init__(self, cam_id):
        super().__init__()
        self.cam_id = cam_id
        self.running = False

    def run(self):
        self.running = True
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        ws_url = SERVER_URL.replace("http", "ws") + f"/ws/video/{self.cam_id}"
        async def listen():
            try:
                async with websockets.connect(ws_url) as websocket:
                    while self.running:
                        try:
                            data = await websocket.recv()
                            img_data = base64.b64decode(data)
                            nparr = np.frombuffer(img_data, np.uint8)
                            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                            if frame is not None:
                                h, w, ch = frame.shape
                                img = QImage(frame.data, w, h, ch * w, QImage.Format_BGR888)
                                self.frame_received.emit(self.cam_id, img.copy())
                        except: await asyncio.sleep(0.1)
            except: pass
        try: loop.run_until_complete(listen())
        except: pass

    def stop(self):
        self.running = False
        self.wait()

class CamConfigDialog(QDialog):
    def __init__(self, cam_data, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"配置摄像头 - 通道 {cam_data['id']+1}")
        self.setFixedWidth(450)
        layout = QFormLayout(self)
        self.name_edit = QLineEdit(str(cam_data.get('name', '')))
        self.url_edit = QLineEdit(str(cam_data.get('rtsp_url', '')))
        self.ip_edit = QLineEdit(str(cam_data.get('ip', '')))
        layout.addRow("显示名称:", self.name_edit)
        layout.addRow("RTSP URL:", self.url_edit)
        layout.addRow("设备 IP:", self.ip_edit)
        btns = QHBoxLayout()
        save_btn = QPushButton("保存"); save_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("取消"); cancel_btn.clicked.connect(self.reject)
        btns.addWidget(save_btn); btns.addWidget(cancel_btn)
        layout.addRow(btns)
    def get_result(self):
        return {"name": self.name_edit.text(), "rtsp_url": self.url_edit.text(), "ip": self.ip_edit.text()}

class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Smart Lab - 账户登录")
        self.setFixedWidth(400)
        self.user_info = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.setSpacing(15)
        title = QLabel("智能实验室科研工作站")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: #2C3E50; margin-bottom: 20px;")
        layout.addWidget(title)
        self.user_input = QLineEdit()
        self.user_input.setPlaceholderText("请输入用户名")
        self.user_input.setMinimumHeight(45)
        self.user_input.setStyleSheet("padding-left: 10px; border: 1px solid #D5DBDB; border-radius: 4px;")
        layout.addWidget(self.user_input)
        self.pwd_input = QLineEdit()
        self.pwd_input.setPlaceholderText("请输入密码")
        self.pwd_input.setEchoMode(QLineEdit.Password)
        self.pwd_input.setMinimumHeight(45)
        self.pwd_input.setStyleSheet("padding-left: 10px; border: 1px solid #D5DBDB; border-radius: 4px;")
        layout.addWidget(self.pwd_input)
        self.login_btn = QPushButton("立即登录")
        self.login_btn.setMinimumHeight(50)
        self.login_btn.setStyleSheet("background-color: #3498DB; color: white; font-weight: bold; border-radius: 4px; font-size: 16px;")
        self.login_btn.clicked.connect(self.handle_login)
        layout.addWidget(self.login_btn)
    def handle_login(self):
        user = self.user_input.text()
        pwd = self.pwd_input.text()
        try:
            res = requests.post(f"{SERVER_URL}/auth/login", json={"username": user, "password": pwd})
            data = res.json()
            if data.get("success"):
                self.user_info = data["user"]; self.accept()
            else: QMessageBox.critical(self, "登录失败", data.get("message", "未知错误"))
        except: QMessageBox.critical(self, "网络错误", "无法连接服务器")

class AssetDialog(QDialog):
    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle("资产信息编辑" if data else "新增资产")
        self.setFixedWidth(500)
        layout = QFormLayout(self)
        self.inputs = {}
        try:
            cfg = requests.get(f"{SERVER_URL}/assets/config").json()
            cats, brands = cfg['categories'], cfg['brands']
        except: cats, brands = ["试验设备"], ["通用"]
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(cats); self.cat_combo.addItem("+ 新增类别...")
        if data: self.cat_combo.setCurrentText(data.get('category', ''))
        layout.addRow("资产类别:", self.cat_combo)
        self.brand_combo = QComboBox()
        self.brand_combo.addItems(brands); self.brand_combo.addItem("+ 新增品牌...")
        layout.addRow("制造商品牌:", self.brand_combo)
        self.no_edit = QLineEdit()
        self.no_edit.setReadOnly(True); self.no_edit.setStyleSheet("background: #F4F6F7; font-weight: bold; color: #2E86C1; height: 30px;")
        layout.addRow("资产编号 (10位):", self.no_edit); self.inputs['asset_no'] = self.no_edit
        self.name_edit = QLineEdit()
        if data: self.name_edit.setText(data.get('name', ''))
        self.setup_name_completer()
        layout.addRow("资产名称:", self.name_edit); self.inputs['name'] = self.name_edit
        fields = [("model", "型号规格"), ("location", "存放位置")]
        for key, label in fields:
            edit = QLineEdit()
            if data: edit.setText(str(data.get(key, "")))
            layout.addRow(label, edit); self.inputs[key] = edit
        self.cat_combo.currentTextChanged.connect(self.on_cat_changed)
        self.brand_combo.currentTextChanged.connect(self.on_brand_changed)
        if not data: self.auto_gen_code()
        else: self.no_edit.setText(data.get('asset_no', ""))
        btns = QHBoxLayout()
        save = QPushButton("确定"); save.clicked.connect(self.accept)
        cancel = QPushButton("取消"); cancel.clicked.connect(self.reject)
        btns.addWidget(save); btns.addWidget(cancel); layout.addRow(btns)
    def setup_name_completer(self):
        try:
            res = requests.get(f"{SERVER_URL}/assets/names").json()
            completer = QCompleter(res.get("names", []), self)
            completer.setCaseSensitivity(Qt.CaseInsensitive); completer.setFilterMode(Qt.MatchContains)
            self.name_edit.setCompleter(completer)
        except: pass
    def on_cat_changed(self, t):
        if t == "+ 新增类别...":
            v, ok = QInputDialog.getText(self, "新增类别", "名称:")
            if ok and v: self.cat_combo.insertItem(self.cat_combo.count()-1, v); self.cat_combo.setCurrentText(v)
        self.auto_gen_code()
    def on_brand_changed(self, t):
        if t == "+ 新增品牌...":
            v, ok = QInputDialog.getText(self, "新增品牌", "名称:")
            if ok and v: self.brand_combo.insertItem(self.brand_combo.count()-1, v); self.brand_combo.setCurrentText(v)
        self.auto_gen_code()
    def auto_gen_code(self):
        c, b = self.cat_combo.currentText(), self.brand_combo.currentText()
        if "+" in c or "+" in b: return
        try:
            res = requests.get(f"{SERVER_URL}/assets/next_code", params={"category": c, "brand": b}).json()
            self.no_edit.setText(res['code'])
        except: pass
    def get_data(self):
        d = {k: v.text() for k, v in self.inputs.items()}
        d['category'] = self.cat_combo.currentText()
        return d

class NasUploadDialog(QDialog):
    def __init__(self, parent=None, user_info=None):
        super().__init__(parent)
        self.user_info = user_info
        self.setWindowTitle("上传文件并设置权限")
        self.setFixedWidth(550)
        self.layout = QVBoxLayout(self)
        file_layout = QHBoxLayout()
        self.path_edit = QLineEdit(); self.path_edit.setPlaceholderText("请选择要上传的文件...")
        btn_browse = QPushButton("浏览..."); btn_browse.clicked.connect(self.browse_file)
        file_layout.addWidget(self.path_edit); file_layout.addWidget(btn_browse)
        self.layout.addLayout(file_layout)
        self.layout.addWidget(QLabel("<b>设置可见性:</b>"))
        self.btn_group = QButtonGroup(self)
        self.radio_private = QRadioButton("私有 (仅自己和管理员可见)")
        self.radio_public = QRadioButton("公开 (实验室内所有人可见)")
        self.radio_custom = QRadioButton("自定义 (指定组或指定成员可见)")
        self.radio_private.setChecked(True)
        self.btn_group.addButton(self.radio_private); self.btn_group.addButton(self.radio_public); self.btn_group.addButton(self.radio_custom)
        self.layout.addWidget(self.radio_private); self.layout.addWidget(self.radio_public); self.layout.addWidget(self.radio_custom)
        self.custom_panel = QFrame(); self.custom_panel.setFrameShape(QFrame.StyledPanel)
        self.custom_panel.setStyleSheet("background: #FBFCFC; border: 1px solid #D5DBDB; border-radius: 4px;")
        cp_layout = QVBoxLayout(self.custom_panel)
        list_layout = QHBoxLayout()
        group_vbox = QVBoxLayout(); group_vbox.addWidget(QLabel("指定课题组:"))
        self.group_list = QListWidget(); self.group_list.setSelectionMode(QAbstractItemView.MultiSelection)
        group_vbox.addWidget(self.group_list); list_layout.addLayout(group_vbox)
        user_vbox = QVBoxLayout(); user_vbox.addWidget(QLabel("指定成员:"))
        self.user_list = QListWidget(); self.user_list.setSelectionMode(QAbstractItemView.MultiSelection)
        user_vbox.addWidget(self.user_list); list_layout.addLayout(user_vbox)
        cp_layout.addLayout(list_layout)
        self.cb_write = QCheckBox("允许这些被授权的成员删除或覆盖此文件")
        cp_layout.addWidget(self.cb_write); self.layout.addWidget(self.custom_panel)
        self.custom_panel.setVisible(False); self.radio_custom.toggled.connect(lambda checked: self.custom_panel.setVisible(checked))
        btns = QHBoxLayout(); btn_ok = QPushButton("开始上传"); btn_ok.setStyleSheet("background: #3498DB; color: white; font-weight: bold; padding: 8px 20px;")
        btn_ok.clicked.connect(self.accept); btn_cancel = QPushButton("取消"); btns.addStretch(); btns.addWidget(btn_ok); btns.addWidget(btn_cancel)
        self.layout.addLayout(btns); self.load_system_data()
    def load_system_data(self):
        try:
            gs = requests.get(f"{SERVER_URL}/system/groups").json().get('groups', [])
            self.group_list.addItems(gs)
            us = requests.get(f"{SERVER_URL}/system/users").json().get('users', [])
            self.user_list.addItems([u['username'] for u in us if u['username'] != self.user_info['username']])
        except: pass
    def browse_file(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择文件")
        if p: self.path_edit.setText(p)
    def get_upload_data(self):
        pt = "private"
        if self.radio_public.isChecked(): pt = "public"
        elif self.radio_custom.isChecked(): pt = "custom"
        return { "file_path": self.path_edit.text(), "permission_type": pt, "allowed_groups": json.dumps([i.text() for i in self.group_list.selectedItems()]),
                 "allowed_users": json.dumps([i.text() for i in self.user_list.selectedItems()]), "allow_write": 1 if self.cb_write.isChecked() else 0 }

class HistoryDialog(QDialog):
    def __init__(self, asset_name, history, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"借还历史 - {asset_name}")
        self.setFixedWidth(550)
        layout = QVBoxLayout(self)
        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["用户", "操作", "时间"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.setRowCount(len(history))
        for i, h in enumerate(history):
            table.setItem(i, 0, QTableWidgetItem(h['username']))
            table.setItem(i, 1, QTableWidgetItem(h['action']))
            # 时间格式化: 2024-04-16 15:30
            t_str = h['time'][:16] if len(h['time']) > 16 else h['time']
            table.setItem(i, 2, QTableWidgetItem(t_str))
        layout.addWidget(table)
        btn = QPushButton("确定"); btn.clicked.connect(self.accept); layout.addWidget(btn)

class CameraDialog(QDialog):
    def __init__(self, parent=None, initial_data=None):
        super().__init__(parent)
        self.setWindowTitle("摄像头配置")
        self.setFixedWidth(400)
        layout = QFormLayout(self)
        initial_data = initial_data or {}
        self.name_edit = QLineEdit(initial_data.get('name', ''))
        self.ip_edit = QLineEdit(initial_data.get('ip', ''))
        self.port_edit = QLineEdit(initial_data.get('port', '554'))
        self.onvif_port_edit = QLineEdit(initial_data.get('onvif_port', '80'))
        self.user_edit = QLineEdit(initial_data.get('user', 'admin'))
        self.pwd_edit = QLineEdit(initial_data.get('pwd', ''))
        self.pwd_edit.setEchoMode(QLineEdit.Password)
        self.path_edit = QLineEdit(initial_data.get('path', 'stream1'))
        
        layout.addRow("名称:", self.name_edit)
        layout.addRow("IP地址:", self.ip_edit)
        layout.addRow("RTSP端口:", self.port_edit)
        layout.addRow("ONVIF端口:", self.onvif_port_edit)
        layout.addRow("用户名:", self.user_edit)
        layout.addRow("密码:", self.pwd_edit)
        layout.addRow("路径/通道:", self.path_edit)
        
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_data(self):
        # 自动清洗 IP 输入，去掉 http:// 或 rtsp:// 前缀及末尾斜杠
        raw_ip = self.ip_edit.text().strip()
        clean_ip = raw_ip.replace("http://", "").replace("https://", "").replace("rtsp://", "").rstrip("/")
        
        return {
            "name": self.name_edit.text().strip(),
            "ip": clean_ip,
            "port": self.port_edit.text().strip(),
            "onvif_port": self.onvif_port_edit.text().strip(),
            "user": self.user_edit.text().strip(),
            "pwd": self.pwd_edit.text().strip(),
            "path": self.path_edit.text().strip().lstrip("/") # 去掉路径开头的斜杠
        }

class ChannelConfigDialog(QDialog):
    def __init__(self, parent, channel_id, current_config):
        super().__init__(parent)
        self.setWindowTitle(f"配置通道: {channel_id}")
        self.setFixedWidth(350)
        layout = QFormLayout(self)
        self.name_edit = QLineEdit(current_config.get('name', channel_id))
        self.unit_edit = QLineEdit(current_config.get('unit', '-'))
        self.scale_edit = QLineEdit(str(current_config.get('scale', 1.0)))
        self.offset_edit = QLineEdit(str(current_config.get('offset', 0.0)))
        layout.addRow("显示名称:", self.name_edit)
        layout.addRow("单位:", self.unit_edit)
        layout.addRow("比例系数 (X):", self.scale_edit)
        layout.addRow("偏移量 (+):", self.offset_edit)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def get_data(self):
        try:
            return {
                "name": self.name_edit.text(),
                "unit": self.unit_edit.text(),
                "scale": float(self.scale_edit.text()),
                "offset": float(self.offset_edit.text())
            }
        except: return None

class DAQConfigDialog(QDialog):
    def __init__(self, parent, current_config):
        super().__init__(parent)
        self.setWindowTitle("采集仪配置")
        self.setFixedWidth(350)
        layout = QFormLayout(self)
        self.ip_edit = QLineEdit(current_config.get('ip', '0.0.0.0'))
        self.port_edit = QLineEdit(str(current_config.get('port', 19001)))
        self.name_edit = QLineEdit(current_config.get('name', 'DTLinks-DAQ'))
        layout.addRow("采集仪 IP:", self.ip_edit)
        layout.addRow("UDP 端口:", self.port_edit)
        layout.addRow("设备显示名称:", self.name_edit)
        self.status_lbl = QLabel("状态: 未连接")
        layout.addRow(self.status_lbl)
        
        btns = QHBoxLayout()
        self.start_btn = QPushButton("保存并启动")
        self.start_btn.setStyleSheet("background: #27AE60; color: white;")
        self.start_btn.clicked.connect(self.accept)
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setStyleSheet("background: #E74C3C; color: white;")
        self.stop_btn.clicked.connect(self.reject)
        btns.addWidget(self.start_btn); btns.addWidget(self.stop_btn)
        layout.addRow(btns)

    def get_data(self):
        return {
            "ip": self.ip_edit.text(),
            "port": int(self.port_edit.text()),
            "name": self.name_edit.text()
        }

class PopOutWindow(QWidget):
    def __init__(self, widget, title, on_close_callback):
        super().__init__()
        self.setWindowTitle(title)
        self.setMinimumSize(600, 400)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.widget = widget
        self.layout.addWidget(widget)
        self.on_close_callback = on_close_callback
        # 设置窗口标志，使其成为独立窗口并保持在最前（可选）
        self.setWindowFlags(Qt.Window)

    def closeEvent(self, event):
        self.layout.removeWidget(self.widget)
        self.on_close_callback(self.widget)
        event.accept()

class ClickableHeader(QFrame):
    doubleClicked = Signal()
    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.doubleClicked.emit()

class MainWindow(QMainWindow):
    def __init__(self, user_info):
        super().__init__()
        self.user_info = user_info
        if 'group_name' not in self.user_info: self.user_info['group_name'] = "未分配"
        self.setWindowTitle(f"Smart Lab - {user_info['username']} ({'管理员' if user_info['role']=='admin' else '普通用户'})")
        self.resize(1600, 1000); self.setStyleSheet(STYLE_SHEET)
        self.plot_mode, self.current_plot_target, self.plot_x_target, self.plot_y_target = "time", None, None, None
        self.units_map, self.data_history = {}, {}
        self.daq_configs = {} # 通道配置缓存
        # 延迟 1 秒获取配置，确保网络环境就绪
        QTimer.singleShot(1000, self.fetch_daq_configs)
        
        # 导入 VideoWorker
        from client.workers import MQTTWorker, VideoWorker, DAQBridgeWorker
        
        self.mqtt_worker = MQTTWorker()
        self.daq_bridge = None
        self.daq_bridge_config = {"ip": "0.0.0.0", "port": 19001, "name": "DTLinks-DAQ"}
        self.video_workers = [VideoWorker(camera_id=i) for i in range(4)]
        self.camera_configs = self.load_camera_configs()
        
        self.setup_ui(); self.connect_signals()
        self.mqtt_worker.start()
        
        # 加载初始摄像头 URL
        for i, config in self.camera_configs.items():
            idx = int(i)
            if idx < 4:
                url = f"rtsp://{config['user']}:{config['pwd']}@{config['ip']}:{config['port']}/{config['path']}"
                self.video_workers[idx].set_source(url)

    def load_camera_configs(self):
        try:
            if os.path.exists("camera_config.json"):
                with open("camera_config.json", "r") as f: return json.load(f)
        except: pass
        return {}

    def fetch_daq_configs(self):
        try:
            res = requests.get(f"{SERVER_URL}/daq/config")
            if res.status_code == 200:
                self.daq_configs = res.json()
        except Exception as e:
            print(f"Error fetching DAQ configs: {e}")

    def on_sensor_double_clicked(self, item, column):
        # 只有子节点（通道）才有 parent()，父节点（设备）没有
        if item.parent() is None:
            return
            
        # 获取 Channel ID
        channel_id = item.data(0, Qt.UserRole)
        if not channel_id:
            channel_id = f"{item.parent().text(0)}_{item.text(0)}"
            
        self.configure_channel(channel_id)

    def configure_channel(self, channel_id):
        current = self.daq_configs.get(channel_id, {})
        dlg = ChannelConfigDialog(self, channel_id, current)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            if data:
                try:
                    res = requests.post(f"{SERVER_URL}/daq/config/update", json={
                        "channel_id": channel_id,
                        **data
                    })
                    if res.status_code == 200:
                        QMessageBox.information(self, "成功", f"通道 {channel_id} 配置已同步到服务器")
                        self.fetch_daq_configs() # 刷新本地配置
                except:
                    QMessageBox.warning(self, "错误", "无法连接到服务器进行同步")

    def manage_daq_bridge(self):
        # 先获取服务器上的当前状态
        try:
            status_res = requests.get(f"{SERVER_URL}/daq/status").json()
            is_running = status_res.get("running", False)
            curr_config = status_res.get("config", self.daq_bridge_config)
        except:
            is_running = False
            curr_config = self.daq_bridge_config

        dlg = DAQConfigDialog(self, curr_config)
        if is_running:
            dlg.status_lbl.setText("状态: 🟢 服务器正在采集")
            dlg.start_btn.setText("更新配置并重启")
        
        if dlg.exec() == QDialog.Accepted:
            new_config = dlg.get_data()
            try:
                # 调用服务器 API 启动/重启采集
                res = requests.post(f"{SERVER_URL}/daq/start", json=new_config)
                if res.json().get("success"):
                    self.daq_bridge_config = new_config
                    QMessageBox.information(self, "成功", "服务器采集引擎已启动")
                else:
                    QMessageBox.warning(self, "失败", res.json().get("message"))
            except:
                QMessageBox.critical(self, "错误", "无法连接服务器启动采集")
        else:
            # 如果点击了“停止”按钮 (Rejected 逻辑在对话框中对应的是停止)
            try:
                res = requests.post(f"{SERVER_URL}/daq/stop")
                if res.status_code == 200:
                    QMessageBox.information(self, "信息", "服务器采集引擎已停止")
            except:
                QMessageBox.critical(self, "错误", "无法连接服务器停止采集")

    def save_camera_configs(self):
        try:
            with open("camera_config.json", "w") as f: json.dump(self.camera_configs, f)
        except: pass

    def setup_ui(self):
        central = QWidget(); self.setCentralWidget(central); main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0); main_layout.setSpacing(0)
        self.sidebar = QFrame(); self.sidebar.setObjectName("Sidebar"); self.sidebar.setFixedWidth(65)
        self.sidebar_layout = QVBoxLayout(self.sidebar); self.sidebar_layout.setContentsMargins(0, 20, 0, 0); self.sidebar_layout.setSpacing(5)
        self.nav_btns = []
        nav_items = [("🔬", " 试验监控", 0), ("📦", " 资产管理", 1), ("📂", " 数据中心", 2), ("📞", " 线上会议", 3)]
        for icon, text, idx in nav_items:
            if idx == 1 and self.user_info['role'] != 'admin': continue
            btn = QPushButton(icon); btn.setObjectName("NavButton"); btn.setProperty("active", "false"); btn.setToolTip(text.strip())
            btn.clicked.connect(lambda *args, i=idx: self.switch_page(i))
            self.sidebar_layout.addWidget(btn); self.nav_btns.append((btn, icon, text))
        self.sidebar_layout.addStretch(); main_layout.addWidget(self.sidebar)
        self.sidebar.setMouseTracking(True); self.sidebar.enterEvent = self.expand_sidebar; self.sidebar.leaveEvent = self.collapse_sidebar
        self.pages = QStackedWidget(); self.pages.setContentsMargins(15, 15, 15, 15); main_layout.addWidget(self.pages)
        self.init_field_page(); self.init_asset_page(); self.init_storage_page(); 
        
        # 集成语音会议模块
        self.conference_page = ConferencePage(self.user_info)
        self.pages.addWidget(self.conference_page)
        
        self.switch_page(0)

    def expand_sidebar(self, e):
        self.anim = QPropertyAnimation(self.sidebar, b"minimumWidth")
        self.anim.setDuration(200); self.anim.setStartValue(65); self.anim.setEndValue(180); self.anim.start()
        for b, i, t in self.nav_btns: b.setText(i + t)
    def collapse_sidebar(self, e):
        self.anim = QPropertyAnimation(self.sidebar, b"minimumWidth")
        self.anim.setDuration(200); self.anim.setStartValue(180); self.anim.setEndValue(65); self.anim.start()
        for b, i, t in self.nav_btns: b.setText(i)

    def switch_page(self, idx):
        self.pages.setCurrentIndex(idx)
        for i, (b, _, _) in enumerate(self.nav_btns): b.setProperty("active", "true" if i == idx else "false"); b.style().unpolish(b); b.style().polish(b)

    def init_field_page(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        
        sensor_card = QFrame()
        sensor_card.setObjectName("ContentCard")
        sensor_card.setFixedWidth(350)
        sc_layout = QVBoxLayout(sensor_card)
        
        title = QLabel("传感器通道列表")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        sc_layout.addWidget(title)
        
        self.sensor_tree = QTreeWidget(sensor_card)
        self.sensor_tree.setHeaderLabels(["通道名", "实时值", "单位"])
        self.sensor_tree.setDragEnabled(True)
        self.sensor_tree.setAcceptDrops(True)
        self.sensor_tree.setDropIndicatorShown(True)
        self.sensor_tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.sensor_tree.itemClicked.connect(self.on_sensor_selected)
        self.sensor_tree.itemDoubleClicked.connect(self.on_sensor_double_clicked)
        self.sensor_tree.dropEvent = self.on_sensor_drop
        
        sc_layout.addWidget(self.sensor_tree)
        layout.addWidget(sensor_card)
        self.video_card = QFrame()
        self.video_card.setObjectName("ContentCard")
        vc_layout = QVBoxLayout(self.video_card)
        
        # 使用可双击的标题栏
        self.video_header = ClickableHeader()
        self.video_header.setFixedHeight(30)
        h = QHBoxLayout(self.video_header)
        h.setContentsMargins(5, 0, 5, 0)
        h.addWidget(QLabel("<b>视频监控</b>"))
        h.addStretch()
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["单画面", "双画面", "四画面"])
        self.layout_combo.currentIndexChanged.connect(self.on_layout_changed)
        h.addWidget(self.layout_combo)
        
        self.video_header.doubleClicked.connect(lambda: self.pop_out_widget(self.video_card, "视频监控", "video"))
        vc_layout.addWidget(self.video_header)
        self.video_grid_widget = QWidget(); self.video_grid = QGridLayout(self.video_grid_widget); self.video_containers, self.video_labels = [], []
        for i in range(4):
            c = QFrame(); c.setStyleSheet("background: #1C2833; border-radius: 4px;"); v = QVBoxLayout(c)
            h = QHBoxLayout(); h.addWidget(QLabel(f"<font color='white'>CAM-{i+1}</font>"))
            
            # PTZ 控制按钮 (小型)
            ptz_layout = QHBoxLayout(); ptz_layout.setSpacing(2)
            for cmd, icon in [("up", "🔼"), ("down", "🔽"), ("left", "◀️"), ("right", "▶️"), ("zoom_in", "➕"), ("zoom_out", "➖")]:
                p_btn = QPushButton(icon); p_btn.setFixedSize(22, 22)
                p_btn.setStyleSheet("background: #2E4053; border: none; color: white; font-size: 10px;")
                p_btn.pressed.connect(lambda *args, idx=i, c=cmd: self.ptz_control(idx, c, True))
                p_btn.released.connect(lambda *args, idx=i, c=cmd: self.ptz_control(idx, c, False))
                ptz_layout.addWidget(p_btn)
            h.addLayout(ptz_layout)
            
            h.addStretch()
            btn = QPushButton("⚙️"); btn.setFixedSize(24, 24)
            btn.clicked.connect(lambda *args, idx=i: self.configure_camera(idx)); h.addWidget(btn); v.addLayout(h)
            lbl = QLabel("NO SIGNAL"); lbl.setAlignment(Qt.AlignCenter); lbl.setStyleSheet("color: #566573; font-size: 18px;"); v.addWidget(lbl)
            self.video_containers.append(c); self.video_labels.append(lbl)
        vc_layout.addWidget(self.video_grid_widget)
        
        # 1. 定义绘图容器
        self.plot_container = QWidget()
        self.plot_grid = QGridLayout(self.plot_container)
        self.plot_grid.setContentsMargins(0, 0, 0, 0)
        self.plot_grid.setSpacing(5)
        self.active_plots = {}

        # 2. 定义 Splitter 并组装
        self.right_splitter = QSplitter(Qt.Vertical)
        self.right_splitter.addWidget(self.video_card)
        self.right_splitter.addWidget(self.plot_container)
        self.right_splitter.setStretchFactor(0, 1)
        self.right_splitter.setStretchFactor(1, 1)

        layout.addWidget(self.right_splitter)
        self.pages.addWidget(page); self.on_layout_changed(0)


    def add_plot_window(self, channel_id):
        if channel_id in self.active_plots: return
        if len(self.active_plots) >= 4:
            QMessageBox.warning(self, "提醒", "最多支持同时显示 4 个绘图窗口")
            return

        cfg = self.daq_configs.get(channel_id, {})
        display_name = cfg.get("name", channel_id)
        unit = cfg.get("unit", "-")

        card = QFrame(); card.setObjectName("ContentCard")
        l = QVBoxLayout(card); l.setContentsMargins(5,5,5,5)
        
        # 使用可双击的标题栏
        header_widget = ClickableHeader()
        header = QHBoxLayout(header_widget)
        header.setContentsMargins(0,0,0,0)
        title = QLabel(f"<b>{display_name} </b>")
        close_btn = QPushButton("×")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet("background: #E74C3C; color: white; border-radius: 10px; font-weight: bold;")
        close_btn.clicked.connect(lambda: self.remove_plot_window(channel_id))
        header.addWidget(title); header.addStretch(); header.addWidget(close_btn)
        
        header_widget.doubleClicked.connect(lambda: self.pop_out_widget(card, f"绘图: {display_name}", f"plot_{channel_id}"))
        l.addWidget(header_widget)

        pw = pg.PlotWidget(background='w')
        pw.setLabel('left', "数值", units=unit)
        pw.setLabel('bottom', "时间", units="s")
        pw.setXRange(0, 100, padding=0)
        curve = pw.plot(pen=pg.mkPen('#E74C3C', width=2))
        l.addWidget(pw)

        # 计算网格位置 (最多2x2)
        idx = len(self.active_plots)
        self.plot_grid.addWidget(card, idx // 2, idx % 2)
        
        self.active_plots[channel_id] = {"frame": card, "plot": pw, "curve": curve}

    def remove_plot_window(self, channel_id):
        if channel_id in self.active_plots:
            info = self.active_plots.pop(channel_id)
            widget = info["frame"]
            try:
                # 检查 widget 是否仍然有效
                if widget:
                    if hasattr(widget, "_floating_win"):
                        # 清理弹出窗口
                        fw = widget._floating_win
                        fw.on_close_callback = None # 移除回调防止重复触发
                        fw.close()
                        delattr(widget, "_floating_win")
                    
                    # 安全地从父级脱离并标记销毁
                    widget.setParent(None)
                    widget.deleteLater()
            except (RuntimeError, ReferenceError):
                pass # 对象已由 Qt 内部销毁
            
            self.reorder_plots()

    def reorder_plots(self):
        while self.plot_grid.count():
            it = self.plot_grid.takeAt(0)
            if it.widget(): it.widget().setParent(None)
        
        # 仅将未弹出的窗口加回网格
        visible_idx = 0
        for cid, info in self.active_plots.items():
            if not hasattr(info["frame"], "_floating_win"):
                self.plot_grid.addWidget(info["frame"], visible_idx // 2, visible_idx % 2)
                visible_idx += 1

    def pop_out_widget(self, widget, title, type_id):
        if hasattr(widget, "_floating_win"): return
        
        # 记录弹出状态
        widget._floating_win = PopOutWindow(widget, title, lambda w: self.dock_back_widget(w, type_id))
        widget._floating_win.show()
        
        # 如果是绘图窗口，重新排列剩余窗口以填补空隙
        if type_id.startswith("plot_"):
            self.reorder_plots()

    def dock_back_widget(self, widget, type_id):
        if hasattr(widget, "_floating_win"):
            # 必须先删除属性，否则 reorder_plots 会认为它还在弹出状态
            delattr(widget, "_floating_win")
        
        if type_id == "video":
            self.right_splitter.insertWidget(0, widget)
        elif type_id.startswith("plot_"):
            self.reorder_plots()

    def init_asset_page(self):
        p = QWidget(); l = QVBoxLayout(p); tool_bar = QHBoxLayout()
        self.asset_search = QLineEdit(); self.asset_search.setPlaceholderText("🔍 搜索..."); self.asset_search.returnPressed.connect(self.refresh_assets)
        add_btn = QPushButton("➕ 新增资产"); add_btn.clicked.connect(self.add_asset)
        export_tmpl_btn = QPushButton("导出模板"); export_tmpl_btn.clicked.connect(self.export_asset_template)
        import_btn = QPushButton("导入数据"); import_btn.clicked.connect(self.import_assets)
        scan_btn = QPushButton("扫码借还"); scan_btn.clicked.connect(self.mock_scan_action)
        refresh_btn = QPushButton("刷新"); refresh_btn.clicked.connect(self.refresh_assets)
        tool_bar.addWidget(self.asset_search); tool_bar.addWidget(add_btn); tool_bar.addWidget(export_tmpl_btn); tool_bar.addWidget(import_btn); tool_bar.addWidget(scan_btn); tool_bar.addStretch(); tool_bar.addWidget(refresh_btn); l.addLayout(tool_bar)
        self.asset_table = QTableWidget(); headers = ["ID", "资产编号", "名称", "类别", "型号规格", "存放位置", "状态", "占用人", "操作"]
        self.asset_table.setColumnCount(len(headers)); self.asset_table.setHorizontalHeaderLabels(headers)
        self.asset_table.setContextMenuPolicy(Qt.CustomContextMenu); self.asset_table.customContextMenuRequested.connect(self.show_asset_context_menu)
        self.asset_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.asset_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); l.addWidget(self.asset_table); self.pages.addWidget(p); self.refresh_assets()

    def refresh_assets(self):
        try:
            q = self.asset_search.text()
            res = requests.get(f"{SERVER_URL}/assets", params={"q": q}).json()
            self.asset_table.setRowCount(0)
            for i, d in enumerate(res):
                self.asset_table.insertRow(i)
                is_borrowed = d['status'] == "借出"
                keys = ["id", "asset_no", "name", "category", "model", "location", "status", "current_user"]
                for j, k in enumerate(keys):
                    it = QTableWidgetItem(str(d.get(k, "")) if d.get(k) else "--"); it.setTextAlignment(Qt.AlignCenter)
                    if is_borrowed: it.setBackground(QColor("#EBEDEF"))
                    self.asset_table.setItem(i, j, it)
                btn_box = QWidget(); bh = QHBoxLayout(btn_box); bh.setContentsMargins(2,2,2,2)
                act_btn = QPushButton("借用" if d['status']=="在库" else "归还")
                act_btn.clicked.connect(lambda *args, aid=d['id'], act=act_btn.text(): self.handle_asset_action(aid, act))
                his_btn = QPushButton("📜 历史")
                his_btn.clicked.connect(lambda *args, aid=d['id'], name=d['name']: self.view_asset_history(aid, name))
                bh.addWidget(act_btn); bh.addWidget(his_btn)
                self.asset_table.setCellWidget(i, 8, btn_box)
        except: pass

    def view_asset_history(self, aid, name):
        try:
            res = requests.get(f"{SERVER_URL}/assets/{aid}/history").json()
            HistoryDialog(name, res, self).exec()
        except: pass

    def show_asset_context_menu(self, pos):
        item = self.asset_table.itemAt(pos)
        if not item: return
        row, aid = item.row(), int(self.asset_table.item(item.row(), 0).text())
        m = QMenu(self); edit_act = m.addAction("✏️ 编辑"); del_act = m.addAction("❌ 删除")
        a = m.exec(self.asset_table.mapToGlobal(pos))
        if a == edit_act: self.edit_asset(aid, row)
        elif a == del_act: self.delete_asset(aid)

    def edit_asset(self, aid, row):
        d = { k: self.asset_table.item(row, i).text() for i, k in enumerate(["id", "asset_no", "name", "category", "model", "location", "status", "current_user"]) }
        dlg = AssetDialog(self, d)
        if dlg.exec(): requests.put(f"{SERVER_URL}/assets/{aid}", json=dlg.get_data()); self.refresh_assets()

    def add_asset(self):
        d = AssetDialog(self)
        if d.exec(): requests.post(f"{SERVER_URL}/assets", json=d.get_data()); self.refresh_assets()

    def export_asset_template(self):
        p, _ = QFileDialog.getSaveFileName(self, "保存模板", "template.csv", "CSV (*.csv)")
        if p:
            r = requests.get(f"{SERVER_URL}/assets/template")
            with open(p, 'wb') as f: f.write(r.content)

    def import_assets(self):
        p, _ = QFileDialog.getOpenFileName(self, "导入数据", "", "CSV (*.csv)")
        if p:
            dummy = [{"asset_no": "0110100001", "name": "作动器", "category": "试验设备", "model": "MTS", "location": "棚库"}]
            requests.post(f"{SERVER_URL}/assets/import", json=dummy); self.refresh_assets()

    def delete_asset(self, aid):
        if QMessageBox.question(self, "确认", "确定删除？") == QMessageBox.Yes: requests.delete(f"{SERVER_URL}/assets/{aid}"); self.refresh_assets()

    def handle_asset_action(self, aid, act):
        requests.post(f"{SERVER_URL}/assets/action", json={"asset_id": aid, "action": act, "username": self.user_info['username']})
        self.refresh_assets()

    def mock_scan_action(self):
        c, ok = QInputDialog.getText(self, "扫码", "编号:")
        if ok and c:
            res = requests.get(f"{SERVER_URL}/assets", params={"q": c}).json()
            a = next((x for x in res if x['asset_no'] == c), None)
            if a: self.handle_asset_action(a['id'], "归还" if a['status']=="借出" else "借用")

    def init_storage_page(self):
        page = QWidget(); layout = QVBoxLayout(page); tool_bar = QHBoxLayout()
        tool_bar.addWidget(QLabel("<h2>📂 数据中心 </h2>")); tool_bar.addStretch()
        btn_up = QPushButton("📤 上传"); btn_up.clicked.connect(self.upload_nas_file)
        btn_ref = QPushButton("🔄 刷新"); btn_ref.clicked.connect(self.refresh_nas_files)
        tool_bar.addWidget(btn_up); tool_bar.addWidget(btn_ref); layout.addLayout(tool_bar)
        self.nas_table = QTableWidget(); self.nas_table.setColumnCount(7); self.nas_table.setHorizontalHeaderLabels(["ID", "文件名", "大小", "上传者", "时间", "可见性", "操作"])
        self.nas_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); layout.addWidget(self.nas_table); self.pages.addWidget(page); self.refresh_nas_files()

    def refresh_nas_files(self):
        try:
            p = {"username": self.user_info['username'], "group_name": self.user_info.get('group_name', '未分配'), "role": self.user_info['role']}
            res = requests.get(f"{SERVER_URL}/nas/list", params=p).json().get("files", [])
            self.nas_table.setRowCount(0)
            for i, f in enumerate(res):
                self.nas_table.insertRow(i)
                for j, v in enumerate([str(f['id']), f['filename'], f"{f['size']/1024:.1f}KB", f['uploader'], f['upload_time'], f['permission_type']]):
                    it = QTableWidgetItem(v); it.setTextAlignment(Qt.AlignCenter); self.nas_table.setItem(i, j, it)
                btn_box = QWidget(); bh = QHBoxLayout(btn_box); bh.setContentsMargins(0,0,0,0)
                dl = QPushButton("下载"); dl.clicked.connect(lambda *args, fid=f['id'], fname=f['filename']: self.download_nas_file(fid, fname)); bh.addWidget(dl)
                if f['can_edit']:
                    de = QPushButton("删除"); de.clicked.connect(lambda *args, fid=f['id']: self.delete_nas_file(fid)); bh.addWidget(de)
                self.nas_table.setCellWidget(i, 6, btn_box)
        except: pass

    def upload_nas_file(self):
        dlg = NasUploadDialog(self, self.user_info)
        if dlg.exec():
            d = dlg.get_upload_data()
            requests.post(f"{SERVER_URL}/nas/upload", data={"uploader": self.user_info['username'], "permission_type": d['permission_type'], "allowed_groups": d['allowed_groups'], "allowed_users": d['allowed_users'], "allow_write": d['allow_write']}, files={"file": open(d['file_path'], 'rb')})
            self.refresh_nas_files()

    def download_nas_file(self, fid, original_name):
        # 自动建议原始文件名作为保存名
        p, _ = QFileDialog.getSaveFileName(self, "下载文件 - 另存为", original_name)
        if p:
            try:
                r = requests.get(f"{SERVER_URL}/nas/download/{fid}", 
                                 params={"username": self.user_info['username'], 
                                         "group_name": self.user_info.get('group_name', '未分配'), 
                                         "role": self.user_info['role']}, 
                                 stream=True)
                if r.status_code == 200:
                    with open(p, 'wb') as f:
                        for c in r.iter_content(8192): f.write(c)
                    QMessageBox.information(self, "成功", f"文件已保存至:\n{p}")
                else:
                    QMessageBox.warning(self, "失败", f"无法下载文件: {r.status_code}")
            except Exception as e:
                QMessageBox.critical(self, "错误", str(e))

    def delete_nas_file(self, fid):
        if QMessageBox.question(self, "确认", "删除文件？") == QMessageBox.Yes:
            requests.delete(f"{SERVER_URL}/nas/delete/{fid}", params={"username": self.user_info['username'], "group_name": self.user_info.get('group_name', '未分配'), "role": self.user_info['role']})
            self.refresh_nas_files()

    def on_sensor_selected(self, item, col):
        if not item.parent(): return
        
        # 获取真实的 Channel ID
        channel_id = item.data(0, Qt.UserRole)
        if not channel_id:
            channel_id = f"{item.parent().text(0)}_{item.text(0)}"
            
        # 检查是否按下了 Ctrl 键 (在 macOS 上通常也是使用 Control 键或者 Command 键，PySide 中 Qt.ControlModifier 兼容两者)
        modifiers = QApplication.keyboardModifiers()
        if modifiers == Qt.ControlModifier:
            # 新增模式
            self.add_plot_window(channel_id)
        else:
            # 替换模式：先清空所有，再添加当前的
            for cid in list(self.active_plots.keys()):
                self.remove_plot_window(cid)
            self.add_plot_window(channel_id)
    def show_sensor_context_menu(self, pos): pass
    def on_layout_changed(self, idx):
        while self.video_grid.count():
            it = self.video_grid.takeAt(0)
            if it.widget(): it.widget().setParent(None)
        t = [0] if idx==0 else ([0,1] if idx==1 else [0,1,2,3])
        c = 1 if idx==0 else 2
        for i, cid in enumerate(t):
            self.video_containers[cid].show(); self.video_grid.addWidget(self.video_containers[cid], i//c, i%c)
            if not self.video_workers[cid].isRunning(): 
                self.video_workers[cid].start()

    def update_video(self, img, cid):
        if self.video_containers[cid].isVisible():
            p = QPixmap.fromImage(img); l = self.video_labels[cid]
            l.setPixmap(p.scaled(l.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def update_video_status(self, status, cid):
        if not self.video_labels[cid].pixmap():
            self.video_labels[cid].setText(status)

    def configure_camera(self, idx):
        initial = self.camera_configs.get(str(idx), {})
        dlg = CameraDialog(self, initial)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.get_data()
            self.camera_configs[str(idx)] = data
            self.save_camera_configs()
            
            # 重新生成 RTSP URL 并重新连接
            url = f"rtsp://{data['user']}:{data['pwd']}@{data['ip']}:{data['port']}/{data['path']}"
            self.video_workers[idx].stop()
            self.video_workers[idx].set_source(url)
            self.video_workers[idx].start()
            QMessageBox.information(self, "设置成功", f"CAM-{idx+1} 配置已更新")

    def ptz_control(self, idx, cmd, is_start):
        """控制摄像头 PTZ"""
        config = self.camera_configs.get(str(idx))
        if not config: return
        
        # 为了防止界面卡顿，PTZ 操作应在后台执行
        threading.Thread(target=self._exec_ptz, args=(config, cmd, is_start), daemon=True).start()

    def _exec_ptz(self, config, cmd, is_start):
        try:
            from onvif import ONVIFCamera
            # 兼容性处理：如果配置中没有 onvif_port，则默认使用 80
            onvif_port = int(config.get('onvif_port', 80))
            mycam = ONVIFCamera(config['ip'], onvif_port, config['user'], config['pwd'])
            ptz = mycam.create_ptz_service()
            media = mycam.create_media_service()
            profile = media.GetProfiles()[0]
            
            request = ptz.create_type('ContinuousMove')
            request.ProfileToken = profile.token
            
            if not is_start:
                ptz.Stop({'ProfileToken': profile.token})
                return

            status = ptz.GetStatus({'ProfileToken': profile.token})
            request.Velocity = status.Position # 默认速度
            
            # 设定速度向量 (x: pan, y: tilt, z: zoom)
            vx, vy, vz = 0, 0, 0
            speed = 0.5
            if cmd == "up": vy = speed
            elif cmd == "down": vy = -speed
            elif cmd == "left": vx = -speed
            elif cmd == "right": vx = speed
            elif cmd == "zoom_in": vz = speed
            elif cmd == "zoom_out": vz = -speed
            
            request.Velocity.PanTilt.x = vx
            request.Velocity.PanTilt.y = vy
            request.Velocity.Zoom.x = vz
            
            ptz.ContinuousMove(request)
        except Exception as e:
            print(f"PTZ Error: {e}")

    def connect_signals(self):
        self.mqtt_worker.data_received.connect(self.process_sensor_data)
        for i, w in enumerate(self.video_workers):
            # 使用默认参数 capture 当前的 i 值
            w.frame_received.connect(lambda img, cid=i: self.update_video(img, cid))
            w.status_changed.connect(lambda status, cid=i: self.update_video_status(status, cid))
    def on_sensor_drop(self, event):
        # 修复 DeprecationWarning: 使用 position().toPoint()
        pos = event.position().toPoint()
        target_item = self.sensor_tree.itemAt(pos)
        source_item = self.sensor_tree.currentItem()
        if target_item and source_item and target_item != source_item:
            if target_item.parent() and source_item.parent():
                x_cid = source_item.data(0, Qt.UserRole)
                y_cid = target_item.data(0, Qt.UserRole)
                if x_cid and y_cid:
                    self.add_xy_plot_window(x_cid, y_cid)
        event.ignore()

    def add_xy_plot_window(self, x_cid, y_cid):
        plot_id = f"xy_{x_cid}_{y_cid}"
        if plot_id in self.active_plots: return
        if len(self.active_plots) >= 4:
            QMessageBox.warning(self, "提醒", "最多支持同时显示 4 个绘图窗口"); return
        
        x_cfg = self.daq_configs.get(x_cid, {})
        y_cfg = self.daq_configs.get(y_cid, {})
        x_name = x_cfg.get("name", x_cid)
        y_name = y_cfg.get("name", y_cid)
        
        card = QFrame(); card.setObjectName("ContentCard"); l = QVBoxLayout(card); l.setContentsMargins(5,5,5,5)
        header_widget = ClickableHeader(); header = QHBoxLayout(header_widget)
        title = QLabel(f"<b>滞回图: {x_name} - {y_name}</b>")
        close_btn = QPushButton("×"); close_btn.setFixedSize(20, 20); close_btn.setStyleSheet("background:#E74C3C;color:white;border-radius:10px;")
        close_btn.clicked.connect(lambda: self.remove_plot_window(plot_id))
        header.addWidget(title); header.addStretch(); header.addWidget(close_btn)
        header_widget.doubleClicked.connect(lambda: self.pop_out_widget(card, f"滞回图: {x_name}-{y_name}", plot_id))
        l.addWidget(header_widget)
        
        pw = pg.PlotWidget(background='w'); pw.setLabel('bottom', x_name, units=x_cfg.get("unit", "")); pw.setLabel('left', y_name, units=y_cfg.get("unit", "")); pw.showGrid(x=True, y=True)
        curve = pw.plot(pen=pg.mkPen('#3498DB', width=1.5)); l.addWidget(pw)
        
        self.plot_grid.addWidget(card, len(self.active_plots)//2, len(self.active_plots)%2)
        self.active_plots[plot_id] = {"frame": card, "plot": pw, "curve": curve, "type": "xy", "x_cid": x_cid, "y_cid": y_cid}

    @Slot(dict)
    def process_sensor_data(self, data):
        for s in data.get("sensors", []):
            sn = s["name"]
            roots = self.sensor_tree.findItems(sn, Qt.MatchExactly, 0)
            r = roots[0] if roots else QTreeWidgetItem(self.sensor_tree, [sn])
            
            for cn, v in s["channels"].items():
                channel_id = f"{sn}_{cn}"
                cfg = self.daq_configs.get(channel_id, {})
                display_name = cfg.get("name", cn)
                unit = cfg.get("unit", "-")
                scale = cfg.get("scale", 1.0)
                offset = cfg.get("offset", 0.0)
                
                # 处理批量数据或单点数据
                vals = v if isinstance(v, list) else [v]
                processed_vals = [val * scale + offset for val in vals]
                
                if channel_id not in self.data_history: self.data_history[channel_id] = []
                self.data_history[channel_id].extend(processed_vals)
                
                # 1kHz 采样率下，保留 2000 个点 (2秒数据)
                if len(self.data_history[channel_id]) > 2000:
                    self.data_history[channel_id] = self.data_history[channel_id][-2000:]
                
                # 更新树状列表显示 (只显示最新的一个点)
                last_val = processed_vals[-1]
                for i in range(r.childCount()):
                    child = r.child(i)
                    if child.data(0, Qt.UserRole) == channel_id:
                        child.setText(0, display_name)
                        child.setText(1, f"{last_val:.2f}")
                        child.setText(2, unit)
                        break
                else:
                    new_item = QTreeWidgetItem(r, [display_name, f"{last_val:.2f}", unit])
                    new_item.setData(0, Qt.UserRole, channel_id)
                    
        # 更新所有激活的绘图窗口
        for pid, info in self.active_plots.items():
            if info.get("type") == "xy":
                x_cid, y_cid = info["x_cid"], info["y_cid"]
                if x_cid in self.data_history and y_cid in self.data_history:
                    min_len = min(len(self.data_history[x_cid]), len(self.data_history[y_cid]))
                    # 滞回图显示最后 1000 个点
                    display_len = min(min_len, 1000)
                    info["curve"].setData(self.data_history[x_cid][-display_len:], self.data_history[y_cid][-display_len:])
            else:
                y_data = self.data_history.get(pid, [])
                if y_data:
                    # 时程图显示最后 500 个点
                    display_len = min(len(y_data), 500)
                    plot_y = y_data[-display_len:]
                    plot_x = list(range(len(plot_y)))
                    info["curve"].setData(plot_x, plot_y)
    def closeEvent(self, e):
        for w in self.video_workers: w.stop()
        self.mqtt_worker.stop(); e.accept()

if __name__ == "__main__":
    app = QApplication(sys.argv); app.setFont(QFont("Arial", 11)); login = LoginDialog()
    if login.exec() == QDialog.Accepted:
        window = MainWindow(login.user_info); window.show(); sys.exit(app.exec())
