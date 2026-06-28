#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <Adafruit_ADS1X15.h>
#include <math.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ======================================================
// OLED Display
// ======================================================

#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64

Adafruit_SSD1306 display(
  SCREEN_WIDTH,
  SCREEN_HEIGHT,
  &Wire,
  -1
);

// ======================================================
// WiFi + Server
// ======================================================

const char* ssid       = "YOUR_FACTORY_WIFI_SSID";
const char* password   = "YOUR_FACTORY_WIFI_PASSWORD";
const char* serverURL  = "https://YOUR-APP-NAME.onrender.com/predict";
const char* MACHINE_ID = "CNC-01";

// ======================================================
// Hardware
// ======================================================

#define MPU_ADDR   0x69
#define SDA_PIN    21
#define SCL_PIN    22
#define BUZZER_PIN 23

Adafruit_ADS1115 ads;

// ======================================================
// Calibration & Thresholds
// ======================================================

float calibrationFactor  = 500.0;
float currentThreshold   = 0.060;
float vibrationThreshold = 1.000;

float baseline_x = 0;
float baseline_y = 0;
float baseline_z = 0;

// ======================================================
// Machine States
// ======================================================

enum MachineState {
  MACHINE_OFF,
  MACHINE_IDLE,
  MACHINE_WORKING
};

MachineState currentState = MACHINE_OFF;

int postCounter = 0;

// ======================================================
// MPU6050 Helpers
// ======================================================

void writeRegister(byte reg, byte value) {

  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission(true);
}

int16_t readWord(byte reg) {

  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.endTransmission(false);

  Wire.requestFrom(MPU_ADDR, 2, true);

  return (Wire.read() << 8) | Wire.read();
}

float readAX() {
  return (readWord(0x3B) / 16384.0) * 9.81;
}

float readAY() {
  return (readWord(0x3D) / 16384.0) * 9.81;
}

float readAZ() {
  return (readWord(0x3F) / 16384.0) * 9.81;
}

// ======================================================
// OLED Boot Animation
// ======================================================

void bootAnimation() {

  for (int x = 128; x > -120; x -= 3) {

    display.clearDisplay();

    // Border
    display.drawRect(0, 0, 128, 64, WHITE);

    // Moving Title
    display.setTextSize(1);
    display.setTextColor(WHITE);

    display.setCursor(x, 20);
    display.println("SMARTSENSE CNC");

    display.setCursor(x + 12, 40);
    display.println("Machine Monitor");

    display.display();

    delay(20);
  }

  // Final Screen
  display.clearDisplay();

  display.drawRect(0, 0, 128, 64, WHITE);

  display.setTextSize(1);

  display.setCursor(22, 18);
  display.println("SMARTSENSE CNC");

  display.setCursor(32, 38);
  display.println("Starting...");

  display.display();

  delay(1500);
}

// ======================================================
// OLED State Screen
// ======================================================

void drawStateScreen(
  String state,
  float current,
  float vibration
) {

  static int floatOffset = 0;
  static bool moveDown = true;

  // Floating Animation
  if (moveDown) {

    floatOffset++;

    if (floatOffset > 4)
      moveDown = false;
  }
  else {

    floatOffset--;

    if (floatOffset < 0)
      moveDown = true;
  }

  display.clearDisplay();

  // Border
  display.drawRect(0, 0, 128, 64, WHITE);

  // Header
  display.setTextSize(1);
  display.setTextColor(WHITE);

  display.setCursor(22, 5);
  display.println("SMARTSENSE CNC");

  // Divider
  display.drawLine(0, 16, 128, 16, WHITE);

  // Main State Text
  display.setTextSize(2);

  if (state == "OFF") {

    display.setCursor(38, 26);
    display.println("OFF");
  }
  else if (state == "IDLE") {

    display.setCursor(28, 24 + floatOffset);
    display.println("IDLE");
  }
  else {

    display.setCursor(6, 24 + floatOffset);
    display.println("WORKING");
  }

  // Bottom Data
  display.setTextSize(1);

  display.setCursor(4, 54);

  display.print("I:");
  display.print(current, 2);
  display.print("A");

  display.setCursor(70, 54);

  display.print("V:");
  display.print(vibration, 1);

  display.display();
}

// ======================================================
// Calibrate MPU6050
// ======================================================

void calibrateMPU() {

  Serial.println("Keep MPU6050 still...");
  delay(3000);

  float sx = 0;
  float sy = 0;
  float sz = 0;

  int samples = 50;

  for (int i = 0; i < samples; i++) {

    sx += readAX();
    sy += readAY();
    sz += readAZ();

    delay(50);
  }

  baseline_x = sx / samples;
  baseline_y = sy / samples;
  baseline_z = sz / samples;

  Serial.println("MPU6050 calibrated.");
}

// ======================================================
// Get State Label
// ======================================================

String getStateLabel(MachineState s) {

  switch (s) {

    case MACHINE_OFF:
      return "OFF";

    case MACHINE_IDLE:
      return "IDLE";

    case MACHINE_WORKING:
      return "WORKING";

    default:
      return "UNKNOWN";
  }
}

// ======================================================
// Detect Machine State
// ======================================================

MachineState detectState(
  float current,
  float vibration
) {

  if (
    current >= currentThreshold &&
    vibration >= vibrationThreshold
  ) {

    return MACHINE_WORKING;
  }

  if (
    current >= currentThreshold &&
    vibration < vibrationThreshold
  ) {

    return MACHINE_IDLE;
  }

  return MACHINE_OFF;
}

// ======================================================
// Send Data to Flask
// ======================================================

void postToFlask(
  float current,
  float vibration,
  String state
) {

  if (WiFi.status() != WL_CONNECTED) {

    Serial.println("[WiFi] Not Connected");
    return;
  }

  HTTPClient http;

  http.begin(serverURL);

  http.addHeader(
    "Content-Type",
    "application/json"
  );

  StaticJsonDocument<128> doc;

  doc["machine_id"] = MACHINE_ID;
  doc["vibration"]  = vibration;
  doc["current"]    = current;
  doc["state"]      = state;

  String payload;

  serializeJson(doc, payload);

  int httpCode = http.POST(payload);

  if (httpCode == 200) {

    Serial.println("[Flask] Success");
  }
  else {

    Serial.print("[Flask] Error: ");
    Serial.println(httpCode);
  }

  http.end();
}

// ======================================================
// Setup
// ======================================================

void setup() {

  Serial.begin(115200);

  delay(1000);

  pinMode(BUZZER_PIN, OUTPUT);

  digitalWrite(BUZZER_PIN, LOW);

  // I2C
  Wire.begin(SDA_PIN, SCL_PIN);

  // OLED Init
  if (!display.begin(
        SSD1306_SWITCHCAPVCC,
        0x3C
      )) {

    Serial.println("OLED Failed");

    while (1);
  }

  // Startup Animation
  bootAnimation();

  // ADS1115 Init
  if (!ads.begin()) {

    Serial.println("ADS1115 NOT detected");

    while (1);
  }

  Serial.println("ADS1115 detected");

  // Wake MPU6050
  writeRegister(0x6B, 0x00);

  delay(100);

  calibrateMPU();

  // WiFi Connect
  Serial.print("Connecting WiFi");

  WiFi.begin(ssid, password);

  int attempts = 0;

  while (
    WiFi.status() != WL_CONNECTED &&
    attempts < 20
  ) {

    delay(500);

    Serial.print(".");

    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {

    Serial.println("\nWiFi Connected");

    Serial.print("ESP32 IP: ");

    Serial.println(WiFi.localIP());
  }
  else {

    Serial.println("\nWiFi Failed");
  }

  Serial.println("SmartSense CNC Started");
}

// ======================================================
// Main Loop
// ======================================================

void loop() {

  // ===================================================
  // Current Measurement
  // ===================================================

  int samples = 100;

  long sum = 0;

  for (int i = 0; i < samples; i++) {

    sum += ads.readADC_SingleEnded(0);
  }

  float midpoint =
    sum / (float)samples;

  float sumSquares = 0;

  for (int i = 0; i < samples; i++) {

    float centered =
      ads.readADC_SingleEnded(0) - midpoint;

    sumSquares += centered * centered;
  }

  float rmsADC =
    sqrt(sumSquares / samples);

  float voltage =
    rmsADC * 0.0001875;

  float current =
    voltage * calibrationFactor;

  if (current < 0.01) {

    current = 0;
  }

  // ===================================================
  // Vibration Measurement
  // ===================================================

  float ax = readAX();
  float ay = readAY();
  float az = readAZ();

  float dx = ax - baseline_x;
  float dy = ay - baseline_y;
  float dz = az - baseline_z;

  float vibration =
    sqrt(dx * dx + dy * dy + dz * dz);

  // ===================================================
  // Detect Machine State
  // ===================================================

  MachineState newState =
    detectState(current, vibration);

  if (newState != currentState) {

    Serial.println("=================================");

    Serial.print(
      getStateLabel(currentState)
    );

    Serial.print(" --> ");

    Serial.println(
      getStateLabel(newState)
    );

    Serial.println("=================================");

    currentState = newState;
  }

  // ===================================================
  // Continuous Buzzer
  // ===================================================

  if (currentState == MACHINE_IDLE) {

    digitalWrite(BUZZER_PIN, HIGH);
  }
  else {

    digitalWrite(BUZZER_PIN, LOW);
  }

  // ===================================================
  // OLED Display
  // ===================================================

  drawStateScreen(
    getStateLabel(currentState),
    current,
    vibration
  );

  // ===================================================
  // Serial Monitor
  // ===================================================

  Serial.print("Current: ");
  Serial.print(current, 3);
  Serial.println(" A");

  Serial.print("Vibration: ");
  Serial.print(vibration, 3);
  Serial.println(" m/s²");

  Serial.print("State: ");
  Serial.println(
    getStateLabel(currentState)
  );

  Serial.println("--------------------------------");

  // ===================================================
  // Send Data to Flask
  // ===================================================

  postCounter++;

  if (postCounter >= 5) {

    postToFlask(
      current,
      vibration,
      getStateLabel(currentState)
    );

    postCounter = 0;
  }

  // Smooth OLED animation
  delay(120);
}
