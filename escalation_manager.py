import json
import logging
import re
import sqlite3

from intent_classifier import is_greeting


def should_escalate(message, intent=None, confidence=None, db_path="database.db"):
    text = (message or "").strip()
    if not text:
        return False
    if is_greeting(text):
        return False

    manager = EscalationManager(db_path)
    lowered = text.lower()
    if manager.is_toxic(text):
        return True

    explicit_patterns = [
        r"\b(talk to admin|contact admin|speak to human|speak with admin|need help from admin|please escalate|connect me to admin)\b",
        r"\b(help me|i need help|need help)\b",
    ]
    if any(re.search(pattern, lowered) for pattern in explicit_patterns):
        return True
    return False


class EscalationManager:
    def __init__(self, db_path="database.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.toxic_pattern = re.compile(
            r"\b(fuck|shit|damn|bitch|asshole|idiot|stupid|moron|dumb|hate|racist|nazi|kill|die)\b",
            re.IGNORECASE
        )
        self.escalation_keywords = [
            "help", "admin", "complaint", "problem", "issue", "urgent", "speak to human", "contact admin"
        ]
        self.low_confidence_threshold = 0.55
        self.max_failures = 3
        self.failure_counts = {}

    def is_toxic(self, text):
        return bool(self.toxic_pattern.search(text or ""))

    def determine_action(self, text, intent, confidence, failed_attempts=0):
        lowered = (text or "").lower()

        if self.is_toxic(text):
            return "escalate", "That language is not appropriate. Please keep the conversation respectful."

        explicit_escalation_patterns = [
            r"\b(talk to admin|contact admin|speak to human|speak with admin|need help from admin|please escalate|connect me to admin)\b",
            r"\b(help me|i need help|need help)\b",
        ]
        if any(re.search(pattern, lowered) for pattern in explicit_escalation_patterns):
            return "escalate", "I’m connecting you with an admin because this needs specialist support."

        if failed_attempts >= self.max_failures and confidence < self.low_confidence_threshold:
            return "escalate", "I’m having trouble answering that precisely, so I’m escalating this to an admin for support."

        if confidence < self.low_confidence_threshold:
            return "clarify", None

        return "respond", None

    def record_failure(self, session_id, user_id=None):
        key = (str(session_id), str(user_id) if user_id is not None else "anonymous")
        self.failure_counts[key] = self.failure_counts.get(key, 0) + 1
        failed_attempts = self.failure_counts[key]
        self.logger.info("Recorded low-confidence failure %s for session %s", failed_attempts, session_id)
        return failed_attempts

    def clear_failure_count(self, session_id, user_id=None):
        key = (str(session_id), str(user_id) if user_id is not None else "anonymous")
        if key in self.failure_counts:
            del self.failure_counts[key]
