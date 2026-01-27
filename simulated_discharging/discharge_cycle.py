"""
Battery Discharge Scheduler with Voltage Logging

This script uses kelctl to discharge a battery according to a schedule
defined in a CSV file and logs voltage readings every second.

Schedule CSV format (schedule.csv):
time_seconds,current_amps
0,1.0
300,2.0
600,1.5
900,0.5

The script will:
1. Read the discharge schedule from a CSV file
2. Apply the scheduled current values at the specified times
3. Log voltage readings every 1 second to a CSV file
4. Handle graceful shutdown on Ctrl+C
"""

import csv
import time
import argparse
import sys
from kelctl import KELSerial

class BatteryDischargeScheduler:
    def __init__(self, port, schedule_file, log_file='voltage_log.csv', logging_interval=1.0):
        """
        Initialize the battery discharge scheduler.
        
        Args:
            port: Serial port for the electronic load (e.g., '/dev/ttyACM0' or 'COM3')
            schedule_file: Path to CSV file with discharge schedule
            log_file: Path to output CSV file for voltage logging
            logging_interval: Time interval (in seconds) between voltage logs
        """
        self.port = port
        self.schedule_file = schedule_file
        self.log_file = log_file
        self.schedule = []
        self.load = None
        self.running = False
        self.logging_interval = logging_interval
        
    def load_schedule(self):
        """Load the discharge schedule from CSV file."""
        print(f"Loading schedule from {self.schedule_file}...")
        try:
            with open(self.schedule_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    time_sec = float(row['time_seconds'])
                    current = float(row['current_amps'])
                    self.schedule.append({'time': time_sec, 'current': current})
            
            self.schedule.sort(key=lambda x: x['time'])
            
            print(f"Loaded {len(self.schedule)} schedule points:")
            for point in self.schedule:
                print(f"  t={point['time']}s → {point['current']}A")
                
        except FileNotFoundError:
            print(f"Error: Schedule file '{self.schedule_file}' not found!")
            sys.exit(1)
        except (KeyError, ValueError) as e:
            print(f"Error parsing schedule file: {e}")
            print("Expected CSV format: time_seconds,current_amps")
            sys.exit(1)
    
    def initialize_log_file(self):
        """Create the voltage log file with headers."""
        with open(self.log_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['elapsed_seconds', 'voltage_volts', 
                           'current_amps', 'power_watts'])
        print(f"Initialized log file: {self.log_file}")
    
    def get_scheduled_current(self, elapsed_time):
        """
        Get the scheduled current for the given elapsed time.
        Uses the most recent schedule point that has passed.
        """
        if not self.schedule:
            return 0.0
            
        current = self.schedule[0]['current']
        for point in self.schedule:
            if elapsed_time >= point['time']:
                current = point['current']
            else:
                break
        return current
    
    def run(self):
        print(f"\nConnecting to electronic load on {self.port}...")
        
        try:
            with KELSerial(self.port) as self.load:
                print(f"Connected to: {self.load.model}")
                print(f"Status: {self.load.status}")
                
                # Set to constant current mode
                print("\nSetting to constant current mode...")
                self.load.current = 0.0
                
                # Turn on the load
                print("Turning on load input...")
                self.load.input.on()
                
                # Initialize logging
                self.initialize_log_file()
                
                # Start the discharge process
                print("\nStarting discharge process...")
                print("Press Ctrl+C to stop\n")
                
                start_time = time.time()
                self.running = True
                next_log_time = start_time
                
                while self.running:
                    current_time = time.time()
                    elapsed = current_time - start_time
                    
                    # Update current based on schedule
                    scheduled_current = self.get_scheduled_current(elapsed)
                    self.load.current = scheduled_current
                    
                    # Log voltage every second
                    if current_time >= next_log_time:
                        next_log_time = current_time + self.logging_interval
                        voltage = self.load.measured_voltage
                        current = self.load.measured_current
                        power = self.load.measured_power
                        
                        # Write to log file
                        with open(self.log_file, 'a', newline='') as f:
                            writer = csv.writer(f)
                            writer.writerow([f'{elapsed:.3f}', 
                                           f'{voltage:.4f}', f'{current:.4f}', 
                                           f'{power:.4f}'])
                        
                        # Print status
                        print(f"[{elapsed:7.1f}s] V={voltage:6.3f}V  "
                              f"I={current:6.3f}A  P={power:7.3f}W  ")
                    
                    time.sleep(max(0, next_log_time - time.time()))
                    
        except KeyboardInterrupt:
            print("\n\nStopping discharge process...")
        except Exception as e:
            print(f"\nError: {e}")
            raise
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Clean up and turn off the load."""
        if self.load:
            try:
                print("Turning off load...")
                self.load.current = 0.0
                self.load.input.off()
                print("Load turned off safely.")
            except Exception as e:
                print(f"Error during cleanup: {e}")
        
        self.running = False
        print(f"\nVoltage data logged to: {self.log_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Battery discharge scheduler with voltage logging',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
            Examples:
            # Run with default settings
            python script.py /dev/ttyACM0 schedule.csv
            
            # Specify custom log file
            python script.py /dev/ttyACM0 schedule.csv --log battery_test.csv
            
            # Create an example schedule file
            python script.py --create-example
                    """
    )
    
    parser.add_argument('port', nargs='?', 
                       help='Serial port (e.g., /dev/ttyACM0 or COM3)')
    parser.add_argument('schedule', nargs='?',
                       help='Path to discharge schedule CSV file')
    parser.add_argument('--log', default='voltage_log.csv',
                       help='Output CSV file for voltage logging (default: voltage_log.csv)')
    
    args = parser.parse_args()
    
    if not args.port or not args.schedule:
        parser.print_help()
        print("\nError: Both port and schedule arguments are required (or use --create-example)")
        sys.exit(1)
    
    scheduler = BatteryDischargeScheduler(
        port=args.port,
        schedule_file=args.schedule,
        log_file=args.log,
    )
    
    scheduler.load_schedule()
    scheduler.run()


if __name__ == '__main__':
    main()