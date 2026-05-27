/*
============================================================================
  AquaSense — MQTT via SIM800L
  ESP32-S3 + SIM800L → GPRS → MQTT broker (broker.hivemq.com:1883)

  Features:
  - DS18B20 temperature sensing
  - Ultrasonic water level sensing
  - Blind-zone handling
  - Temperature compensated distance
  - MQTT publish over GPRS
============================================================================
*/

#define TINY_GSM_MODEM_SIM800

#include <TinyGsmClient.h>
#include <PubSubClient.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <HardwareSerial.h>

// ─────────────────────────────────────────────────────────────────────────────
// SETTINGS
// ─────────────────────────────────────────────────────────────────────────────
const char* APN         = "internet";
const char* NODE_ID     = "NODE_01";

const char* MQTT_BROKER = "broker.hivemq.com";
const int   MQTT_PORT   = 1883;
const char* MQTT_TOPIC  = "aquasense/NODE_01";

// ─────────────────────────────────────────────────────────────────────────────
// PINS
// ─────────────────────────────────────────────────────────────────────────────
#define DS18B20_PIN   16

#define TRIG_PIN      17
#define ECHO_PIN      18

#define SIM_ESP_RX     9
#define SIM_ESP_TX    10
#define SIM_RST       11

// ─────────────────────────────────────────────────────────────────────────────
// TANK & TIMING
// ─────────────────────────────────────────────────────────────────────────────
#define SAMPLE_MS         15000UL

// Actual tank height
#define TANK_HEIGHT_CM    152.4f

// Height of sensor from tank bottom
#define SENSOR_HEIGHT_CM  140.4f

// Ultrasonic blind zone
#define BLIND_ZONE_CM     14.0f  //15 - 1 bcz 1cm calibrate during testing

// ─────────────────────────────────────────────────────────────────────────────
// OBJECTS
// ─────────────────────────────────────────────────────────────────────────────
HardwareSerial simSerial(1);
HardwareSerial UltrasonicSerial(2);

OneWire oneWire(DS18B20_PIN);
DallasTemperature tempSensor(&oneWire);

TinyGsm modem(simSerial);
TinyGsmClient gsmClient(modem);

PubSubClient mqtt(gsmClient);

// ─────────────────────────────────────────────────────────────────────────────
// STATE VARIABLES
// ─────────────────────────────────────────────────────────────────────────────
float curTemp      = 25.0f;

// Start assuming empty tank
float lastDist     = SENSOR_HEIGHT_CM;

float waterLevel   = 0.0f;

unsigned long tLastSample = 0;


// ═════════════════════════════════════════════════════════════════════════════
// TEMPERATURE SENSOR
// ═════════════════════════════════════════════════════════════════════════════
float readTemperature() {

  tempSensor.requestTemperatures();

  float t = tempSensor.getTempCByIndex(0);

  // Accept only valid temperatures
  if (t > -55.0f && t < 125.0f) {
    return t;
  }

  return curTemp;
}


// ═════════════════════════════════════════════════════════════════════════════
// ULTRASONIC SENSOR
// ═════════════════════════════════════════════════════════════════════════════
float readSonar() {

  while (UltrasonicSerial.available()) {
    UltrasonicSerial.read();
  }

  UltrasonicSerial.write(0x55);

  unsigned long start = millis();

  while (UltrasonicSerial.available() < 4) {

    if (millis() - start > 200) {
      return -1;
    }
  }

  uint8_t data[4];

  UltrasonicSerial.readBytes(data, 4);

  if (data[0] == 0xFF) {

    int dist_mm =
      (data[1] << 8) | data[2];

    int checksum =
      (data[0] + data[1] + data[2]) & 0xFF;

    if (checksum == data[3] &&
        dist_mm > 0 &&
        dist_mm < 8000) {

      return dist_mm / 10.0f;
    }
  }

  return -1;
}


// ═════════════════════════════════════════════════════════════════════════════
// MQTT CONNECT
// ═════════════════════════════════════════════════════════════════════════════
bool mqttConnect() {

  Serial.print("[MQTT] Connecting...");

  String clientId =
    "AquaSense_" +
    String(NODE_ID) +
    "_" +
    String(millis());

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

  delay(3000);

  Serial.println("BOOT OK");

  pinMode(SIM_RST, OUTPUT);
  digitalWrite(SIM_RST, HIGH);

  Serial.println("SIM RESET PIN OK");

  tempSensor.begin();

  Serial.println("TEMP SENSOR OK");

  simSerial.begin(
    9600,
    SERIAL_8N1,
    SIM_ESP_RX,
    SIM_ESP_TX
  );

  Serial.println("SIM SERIAL OK");

  UltrasonicSerial.begin(
    9600,
    SERIAL_8N1,
    ECHO_PIN,
    TRIG_PIN
  );

  Serial.println("ULTRASONIC SERIAL OK");

  delay(3000);

  Serial.println("[GSM] Restarting modem...");

  modem.restart();

  Serial.println("MODEM RESTART DONE");

  Serial.print("[GSM] Waiting for network...");

  if (!modem.waitForNetwork(60000L)) {

    Serial.println(" FAIL");

    return;
  }

  Serial.println(" OK");

  Serial.print("[GSM] Connecting GPRS...");

  if (!modem.gprsConnect(APN)) {

    Serial.println(" FAIL");

    return;
  }

  Serial.println(" OK");

  Serial.print("[GSM] IP: ");
  Serial.println(modem.localIP());

  mqtt.setServer(MQTT_BROKER, MQTT_PORT);

  mqttConnect();
}

void loop() {

  // ── MQTT KEEPALIVE ────────────────────────────────────────────────────────
  if (!mqtt.connected()) {

    Serial.println("[MQTT] Reconnecting...");

    if (!modem.isGprsConnected()) {

      Serial.println("[GSM] Reconnecting GPRS...");

      modem.gprsConnect(APN);
    }

    mqttConnect();
  }

  mqtt.loop();


  // ── PERIODIC SAMPLING ─────────────────────────────────────────────────────
  unsigned long now = millis();

  if (now - tLastSample >= SAMPLE_MS) {

    tLastSample = now;

    // Temperature
    curTemp = readTemperature();

    delay(50);

    // Distance
    float d = readSonar();

    // Accept only valid readings
    if (d >= BLIND_ZONE_CM &&
        d <= SENSOR_HEIGHT_CM) {

      lastDist = d;
    }

    float curDist = lastDist;

    // Temperature compensation
    float vWtc =
      343.0f *
      sqrt((curTemp + 273.0f) / 273.0f);

    float distCompensated =
      curDist * (vWtc / 343.0f);

    // Water level
    waterLevel =
      SENSOR_HEIGHT_CM - distCompensated;

    if (waterLevel < 0)
      waterLevel = 0;

    if (waterLevel > SENSOR_HEIGHT_CM)
      waterLevel = SENSOR_HEIGHT_CM;

    // JSON payload
    char payload[128];

    snprintf(
      payload,
      sizeof(payload),
      "{\"node_id\":\"%s\",\"temperature\":%.1f,\"water_level\":%.1f}",
      NODE_ID,
      curTemp,
      waterLevel
    );

    // Publish
    bool ok =
      mqtt.publish(
        MQTT_TOPIC,
        payload,
        true
      );

    Serial.print("[MQTT] Published: ");
    Serial.print(payload);

    Serial.println(ok ? " [OK]" : " [FAIL]");
  }
}
