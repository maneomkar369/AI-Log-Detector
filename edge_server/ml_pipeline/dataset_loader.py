import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler

class DatasetLoader:
    def __init__(self, file_path="sample_cicandmal_data.csv"):
        self.file_path = file_path
        self.scaler = StandardScaler()

    def load_and_preprocess(self):
        """Loads CSV data, encodes labels, and scales features."""
        try:
            df = pd.read_csv(self.file_path)
            print(f"[Loader] Successfully loaded {len(df)} records from {self.file_path}")
        except FileNotFoundError:
            raise Exception(f"Dataset {self.file_path} not found. Please place the CSV in this directory.")

        if "Label" not in df.columns:
            raise KeyError("The dataset must contain a 'Label' column.")

        # Convert labels: Benign -> 0, Malware/Anomaly -> 1
        y = np.where(df["Label"].str.lower() == "benign", 0, 1)

        # Drop the label column for features
        X = df.drop(columns=["Label"])

        # Map to 72-dimension space (Simulated by expanding features or using actual 72 cols)
        # For this prototype, we process the exact columns provided in the dataset
        features = X.columns.tolist()

        # Split into train/test (80/20)
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

        # Scale features
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        return X_train_scaled, X_test_scaled, y_train, y_test, features
