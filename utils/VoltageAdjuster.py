from pathlib import Path
import numpy as np
import pandas as pd
import sys


class VoltageSmoother:
    def __init__(self, file_path, amp_threshold, window_size):
        self.file_path = Path(file_path)
        self.amp_threshold = abs(float(amp_threshold))
        # Make sure that the data starts after at least 1 window size has passed
        # Maybe make sure that there is a method to fill in 0s if the data starts before 1 window length has passed 
        self.window_size = int(window_size) 

        self.data = None
        self.voltages = None
        self.currents = None

    @staticmethod
    def sign_of(x):
        if x > 0:
            return 1
        elif x < 0:
            return -1
        else:
            return 0

    def find_changes(self, x):
        changes = [[], []]

        for i in range(len(x) - 1): # For some reason the array isn't being populated, determine why
            if abs(x[i] - x[i + 1]) >= self.amp_threshold:
                changes[0].append(i)
                changes[1].append(x[i + 1] - x[i])

        for i in range(len(changes[0]) - 1, 0, -1):
            if (
                changes[0][i] == changes[0][i - 1] + 1
                and self.sign_of(changes[1][i]) == self.sign_of(changes[1][i - 1])
            ):
                changes[0].pop(i)
                changes[1].pop(i)

        return changes[0]

    def load_data(self):
        self.data = pd.read_csv(self.file_path).to_numpy()
        self.voltages = self.data[:, 1]
        self.currents = self.data[:, 2]

    def compute_internal_resistance(self):
        changes = self.find_changes(self.currents)
        resistances = []

        for x in changes: #This loop doesn't run for some reason: determine why
            if self.window_size < x <= (len(self.currents) - self.window_size - 1):
                dI = (
                    np.median(self.currents[x + 1 : x + 1 + self.window_size])
                    - np.median(self.currents[x - self.window_size : x])
                )
                dV = (
                    np.median(self.voltages[x + 1 : x + 1 + self.window_size])
                    - np.median(self.voltages[x - self.window_size : x])
                )
                if dI != 0:
                    resistances.append(-dV / dI)

        return np.mean(resistances)

    def correct_voltages(self):
        internal_resistance = self.compute_internal_resistance()
        corrected_voltages = self.currents * internal_resistance + self.voltages
        self.data[:, 1] = corrected_voltages

    def save(self):
        df_out = pd.DataFrame(
            self.data,
            columns=[
                "elapsed_seconds",
                "voltage_volts",
                "current_amps",
                "power_watts",
            ],
        )

        n = 0
        while True:
            if n == 0:
                out_path = self.file_path.with_name(
                    self.file_path.stem + "_adjusted.csv"
                )
            else:
                out_path = self.file_path.with_name(
                    f"{self.file_path.stem}_adjusted({n}).csv"
                )

            if out_path.exists():
                n += 1
            else:
                df_out.to_csv(out_path, index=False)
                return out_path

    def run(self):
        self.load_data()
        self.correct_voltages()
        return self.save()
    
if __name__ == "__main__":
    
    if len(sys.argv) != 4:
        print("Usage: python voltage_smoother.py <csv_file> <amp_threshold> <window_size>")
        sys.exit(1)

    _, csv_file, amp_threshold, window_size = sys.argv

    smoother = VoltageSmoother(
        file_path=csv_file,
        amp_threshold=amp_threshold,
        window_size=window_size,
    )

    output = smoother.run()
    print(f"Voltage corrected file written to: {output}")

        