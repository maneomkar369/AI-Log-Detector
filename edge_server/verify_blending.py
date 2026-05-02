from datetime import datetime, timedelta, timezone
import numpy as np

def test_blending():
    now = datetime.now(timezone.utc)
    
    warmup_seconds = 24.0 * 3600.0
    blending_seconds = 7.0 * 24.0 * 3600.0
    
    # Generic baseline is typically an identity matrix and zeros
    generic_mean = np.zeros(72)
    personalized_mean = np.ones(72) * 10.0 # Just a distinct dummy value
    
    print(f"Generic Mean value: {generic_mean[0]}")
    print(f"Personalized Mean value: {personalized_mean[0]}\n")
    
    test_cases = [
        ("At Registration (Age = 0)", now),
        ("During Warm-up (Age = 12 hrs)", now - timedelta(hours=12)),
        ("End of Warm-up (Age = 24 hrs)", now - timedelta(hours=24)),
        ("Mid Blending (Age = 4.5 days)", now - timedelta(days=4.5)),
        ("End of Blending (Age = 8 days)", now - timedelta(days=8)),
        ("Mature (Age = 30 days)", now - timedelta(days=30))
    ]
    
    for name, first_seen in test_cases:
        age_seconds = max(0.0, (now - first_seen).total_seconds())
        
        if age_seconds <= warmup_seconds:
            alpha = 1.0
        elif age_seconds < (warmup_seconds + blending_seconds):
            progress = (age_seconds - warmup_seconds) / blending_seconds
            alpha = 1.0 - progress
        else:
            alpha = 0.0
            
        effective_mean = (alpha * generic_mean) + ((1.0 - alpha) * personalized_mean)
        
        print(f"[{name}]")
        print(f"  Alpha (Mixing Factor): {alpha:.4f}")
        print(f"  Effective Mean value:  {effective_mean[0]:.4f}\n")

if __name__ == "__main__":
    test_blending()
