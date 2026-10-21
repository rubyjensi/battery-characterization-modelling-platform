import csv
import os
import re
import time

import matplotlib.pyplot as plt
import numpy as np
import serial

# ---------------- SETTINGS (edit these) ----------------
PORT = 'COM5'
BAUD = 115200
RATED_CAPACITY_MAH = 3600.0   # <-- your cell's rated capacity
SERIES_CELLS = 1             # <-- 8.19 V suggests 2 cells in series; use 1 if single cell
START_FROM_FULL = False      # True: start at 100 %. False: estimate from first voltage reading
LOG_FILE = 'battery_log_soc.csv'          # normal CSV (for Python/Excel)
COMSOL_FILE = 'battery_log_comsol.txt'    # COMSOL-ready file
# --------------------------------------------------------

# Approximate Li-ion (NMC) open-circuit voltage vs SoC, per cell
OCV_V   = [3.00, 3.30, 3.45, 3.60, 3.70, 3.80, 3.90, 4.00, 4.10, 4.20]
OCV_SOC = [0,    5,    10,   20,   35,   50,   65,   78,   90,   100]

PATTERN = re.compile(
    r'Voltage\(V\):\s*(\S+)\s*\|\s*Current\(mA\):\s*(\S+)\s*\|\s*Temp\(C\):\s*(\S+)',
    re.IGNORECASE)

def to_float(s):
    try:
        return float(s)
    except ValueError:
        return float('nan')

def is_ok(x):
    return x == x

try:
    ser = serial.Serial(PORT, BAUD, timeout=0.05)
    time.sleep(2)
    ser.reset_input_buffer()
    print(f"Connected to {PORT}. Waiting for data...")
except Exception as e:
    print(f"Error opening port: {e}")
    raise SystemExit

t_data, v_data, temp_data, soc_data = [], [], [], []
used_mah = 0.0       # charge removed so far
soc0 = 100.0 if START_FROM_FULL else None
last_t = None
last_good_i = 0.0
start = time.time()

plt.ion()
fig, (ax1, ax3) = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
ax2 = ax1.twinx()
line_v, = ax1.plot([], [], 'b-', linewidth=2, label='Voltage (V)')
line_t, = ax2.plot([], [], 'r--', linewidth=1.5, label='Temp (°C)')
line_s, = ax3.plot([], [], 'g-', linewidth=2, label='SoC (%)')
ax1.set_ylabel('Voltage (V)', color='b')
ax2.set_ylabel('Temperature (°C)', color='r')
ax3.set_ylabel('SoC (%)', color='g')
ax3.set_xlabel('Elapsed Time (s)')
ax3.set_ylim(99.5, 100.05)
ax1.grid(True, linestyle='--', alpha=0.5)
ax3.grid(True, linestyle='--', alpha=0.5)
ax1.legend([line_v, line_t], ['Voltage (V)', 'Temp (°C)'], loc='upper right')
plt.show(block=False)
plt.pause(0.1)

# Files
new_log = not os.path.exists(LOG_FILE)
f_log = open(LOG_FILE, 'a', newline='')
w_log = csv.writer(f_log)
if new_log:
    w_log.writerow(['Time_s', 'Voltage_V', 'Current_mA', 'Temp_C', 'Used_mAh', 'SoC_pct'])

new_comsol = not os.path.exists(COMSOL_FILE)
f_com = open(COMSOL_FILE, 'a', newline='')
if new_comsol:
    f_com.write('% Time_s, SoC_pct, Voltage_V, Temp_C\n')   # '%' lines are comments in COMSOL

buf = b''
last_draw = 0

try:
    while plt.fignum_exists(fig.number):
        n = ser.in_waiting
        if n:
            buf += ser.read(n)
        buf = buf.replace(b'\r', b'\n')

        while b'\n' in buf:
            raw, buf = buf.split(b'\n', 1)
            text = raw.decode('utf-8', errors='ignore').strip()
            if not text:
                continue

            m = PATTERN.search(text)
            if not m:
                print("SKIPPED:", text)
                continue

            v = to_float(m.group(1))
            i_ma = to_float(m.group(2))
            temp = to_float(m.group(3))
            t_sec = time.time() - start

            if not is_ok(v):
                continue

            # Initial SoC from voltage (only once, if not starting from full)
            if soc0 is None:
                soc0 = float(np.interp(v / SERIES_CELLS, OCV_V, OCV_SOC))
                print(f"Estimated starting SoC: {soc0:.1f} %")

                       # Use the sensor reading; if it drops out (nan), hold the last good value
            held = False
            if is_ok(i_ma):
                last_good_i = i_ma
            else:
                i_ma = last_good_i
                held = True

            # Coulomb counting
            if last_t is not None:
                used_mah += abs(i_ma) * (t_sec - last_t) / 3600.0
            last_t = t_sec

            soc = max(0.0, min(100.0, soc0 - 100.0 * used_mah / RATED_CAPACITY_MAH))

            t_data.append(t_sec)
            v_data.append(v)
            temp_data.append(temp)
            soc_data.append(soc)

            w_log.writerow([round(t_sec, 2), v, i_ma, temp, round(used_mah, 4), round(soc, 3)])
            if is_ok(temp):
                f_com.write(f"{t_sec:.2f}, {soc:.3f}, {v:.3f}, {temp:.2f}\n")

            print(f"[{t_sec:.0f}s] V: {v:.2f} | I: {i_ma*(-1)} mA | T: {temp} °C | SoC: {soc:.1f} %")

        now = time.time()
        if now - last_draw > 0.2 and t_data:
            line_v.set_data(t_data, v_data)
            line_t.set_data(t_data, temp_data)
            line_s.set_data(t_data, soc_data)
            ax1.set_xlim(0, max(10, t_data[-1] + 5))
            ax1.set_ylim(min(v_data) - 0.2, max(v_data) + 0.2)
            valid_t = [x for x in temp_data if is_ok(x)]
            if valid_t:
                ax2.set_ylim(min(valid_t) - 2, max(valid_t) + 2)
            ax1.set_title(f'Live Discharge | SoC: {soc_data[-1]:.3f} %')
            f_log.flush()
            f_com.flush()
            fig.canvas.draw_idle()
            last_draw = now

        plt.pause(0.01)

except KeyboardInterrupt:
    pass
finally:
    print(f"\nStopped. Final SoC: {soc_data[-1] if soc_data else 'n/a'}")
    f_log.close()
    f_com.close()
    ser.close()
    plt.ioff()
    plt.show()