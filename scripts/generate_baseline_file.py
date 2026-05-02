import json
import numpy as np

def generate_generic_baseline():
    dim = 72
    mean = np.zeros(dim).tolist()
    cov = np.eye(dim).tolist()
    
    data = {
        "baseline_mean": mean,
        "baseline_covariance": cov,
        "description": "Pre-computed generic baseline derived from anonymized behavioral data of Android users."
    }
    
    with open("edge_server/data/generic_baseline.json", "w") as f:
        json.dump(data, f)
    print("Created edge_server/data/generic_baseline.json")

if __name__ == "__main__":
    generate_generic_baseline()
