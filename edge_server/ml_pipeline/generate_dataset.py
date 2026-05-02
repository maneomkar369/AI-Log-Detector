import csv
import random

# Simulating CICAndMal + AI Log Detector features
headers = [
    "Flow_Duration", "Tot_Fwd_Pkts", "Tot_Bwd_Pkts", 
    "Bwd_Pkt_Len_Max", "Flow_IAT_Mean", 
    "App_Transitions_5s", "Keystroke_Flight_Mean", "Touch_Pressure_Variance",
    "Sensitive_Permission_Access", "TFLite_Phishing_Score",
    "Label"
]

def generate_benign():
    return [
        random.randint(1000, 50000),      # Flow Duration
        random.randint(1, 10),            # Tot_Fwd_Pkts
        random.randint(1, 10),            # Tot_Bwd_Pkts
        random.randint(50, 1500),         # Bwd_Pkt_Len_Max
        random.uniform(5.0, 50.0),        # Flow_IAT_Mean
        random.randint(0, 2),             # App_Transitions_5s (Low)
        random.uniform(80.0, 150.0),      # Keystroke Flight Time (Normal)
        random.uniform(0.01, 0.05),       # Touch variance (Smooth)
        0,                                # Permissions
        random.uniform(0.0, 0.2),         # Phishing Score
        "Benign"
    ]

def generate_malware():
    return [
        random.randint(100000, 5000000),  # Flow Duration (Anomalous)
        random.randint(20, 200),          # Tot_Fwd_Pkts
        random.randint(20, 200),          # Tot_Bwd_Pkts
        random.randint(2000, 8000),       # Bwd_Pkt_Len_Max
        random.uniform(0.1, 2.0),         # Flow_IAT_Mean (Automated burst)
        random.randint(5, 20),            # App_Transitions_5s (High, script)
        random.uniform(10.0, 40.0),       # Keystroke (Too fast, robotic)
        random.uniform(0.2, 0.8),         # Touch variance (Spiky/random)
        random.choice([0, 1]),            # Permissions
        random.uniform(0.6, 1.0),         # Phishing Score (High)
        "Malware"
    ]

with open("sample_cicandmal_data.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(headers)
    for _ in range(8000):
        writer.writerow(generate_benign())
    for _ in range(2000):
        writer.writerow(generate_malware())

print("Generated sample_cicandmal_data.csv with 10,000 rows.")
