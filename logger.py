import serial
import csv
import time
from datetime import datetime

PORT = "COM4"
BAUD_RATE = 115200
OUTPUT_FILE = "esp32_battery_log.csv"

def main():
    print("Connecting to ESP32...")
    ser = serial.Serial(PORT, BAUD_RATE, timeout=2)

    time.sleep(2)

    print("Logging data...")
    print("Press Ctrl+C to stop.\n")

    with open(OUTPUT_FILE, "w", newline="") as file:
        writer = csv.writer(file)

        writer.writerow([
            "Timestamp",
            "Voltage_V",
            "Current_mA",
            "Power_mW"
        ])

        try:
            while True:
                line = ser.readline().decode(
                    "utf-8",
                    errors="ignore"
                ).strip()

                if not line:
                    continue

                # Expected ESP32 format:
                # voltage,current
                try:
                    voltage, current = map(float, line.split(","))

                    power = voltage * current

                    timestamp = datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )

                    writer.writerow([
                        timestamp,
                        voltage,
                        current,
                        power
                    ])

                    file.flush()

                    print(
                        f"{timestamp} | "
                        f"V = {voltage:.3f} V | "
                        f"I = {current:.2f} mA | "
                        f"P = {power:.2f} mW"
                    )

                except ValueError:
                    print("Invalid ESP32 data:", line)

        except KeyboardInterrupt:
            print("\nLogging stopped.")

        finally:
            ser.close()

if __name__ == "__main__":
    main()