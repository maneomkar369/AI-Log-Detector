def explain_feature_contributions(feature_contributions: dict) -> list[str]:
    """
    Translates raw Mahalanobis feature contribution indices into human-readable explanations.
    
    Feature Vector Layout (72 dims total):
    - [0:24] Temporal: Hour-of-day usage distribution.
    - [24:34] Sequential: Top-K app frequency distribution.
    - [34:44] Sequential: App transition entropy.
    - [44:52] Sequential: Top transition probabilities.
    - [52:57] Interaction: Keystroke timing stats.
    - [57:62] Interaction: Touch duration stats.
    - [62:67] Interaction: Swipe velocity stats.
    - [67:72] Interaction: Combined/Network/Security stats.
    """
    if not feature_contributions:
        return []

    explanations = []
    
    # Sort contributions by value descending
    sorted_features = sorted(feature_contributions.items(), key=lambda x: x[1], reverse=True)
    
    for idx, weight in sorted_features:
        pct = weight * 100
        if pct < 5.0:
            continue
            
        idx = int(idx)
        if 0 <= idx < 24:
            explanations.append(f"Highly unusual device activity around {idx}:00 (contributed {pct:.1f}% to anomaly score).")
        elif 24 <= idx < 34:
            explanations.append(f"Abnormal frequency of specific app usage (contributed {pct:.1f}%).")
        elif 34 <= idx < 44:
            explanations.append(f"Unusual app switching behavior / transition entropy (contributed {pct:.1f}%).")
        elif 44 <= idx < 52:
            explanations.append(f"Unexpected opening sequence between apps (contributed {pct:.1f}%).")
        elif 52 <= idx < 57:
            explanations.append(f"Anomalous keystroke dynamics detected (contributed {pct:.1f}%).")
        elif 57 <= idx < 62:
            explanations.append(f"Atypical touch durations (possible automation or fatigue) (contributed {pct:.1f}%).")
        elif 62 <= idx < 67:
            explanations.append(f"Irregular swipe velocities (contributed {pct:.1f}%).")
        elif 67 <= idx < 72:
            explanations.append(f"Deviant network, security, or global interaction properties (contributed {pct:.1f}%).")
            
    return explanations
