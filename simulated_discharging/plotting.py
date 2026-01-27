import matplotlib.pyplot as plt
import csv

log_file = 'test_data/battery_test.csv'

elapsed_time = []
voltage = []

with open(log_file, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        elapsed_time.append(float(row['elapsed_seconds']))
        voltage.append(float(row['voltage_volts']))

plt.figure(figsize=(10, 6))
plt.plot(elapsed_time[22:180], voltage[22:180], 'b-', linewidth=1.5)
plt.xlabel('Elapsed Time (seconds)', fontsize=12)
plt.ylabel('Voltage (V)', fontsize=12)
plt.title('Battery Voltage vs Time', fontsize=14, fontweight='bold')
plt.grid(True, alpha=0.3)
plt.tight_layout()

plt.show()
