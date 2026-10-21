#include <Wire.h>
#include <Adafruit_INA219.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// Pins Setup
const int gatePin = 2;       // MOSFET Gate pin
const int oneWireBus = 4;    // DS18B20 Temp probe pin

Adafruit_INA219 ina219;
OneWire oneWire(oneWireBus);
DallasTemperature tempSensor(&oneWire);

void setup() {
  Serial.begin(115200);

  // Safety: Startup par MOSFET load ko strictly OFF rakhein
  pinMode(gatePin, OUTPUT);
  digitalWrite(gatePin, LOW);

  // I2C Pins initialize (SDA = 21, SCL = 22)
  Wire.begin(21, 22);

  if (!ina219.begin()) {
    Serial.println("ERR: INA219 not detected! Check SDA/SCL wires.");
  }

  tempSensor.begin();
  delay(1000);
  Serial.println("SYSTEM_READY: Safe to verify baseline.");
}

void loop() {
  tempSensor.requestTemperatures();
  float temp_C = tempSensor.getTempCByIndex(0);
  float voltage = ina219.getBusVoltage_V();
  float current_mA = ina219.getCurrent_mA();

  // Safety cutoff interlock: voltage girne ya overheating par load turant band
  if ((voltage < 2.50 && voltage > 0.50) || temp_C > 45.0) {
    digitalWrite(gatePin, LOW);
  }

  // Serial Monitor telemetry stream
  Serial.print("Voltage(V): ");
  Serial.print(voltage, 2);
  Serial.print(" | Current(mA): ");
  Serial.print(current_mA, 1);
  Serial.print(" | Temp(C): ");
  Serial.println(temp_C, 1);

  delay(1000);
}