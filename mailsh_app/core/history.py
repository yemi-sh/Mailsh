"""
Email sending history tracking.

This module maintains a log of all sent emails and provides statistics
about sending success rates and history.
"""

import json
from pathlib import Path
from typing import List, Dict


class History:
    """Email history tracker"""
    
    def __init__(self, config_dir: Path):
        self.history_file = config_dir / "history.jsonl"
    
    def add(self, email_data: Dict):
        with open(self.history_file, 'a') as f:
            f.write(json.dumps(email_data) + '\n')
    
    def get_all(self) -> List[Dict]:
        if not self.history_file.exists():
            return []
        
        history = []
        with open(self.history_file, 'r') as f:
            for line in f:
                if line.strip():
                    history.append(json.loads(line))
        return history
    
    def get_stats(self) -> Dict:
        history = self.get_all()
        total = len(history)
        sent = sum(1 for h in history if h['status'] == 'sent')
        failed = sum(1 for h in history if h['status'] == 'failed')
        
        return {
            "total": total,
            "sent": sent,
            "failed": failed,
            "success_rate": (sent / total * 100) if total > 0 else 0
        }