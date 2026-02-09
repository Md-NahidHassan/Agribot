#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <Servo.h>

/* ================= 1. CAR PIN CONFIG ================= */
const int LM_F = 3;
const int LM_B = 4;
const int RM_F = 5;
const int RM_B = 6;

const int CAR_TRIG_PIN = 7; // For car
const int CAR_ECHO_PIN = 8;
const int HEAD_SERVO_PIN = 9;

/* ================= 2. ARM & HARVEST CONFIG ================= */
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

#define SERVOMIN  150 
#define SERVOMAX  600 

const int soilSensorPin = A0;    
const int pumpPin = 10;          
const int extraServoChannel = 4; // For soil sensor

// arm  (HC-SR04 for Arm)
const int ARM_ECHO_PIN = 12;
const int ARM_TRIG_PIN = 13;

/* ================= OBJECTS & VARIABLES ================= */
Servo headServo;

// Car Variables
char currentCommand = 'x';    
bool autoMode = false;        
const int OBSTACLE_DISTANCE = 25; 

// Arm Settings
const int autoDelay = 8;        
const int dryThreshold = 700;    
const int servoUpPos = 90;       
const int servoDownPos = 70;  
int currentPos[16]; 

/* ================= SETUP ================= */
void setup() {
  Serial.begin(9600);

  // --- Car Setup ---
  pinMode(LM_F, OUTPUT); pinMode(LM_B, OUTPUT);
  pinMode(RM_F, OUTPUT); pinMode(RM_B, OUTPUT);
  pinMode(CAR_TRIG_PIN, OUTPUT); pinMode(CAR_ECHO_PIN, INPUT);
  
  headServo.attach(HEAD_SERVO_PIN);
  headServo.write(90); 

  // --- Arm Setup ---
  pwm.begin();
  pwm.setPWMFreq(60);
  
  pinMode(pumpPin, OUTPUT);
  digitalWrite(pumpPin, HIGH); // Pump OFF (Active Low)

  pinMode(ARM_TRIG_PIN, OUTPUT);
  pinMode(ARM_ECHO_PIN, INPUT);

  // arm position
  setFastPos(0, 90);   
  setFastPos(1, 90);   
  setFastPos(2, 90);   
  setFastPos(3, 130);  // Safety limit
  setFastPos(extraServoChannel, servoUpPos); 

  Serial.println("System Ready: Car + Arm + Harvest");
}

/* ================= MAIN LOOP ================= */
void loop() {
  // 1. Sriyal Comand read
  readSmartCommand();

  // 2. Car logic
  int distance = readCarDistance();

  // ===== OBSTACLE HANDLING =====
  if (distance > 0 && distance < OBSTACLE_DISTANCE) {
    if (autoMode || currentCommand == 'w') {
       avoidObstacle();
       if (!autoMode) currentCommand = 'x'; 
    }
    else if (currentCommand != 'x') {
       manualMove();
    }
    else {
       stopCar();
    }
  }
  // ===== NORMAL DRIVING =====
  else {
    if (currentCommand != 'x') {
      manualMove(); 
    }
    else if (autoMode) {
      moveForward(); 
    }
    else {
      stopCar();
    }
  }
  delay(30);
}

/* ================= SMART COMMAND PARSER ================= */
void readSmartCommand() {
  if (Serial.available() > 0) {
    char c = Serial.peek(); 

    if (isDigit(c)) {
       int channel = Serial.parseInt(); 
       int angle = Serial.parseInt();
       
       if (Serial.read() == '\n') {
          handleArmCommand(channel, angle);
       }
    }

    else {
       char cmd = Serial.read();
       handleCarCommand(cmd);
    }
  }
}

/* ================= CAR LOGIC (YOUR CODE) ================= */
void handleCarCommand(char cmd) {
  // Mode Control
  if (cmd == 'U') { 
    autoMode = true; 
    Serial.println("AUTO MODE: ON"); 
  }
  else if (cmd == 'M') { 
    autoMode = false; 
    currentCommand = 'x'; 
    stopCar(); 
    Serial.println("MANUAL MODE: ACTIVE"); 
  }
  
  // Movement
  else if (cmd == 'w' || cmd == '8') currentCommand = 'w';
  else if (cmd == 's' || cmd == '2') currentCommand = 's';
  else if (cmd == 'a' || cmd == '4') currentCommand = 'a';
  else if (cmd == 'd' || cmd == '6') currentCommand = 'd';
  
  // Stop
  else if (cmd == 'x' || cmd == '5') {
    currentCommand = 'x'; 
    autoMode = false; 
    stopCar();
    Serial.println("STOPPED (Auto Mode OFF)");
  }
}

void manualMove() {
  if (currentCommand == 'w') moveForward();
  else if (currentCommand == 's') moveBackward();
  else if (currentCommand == 'a') turnLeft();
  else if (currentCommand == 'd') turnRight();
}

void avoidObstacle() {
  stopCar();
  moveBackward();
  delay(400); 
  stopCar();

  headServo.write(20); 
  delay(500);
  int rightDist = readCarDistance();

  headServo.write(160); 
  delay(500);
  int leftDist = readCarDistance();

  headServo.write(90); 
  delay(300);

  if (rightDist > leftDist) {
    turnRight();
    delay(450); 
  } else {
    turnLeft();
    delay(450); 
  }
  stopCar();
}

int readCarDistance() { // Car ultrasonic (7, 8)
  digitalWrite(CAR_TRIG_PIN, LOW); delayMicroseconds(2);
  digitalWrite(CAR_TRIG_PIN, HIGH); delayMicroseconds(10);
  digitalWrite(CAR_TRIG_PIN, LOW);
  long duration = pulseIn(CAR_ECHO_PIN, HIGH, 30000);
  int cm = duration / 29 / 2;
  if (cm <= 0) return 400; 
  return cm;
}

// Motor Functions
void moveForward() { digitalWrite(LM_F, HIGH); digitalWrite(LM_B, LOW); digitalWrite(RM_F, HIGH); digitalWrite(RM_B, LOW); }
void moveBackward() { digitalWrite(LM_F, LOW); digitalWrite(LM_B, HIGH); digitalWrite(RM_F, LOW); digitalWrite(RM_B, HIGH); }
void turnRight() { digitalWrite(LM_F, HIGH); digitalWrite(LM_B, LOW); digitalWrite(RM_F, LOW); digitalWrite(RM_B, HIGH); }
void turnLeft() { digitalWrite(LM_F, LOW); digitalWrite(LM_B, HIGH); digitalWrite(RM_F, HIGH); digitalWrite(RM_B, LOW); }
void stopCar() { digitalWrite(LM_F, LOW); digitalWrite(LM_B, LOW); digitalWrite(RM_F, LOW); digitalWrite(RM_B, LOW); }

/* ================= ARM & HARVEST LOGIC ================= */
void handleArmCommand(int channel, int angle) {
    // A.Soil check
    if (channel == 99) {
      runAutoCheckSequence();
    }
    
    // B. arm (HC-SR04 pin 12,13)
    else if (channel == 98) {
      long dist = readArmDistance();
      Serial.print("D:"); Serial.println(dist);
    }

    // C. Pump control
    else if (channel == 8) {
      if (angle == 1) digitalWrite(pumpPin, LOW); // ON
      else digitalWrite(pumpPin, HIGH); // OFF
    }

    // D. manual control
    else {
      setFastPos(channel, angle);
    }
}

// arm distance 
long readArmDistance() {
  digitalWrite(ARM_TRIG_PIN, LOW); delayMicroseconds(2);
  digitalWrite(ARM_TRIG_PIN, HIGH); delayMicroseconds(10);
  digitalWrite(ARM_TRIG_PIN, LOW);
  long duration = pulseIn(ARM_ECHO_PIN, HIGH, 30000); // 30ms timeout
  if (duration == 0) return 999; 
  return duration * 0.034 / 2;
}

// first movement
void setFastPos(int channel, int angle) {
  if (angle < 0) angle = 0;
  if (angle > 180) angle = 180;
  if (channel == 3 && angle > 140) angle = 140; // Safety
  
  int pulse = map(angle, 0, 180, SERVOMIN, SERVOMAX);
  pwm.setPWM(channel, 0, pulse);
  currentPos[channel] = angle;
}

// soil check
void runAutoCheckSequence() {
  Serial.println("Status: Checking Soil...");
  moveServoSmooth(extraServoChannel, servoDownPos); 
  delay(4000);
  int moisture = analogRead(soilSensorPin);
  Serial.print("S:"); Serial.println(moisture);
  moveServoSmooth(extraServoChannel, servoUpPos); 
  delay(1000);

  if (moisture > dryThreshold) {
    digitalWrite(pumpPin, LOW); 
    Serial.println("Status: Pump ON");
  } else {
    digitalWrite(pumpPin, HIGH); 
    Serial.println("Status: Pump OFF");
  }
}

void moveServoSmooth(int channel, int target) {
  int start = currentPos[channel]; 
  if (start != target) {
    if (start < target) {
      for (int i = start; i <= target; i++) {
        pwm.setPWM(channel, 0, map(i, 0, 180, SERVOMIN, SERVOMAX)); delay(autoDelay); 
      }
    } else {
      for (int i = start; i >= target; i--) {
        pwm.setPWM(channel, 0, map(i, 0, 180, SERVOMIN, SERVOMAX)); delay(autoDelay);
      }
    }
  }
  currentPos[channel] = target; 
}