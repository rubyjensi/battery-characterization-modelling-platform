import sys

import matplotlib.pyplot as plt
import pandas as pd

# usage: python plot_cycles.py battery_log_20261008_1530.csv
path = sys.argv[1] if len(sys.argv) > 1 else 'battery_log_20261008_2012.csv'
df = pd.read_csv(path)
t_h = df['Time_s'] / 3600.0

fig, ax = plt.subplots(figsize=(12, 4))
ax.plot(t_h, df['Voltage_V'], 'b-', linewidth=1.5)
ax.set_xlabel('time/h')
ax.set_ylabel('Ewe/V', color='b')
ax.set_ylim(2.9, 4.3)

ax2 = ax.twinx()
ax2.plot(t_h, df['Current_mA'], 'r-', linewidth=1.2)
ax2.set_ylabel('<I>/mA', color='r')

ax.set_title('U and I vs time in a charge discharge protocol')
ax.grid(alpha=0.3)
fig.tight_layout()
plt.show()