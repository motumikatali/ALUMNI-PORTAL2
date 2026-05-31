import difflib
import json
import logging
import re
import sqlite3

import numpy as np

try:
    import spacy
except ImportError:
    spacy = None

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
except ImportError:
    TfidfVectorizer = None
    LogisticRegression = None


GREETINGS = [
    "hi", "hello", "hey", "good morning", "good afternoon", "good evening", "how are you"
]


def is_greeting(message):
    text = (message or "").strip().lower()
    if not text:
        return False
    if any(re.search(rf"\b{re.escape(phrase)}\b", text) for phrase in GREETINGS):
        return True
    normalized = re.sub(r"[^a-z0-9\s]", " ", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return any(difflib.SequenceMatcher(None, normalized, phrase).ratio() >= 0.72 for phrase in GREETINGS)


def is_question(message):
    text = (message or "").strip()
    if not text:
        return False
    if "?" in text:
        return True
    lowered = text.lower()
    return any(lowered.startswith(prefix) for prefix in ["how ", "what ", "when ", "where ", "why ", "can ", "could ", "do ", "does ", "is ", "are ", "would ", "will "])


_classifier_cache = {}


def get_intent_classifier(db_path="database.db"):
    if db_path not in _classifier_cache:
        _classifier_cache[db_path] = IntentClassifier(db_path)
    return _classifier_cache[db_path]


def detect_intent(message, db_path="database.db"):
    try:
        from knowledge_base import KnowledgeBase
        KnowledgeBase(db_path).ensure_tables()
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to ensure chatbot tables: %s", exc)

    classifier = get_intent_classifier(db_path)
    try:
        intent, confidence = classifier.classify(message or "")
        return {
            "intent": intent,
            "confidence": float(confidence),
        }
    except Exception as exc:
        logging.getLogger(__name__).warning("Failed to detect intent: %s", exc)
        return {
            "intent": "unknown/general questions",
            "confidence": 0.0,
        }


class IntentClassifier:
    def __init__(self, db_path="database.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.nlp = None
        if spacy is not None:
            try:
                self.nlp = spacy.load("en_core_web_sm")
            except OSError:
                self.logger.warning("spaCy model 'en_core_web_sm' not available; using fallback preprocessing.")
        else:
            self.logger.warning("spaCy is not available; using fallback preprocessing.")

        self.intent_examples = {
            "greetings": [
                "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
                "how are you", "what's up", "hi there", "hello there"
            ],
            "internship inquiries": [
                "how do I apply for an internship",
                "where can I find internships",
                "internship opportunities",
                "what internship roles are available",
                "which internships are open"
            ],
            "recruiter inquiries": [
                "how do recruiters approve students",
                "how do recruiters review applications",
                "what do recruiters look for",
                "how does recruiter matching work"
            ],
            "student inquiries": [
                "how do I check my application status",
                "can I see my student profile",
                "how do I view my internship applications",
                "student profile information"
            ],
            "profile help": [
                "how do I edit my profile",
                "how can I update my CV",
                "how do I upload my resume",
                "where can I add my CV",
                "edit profile"
            ],
            "application help": [
                "how to apply for jobs",
                "apply for an internship",
                "submit application",
                "application process"
            ],
            "complaints": [
                "I am unhappy with the portal",
                "this system is broken",
                "I have a complaint",
                "the application is not working"
            ],
            "technical support": [
                "login is not working",
                "reset password issue",
                "technical issue",
                "the website is broken",
                "error when uploading"
            ],
            "unknown/general questions": [
                "tell me about AI",
                "what is software engineering",
                "what are career tips",
                "can you help me with general advice",
                "how do I improve my CV"
            ],
        }

        self.vectorizer = None
        self.model = None
        self._train_model()

    def _train_model(self):
        if TfidfVectorizer is None or LogisticRegression is None:
            self.logger.warning("scikit-learn is not available; intent classification will use keyword fallback.")
            return
        texts = []
        labels = []
        for intent, examples in self.intent_examples.items():
            for example in examples:
                texts.append(example)
                labels.append(intent)

        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, stop_words="english")
        X = self.vectorizer.fit_transform(texts)
        self.model = LogisticRegression(max_iter=1000)
        self.model.fit(X, labels)

    def _preprocess(self, text):
        cleaned = re.sub(r"[^A-Za-z0-9\s]", " ", (text or "").lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if self.nlp is not None:
            doc = self.nlp(cleaned)
            lemmas = [token.lemma_.lower() for token in doc if not token.is_stop and token.is_alpha and len(token.text) > 1]
            return " ".join(lemmas)
        return cleaned

    def _keyword_intent(self, text):
        if is_greeting(text):
            return "greetings", 0.98
        if any(term in text for term in ["complaint", "unhappy", "broken", "not working", "issue"]):
            return "complaints", 0.72
        if any(term in text for term in ["login", "password", "reset", "error", "technical", "upload"]):
            return "technical support", 0.68
        if any(term in text for term in ["edit profile", "upload cv", "resume", "cv"]):
            return "profile help", 0.75
        if any(term in text for term in ["apply", "application", "internship"]):
            return "internship inquiries", 0.70
        if any(term in text for term in ["recruiter", "approve", "review"]):
            return "recruiter inquiries", 0.74
        return None, 0.0

    def classify(self, text):
        cleaned = self._preprocess(text)
        keyword_intent, keyword_conf = self._keyword_intent(cleaned)
        if keyword_intent:
            confidence = keyword_conf
            intent = keyword_intent
            self._record_intent(text, intent, confidence)
            return intent, confidence

        if self.vectorizer is None or self.model is None:
            intent = "unknown/general questions"
            confidence = 0.4
            self._record_intent(text, intent, confidence)
            return intent, confidence

        vector = self.vectorizer.transform([cleaned])
        predicted = self.model.predict(vector)[0]
        probabilities = self.model.predict_proba(vector)[0]
        confidence = float(np.max(probabilities)) if len(probabilities) else 0.0

        if confidence < 0.35:
            predicted = "unknown/general questions"
            confidence = 0.35

        self._record_intent(text, predicted, confidence)
        return predicted, confidence

    def _record_intent(self, text, intent, confidence):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """
                INSERT INTO chatbot_intents (intent, example, confidence, created_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (intent, (text or "")[:500], round(float(confidence), 3))
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            logging.getLogger(__name__).warning("Failed to record intent: %s", exc)
