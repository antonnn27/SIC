#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <math.h>

#define PIN_DHT       4
#define PIN_LOAD      36
#define PIN_CASE      39
#define PIN_SCREEN    25
#define PIN_BUZZER    13
#define PIN_BTN       18

#define PIN_LED_G     26
#define PIN_LED_Y     27
#define PIN_LED_R     14

#define DHTTYPE DHT22

const char* WIFI_SSID = "Wokwi-GUEST";
const char* WIFI_PASS = "";

const char* MQTT_SERVER = "broker.hivemq.com";
const int MQTT_PORT = 1883;

const char* MQTT_TOPIC = "smartphone/thermal/telemetry";

WiFiClient espClient;
PubSubClient mqtt(espClient);

DHT dht(PIN_DHT, DHTTYPE);
LiquidCrystal_I2C lcd(0x27, 16, 2);

// Daya dasar dan pengaruh beban CPU
const float P_BASE = 0.25;
const float P_CPU = 6.5;

// Parameter pelepasan dan kapasitas panas
const float G_PASIF = 0.30;
const float C_TERMAL = 8.0;

// Histeresis untuk mencegah status berubah terlalu sering
const float HYS = 0.5;

// Suhu referensi lingkungan
const float T_AMB_REF = 20.0;

// Pengaruh suhu lingkungan
const float AMB_HEAT_GAIN = 0.020;
const float AMB_COOL_LOSS = 0.010;

// Kondisi casing
const float CASE_NONE = 0.0;
const float CASE_INSTALLED = 1.0;

// Batas kenaikan level suhu
// Level 0 = IDLE
// Level 1 = RINGAN
// Level 2 = BERAT
// Level 3 = OVERHEAT
const float T_UP[3] = {
    30.0,
    37.0,
    44.0
};

const int CLOCK_PCT[4] = {
    100, 100, 80, 25
};

const int BRIGHT_PCT[4] = {
    100, 100, 70, 25
};

// Nama status untuk LCD dan MQTT
const char* NAMA_LCD[4] = {
  "IDLE",
  "RINGAN",
  "BERAT",
  "OVERHEAT"
};

float tAmb = 20.0;
float suhu = 20.0;
float beban = 0.0;

float casing = CASE_NONE;

bool charging = false;
bool lastButtonReading = HIGH;
bool stableButtonState = HIGH;

int level = 0;

unsigned long lastDHT = 0;
unsigned long lastModel = 0;
unsigned long lastLCD = 0;
unsigned long lastMQTT = 0;
unsigned long lastButtonChange = 0;

const unsigned long DHT_INTERVAL = 2500;
const unsigned long MODEL_INTERVAL = 100;
const unsigned long LCD_INTERVAL = 250;
const unsigned long MQTT_INTERVAL = 2000;
const unsigned long DEBOUNCE_DELAY = 40;

#if defined(ESP_ARDUINO_VERSION_MAJOR) && \
    ESP_ARDUINO_VERSION_MAJOR >= 3

  void initPWM() {
    ledcAttach(PIN_SCREEN, 5000, 8);
  }

  void writePWM(int duty) {
    ledcWrite(PIN_SCREEN, duty);
  }

#else

  const int PWM_CHANNEL = 0;

  void initPWM() {
    ledcSetup(PWM_CHANNEL, 5000, 8);
    ledcAttachPin(PIN_SCREEN, PWM_CHANNEL);
  }

  void writePWM(int duty) {
    ledcWrite(PWM_CHANNEL, duty);
  }

#endif

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  Serial.println();
  Serial.print("Menghubungkan ke WiFi");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  unsigned long startAttempt = millis();

  while (WiFi.status() != WL_CONNECTED &&
         millis() - startAttempt < 15000) {
    delay(300);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.println("WiFi terhubung!");
    Serial.print("IP address: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println();
    Serial.println("WiFi belum terhubung.");
  }
}

void reconnectMQTT() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  if (mqtt.connected()) {
    return;
  }

  String clientId =
      "SmartphoneThermal-"
      + String((uint32_t)ESP.getEfuseMac(), HEX);

  Serial.print("Menghubungkan MQTT...");

  if (mqtt.connect(clientId.c_str())) {
    Serial.println("berhasil!");
  } else {
    Serial.print("gagal, state = ");
    Serial.println(mqtt.state());
  }
}

void bacaTombol() {
  bool reading = digitalRead(PIN_BTN);

  if (reading != lastButtonReading) {
    lastButtonChange = millis();
    lastButtonReading = reading;
  }

  if (millis() - lastButtonChange > DEBOUNCE_DELAY) {
    if (reading != stableButtonState) {
      stableButtonState = reading;

      if (stableButtonState == LOW) {
        charging = !charging;

        Serial.print("Charging: ");
        Serial.println(charging ? "AKTIF" : "NONAKTIF");
      }
    }
  }
}

void bacaDHT() {
  unsigned long now = millis();

  if (now - lastDHT < DHT_INTERVAL) {
    return;
  }

  lastDHT = now;

  float temp = dht.readTemperature();

  if (!isnan(temp) && temp >= -20.0 && temp <= 80.0) {
    tAmb = temp;

    Serial.print("Suhu lingkungan: ");
    Serial.print(tAmb, 1);
    Serial.println(" C");
  } else {
    Serial.println("Pembacaan DHT22 tidak valid.");
  }
}

void updateModel(float dt) {
  // Membaca beban CPU dari potensiometer
  int adcLoad = analogRead(PIN_LOAD);

  beban = constrain(adcLoad, 0, 4095) / 4095.0;

  // Membaca kondisi casing
  int switchState = digitalRead(PIN_CASE);

  casing = (switchState == HIGH)
           ? CASE_INSTALLED
           : CASE_NONE;

  // Pengaruh suhu lingkungan terhadap pemanasan
  float ambientExcess =
      fmaxf(0.0, tAmb - T_AMB_REF);

  float ambientHeatFactor =
      1.0 + AMB_HEAT_GAIN * ambientExcess;

  ambientHeatFactor =
      constrain(ambientHeatFactor, 1.0, 1.5);

  // Faktor pelepasan panas lingkungan
  float ambientCoolFactor =
      1.0 - AMB_COOL_LOSS * ambientExcess;

  ambientCoolFactor =
      constrain(ambientCoolFactor, 0.70, 1.0);

  // Casing terpasang: pelepasan panas lebih kecil
  // Casing dilepas: pelepasan panas lebih besar
  float caseFactor =
      (casing == CASE_INSTALLED) ? 0.55 : 1.50;

  float g =
      G_PASIF * caseFactor * ambientCoolFactor;

  // Penurunan daya pemanasan CPU ketika suhu tinggi.
  // Mulai pada 37 C agar kenaikan suhu melambat.
  float thermalPowerFactor = 1.0;

  if (suhu > 37.0) {
    thermalPowerFactor =
        1.0 - 0.075 * (suhu - 37.0);
  }

  thermalPowerFactor =
      constrain(thermalPowerFactor, 0.55, 1.0);

  // Clock CPU mengikuti level termal
  float clockFactor = CLOCK_PCT[level] / 100.0;

  // Panas yang dihasilkan CPU dan sistem
  float panas =
      (P_BASE +
       beban * clockFactor * P_CPU *
       thermalPowerFactor) *
      ambientHeatFactor;

  // Panas yang dilepaskan ke lingkungan
  float panasKeluar = g * (suhu - tAmb);

  // Daya panas bersih
  float netPower = panas - panasKeluar;

  // Charging membuat pemanasan bersih 2 kali lebih cepat.
  // Faktor ini diterapkan ketika netPower positif.
  if (charging && netPower > 0.0) {
    netPower *= 2.0;
  }

  // Menghitung perubahan suhu
  suhu += (netPower / C_TERMAL) * dt;

  // Pengaman jika perhitungan menghasilkan nilai tidak valid
  if (!isfinite(suhu)) {
    suhu = tAmb;
    level = 0;
  }

  // Level naik sesuai ambang suhu
  while (level < 3 && suhu >= T_UP[level]) {
    level++;
  }

  // Level turun menggunakan histeresis
  while (level > 0 &&
         suhu < T_UP[level - 1] - HYS) {
    level--;
  }

  // Menampilkan data di Serial Monitor
  Serial.print("Ambien: ");
  Serial.print(tAmb, 1);

  Serial.print(" C | SoC: ");
  Serial.print(suhu, 1);

  Serial.print(" C | Beban: ");
  Serial.print(beban * 100.0, 0);

  Serial.print("% | Casing: ");
  Serial.print(casing == CASE_INSTALLED ? "ADA" : "TIDAK");

  Serial.print(" | Charging: ");
  Serial.print(charging ? "ON" : "OFF");

  Serial.print(" | Status: ");
  Serial.println(NAMA_LCD[level]);
}

void updateOutput() {
  // Kecerahan layar mengikuti level termal
  int pwm = BRIGHT_PCT[level] * 255 / 100;

  writePWM(pwm);

  // LED hijau: IDLE
  digitalWrite(PIN_LED_G, level <= 1);

  // LED kuning: RINGAN
  digitalWrite(PIN_LED_Y, level == 2);

  // LED merah: BERAT atau OVERHEAT
  digitalWrite(PIN_LED_R, level == 3);

  // Buzzer berkedip saat overheat
  unsigned long now = millis();

  if (level == 3 && (now / 300) % 2 == 0) {
    tone(PIN_BUZZER, 2000);
  } else {
    noTone(PIN_BUZZER);
  }
}

void updateLcd() {
  // Baris pertama: suhu dan status
  char line1[17];

  snprintf(
    line1,
    sizeof(line1),
    "T%5.1fC %-8s",
    suhu,
    NAMA_LCD[level]
  );

  lcd.setCursor(0, 0);
  lcd.print("                ");
  lcd.setCursor(0, 0);
  lcd.print(line1);

  // Baris kedua: beban CPU, clock, dan charging
  char line2[17];

  snprintf(
    line2,
    sizeof(line2),
    "Ld%3d Clk%3d %s",
    (int)(beban * 100.0),
    CLOCK_PCT[level],
    charging ? "CHG" : "---"
  );

  lcd.setCursor(0, 1);
  lcd.print("                ");
  lcd.setCursor(0, 1);
  lcd.print(line2);
}

void kirimTelemetri() {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  if (!mqtt.connected()) {
    reconnectMQTT();
    return;
  }

  char payload[256];

  snprintf(
    payload,
    sizeof(payload),
    "{"
      "\"soc_temperature\":%.2f,"
      "\"ambient_temp\":%.2f,"
      "\"cpu_load_pct\":%.1f,"
      "\"casing_installed_pct\":%.0f,"
      "\"clock_pct\":%d,"
      "\"brightness_pct\":%d,"
      "\"is_charging\":%s,"
      "\"thermal_level\":%d,"
      "\"status\":\"%s\""
    "}",
    suhu,
    tAmb,
    beban * 100.0,
    casing == CASE_INSTALLED ? 100.0 : 0.0,
    CLOCK_PCT[level],
    BRIGHT_PCT[level],
    charging ? "true" : "false",
    level,
    NAMA_LCD[level]
  );

  bool success = mqtt.publish(MQTT_TOPIC, payload);

  Serial.print("MQTT: ");
  Serial.println(success ? "terkirim" : "gagal");

  Serial.println(payload);
}

void setup() {
  Serial.begin(115200);

  // Konfigurasi pin sensor dan input
  pinMode(PIN_LOAD, INPUT);
  pinMode(PIN_CASE, INPUT);
  pinMode(PIN_BTN, INPUT_PULLUP);

  // Konfigurasi LED
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_Y, OUTPUT);
  pinMode(PIN_LED_R, OUTPUT);

  digitalWrite(PIN_LED_G, LOW);
  digitalWrite(PIN_LED_Y, LOW);
  digitalWrite(PIN_LED_R, LOW);

  // Konfigurasi buzzer
  pinMode(PIN_BUZZER, OUTPUT);
  noTone(PIN_BUZZER);

  // Inisialisasi PWM layar
  initPWM();
  writePWM(255);

  // Inisialisasi I2C dan LCD
  Wire.begin(21, 22);

  lcd.init();
  lcd.backlight();

  lcd.setCursor(0, 0);
  lcd.print("Smartphone");
  lcd.setCursor(0, 1);
  lcd.print("Thermal Model");

  // Inisialisasi DHT22
  dht.begin();

  delay(1500);

  // Membaca suhu awal lingkungan
  float initialTemp = dht.readTemperature();

  if (!isnan(initialTemp) &&
      initialTemp >= -20.0 &&
      initialTemp <= 80.0) {
    tAmb = initialTemp;
  }

  // Suhu awal SoC mengikuti suhu lingkungan
  suhu = tAmb;

  // Menentukan level awal sesuai suhu
  if (suhu >= 44.0) {
    level = 3;
  } else if (suhu >= 37.0) {
    level = 2;
  } else if (suhu >= 30.0) {
    level = 1;
  } else {
    level = 0;
  }

  // Konfigurasi MQTT
  mqtt.setServer(MQTT_SERVER, MQTT_PORT);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(30);

  // Koneksi WiFi
  connectWiFi();

  // Tampilkan status awal
  updateOutput();
  updateLcd();

  Serial.println();
  Serial.println("================================");
  Serial.println("SMARTPHONE THERMAL THROTTLING");
  Serial.println("================================");
  Serial.println("Idle     : < 30 C");
  Serial.println("Ringan   : 30 - < 37 C");
  Serial.println("Berat    : 37 - < 44 C");
  Serial.println("Overheat : >= 44 C");
  Serial.println("================================");
}

void loop() {
  unsigned long now = millis();

  // Membaca tombol charging
  bacaTombol();

  // Memperbarui sensor lingkungan
  bacaDHT();

  // Memperbarui model termal setiap 100 ms
  if (now - lastModel >= MODEL_INTERVAL) {
    float dt = (now - lastModel) / 1000.0;
    lastModel = now;

    // Membatasi dt agar perubahan waktu tidak terlalu besar
    dt = constrain(dt, 0.0, 0.5);

    updateModel(dt);
    updateOutput();
  }

  // Memperbarui LCD
  if (now - lastLCD >= LCD_INTERVAL) {
    lastLCD = now;
    updateLcd();
  }

  // Memperbarui koneksi MQTT
  if (WiFi.status() == WL_CONNECTED) {
    if (!mqtt.connected()) {
      reconnectMQTT();
    } else {
      mqtt.loop();
    }
  } else {
    // Mencoba koneksi ulang secara berkala
    static unsigned long lastWiFiAttempt = 0;

    if (now - lastWiFiAttempt >= 10000) {
      lastWiFiAttempt = now;
      connectWiFi();
    }
  }

  // Mengirim telemetri setiap 2 detik
  if (now - lastMQTT >= MQTT_INTERVAL) {
    lastMQTT = now;
    kirimTelemetri();
  }

  delay(5);
}
