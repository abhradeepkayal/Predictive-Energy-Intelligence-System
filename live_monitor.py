import serial
import pandas as pd
import numpy as np
import re
import joblib
from collections import deque



model = joblib.load("xgboost_power_predictor.pkl")


PORT = 'COM5' #amader COM port

BAUD_RATE = 115200

ser = serial.Serial(PORT, BAUD_RATE)

print("Connected to ESP32...")
print("Waiting for live data...\n")


power_window = deque(maxlen=5)
pf_window = deque(maxlen=5)
current_window = deque(maxlen=5)

prev_pf = None
prev_current = None
prev_power = None



def classify_health(score):

    if score >= 85:
        return "Healthy"

    elif score >= 70:
        return "Mild Risk"

    elif score >= 50:
        return "Moderate Risk"

    else:
        return "Severe Risk"


def diagnose_fault(row):

    messages = []

    if row["RollingStd_Power"] > 3:
        messages.append("High power fluctuation detected")

    elif row["RollingStd_Power"] > 1.5:
        messages.append("Moderate load instability observed")

    if abs(row["PF_Drift"]) > 0.02:
        messages.append("Possible power factor degradation")

    if abs(row["Current_Drift"]) > 0.0008:
        messages.append("Current instability increasing")

    if row["PredictionError"] > 2:
        messages.append("Unexpected appliance behavior predicted")

    if row["HealthScore"] < 50:
        messages.append("Maintenance recommended")

    if len(messages) == 0:
        return "Normal stable operation"

    return " | ".join(messages)



while True:

    try:

        line = ser.readline().decode('utf-8').strip()

        print("\nRaw:", line)

        pattern = r"Vrms:\s*([\d\.]+)V\s*\|\s*Irms:\s*([\d\.]+)A\s*\|\s*Watt:\s*([\d\.]+)W\s*\|\s*PF:\s*([\d\.\-]+)"

        match = re.search(pattern, line)

        if not match:
            print("Invalid data format")
            continue

        Vrms = float(match.group(1))
        Irms = float(match.group(2))
        RealPower = float(match.group(3))
        PF = float(match.group(4))


        ApparentPower = Vrms * Irms

        if RealPower != 0:
            SP_Ratio = ApparentPower / RealPower
            CurrentPerWatt = Irms / RealPower
        else:
            SP_Ratio = 0
            CurrentPerWatt = 0

        power_window.append(RealPower)
        pf_window.append(PF)
        current_window.append(Irms)

        RollingMean_Power = np.mean(power_window)
        RollingMean_PF = np.mean(pf_window)
        RollingMean_Current = np.mean(current_window)

        RollingStd_Power = np.std(power_window)
        RollingStd_PF = np.std(pf_window)
        RollingStd_Current = np.std(current_window)

        if prev_pf is None:
            PF_Drift = 0
            Current_Drift = 0
            Power_Drift = 0
        else:
            PF_Drift = PF - prev_pf
            Current_Drift = Irms - prev_current
            Power_Drift = RealPower - prev_power

        prev_pf = PF
        prev_current = Irms
        prev_power = RealPower

        input_df = pd.DataFrame([{
            "LoadType": 0,
            "Condition": 0,
            "Vrms": Vrms,
            "Irms": Irms,
            "RealPower": RealPower,
            "PF": PF,
            "ApparentPower": ApparentPower,
            "SP_Ratio": SP_Ratio,
            "CurrentPerWatt": CurrentPerWatt,
            "PF_Drift": PF_Drift,
            "Current_Drift": Current_Drift,
            "Power_Drift": Power_Drift,
            "RollingMean_Power": RollingMean_Power,
            "RollingMean_PF": RollingMean_PF,
            "RollingMean_Current": RollingMean_Current,
            "RollingStd_Power": RollingStd_Power,
            "RollingStd_PF": RollingStd_PF,
            "RollingStd_Current": RollingStd_Current
        }])

        predicted_power = model.predict(input_df)[0]

        PredictionError = abs(
            RealPower - predicted_power
        )


        instability_score = (
            0.4 * min(PredictionError / 10, 1) +
            0.3 * min(RollingStd_Power / 5, 1) +
            0.15 * min(abs(PF_Drift) / 0.05, 1) +
            0.15 * min(abs(Current_Drift) / 0.005, 1)
        )

        HealthScore = max(
            0,
            100 - instability_score * 100
        )

        HealthStatus = classify_health(
            HealthScore
        )

        row = {
            "RollingStd_Power": RollingStd_Power,
            "PF_Drift": PF_Drift,
            "Current_Drift": Current_Drift,
            "PredictionError": PredictionError,
            "HealthScore": HealthScore
        }
        Diagnosis = diagnose_fault(row)

        print("----------------------------------------")
        print(f"Vrms: {Vrms:.2f} V")
        print(f"Irms: {Irms:.4f} A")
        print(f"Real Power: {RealPower:.2f} W")
        print(f"PF: {PF:.3f}")
        print(f"Predicted Next Power: {predicted_power:.2f} W")
        print(f"Prediction Error: {PredictionError:.2f} W")
        print(f"Health Score: {HealthScore:.2f}")
        print(f"Health Status: {HealthStatus}")
        print(f"Diagnosis: {Diagnosis}")
        print("----------------------------------------")

    except Exception as e:
        print("Error:", e)