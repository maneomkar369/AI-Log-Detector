import os
import json
import joblib
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix, classification_report

from dataset_loader import DatasetLoader

def main():
    print("="*60)
    print(" AI Log Detector - Real Dataset ML Training Pipeline ")
    print("="*60)
    
    loader = DatasetLoader()
    X_train, X_test, y_train, y_test, features = loader.load_and_preprocess()

    print(f"\n[Training] Training RandomForestClassifier on {len(X_train)} samples...")
    model = RandomForestClassifier(n_estimators=100, random_state=42, class_weight='balanced')
    model.fit(X_train, y_train)

    print("[Evaluation] Executing predictions on test set...")
    y_pred = model.predict(X_test)

    # Metrics
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred)
    rec = recall_score(y_test, y_pred)
    f1 = f1_score(y_test, y_pred)
    cm = confusion_matrix(y_test, y_pred)

    print("\n" + "="*30)
    print(" 📊 EVALUATION METRICS")
    print("="*30)
    print(f"Accuracy:  {acc:.4f} ({acc*100:.2f}%)")
    print(f"Precision: {prec:.4f} ({prec*100:.2f}%)")
    print(f"Recall:    {rec:.4f} ({rec*100:.2f}%)")
    print(f"F1 Score:  {f1:.4f} ({f1*100:.2f}%)")

    print("\n 🧩 CONFUSION MATRIX")
    print("                 Predicted Benign | Predicted Anomaly")
    print(f"Actual Benign:   [ {cm[0][0]:>5} ]        [ {cm[0][1]:>5} ]")
    print(f"Actual Anomaly:  [ {cm[1][0]:>5} ]        [ {cm[1][1]:>5} ]")

    print("\n📝 CLASSIFICATION REPORT")
    print(classification_report(y_test, y_pred, target_names=["Benign", "Malware"]))

    # Save findings
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    
    report_dict = {
        "metrics": {
            "accuracy": acc,
            "precision": prec,
            "recall": rec,
            "f1_score": f1
        },
        "confusion_matrix": cm.tolist()
    }
    
    with open(f"{output_dir}/evaluation_results.json", "w") as f:
        json.dump(report_dict, f, indent=4)
        
    model_path = f"{output_dir}/random_forest_model.pkl"
    joblib.dump(model, model_path)
    print(f"\n[Export] Model saved to {model_path}")
    print(f"[Export] Results saved to {output_dir}/evaluation_results.json")
    print("\n>> To train on actual Kaggle Data, replace 'sample_cicandmal_data.csv' with your dataset and run again.")

if __name__ == "__main__":
    main()
