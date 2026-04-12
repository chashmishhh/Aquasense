/*
============================================================================
  AquaSense — DIRECT TO SUPABASE
  ESP32-S3 + SIM800L → GPRS → Supabase REST API (HTTPS)
  field1 = Temperature (°C), field2 = Water Level (cm)
============================================================================
*/

#include <OneWire.h>
#include <DallasTemperature.h>
#include <HardwareSerial.h>

// ─── SETTINGS ────────────────────────────────────────────────────────────────
const char* APN          = "internet";   // your SIM card APN
const char* NODE_ID      = "NODE_001";

const char* SUPABASE_URL =
  "https://cguaghcgesxgmrghaghg.supabase.co/rest/v1/sensor_data";

const char* ANON_KEY =
  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
  ".eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImNndWFnaGNnZXN4Z21yZ2hhZ2hnIiwicm9sZSI"
  6ImFub24iLCJpYXQiOjE3NzQwMDM4MTksImV4cCI6MjA4OTU3OTgxOX0"
  ".A1LSsykrVc3J-DLx3q8RH11XT5kHYKuY3SDJRK6VSvE";

// ─── PINS ────────────────────────────────────────────────────────────────────
#define DS18B20_PIN  16
#define TRIG_PIN     17   // AJSR04M RX ← ESP32 TX
#define ECHO_PIN     18   // AJSR04M TX → ESP32 RX
#define SIM_ESP_RX    9   // ESP32 RX ← SIM TX
#define SIM_ESP_TX   10   // ESP32 TX → SIM RX
#define SIM_RST      11

// ─── TIMING & TANK ───────────────────────────────────────────────────────────
#define SAMPLE_MS       15000UL
#define TANK_HEIGHT_CM  152.4f
#define TANK_CAPACITY_L 2000.0f

// ─── OBJECTS & STATE ─────────────────────────────────────────────────────────
OneWire           oneWire(DS18B20_PIN);
DallasTemperature tempSensor(&oneWire);
HardwareSerial    simSerial(1);
HardwareSerial    UltrasonicSerial(2);

float curTemp    = 25.0f;
float lastDist   = 0.0f;
float waterLevel = 0.0f;
bool  simReady   = false;
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
// SIM HELPERS
// ═════════════════════════════════════════════════════════════════════════════
void simFlush() {
  delay(100);
  while (simSerial.available()) simSerial.read();
}

bool simCmd(const char* cmd, const char* expect, uint16_t timeout = 4000) {
  simFlush();
  if (cmd && strlen(cmd) > 0) simSerial.println(cmd);
  String buf = "";
  unsigned long t = millis();
  while (millis() - t < timeout) {
    while (simSerial.available()) buf += (char)simSerial.read();
    if (buf.indexOf(expect) >= 0) return true;
    delay(10);
  }
  return false;
}

// Wait for a response without sending a command
String simRead(uint16_t timeout = 5000) {
  String buf = "";
  unsigned long t = millis();
  while (millis() - t < timeout) {
    while (simSerial.available()) buf += (char)simSerial.read();
    delay(10);
  }
  return buf;
}


// ═════════════════════════════════════════════════════════════════════════════
// GET NETWORK TIME via AT+CCLK
// Returns "YYYY-MM-DD HH:MM:SS"
// ═════════════════════════════════════════════════════════════════════════════
void getTimestamp(char* buf, int bufLen) {
  simFlush();
  simSerial.println("AT+CCLK?");
  delay(1500);
  String r = "";
  while (simSerial.available()) r += (char)simSerial.read();

  // Format from modem: +CCLK: "26/04/03,17:00:00+22"
  int q = r.indexOf('"');
  if (q >= 0 && (int)r.length() > q + 17) {
    int yy = r.substring(q + 1, q + 3).toInt();
    int mo = r.substring(q + 4, q + 6).toInt();
    int dd = r.substring(q + 7, q + 9).toInt();
    int hh = r.substring(q + 10, q + 12).toInt();
    int mi = r.substring(q + 13, q + 15).toInt();
    int ss = r.substring(q + 16, q + 18).toInt();
    if (mo >= 1 && mo <= 12 && dd >= 1 && dd <= 31) {
      snprintf(buf, bufLen, "20%02d-%02d-%02d %02d:%02d:%02d",
               yy, mo, dd, hh, mi, ss);
      return;
    }
  }
  snprintf(buf, bufLen, "2026-01-01 00:00:00");  // fallback
}


// ═════════════════════════════════════════════════════════════════════════════
// GPRS BEARER INIT (for HTTP AT commands)
// ═════════════════════════════════════════════════════════════════════════════
bool bearerInit() {
  // Enable network time sync so AT+CCLK? returns real time
  simCmd("AT+CLTS=1", "OK", 2000);

  char apnCmd[80];
  snprintf(apnCmd, sizeof(apnCmd), "AT+SAPBR=3,1,\"APN\",\"%s\"", APN);

  simCmd("AT+SAPBR=0,1", "OK", 8000);                        // close if open
  simCmd("AT+SAPBR=3,1,\"CONTYPE\",\"GPRS\"", "OK", 3000);
  simCmd(apnCmd, "OK", 3000);
  if (!simCmd("AT+SAPBR=1,1", "OK", 20000)) return false;   // open bearer

  // Confirm we got an IP
  simSerial.println("AT+SAPBR=2,1");
  String r = simRead(3000);
  return (r.indexOf("+SAPBR") >= 0 && r.indexOf("0.0.0.0") < 0);
}

bool simInit() {
  for (int i = 0; i < 10; i++) {
    if (simCmd("AT", "OK", 1000)) break;
    delay(500);
  }
  simCmd("ATE0",     "OK", 2000);
  simCmd("AT+CMEE=2","OK", 2000);

  for (int i = 0; i < 15; i++) {
    if (simCmd("AT+CPIN?", "READY", 2000)) break;
    delay(1000);
  }

  for (int i = 0; i < 30; i++) {
    simSerial.println("AT+CREG?");
    delay(800);
    String r = simRead(1000);
    if (r.indexOf(",1") >= 0 || r.indexOf(",5") >= 0) break;
    delay(1000);
  }

  return bearerInit();
}


// ═════════════════════════════════════════════════════════════════════════════
// SEND TO SUPABASE via SIM800L HTTP AT commands + SSL
// ═════════════════════════════════════════════════════════════════════════════
bool sendToSupabase(float temp, float level) {

  // --- Build JSON body ---
  char ts[32];
  getTimestamp(ts, sizeof(ts));

  char body[256];
  snprintf(body, sizeof(body),
    "{\"node_id\":\"%s\",\"field1\":%.1f,\"field2\":%.1f,\"created_at\":\"%s\"}",
    NODE_ID, temp, level, ts);
  int bodyLen = strlen(body);

  // --- Terminate any stale HTTP session ---
  simSerial.println("AT+HTTPTERM");
  delay(1000); simFlush();

  // --- Init HTTP service ---
  if (!simCmd("AT+HTTPINIT", "OK", 5000))                         goto fail;

  // --- Bearer profile ---
  if (!simCmd("AT+HTTPPARA=\"CID\",1", "OK", 3000))              goto fail;

  // --- URL ---
  {
    char urlCmd[200];
    snprintf(urlCmd, sizeof(urlCmd),
             "AT+HTTPPARA=\"URL\",\"%s\"", SUPABASE_URL);
    if (!simCmd(urlCmd, "OK", 3000))                              goto fail;
  }

  // --- Enable SSL ---
  if (!simCmd("AT+HTTPSSL=1", "OK", 3000))                       goto fail;

  // --- Content-Type ---
  if (!simCmd("AT+HTTPPARA=\"CONTENT\",\"application/json\"", "OK", 3000))
                                                                  goto fail;

  // --- API Key header ---
  // Send raw so we control exactly what goes on the wire.
  // The AT parser ends the command on the final \r\n only.
  {
    simFlush();
    simSerial.print("AT+HTTPPARA=\"USERDATA\",\"apikey: ");
    simSerial.print(ANON_KEY);
    simSerial.print("\"\r\n");   // ← ONLY CR+LF here — the AT command terminator
    String r = simRead(3000);
    if (r.indexOf("ERROR") >= 0)                                  goto fail;
  }

  // --- POST body ---
  {
    char dc[32];
    snprintf(dc, sizeof(dc), "AT+HTTPDATA=%d,10000", bodyLen);
    if (!simCmd(dc, "DOWNLOAD", 5000))                            goto fail;
    simSerial.print(body);
    delay(bodyLen + 500);
    if (!simCmd("", "OK", 5000))                                  goto fail;
  }

  // --- Execute POST ---
  if (!simCmd("AT+HTTPACTION=1", "OK", 5000))                    goto fail;

  // --- Wait for +HTTPACTION: 1,<status>,<len> ---
  {
    String resp = simRead(15000);
    simSerial.println("AT+HTTPTERM");
    delay(500);
    // 201 = Created, 200 = OK
    return (resp.indexOf(",201") >= 0 || resp.indexOf(",200") >= 0);
  }

fail:
  simSerial.println("AT+HTTPTERM");
  delay(500);
  return false;
}


// ═════════════════════════════════════════════════════════════════════════════
// SETUP
// ═════════════════════════════════════════════════════════════════════════════
void setup() {
  pinMode(SIM_RST, OUTPUT);
  digitalWrite(SIM_RST, HIGH);

  tempSensor.begin();
  simSerial.begin(9600, SERIAL_8N1, SIM_ESP_RX, SIM_ESP_TX);
  UltrasonicSerial.begin(9600, SERIAL_8N1, ECHO_PIN, TRIG_PIN);

  delay(12000);
  simReady = simInit();
}


// ═════════════════════════════════════════════════════════════════════════════
// LOOP
// ═════════════════════════════════════════════════════════════════════════════
void loop() {
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

    // Re-init if lost connection
    if (!simReady) simReady = simInit();

    if (simReady) {
      bool ok = sendToSupabase(curTemp, waterLevel);
      if (!ok) simReady = false;  // force re-init next cycle
    }
  }
}