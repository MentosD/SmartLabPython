import asyncio
import json
import time
import threading
import paho.mqtt.client as mqtt
import nidaqmx
from nidaqmx.constants import AcquisitionType
from common.config import MQTT_BROKER, MQTT_TOPIC_DATA

# 全局控制变量
ni_task_running = False
ni_worker_thread = None
main_asyncio_loop = None

ni_config = {
    "enabled": True,
    "ai_channel": "cDAQ1Mod1/ai0:7",
    "device_name": "NI-cDAQ-9174",
    "sample_rate": 1000,   # 默认 1kHz (1000 Hz)
    "min_val": -10.0,
    "max_val": 10.0
}

def scan_ni_devices():
    """扫描系统中的 NI 设备及物理通道"""
    try:
        sys = nidaqmx.system.System.local()
        devices = []
        for d in sys.devices:
            dev_info = {
                "name": d.name,
                "product_type": d.product_type,
                "ai_channels": [c.name for c in d.ai_physical_chans],
                "ao_channels": [c.name for c in d.ao_physical_chans]
            }
            devices.append(dev_info)
        return {"status": "ok", "devices": devices}
    except Exception as e:
        return {"status": "error", "message": str(e), "devices": []}

def reset_ni_device(dev_name: str = "cDAQ1Mod1"):
    """手动复位 NI 设备"""
    try:
        nidaqmx.system.Device(dev_name).reset_device()
        return {"status": "ok", "message": f"Device {dev_name} reset successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def write_ni_ao(channel: str, voltage: float):
    """向 NI 模拟输出通道 (如 NI 9263 / cDAQ1Mod2/ao0) 写入电压"""
    try:
        with nidaqmx.Task() as task:
            task.ao_channels.add_ao_voltage_chan(channel)
            task.write(float(voltage))
        return {"status": "ok", "channel": channel, "voltage": voltage}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def _ni_thread_loop():
    """在独立的专用线程中运行 NI DAQmx 采集"""
    global ni_task_running, main_asyncio_loop

    client = mqtt.Client()
    try:
        client.connect(MQTT_BROKER, 1883, 60)
        client.loop_start()
    except Exception as e:
        print(f"[NI DAQ Error] MQTT connection failed: {e}")
        return

    print(f"[NI DAQ] Worker Thread Started for channel {ni_config['ai_channel']} @ {ni_config['sample_rate']}Hz")

    while ni_task_running:
        if not ni_config.get("enabled", True):
            time.sleep(0.5)
            continue

        ai_chan = ni_config["ai_channel"]
        rate = float(ni_config.get("sample_rate", 1000))
        min_v = float(ni_config.get("min_val", -10.0))
        max_v = float(ni_config.get("max_val", 10.0))

        chunk_size = max(10, int(rate / 20))

        task = None
        try:
            task = nidaqmx.Task()
            task.ai_channels.add_ai_voltage_chan(ai_chan, min_val=min_v, max_val=max_v)
            task.timing.cfg_samp_clk_timing(rate, sample_mode=AcquisitionType.CONTINUOUS)
            task.start()

            while ni_task_running and ni_config.get("enabled", True):
                raw_data = task.read(number_of_samples_per_channel=chunk_size, timeout=2.0)
                
                now = time.time()
                data_buffer = {}
                if raw_data and isinstance(raw_data[0], list):
                    for i, ch_samples in enumerate(raw_data):
                        ch_name = f"NI_CH{i+1}"
                        data_buffer[ch_name] = [float(v) for v in ch_samples]
                elif raw_data and isinstance(raw_data[0], (float, int)):
                    data_buffer["NI_CH1"] = [float(v) for v in raw_data]

                if data_buffer:
                    payload = {
                        "timestamp": now,
                        "sensors": [{
                            "name": ni_config["device_name"],
                            "channels": data_buffer
                        }]
                    }
                    payload_str = json.dumps(payload)
                    client.publish(MQTT_TOPIC_DATA, payload_str)

                    # 同时也同步分发给手机端 Web WebSocket data_manager
                    try:
                        from server.managers import data_manager
                        if main_asyncio_loop and main_asyncio_loop.is_running():
                            asyncio.run_coroutine_threadsafe(
                                data_manager.broadcast_text(payload_str), 
                                main_asyncio_loop
                            )
                    except Exception:
                        pass

            task.stop()
        except Exception as e:
            print(f"[NI DAQ Info] 设备忙或等待重试: {e}")
            time.sleep(2.0)
        finally:
            if task:
                try:
                    task.close()
                except Exception:
                    pass

    client.loop_stop()
    print("[NI DAQ] Worker Thread Stopped")

async def ni_daq_receiver():
    """FastAPI 调用的入口协程"""
    global ni_task_running, ni_worker_thread, main_asyncio_loop
    if ni_task_running:
        return
        
    main_asyncio_loop = asyncio.get_running_loop()
    ni_task_running = True
    ni_worker_thread = threading.Thread(target=_ni_thread_loop, daemon=True)
    ni_worker_thread.start()
    
    while ni_task_running:
        await asyncio.sleep(1.0)
