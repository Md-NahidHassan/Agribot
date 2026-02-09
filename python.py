import time
import io
import os
import serial
import numpy as np
import threading
import cv2 
from datetime import datetime
from flask import Flask, render_template_string, Response, request, jsonify, render_template
from flask_socketio import SocketIO
from picamera2 import Picamera2 
from PIL import Image

# --- 1. AI Laibary Setup---
try:
    import tflite_runtime.interpreter as tflite
except ImportError:
    try:
        import tensorflow.lite as tflite
    except:
        print("⚠️ AI Library Not Found!")
        tflite = None

# --- 2. Arduno Connection---
SERIAL_PORT = '/dev/ttyACM0' 
BAUD_RATE = 9600
arduino = None

try:
    arduino = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)
    print(f"✅ Connected to Arduino on {SERIAL_PORT}")
except:
    try:
        arduino = serial.Serial('/dev/ttyUSB0', BAUD_RATE, timeout=1)
        print("✅ Connected to Arduino on /dev/ttyUSB0")
    except:
        print("⚠️ WARNING: Arduino not connected! Check Port.")

# --- 3. Camera Setup ---
try:
    picam2 = Picamera2()
    config = picam2.create_preview_configuration(main={"size": (640, 480), "format": "XRGB8888"})
    picam2.configure(config)
    picam2.start()
    print("✅ Picamera2 Started Successfully")
except Exception as e:
    print(f"❌ Camera Error: {e}")

# --- 4.Model Load ---
model_path = "/home/bluefox/tomato_model_v2.tflite"
interpreter = None
if tflite and os.path.exists(model_path):
    interpreter = tflite.Interpreter(model_path=model_path)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()
    print("✅ AI Model Loaded!")

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Global Variable ---
recorded_steps = []
is_recording = False
is_playing = False 
is_tracking = False 
start_record_time = 0

# Harvest Position
target_color = 'RED'
current_base = 90
current_shoulder = 90
current_elbow = 90

# --- 5. Disease Info ---
DISEASE_INFO = {
    0: {"name": "ব্যাকটেরিয়াল স্পট (Bacterial Spot)", "cause": "ব্যাকটেরিয়া...", "sol": "কপার অক্সিক্লোরাইড স্প্রে করুন।", "link": "bacterial_spot"},
    1: {"name": "আগাম ধসা রোগ (Early Blight)", "cause": "ছত্রাকজনিত...", "sol": "ম্যানকোজেব স্প্রে করুন।", "link": "early_blight"},
    2: {"name": "নাবি ধসা রোগ (Late Blight)", "cause": "ছত্রাকজনিত...", "sol": "মেলোডি ডুও স্প্রে করুন।", "link": "late_blight"},
    3: {"name": "লিফ মোল্ড (Leaf Mold)", "cause": "ছত্রাকজনিত...", "sol": "কার্বেন্ডাজিম স্প্রে করুন।", "link": "leaf_mold"},
    4: {"name": "সেপ্টোরিয়া লিফ স্পট (Septoria)", "cause": "ছত্রাকজনিত...", "sol": "সুমিথিয়ন স্প্রে করুন।", "link": "septoria"},
    5: {"name": "মাকড়সার আক্রমণ (Spider Mites)", "cause": "লাল মাকড়সা...", "sol": "ভার্টিমেক স্প্রে করুন।", "link": "spider_mites"},
    6: {"name": "টার্গেট স্পট (Target Spot)", "cause": "ছত্রাকজনিত...", "sol": "এমিস্টার টপ ব্যবহার করুন।", "link": "target_spot"},
    7: {"name": "পাতা কোঁকড়ানো ভাইরাস (Yellow Leaf Curl)", "cause": "সাদা মাছি...", "sol": "ইমিডাক্লোরোপ্রিড স্প্রে করুন।", "link": "yellow_curl"},
    8: {"name": "মোজাইক ভাইরাস (Mosaic Virus)", "cause": "ভাইরাস...", "sol": "আক্রান্ত গাছ তুলে ফেলুন।", "link": "mosaic_virus"},
    9: {"name": "সুস্থ গাছ (Healthy)", "cause": "গাছ ভালো আছে।", "sol": "নিয়মিত পানি দিন।", "link": "healthy"}
}

# --- 6. Smart Sleep ---
def smart_sleep(duration):
    global is_playing, is_tracking
    end_time = time.time() + duration
    while time.time() < end_time:
        if not is_playing and not is_tracking: 
            return False 
        time.sleep(0.1) 
    return True

# --- 7. Web Insterface ---
HTML_CODE = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Smart Agro-Bot Compact</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        /* 1. Body setting */
        body { 
            background-color: #e8f5e9; /* 2.Mobile Bcakground */
            font-family: sans-serif; 
            margin: 0; 
            padding: 5px; 
            text-align: center; 
            height: 100vh;
            overflow: hidden; /* Scroll bar */
        }

        h3 { color: #2e7d32; margin: 2px 0 5px 0; font-size: 18px; }

        /* 2. Camera  */
        .top-container {
            max-width: 320px; /* Video size fixed */
            margin: 0 auto 5px auto;
        }
        
        .video-box { 
            width: 100%; 
            border: 2px solid #2e7d32; 
            background: black; 
            border-radius: 5px; 
            display: block;
        }
        img { width: 100%; display: block; }
        
        /* 3. Buttom section */
        .bottom-container {
            display: flex;
            gap: 10px;
            max-width: 900px;
            margin: 0 auto;
            justify-content: center;
            height: calc(100vh - 280px); /*Body length */
        }

        .col-left, .col-right { 
            flex: 1; 
            background: #F8BBD0; 
            padding: 8px;
            border-radius: 10px;
            border: 2px solid #EC407A;
            color: #333;

        h4 { margin: 0 0 5px 0; border-bottom: 1px solid #C2185B; padding-bottom: 3px; font-size: 14px; color: #880E4F; }

        
        .box { background: white; padding: 5px; border-radius: 5px; margin-bottom: 5px; border: 1px solid #ff80ab; }
        
        button { padding: 5px; font-weight: bold; border: none; border-radius: 4px; cursor: pointer; color: white; font-size: 11px; margin: 1px; }
        
        .btn-full { width: 98%; }
        .btn-half { width: 48%; }
        
        
        .scan { background: #E91E63; font-size: 12px; width: 100%; margin-top: 2px; padding: 5px;}
        .btn-check { background: #7e57c2; }
        .btn-red { background: #e53935; }
        .btn-green { background: #43a047; }
        .btn-pump-on { background: #039be5; }
        .btn-pump-off { background: #d32f2f; }
        .btn-home { background: #009688; }

        /* Car Control Buttons */
        .go { background: #43a047; width: 50px; height: 35px; font-size: 16px; } 
        .stop { background: #d32f2f; width: 50px; height: 35px; font-size: 12px; } 
        .turn { background: #ffa000; width: 50px; height: 35px; font-size: 16px; }
        .mode { background: #1976d2; width: 45%; margin-bottom: 5px; }

        /* Result Box */
        #result-box { display:none; position: absolute; top: 50px; left: 50%; transform: translateX(-50%); width: 280px; padding: 10px; border: 2px solid white; border-radius: 8px; background: rgba(0,0,0,0.9); text-align: left; font-size: 12px; color: white; z-index: 100;}

        /* Sliders (Compact) */
        .slider-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }
        .slider-item { background: #eee; padding: 3px; border-radius: 4px; border: 1px solid #ccc;}
        .slider-wrapper { text-align: left; }
        label { font-size: 10px; display: flex; justify-content: space-between; color: black;}
        span { color: #E91E63; font-weight: bold; }
        input[type=range] { width: 100%; margin: 2px 0 0 0; cursor: pointer; }
        
        .rec-panel { display: flex; gap: 2px; justify-content: center; margin-top:5px;}
        .rec-panel button { flex: 1; font-size: 10px; }
    </style>
</head>
<body>
    <h3>🚜 Smart Agro-Bot(UIU)</h3>
    
    <div class="top-container">
        <div class="video-box"><img src="{{ url_for('video_feed') }}"></div>
        <button class="scan" onclick="scanDisease()">📸 স্ক্যান করুন (AI)</button>
        
        <div id="result-box">
            <div id="d-name">...</div>
            <div style="text-align:center; color:#00e676;">সঠিকতা: <span id="d-acc">0</span>%</div>
            <hr>
            <b>⚠️ কারণ:</b> <span id="d-cause">...</span><br>
            <b>💊 সমাধান:</b> <span id="d-sol">...</span><br>
            <div style="text-align:center; margin-top:5px;">
                <a id="d-link" href="#" target="_blank" style="color:#4fc3f7;">বিস্তারিত দেখুন</a>
                <button onclick="document.getElementById('result-box').style.display='none'" style="background:red; width:50px; float:right;">X</button>
            </div>
        </div>
    </div>

    <div class="bottom-container">
        
        <div class="col-left">
            <h4>🚗 Car Control</h4>
            
            <div style="margin-bottom:5px;">
                <button class="mode" onclick="sendCar('M')">Manual</button>
                <button class="mode" onclick="sendCar('U')">Auto</button>
            </div>
            
            <div style="background:white; padding:10px; border-radius:8px; display:inline-block; border:1px solid #f8bbd0;">
                <button class="go" onclick="sendCar('w')">▲</button><br>
                <button class="turn" onclick="sendCar('a')">◀</button>
                <button class="stop" onclick="sendCar('x')">■</button>
                <button class="turn" onclick="sendCar('d')">▶</button><br>
                <button class="go" onclick="sendCar('s')">▼</button>
            </div>
            <p id="status" style="font-size:11px; margin-top:5px; font-weight:bold;">Ready...</p>
        </div>

        <div class="col-right">
            <h4>🦾 Arm & Harvest</h4>

            <div class="box">
                <div style="display:flex; justify-content:center;">
                    <button class="btn-red btn-half" onclick="harvest('RED')">🔴 Red</button>
                    <button class="btn-green btn-half" onclick="harvest('GREEN')">🟢 Green</button>
                </div>
            </div>

            <div class="box" style="display: flex; gap: 2px;">
                <button class="btn-check" style="flex:1;" onclick="checkSoil()">🔍 Soil</button>
                <button class="btn-pump-on" style="flex:1;" onclick="pumpCtrl(1)">💧 ON</button>
                <button class="btn-pump-off" style="flex:1;" onclick="pumpCtrl(0)">OFF</button>
            </div>

            <div class="box">
                <div class="slider-grid">
                    <div class="slider-item"><div class="slider-wrapper"><label>Grip <span id="v_Gripper">140</span></label><input type="range" min="0" max="140" value="140" id="Gripper" oninput="sendArm(this)"></div></div>
                    <div class="slider-item"><div class="slider-wrapper"><label>Elbow <span id="v_Elbow">90</span></label><input type="range" min="0" max="180" value="90" id="Elbow" oninput="sendArm(this)"></div></div>
                    <div class="slider-item"><div class="slider-wrapper"><label>Shldr <span id="v_Shoulder">90</span></label><input type="range" min="0" max="180" value="90" id="Shoulder" oninput="sendArm(this)"></div></div>
                    <div class="slider-item"><div class="slider-wrapper"><label>Base <span id="v_Base">90</span></label><input type="range" min="0" max="180" value="90" id="Base" oninput="sendArm(this)"></div></div>
                </div>
            </div>

            <div class="rec-panel">
                <button onclick="goHome()" class="btn-home">🏠 RST</button>
                <button id="btnRec" onclick="toggleRec()" style="background:#fbc02d; color:black;">● REC</button>
                <button onclick="playOnce()" style="background:#29b6f6;">▶ 1x</button>
                <button onclick="playLoop()" style="background:#66bb6a;">↻ Loop</button>
                <button onclick="stopPlay()" style="background:#ef5350;">■ STOP</button>
            </div>
        </div>
    </div>

    <script>
        var socket = io();
        var recording = false;
        
        socket.on('status_msg', function(msg) { document.getElementById("status").innerText = msg; });
        socket.on('update_ui', function(data) { document.getElementById(data.id).value = data.val; document.getElementById("v_" + data.id).innerText = data.val; });

        function sendArm(el) { document.getElementById("v_" + el.id).innerText = el.value; socket.emit('move', {id: el.id, val: el.value}); }
        function checkSoil() { document.getElementById("status").innerText = "Checking soil..."; socket.emit('check_sensor'); }
        function pumpCtrl(val) { socket.emit('move', {id: 'Pump', val: val}); }
        function harvest(color) { socket.emit('harvest_request', color); }
        
        function toggleRec() {
            var btn = document.getElementById("btnRec");
            if (!recording) { recording = true; btn.innerText = "■ STOP"; socket.emit('rec_ctrl', 'start'); } 
            else { recording = false; btn.innerText = "● REC"; socket.emit('rec_ctrl', 'stop'); }
        }
        function playOnce() { socket.emit('play_ctrl', 'once'); }
        function playLoop() { socket.emit('play_ctrl', 'loop'); }
        function stopPlay() { socket.emit('play_ctrl', 'stop'); }
        function goHome() { socket.emit('go_home'); }
        
        function sendCar(c){ fetch('/command?cmd='+c); }
        
        document.addEventListener('keydown', function(event) {
            const key = event.key;
            if (key === "ArrowUp" || key === "8") sendCar('w');
            else if (key === "ArrowDown" || key === "2") sendCar('s');
            else if (key === "ArrowLeft" || key === "4") sendCar('a');
            else if (key === "ArrowRight" || key === "6") sendCar('d');
            else if (key === "x" || key === "5" || key === " ") sendCar('x');
        });

        function scanDisease() {
            var box = document.getElementById('result-box');
            box.style.display = 'block';
            document.getElementById('d-name').innerText = "অপেক্ষা করুন...";
            fetch('/predict')
            .then(res => res.json())
            .then(data => {
                document.getElementById('d-name').innerText = data.name;
                document.getElementById('d-acc').innerText = data.accuracy;
                document.getElementById('d-cause').innerText = data.cause;
                document.getElementById('d-sol').innerText = data.sol;
                document.getElementById('d-link').href = "/" + data.link; 
                if(data.action === "Spray") {
                    document.getElementById('d-name').style.color = "#ff5252";
                    alert("⚠️ রোগ ধরা পড়েছে!");
                } else {
                    document.getElementById('d-name').style.color = "#69f0ae";
                }
            })
            .catch(err => { document.getElementById('d-name').innerText = "এরর!"; });
        }
    </script>
</body>
</html>
"""

# --- 8. Vision Processing ---
def process_frame_tracking(frame):
    global current_base, is_tracking, target_color
    if not is_tracking: return frame
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = None
    if target_color == 'RED':
        lower1 = np.array([0, 120, 70]); upper1 = np.array([10, 255, 255])
        lower2 = np.array([170, 120, 70]); upper2 = np.array([180, 255, 255])
        mask = cv2.inRange(hsv, lower1, upper1) + cv2.inRange(hsv, lower2, upper2)
    elif target_color == 'GREEN':
        mask = cv2.inRange(hsv, np.array([35, 50, 50]), np.array([85, 255, 255]))
    if mask is not None:
        contours, _ = cv2.findContours(mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        if contours:
            largest = max(contours, key=cv2.contourArea)
            x, y, w, h = cv2.boundingRect(largest)
            if w > 20:
                cv2.rectangle(frame, (x, y), (x+w, y+h), (0, 255, 0), 2)
                cx = x + w // 2
                center_x = 320 // 2
                if cx < center_x - 30:
                    current_base += 1
                    if current_base > 180: current_base = 180
                    send_arduino(0, current_base)
                elif cx > center_x + 30:
                    current_base -= 1
                    if current_base < 0: current_base = 0
                    send_arduino(0, current_base)
    return frame

def gen_frames():
    while True:
        try:
            array = picam2.capture_array()
            frame = cv2.cvtColor(array, cv2.COLOR_RGBA2RGB)
            frame = cv2.resize(frame, (320, 240))
            frame = process_frame_tracking(frame)
            ret, buffer = cv2.imencode('.jpg', frame)
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        except: pass

# --- 9. Helper Function ---
def send_arduino(ch, ang):
    if arduino and arduino.is_open: arduino.write(f"{ch},{ang}\n".encode())
def get_id(name): 
    if name == 'Pump': return 8
    return {'Base':0, 'Shoulder':1, 'Elbow':2, 'Gripper':3}.get(name, 0)
def get_name(ch): return {0:'Base', 1:'Shoulder', 2:'Elbow', 3:'Gripper'}.get(ch, 'Unknown')
def get_distance():
    if arduino and arduino.is_open:
        arduino.reset_input_buffer()
        arduino.write(b"98,0\n") 
        time.sleep(0.1)
        if arduino.in_waiting:
            try:
                line = arduino.readline().decode().strip()
                if "D:" in line: return int(line.split(":")[1])
            except: pass
    return 100

# --- ১০. Hurvest Logic ---
def harvest_thread_func(color):
    global is_tracking, target_color, current_base, current_shoulder, current_elbow
    target_color = color
    is_tracking = True
    socketio.emit('status_msg', f"Tracking {color}...")
    send_arduino(3, 90)
    if not smart_sleep(2): return 
    dist = get_distance()
    socketio.emit('status_msg', f"Distance: {dist}cm")
    if dist > 30 or dist == 0:
        socketio.emit('status_msg', "Too far! Stopping.")
        is_tracking = False; return
    socketio.emit('status_msg', "Approaching...")
    for i in range(20):
        if not is_tracking: return 
        dist = get_distance()
        if dist <= 7 and dist > 0: break
        current_shoulder += 2; current_elbow -= 2
        send_arduino(1, current_shoulder); send_arduino(2, current_elbow)
        if not smart_sleep(0.5): return 
    socketio.emit('status_msg', "Grabbing (Safety 140)...")
    if not smart_sleep(0.5): return
    send_arduino(3, 140)
    if not smart_sleep(1): return
    socketio.emit('status_msg', "Pulling Back...")
    current_shoulder = 90; current_elbow = 90
    send_arduino(1, 90); send_arduino(2, 90)
    if not smart_sleep(1.5): return
    socketio.emit('status_msg', "Dropping at 160°...")
    send_arduino(0, 160)
    if not smart_sleep(2): return
    send_arduino(3, 90)
    if not smart_sleep(1): return
    send_arduino(0, 90)
    current_base = 90; is_tracking = False
    socketio.emit('status_msg', "Done.")

def playback_loop(mode):
    global is_playing
    if not recorded_steps: return
    send_arduino(recorded_steps[0]['ch'], recorded_steps[0]['ang'])
    socketio.emit('update_ui', {'id': get_name(recorded_steps[0]['ch']), 'val': recorded_steps[0]['ang']})
    time.sleep(1)
    while is_playing:
        for step in recorded_steps:
            if not is_playing: break
            if not smart_sleep(step['delay']): return 
            send_arduino(step['ch'], step['ang'])
            socketio.emit('update_ui', {'id': get_name(step['ch']), 'val': step['ang']})
        if not is_playing: break
        send_arduino(0, 90); send_arduino(1, 90); send_arduino(2, 90); send_arduino(3, 140)
        socketio.emit('update_ui', {'id': 'Gripper', 'val': 140})
        if not smart_sleep(2): return
        if mode == 'once': break 
    is_playing = False
    socketio.emit('status_msg', "Stopped.")

# --- 11. Routes ---
@app.route('/')
def index(): return render_template_string(HTML_CODE)
@app.route('/video_feed')
def video_feed(): return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
@app.route('/command')
def command():
    cmd = request.args.get('cmd')
    if arduino and arduino.is_open:
        try: arduino.write(cmd.encode())
        except: pass
    return "OK"
@app.route('/predict')
def predict():
    if not interpreter:
        return jsonify({"name": "Error", "cause": "Model Error", "sol": "Check System", "link": "#", "accuracy": 0})
    stream = io.BytesIO()
    picam2.capture_file(stream, format='jpeg')
    img = Image.open(stream).convert('RGB').resize((224, 224))
    input_data = np.expand_dims(np.array(img, dtype=np.float32) / 255.0, axis=0)
    interpreter.set_tensor(input_details[0]['index'], input_data)
    interpreter.invoke()
    output_data = interpreter.get_tensor(output_details[0]['index'])
    idx = int(np.argmax(output_data))
    accuracy = round(float(np.max(output_data)) * 100, 2)
    classes = ["Tomato___Bacterial_spot", "Tomato___Early_blight", "Tomato___Late_blight", "Tomato___Leaf_Mold", "Tomato___Septoria_leaf_spot", "Tomato___Spider_mites Two-spotted_spider_mite", "Tomato___Target_Spot", "Tomato___Tomato_Yellow_Leaf_Curl_Virus", "Tomato___Tomato_mosaic_virus", "Tomato___healthy"]
    info = DISEASE_INFO.get(idx, {"name": "অজানা রোগ", "cause": "শনাক্ত করা যায়নি", "sol": "পরামর্শ নিন", "link": "#"})
    action = "None"
    if classes[idx] != "Tomato___healthy":
        action = "Spray"
        if arduino and arduino.is_open: arduino.write(b'p')
    if not os.path.exists("Scan_History"): os.makedirs("Scan_History")
    filename = f"Scan_History/{classes[idx]}_{accuracy}%_{datetime.now().strftime('%d-%m-%Y_%H-%M-%S')}.jpg"
    img.save(filename)
    return jsonify({"name": info["name"], "cause": info["cause"], "sol": info["sol"], "link": info["link"], "action": action, "accuracy": accuracy})

@app.route('/<page_name>')
def show_disease_page(page_name):
    try:
        return render_template(f'{page_name}.html')
    except:
        return f"<h1>Error: {page_name}.html not found in templates folder!</h1>"

# Socket Events
@socketio.on('move')
def on_move(data):
    global is_recording, start_record_time, current_base, current_shoulder, current_elbow
    ch = get_id(data['id']); ang = int(data['val'])
    if ch == 0: current_base = ang
    elif ch == 1: current_shoulder = ang
    elif ch == 2: current_elbow = ang
    send_arduino(ch, ang)
    if is_recording and ch != 8:
        t = time.time()
        recorded_steps.append({'ch': ch, 'ang': ang, 'delay': t - start_record_time})
        start_record_time = t
@socketio.on('harvest_request')
def on_harvest(color): 
    global is_tracking
    if not is_tracking: threading.Thread(target=harvest_thread_func, args=(color,)).start()
@socketio.on('check_sensor')
def on_check(): send_arduino(99, 0)
@socketio.on('rec_ctrl')
def on_rec(cmd):
    global is_recording, start_record_time, recorded_steps
    if cmd == 'start': is_recording = True; recorded_steps = []; start_record_time = time.time(); socketio.emit('status_msg', "Recording...")
    else: is_recording = False; socketio.emit('status_msg', f"Saved {len(recorded_steps)} steps.")
@socketio.on('play_ctrl')
def on_play(cmd):
    global is_playing, is_tracking
    if cmd == 'stop': 
        is_playing = False; is_tracking = False 
        send_arduino(8, 0) 
        socketio.emit('status_msg', "Stopping Immediately (Pump OFF)...")
    elif not is_playing: 
        is_playing = True; threading.Thread(target=playback_loop, args=(cmd,)).start()
@socketio.on('go_home')
def on_go_home():
    global is_playing, is_tracking, current_base, current_shoulder, current_elbow
    is_playing = False; is_tracking = False 
    send_arduino(8, 0) 
    current_base = 90; current_shoulder = 90; current_elbow = 90
    socketio.emit('status_msg', "Resetting Arm...")
    send_arduino(3, 140); time.sleep(0.2)
    send_arduino(1, 90); time.sleep(0.2)
    send_arduino(2, 90); time.sleep(0.2)
    send_arduino(0, 90)
    socketio.emit('update_ui', {'id': 'Base', 'val': 90})
    socketio.emit('update_ui', {'id': 'Shoulder', 'val': 90})
    socketio.emit('update_ui', {'id': 'Elbow', 'val': 90})
    socketio.emit('update_ui', {'id': 'Gripper', 'val': 140})
    socketio.emit('status_msg', "Reset Done ✅")

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)