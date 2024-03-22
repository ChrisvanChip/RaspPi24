from threading import Thread
import time
from pyPS4Controller.controller import Controller
import RPi.GPIO as GPIO
import io
import logging
import requests
import socketserver
import json
from http import server
from threading import Condition

from picamera2 import Picamera2
from picamera2.encoders import JpegEncoder
from picamera2.outputs import FileOutput

PAGE = """\
<html>
<head>
<style>
h1 {
    text-align: center;
    font-family:Roboto;
    color:brown;
    font-weight: normal;
    font-size: 40px;
}
h2 {
    text-align: right;
    font-family:Arial;
    font-size: 20px;
    color:red;

}
.center {
    display: block;
    margin-left: auto;
    margin-right: auto;
    }
    
body {
    background-color: #ffeecc;
    }
</style>
<title>Het KoffieKarretje&trade; LIVE</title>
</head>
<body>
<h2>LIVE-CAM</h2>

<h1>Het KoffieKarretje&trade;</h1>
<img src="stream.mjpg" width="960" height="720" class="center" />
</body>
</html>
"""

GPIO.setmode(GPIO.BOARD)
GPIO.setwarnings(False)

reverse = False
motor_left = {"control_pins": [16, 18, 22, 36], "speed": 0}
motor_right = {"control_pins": [7, 11, 13, 15], "speed": 0}

for pin in motor_left["control_pins"]:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, 0)

for pin in motor_right["control_pins"]:
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, 0)

halfstep_seq_backward = [  
    [1, 0, 0, 0],
    [1, 1, 0, 0],
    [0, 1, 0, 0],
    [0, 1, 1, 0],
    [0, 0, 1, 0],
    [0, 0, 1, 1],
    [0, 0, 0, 1],
    [1, 0, 0, 1],
]
halfstep_seq_forward = [  
    [1, 0, 0, 1],
    [0, 0, 0, 1],
    [0, 0, 1, 1],
    [0, 0, 1, 0],
    [0, 1, 1, 0],
    [0, 1, 0, 0],
    [1, 1, 0, 0],
    [1, 0, 0, 0],
]

class StreamingOutput(io.BufferedIOBase):
    def __init___(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(301)
            self.send_header("Location", "/index.html")
            self.end_headers()
        elif self.path == "/index.html":
            content = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == "/stream.mjpg":
            self.send_response(200)
            self.send_header("Age", 0)
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header(
                "Content-Type", "multipart/x-mixed-replace; boundary=FRAME"
            )
            self.end_headers()
            try:
                while True:
                    with output.condition:
                        output.condition.wait()
                        frame = output.frame
                    self.wfile.write(b"--FRAME\r\n")
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
            except Exception as e:
                logging.warning(
                    "Removed streaming client %s: %s", self.client_address, str(e)
                )
        else:
            self.send_error(404)
            self.end_headers()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True


picam2 = Picamera2()
picam2.configure(picam2.create_video_configuration(main={"size": (640, 480)}))
output = StreamingOutput()
picam2.start_recording(JpegEncoder(), FileOutput(output))


def camera():
    try:
        address = ("", 8000)
        server = StreamingServer(address, StreamingHandler)
        server.serve_forever()
    finally:
        picam2.stop_recording()

camera_thread = Thread(target=camera)
camera_thread.start()

status = {}
def statusf():
    global status
    while True:
        status = json.loads(requests.get("https://koffiekarretje.opdewolk.nl/status").text)["status"]
        time.sleep(5)
Thread(target=statusf).start()

def transf(raw):
    temp = round((raw - 32767) / -10000)  # /65534
    if temp < 1:
        return 1
    return temp


def run_stepper_motor(motor):
    while True:
        speed = motor["speed"]
        if speed == 0:
            time.sleep(0.1)
            continue

        sequence = halfstep_seq_forward
        if 0 < speed < 1:
            print("[WARN] Speed kleiner dan 1, geclampt naar 1")
            speed = 1
        if speed < 0:
            speed = -speed
            sequence = halfstep_seq_backward
        if reverse is True:
            sequence = halfstep_seq_backward

        for halfstep in range(8):
            for pin in range(4):
                GPIO.output(motor["control_pins"][pin], sequence[halfstep][pin])
            time.sleep(speed * 0.001)


motor_left_thread = Thread(target=run_stepper_motor, args=(motor_left,))
motor_left_thread.start()

motor_right_thread = Thread(target=run_stepper_motor, args=(motor_right,))
motor_right_thread.start()

scriptProcess = None
stopScript = False

def script():
    global status, reverse, stopScript
    while True:
        time.sleep(1)
        if status:
            break
    
    while True:
        if requests.get("https://koffiekarretje.opdewolk.nl/moetikvertrekken").text != "JA":
            time.sleep(1)
            continue
        requests.get("https://koffiekarretje.opdewolk.nl/vertrek")
            
        print("SCRIPT: start")
        status = json.loads(requests.get("https://koffiekarretje.opdewolk.nl/status").text)["status"]
        for kamer in status["kamers"]:
            print(kamer)
            if status['kamers'][kamer]['buttonText'] == 'Onderweg':
                print('Bestelling afleveren in deze kamer: bocht -> rechts')
                motor_left["speed"] = 1
                motor_right["speed"] = 0
                if stopScript:
                    return
                time.sleep(status['afstanden']['bocht'])
                
                print('Rechtdoor')
                motor_left["speed"] = 1
                motor_right["speed"] = 1
                if stopScript:
                    return
                time.sleep(status['afstanden']['kamer'])
                
                print('Gearriveerd -> wachten op bevestiging')
                motor_left["speed"] = 0
                motor_right["speed"] = 0
                
                requests.get("https://koffiekarretje.opdewolk.nl/gearriveerd/"+kamer)
                while True:
                    time.sleep(1)
                    if stopScript:
                        return
                    status = json.loads(requests.get("https://koffiekarretje.opdewolk.nl/status").text)["status"]
                    if status['kamers'][kamer]['buttonText'] != 'Onderweg':
                        break
                
                print('Terugrijden uit kamer')
                reverse = True
                motor_left["speed"] = 1
                motor_right["speed"] = 1
                if stopScript:
                    return
                time.sleep(status['afstanden']['kamer'])
                print('Bocht achteruit')
                motor_left["speed"] = 1
                motor_right["speed"] = 0
                if stopScript:
                    return
                time.sleep(status['afstanden']['bocht'])
                reverse = False
            print('Rechtdoor om kamer te passeren')
            motor_left["speed"] = 1
            motor_right["speed"] = 1
            if stopScript:
                return
            time.sleep(status["afstanden"]["tussenstuk"])
        print('Back to base')
        motor_left["speed"] = 0
        motor_right["speed"] = 1
        if stopScript:
            return
        time.sleep(status['afstanden']['bocht']*2)
        motor_left["speed"] = 1
        motor_right["speed"] = 1
        if stopScript:
            return
        time.sleep(status['afstanden']['tussenstuk']*len(status['kamers']))
        motor_left["speed"] = 0
        motor_right["speed"] = 1
        if stopScript:
            return
        time.sleep(status['afstanden']['bocht']*2)
        motor_left["speed"] = 0
        motor_right["speed"] = 0
        requests.get("https://koffiekarretje.opdewolk.nl/einde")
        print("SCRIPT: einde")
        
scriptProcess = Thread(target=script)
stopScript = False
scriptProcess.start()

motorstates = {
    "left": False,
    "right": False,
}

def updateMotor(value):
    if motorstates["left"] and motorstates["right"]:
        motor_left["speed"] = value
        motor_right["speed"] = value
        return
    if motorstates["left"]:
        motor_left["speed"] = value
        motor_right["speed"] = -value
        return
    if motorstates["right"]:
        motor_left["speed"] = -value
        motor_right["speed"] = value
        return

class MyController(Controller):
    def __init___(self, **kwargs):
        Controller.__init___(self, **kwargs)

    def on_R2_press(self, value):
        global stopScript, motorstates
        motorstates["right"] = True
        if not stopScript and scriptProcess is not None and scriptProcess.is_alive():
            requests.get('https://koffiekarretje.opdewolk.nl/einde')
            stopScript = True
            motor_left["speed"] = 0
            motor_right["speed"] = 0

        updateMotor(transf(value))

    def on_R2_release(self):
        global motorstates
        motor_right["speed"] = 0
        motorstates["right"] = False

    def on_L2_press(self, value):
        global stopScript, motorstates
        motorstates["left"] = True
        if scriptProcess is not None and scriptProcess.is_alive():
            stopScript = True
            motor_left["speed"] = 0
            motor_right["speed"] = 0

        updateMotor(transf(value))

    def on_L2_release(self):
        global motorstates
        motorstates["left"] = False

        motor_left["speed"] = 0

    def on_x_press(self):
        global reverse
        print("INPUT: reverse")
        reverse = not reverse
        global stopScript
        if not stopScript and scriptProcess is not None and scriptProcess.is_alive():
            requests.get('https://koffiekarretje.opdewolk.nl/einde')
            stopScript = True
            motor_left["speed"] = 0
            motor_right["speed"] = 0

    def on_triangle_press(self):
        global scriptProcess, stopScript
        if not stopScript and scriptProcess is not None and scriptProcess.is_alive():
            stopScript = True
            requests.get('https://koffiekarretje.opdewolk.nl/einde')
            motor_left["speed"] = 0
            motor_right["speed"] = 0
        scriptProcess = Thread(target=script)
        stopScript = False
        scriptProcess.start()

    # Negeer events van library, anders zorgt dit voor overbodige prints
    def on_R3_down(self,value):
        1
    def on_R3_up(self,value):
        1
    def on_R3_left(self,value):
        1
    def on_R3_right(self,value):
        1
    def on_R3_x_at_rest(self):
        1
    def on_R3_y_at_rest(self):
        1
    def on_L3_down(self,value):
        1
    def on_L3_up(self,value):
        1
    def on_L3_left(self,value):
        1
    def on_L3_right(self,value):
        1
    def on_L3_x_at_rest(self):
        1
    def on_L3_y_at_rest(self):
        1
    
controller = MyController(interface="/dev/input/js0", connecting_using_ds4drv=False)
controller.listen()

GPIO.cleanup()