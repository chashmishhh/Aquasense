/*
============================================================================
  AquaSense — MQTT via SIM800L
  ESP32-S3 + SIM800L → GPRS → MQTT broker (broker.hivemq.com:1883, plain TCP)
  Topic: aquasense/NODE_01
  Payload: {"node_id":"NODE_01","temperature":25.1,"water_level":90.2}

  Libraries needed (install via Arduino Library Manager):
    - TinyGSM        (by Volodymyr Shymanskyy)
    - PubSubClient   (by Nick O'Leary)
    - DallasTemperature + OneWire
============================================================================
*/

#define TINY_GSM_MODEM_SIM800
#include <TinyGsmClient.h>
#include <PubSubClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <HardwareSerial.h>

// ─── SETTINGS ────────────────────────────────────────────────────────────────
const char* APN         = "internet";          // your SIM card APN
const char* NODE_ID     = "NODE_01";

const char* MQTT_BROKER   = "broker.hivemq.com";  // HiveMQ public broker
const int   MQTT_PORT     = 1883;                  // Plain TCP (no TLS)
const char* MQTT_TOPIC    = "aquasense/NODE_01";

// ─── PINS ────────────────────────────────────────────────────────────────────
#define DS18B20_PIN  16
#define ECHO_PIN     18   // AJSR04M TX → ESP32 RX
#define TRIG_PIN     17   // AJSR04M RX ← ESP32 TX
#define SIM_ESP_RX    9   // ESP32 RX ← SIM TX
#define SIM_ESP_TX   10   // ESP32 TX → SIM RX
#define SIM_RST      11

// ─── TIMING & TANK ───────────────────────────────────────────────────────────
#define SAMPLE_MS       15000UL
#define TANK_HEIGHT_CM  152.4f

// ─── OBJECTS ─────────────────────────────────────────────────────────────────
HardwareSerial    simSerial(1);
HardwareSerial    UltrasonicSerial(2);
OneWire           oneWire(DS18B20_PIN);
DallasTemperature tempSensor(&oneWire);
TinyGsm             modem(simSerial);
TinyGsmClient       gsmClient(modem);   // Plain TCP client (SIM800L has no TLS)
PubSubClient        mqtt(gsmClient);

// ─── STATE ───────────────────────────────────────────────────────────────────
float curTemp    = 25.0f;
float lastDist   = 0.0f;
float waterLevel = 0.0f;
unsigned long tLastSample = 0;


// ═════════════════════════════════════════════════════════════════════════════
// SENSORS
// ═════════════════════════════════════════════════════════════════════════════
float readTemperature() {
  tempSensor.requestTemperatures();
  float t = tempSensor.getTempCByIndex(0);
  return (t > -55.0f && t < 125.0f) ? t : curTemp;
}

float readSonar() {
  while (UltrasonicSerial.available()) UltrasonicSerial.read();
  UltrasonicSerial.write(0x55);
  unsigned long start = millis();
  while (UltrasonicSerial.available() < 4) {
    if (millis() - start > 200) return -1;
  }
  uint8_t data[4];
  UltrasonicSerial.readBytes(data, 4);
  if (data[0] == 0xFF) {
    int dist_mm  = (data[1] << 8) | data[2];
    int checksum = (data[0] + data[1] + data[2]) & 0xFF;
    if (checksum == data[3] && dist_mm > 0 && dist_mm < 8000)
      return dist_mm / 10.0f;
  }
  return -1;
}


// ═════════════════════════════════════════════════════════════════════════════
// MQTT CONNECT
// ═════════════════════════════════════════════════════════════════════════════
bool mqttConnect() {
  Serial.print("[MQTT] Connecting to HiveMQ (TCP)...");
  // Unique client ID prevents duplicate session conflicts on broker
  String clientId = "AquaSense_" + String(NODE_ID) + "_" + String(millis());
  // Public broker — no username/password needed
  if (mqtt.connect(clientId.c_str())) {
    Serial.println(" OK");
    return true;
  }
  Serial.print(" FAIL rc=");
  Serial.println(mqtt.state());
  return false;
}


// ═════════════════════════════════════════════════════════════════════════════
// SETUP
// ═════════════════════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(115200);
  delay(100);

  pinMode(SIM_RST, OUTPUT);
  digitalWrite(SIM_RST, HIGH);

  tempSensor.begin();
  simSerial.begin(9600, SERIAL_8N1, SIM_ESP_RX, SIM_ESP_TX);
  UltrasonicSerial.begin(9600, SERIAL_8N1, ECHO_PIN, TRIG_PIN);

  delay(3000);
  Serial.println("[GSM] Restarting modem...");
  modem.restart();

  Serial.print("[GSM] Waiting for network...");
  if (!modem.waitForNetwork(60000L)) {
    Serial.println(" FAIL — check SIM card");
    while (true);
  }
  Serial.println(" OK");

  Serial.print("[GSM] Connecting GPRS (APN: ");
  Serial.print(APN);
  Serial.print(")...");
  if (!modem.gprsConnect(APN)) {
    Serial.println(" FAIL — check APN");
    while (true);
  }
  Serial.println(" OK");
  Serial.print("[GSM] IP: ");
  Serial.println(modem.localIP());

  mqtt.setServer(MQTT_BROKER, MQTT_PORT);
  mqttConnect();
}


// ═════════════════════════════════════════════════════════════════════════════
// LOOP
// ═════════════════════════════════════════════════════════════════════════════
void loop() {

  // ── Keep MQTT alive ──────────────────────────────────────────────────────
  if (!mqtt.connected()) {
    Serial.println("[MQTT] Disconnected, reconnecting...");
    if (!modem.isGprsConnected()) {
      Serial.println("[GSM] GPRS lost, reconnecting...");
      modem.gprsConnect(APN);
    }
    mqttConnect();
  }
  mqtt.loop();

  // ── Sample & publish every SAMPLE_MS ─────────────────────────────────────
  unsigned long now = millis();
  if (now - tLastSample >= SAMPLE_MS) {
    tLastSample = now;

    curTemp = readTemperature();
    delay(50);

    float d = readSonar();
    if (d > 0) lastDist = d;
    float curDist = (lastDist > 0) ? lastDist : 0;

    // Temperature-compensated water level
    float vWtc            = 343.0f * sqrt((curTemp + 273.0f) / 273.0f);
    float distCompensated = curDist * (vWtc / 343.0f);
    waterLevel = TANK_HEIGHT_CM - distCompensated;
    if (waterLevel < 0)              waterLevel = 0;
    if (waterLevel > TANK_HEIGHT_CM) waterLevel = TANK_HEIGHT_CM;

    // Build JSON payload
    char payload[128];
    snprintf(payload, sizeof(payload),
      "{\"node_id\":\"%s\",\"temperature\":%.1f,\"water_level\":%.1f}",
      NODE_ID, curTemp, waterLevel);

    // Publish — retained=true so broker keeps last value for late subscribers
    bool ok = mqtt.publish(MQTT_TOPIC, payload, true);
    Serial.print("[MQTT] Published: ");
    Serial.print(payload);
    Serial.println(ok ? " [OK]" : " [FAIL]");
  }
}