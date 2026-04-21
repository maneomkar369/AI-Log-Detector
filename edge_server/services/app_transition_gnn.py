import numpy as np

class AppTransitionGNN:
    """
    Graph Neural Network (GNN) Scaffold for App Transition Anomaly Detection.
    
    Models app-to-app sequences as a dynamic graph. Uses a simplified
    Message Passing algorithm (implemented in NumPy) to evaluate structural
    anomalies in app-launch sequences (e.g., Calculator -> Gallery -> Banking).
    """

    def __init__(self, embedding_dim: int = 16, num_apps: int = 100):
        self.embedding_dim = embedding_dim
        self.num_apps = num_apps
        
        # Untrained random node embeddings for apps
        self.node_embeddings = np.random.randn(num_apps, embedding_dim)
        
        # Untrained weight matrices for message passing
        self.W_msg = np.random.randn(embedding_dim, embedding_dim)
        self.W_update = np.random.randn(embedding_dim, embedding_dim)

    def _hash_package(self, package_name: str) -> int:
        """Hash package name to a node index."""
        return hash(package_name) % self.num_apps

    def score_transition_sequence(self, sequence: list[str]) -> float:
        """
        Evaluate an app transition sequence using a mock Message Passing step.
        Returns a graph anomaly score (higher = more anomalous).
        """
        if len(sequence) < 2:
            return 0.0

        # Build adjacency array (A)
        nodes = [self._hash_package(app) for app in sequence]
        
        # Initial node features (H_0)
        H = self.node_embeddings[nodes].copy()
        
        # 1-step Message Passing
        # Message = H @ W_msg
        messages = H @ self.W_msg
        
        # Aggregate messages (simple mean across temporal path)
        agg_messages = np.mean(messages, axis=0, keepdims=True)
        
        # Update = H + (agg_messages @ W_update)
        H_new = H + (np.tile(agg_messages, (len(nodes), 1)) @ self.W_update)
        
        # Graph-level embedding (sum pool)
        graph_embed = np.sum(H_new, axis=0)
        
        # Since it's untrained, the anomaly score is simulated via embedding norm divergence
        expected_norm = np.sqrt(self.embedding_dim) # approximate expected norm
        current_norm = np.linalg.norm(graph_embed)
        
        divergence = abs(current_norm - expected_norm)
        
        # Map divergence to [0, 1] probability
        score = 1.0 - np.exp(-divergence * 0.1)
        return float(score)

