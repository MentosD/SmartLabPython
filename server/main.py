from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from contextlib import asynccontextmanager
import uvicorn
import asyncio
import sqlite3
import os
import sys
import json
import uuid
import shutil
import time
from datetime import datetime
from pydantic import BaseModel
from passlib.context import CryptContext

# 路径修复
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.database import init_db, DB_PATH, get_all_channel_configs, update_channel_config
from server.managers import video_managers
from server.streamers import video_streamer, daq_udp_receiver, daq_task_running, daq_config

# 全局任务变量
daq_task = None

# 路径定义
DAQ_CONFIG_PATH = os.path.join(os.path.dirname(__file__), "daq_config.json")

def load_daq_config():
    default = {"ip": "0.0.0.0", "port": 19001, "name": "DTLinks-DAQ"}
    if os.path.exists(DAQ_CONFIG_PATH):
        with open(DAQ_CONFIG_PATH, "r") as f: return json.load(f)
    return default

def save_daq_config(config):
    with open(DAQ_CONFIG_PATH, "w") as f: json.dump(config, f)

# 1. 先定义 lifespan 装饰器
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时的逻辑
    init_db()
    
    # 自动启动采集引擎
    cfg = load_daq_config()
    from server.streamers import daq_config, daq_udp_receiver
    daq_config.update(cfg)
    asyncio.create_task(daq_udp_receiver())
    
    # 从数据库读取摄像头配置并启动抓取器
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, rtsp_url FROM cameras")
    for cam_id, url in cursor.fetchall():
        asyncio.create_task(video_streamer(cam_id, url))
    conn.close()
    yield

# ... 之前的路由 ...

# 2. 创建 FastAPI 实例
app = FastAPI(title="Smart Lab API Server", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/daq/status")
def get_daq_status():
    from server.streamers import daq_task_running, daq_config
    return {"running": daq_task_running, "config": daq_config}

@app.post("/daq/start")
async def start_daq(config: dict):
    from server.streamers import daq_task_running, daq_config
    global daq_task
    if daq_task_running:
        return {"success": False, "message": "采集已在运行中"}
    
    # 更新全局配置
    daq_config["udp_ip"] = config.get("ip", "0.0.0.0")
    daq_config["udp_port"] = int(config.get("port", 19001))
    daq_config["device_name"] = config.get("name", "DTLinks-DAQ")
    
    # 启动异步任务
    daq_task = asyncio.create_task(daq_udp_receiver())
    return {"success": True}

@app.post("/daq/stop")
async def stop_daq():
    import server.streamers as streamers
    streamers.daq_task_running = False
    return {"success": True}

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# 3. 定义模型
class UserAuth(BaseModel):
    username: str
    password: str

class Asset(BaseModel):
    asset_no: str
    name: str
    category: str = ""
    model: str = ""
    location: str = ""
    status: str = "在库"

# 4. 定义所有路由 (@app)

@app.get("/daq/config")
def get_daq_config():
    return get_all_channel_configs()

@app.post("/daq/config/update")
def update_daq_config(config: dict):
    update_channel_config(
        config['channel_id'], 
        config['name'], 
        config['unit'], 
        config.get('scale', 1.0), 
        config.get('offset', 0.0)
    )
    return {"success": True}

@app.post("/auth/register")
def register(user: UserAuth):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", 
                      (user.username, pwd_context.hash(user.password), "user"))
        conn.commit()
        return {"success": True, "message": "注册成功"}
    except sqlite3.IntegrityError:
        return {"success": False, "message": "用户名已存在"}
    finally:
        conn.close()

@app.post("/auth/login")
def login(user: UserAuth):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash, role, group_name FROM users WHERE username=?", (user.username,))
    row = cursor.fetchone()
    conn.close()
    if not row or not pwd_context.verify(user.password, row[0]):
        return {"success": False, "message": "用户名或密码错误"}
    return {
        "success": True, 
        "user": {"username": user.username, "role": row[1], "group_name": row[2]}
    }

# --- 映射表 ---
CATEGORY_MAP = {
    "加载系统 (Loading Systems)": "01", "反力系统 (Reaction Systems)": "02",
    "控制系统 (Control Systems)": "03", "数据采集系统 (Data Acquisition - DAQ)": "04",
    "传感与测量设备 (Sensors & Measurement)": "05", "无损检测设备 (Non-Destructive Testing)": "06",
    "光学与视觉测量设备 (Optical/DIC Systems)": "07", "试件加工设备 (Specimen Preparation)": "08",
    "起重与辅助设备 (Lifting & Auxiliary)": "09", "安全与环境监测 (Safety & Environment)": "10",
    "混合试验与实时仿真平台 (RTHS & Simulation Platforms)": "11",
    "动力学激振设备 (Dynamic Exciters / Shakers)": "12",
    "岩土与土动力学试验设备 (Geotechnical Testing)": "13",
    "结构健康监测系统 (SHM & IoT Gateways)": "14",
    "风洞与流体物理模型设备 (Wind Tunnel & Fluid Modeling)": "15",
    "仪器标定与校准设备 (Calibration & Metrology)": "16",
}

BRAND_MAP = {
    "MTS": "101", "Instron": "102", "National Instruments (NI)": "103",
    "dSPACE": "104", "HBM": "105", "PCB Piezotronics": "106",
    "Dewesoft": "107", "Quanser": "108", "邦威 (Popwil)": "109",
    "东华测试 (Donghua Testing)": "110", "欧美大地 (EPC)": "111",
    "坚华科技 (Jianhua Technology)": "112", "时代试金 (Time Shijin)": "113",
    "基康仪器 (Geokon)": "114", "海康威视 (Hikvision)": "115",
    "Speedgoat": "116", "Moog": "117", "Shore Western": "118",
    "Tokyo Measuring Instruments Lab (TML)": "119", "Brüel & Kjær (B&K)": "120",
    "GDS Instruments": "121", "KYOWA": "122", "Micro-Epsilon": "123",
    "Optotrak (NDI)": "124", "三思纵横 (SUNS)": "125",
    "建研华测 (CABR-MTC)": "126", "智博联 (ZBL)": "127",
    "东方振动 (COINV)": "128", "亿恒科技 (ECON)": "129", "泰斯特 (TST)": "130",
    "通用/其他": "999"
}

@app.get("/assets/config")
def get_assets_config():
    return {"categories": list(CATEGORY_MAP.keys()), "brands": list(BRAND_MAP.keys())}

@app.get("/assets/next_code")
def get_next_code(category: str, brand: str):
    c_code = CATEGORY_MAP.get(category, "99")
    b_code = BRAND_MAP.get(brand, "999")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    prefix = f"{c_code}{b_code}"
    cursor.execute("SELECT asset_no FROM assets WHERE asset_no LIKE ? ORDER BY asset_no DESC LIMIT 1", (f"{prefix}%",))
    row = cursor.fetchone()
    conn.close()
    new_seq = str(int(row[0][-5:]) + 1).zfill(5) if row else "00001"
    return {"code": f"{prefix}{new_seq}"}

@app.get("/assets")
def list_assets(q: str = None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if q:
        cursor.execute("SELECT id, asset_no, name, category, model, location, status, current_user FROM assets WHERE name LIKE ? OR asset_no LIKE ?", (f"%{q}%", f"%{q}%"))
    else:
        cursor.execute("SELECT id, asset_no, name, category, model, location, status, current_user FROM assets")
    cols = [column[0] for column in cursor.description]
    rows = cursor.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]

@app.post("/assets")
def add_asset(asset: Asset):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO assets (asset_no, name, category, model, location, status) VALUES (?, ?, ?, ?, ?, ?)", 
                       (asset.asset_no, asset.name, asset.category, asset.model, asset.location, asset.status))
        conn.commit()
        return {"success": True}
    except Exception as e:
        return {"success": False, "message": str(e)}
    finally:
        conn.close()

@app.get("/assets/names")
def get_asset_names():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT name FROM assets")
    names = [row[0] for row in cursor.fetchall()]
    conn.close()
    return {"names": names}

@app.put("/assets/{asset_id}")
def update_asset(asset_id: int, asset: Asset):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE assets SET asset_no=?, name=?, category=?, model=?, location=?, status=? WHERE id=?", 
                       (asset.asset_no, asset.name, asset.category, asset.model, asset.location, asset.status, asset_id))
        conn.commit()
        return {"success": True}
    except Exception as e:
        return {"success": False, "message": str(e)}
    finally:
        conn.close()

@app.delete("/assets/{asset_id}")
def delete_asset(asset_id: int):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/assets/action")
def asset_action(data: dict):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    new_status = "借出" if data['action'] == "借用" else "在库"
    user = data['username'] if data['action'] == "借用" else None
    local_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE assets SET status=?, current_user=? WHERE id=?", (new_status, user, data['asset_id']))
    cursor.execute("INSERT INTO borrow_log (asset_id, username, action, timestamp) VALUES (?, ?, ?, ?)", 
                  (data['asset_id'], data['username'], data['action'], local_now))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/assets/import")
def import_assets(assets: list[Asset]):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for asset in assets:
        cursor.execute("INSERT OR REPLACE INTO assets (asset_no, name, category, model, location) VALUES (?, ?, ?, ?, ?)",
                      (asset.asset_no, asset.name, asset.category, asset.model, asset.location))
    conn.commit()
    conn.close()
    return {"success": True, "count": len(assets)}

@app.get("/cameras")
def get_cameras():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, rtsp_url FROM cameras")
    rows = cursor.fetchall()
    conn.close()
    return [{"id": r[0], "name": r[1], "rtsp_url": r[2]} for r in rows]

@app.post("/cameras/update")
def update_camera(cam: dict):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE cameras SET name=?, rtsp_url=? WHERE id=?", (cam['name'], cam['rtsp_url'], cam['id']))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.websocket("/ws/video/{cam_id}")
async def video_endpoint(websocket: WebSocket, cam_id: int):
    if cam_id < 0 or cam_id >= 4: return
    manager = video_managers[cam_id]
    await manager.connect(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

NAS_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "nas")
os.makedirs(NAS_DIR, exist_ok=True)

@app.get("/system/groups")
def get_groups():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM groups")
    groups = [row[0] for row in cursor.fetchall()]
    conn.close()
    return {"groups": groups}

@app.get("/system/users")
def get_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT username, group_name FROM users")
    users = [{"username": row[0], "group_name": row[1]} for row in cursor.fetchall()]
    conn.close()
    return {"users": users}

@app.post("/nas/upload")
async def nas_upload(
    file: UploadFile = File(...), uploader: str = Form(...),
    permission_type: str = Form(...), allowed_groups: str = Form("[]"),
    allowed_users: str = Form("[]"), allow_write: int = Form(0)
):
    storage_name = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(NAS_DIR, storage_name)
    with open(file_path, "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    file_size = os.path.getsize(file_path)
    local_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO nas_files (filename, storage_name, size, uploader, permission_type, allowed_groups, allowed_users, allow_write, upload_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (file.filename, storage_name, file_size, uploader, permission_type, allowed_groups, allowed_users, allow_write, local_now))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/nas/list")
def nas_list(username: str, group_name: str, role: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM nas_files")
    rows = cursor.fetchall()
    visible_files = []
    for r in rows:
        fid, fname, sname, size, uploader, time, p_type, groups_json, users_json, a_write = r
        is_visible = (role == 'admin' or uploader == username or p_type == 'public')
        if not is_visible and p_type == 'custom':
            if group_name in json.loads(groups_json) or username in json.loads(users_json): is_visible = True
        if is_visible:
            can_edit = (role == 'admin' or uploader == username or a_write == 1)
            visible_files.append({"id": fid, "filename": fname, "size": size, "uploader": uploader, "upload_time": time, "permission_type": p_type, "can_edit": can_edit})
    conn.close()
    return {"files": visible_files}

@app.get("/nas/download/{file_id}")
def nas_download(file_id: int, username: str, group_name: str, role: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT filename, storage_name, uploader, permission_type, allowed_groups, allowed_users FROM nas_files WHERE id=?", (file_id,))
    row = cursor.fetchone()
    conn.close()
    if not row: return {"error": "文件不存在"}
    fname, sname, uploader, p_type, groups_json, users_json = row
    is_allowed = (role == 'admin' or uploader == username or p_type == 'public')
    if not is_allowed and p_type == 'custom':
        if group_name in json.loads(groups_json) or username in json.loads(users_json): is_allowed = True
    if not is_allowed: return {"error": "无权访问"}
    return FileResponse(os.path.join(NAS_DIR, sname), filename=fname)

@app.delete("/nas/delete/{file_id}")
def nas_delete(file_id: int, username: str, group_name: str, role: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT storage_name, uploader, allow_write, permission_type, allowed_groups, allowed_users FROM nas_files WHERE id=?", (file_id,))
    row = cursor.fetchone()
    if not row: conn.close(); return {"error": "文件不存在"}
    sname, uploader, a_write, p_type, groups_json, users_json = row
    can_delete = (role == 'admin' or uploader == username)
    if not can_delete and a_write == 1 and p_type == 'custom':
        if group_name in json.loads(groups_json) or username in json.loads(users_json): can_delete = True
    if not can_delete: conn.close(); return {"error": "无权删除"}
    file_path = os.path.join(NAS_DIR, sname)
    if os.path.exists(file_path): os.remove(file_path)
    cursor.execute("DELETE FROM nas_files WHERE id=?", (file_id,))
    conn.commit(); conn.close(); return {"success": True}

@app.get("/assets/template")
def get_asset_template():
    import csv
    from io import BytesIO, StringIO
    output = BytesIO(); output.write(b'\xef\xbb\xbf')
    text_buffer = StringIO(); writer = csv.writer(text_buffer)
    writer.writerow(["资产编号", "名称", "类别", "型号规格", "存放位置", "状态"])
    writer.writerow(["0110100001", "液压作动器", "加载系统", "MTS-500", "A1货架", "在库"])
    output.write(text_buffer.getvalue().encode('utf-8')); output.seek(0)
    return StreamingResponse(output, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=asset_template.csv"})

AGORA_APP_ID = "86c31ed2d6e844628c34045ba4759cc9"
AGORA_APP_CERTIFICATE = "023bc6e737444143bee03e358009f4e0"

from agora_token_builder import RtcTokenBuilder
@app.get("/auth/agora_token")
def get_agora_token(channelName: str, uid: int):
    expiration = 3600 * 24
    ts = int(time.time()) + expiration
    token = RtcTokenBuilder.buildTokenWithUid(AGORA_APP_ID, AGORA_APP_CERTIFICATE, channelName, uid, 1, ts)
    return {"token": token, "appId": AGORA_APP_ID}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
