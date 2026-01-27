# HS2 Electrical Ground Support Equipment (EGSE)

The EGSE repository contains scripts for validating the functionality of HS-2's electrical system. To use the repository, first clone it and install the required dependencies:

```
pip install -r requirements.txt
```

# Simulated Loading

To simulate a load on the battery pack, first connect your laptop/PC to the KEL103 E-load via USB, and connect the E-load leads to the BMS (or alternatively, to the battery pack itself). To start a discharge cycle, run (on a Windows machine):

```
python simulated_discharging/discharge_cycle.py COM4 simulated_discharging/examples/schedule.csv --log battery_test.csv
```

(On a non-Windows machine, `COM4` should be replaced with the serial port for that machine. On Linux, this may be `/dev/ttyACM0` or `/dev/ttyUSB0`)

# Simulated Charging

Coming soon...

# Verifying Inhibits

Coming soon...

# Verifying CDH Functionality

Coming soon...