"""
Vector Memory - Semantic search for JARVIS
Uses Ollama embeddings if available, fallback to simple TF-IDF / keyword
"""

import json
import math
import os
import re
from pathlib import Path
from typing import List, Dict, Tuple
from datetime import datetime

from ..config import config


def cosine_sim(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x*y for x,y in zip(a,b))
    norm_a = math.sqrt(sum(x*x for x in a))
    norm_b = math.sqrt(sum(y*y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorStore:
    def __init__(self, store_path: Path = None, embedding_model: str = "nomic-embed-text"):
        self.store_path = store_path or config.MEMORY_FILE.parent / "vectors.json"
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.embedding_model = embedding_model
        self.vectors: List[Dict] = []
        self._load()
        self._ollama_available = None
    
    def _load(self):
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text())
                self.vectors = data if isinstance(data, list) else data.get("vectors", [])
            except:
                self.vectors = []
    
    def _save(self):
        try:
            self.store_path.write_text(json.dumps(self.vectors, indent=2))
        except Exception as e:
            print(f"Vector store save failed: {e}")
    
    def _get_embedding(self, text: str) -> List[float]:
        """Try Ollama embeddings, fallback to simple hash embedding"""
        # Try Ollama
        try:
            import requests
            resp = requests.post(
                f"{config.OLLAMA_HOST}/api/embeddings",
                json={"model": self.embedding_model, "prompt": text},
                timeout=5
            )
            if resp.status_code == 200:
                data = resp.json()
                emb = data.get("embedding")
                if emb:
                    return emb
        except Exception:
            pass
        
        # Fallback: try nomic via ollama list check, else TF-IDF like hash
        # Simple deterministic embedding via char n-grams hashing into 128 dims
        # Not perfect but works offline without model
        return self._hash_embed(text, dim=128)
    
    def _hash_embed(self, text: str, dim: int = 128) -> List[float]:
        text = text.lower()
        vec = [0.0]*dim
        # Use word hashing
        words = re.findall(r'\w+', text)
        for w in words:
            h = hash(w) % dim
            vec[h] += 1.0
        # Add char bigram
        for i in range(len(text)-1):
            bg = text[i:i+2]
            h = hash(bg) % dim
            vec[h] += 0.3
        # Normalize
        norm = math.sqrt(sum(x*x for x in vec)) or 1.0
        return [x/norm for x in vec]
    
    def add(self, text: str, metadata: Dict = None) -> Dict:
        embedding = self._get_embedding(text)
        entry = {
            "id": datetime.now().timestamp(),
            "text": text,
            "embedding": embedding,
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat(),
            "access_count": 0
        }
        self.vectors.append(entry)
        # Keep max 1000 entries, prune oldest low-importance
        if len(self.vectors) > 1000:
            # Sort by access_count + recency
            self.vectors.sort(key=lambda x: (x.get("access_count",0), x.get("timestamp","")), reverse=True)
            self.vectors = self.vectors[:1000]
        self._save()
        return entry
    
    def search(self, query: str, k: int = 5, threshold: float = 0.1) -> List[Dict]:
        if not self.vectors:
            return []
        q_emb = self._get_embedding(query)
        scored = []
        for v in self.vectors:
            emb = v.get("embedding")
            if not emb:
                continue
            score = cosine_sim(q_emb, emb)
            if score >= threshold:
                scored.append((score, v))
        scored.sort(key=lambda x: x[0], reverse=True)
        # Update access count
        for score, v in scored[:k]:
            v["access_count"] = v.get("access_count",0) + 1
        self._save()
        return [ {"score": s, **v} for s,v in scored[:k] ]
    
    def get_all(self, limit: int = 100) -> List[Dict]:
        # Return most recent
        sorted_vec = sorted(self.vectors, key=lambda x: x.get("timestamp",""), reverse=True)
        return sorted_vec[:limit]
    
    def delete(self, query: str) -> int:
        original = len(self.vectors)
        q = query.lower()
        self.vectors = [v for v in self.vectors if q not in v.get("text","").lower()]
        deleted = original - len(self.vectors)
        self._save()
        return deleted
    
    def clear(self):
        self.vectors = []
        self._save()
