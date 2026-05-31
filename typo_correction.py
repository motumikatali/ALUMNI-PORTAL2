import difflib
import logging
import re
import sqlite3

try:
    from rapidfuzz import fuzz, process
except ImportError:  # pragma: no cover - optional dependency fallback
    fuzz = None
    process = None


class TypoCorrector:
    def __init__(self, db_path="database.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.learned_corrections = {}
        self.semantic_corrections = {
            "helo": "hello",
            "hy": "hi",
            "gud": "good",
            "mornng": "morning",
            "moring": "morning",
            "intrnship": "internship",
            "intrnshp": "internship",
            "recuiter": "recruiter",
            "rremove": "remove",
            "remve": "remove",
            "delte": "delete",
            "aply": "apply",
            "profle": "profile",
            "verif": "verify",
            "logn": "login",
            "pasword": "password",
            "hrlp": "help",
            "gud morning": "good morning",
            "good mornng": "good morning",
            "need hlep": "need help",
        }
        self.vocabulary = set()
        self._refresh_vocab()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _refresh_vocab(self):
        self.vocabulary.clear()
        self.vocabulary.update({
            "hello", "hi", "hey", "good", "morning", "afternoon", "evening", "internship",
            "recruiter", "profile", "remove", "delete", "login", "password", "cv", "resume",
            "apply", "verify", "help", "company", "student", "alumni", "dashboard", "portal",
            "recruiting", "verification", "application", "career", "job", "opportunity"
        })

        try:
            from knowledge_base import KnowledgeBase
            knowledge_base = KnowledgeBase(self.db_path)
            for row in knowledge_base.load_knowledge():
                for term in re.findall(r"[A-Za-z][A-Za-z0-9'-]+", (row.get("question") or "")):
                    self.vocabulary.add(term.lower())
                for term in re.findall(r"[A-Za-z][A-Za-z0-9'-]+", (row.get("answer") or "")):
                    self.vocabulary.add(term.lower())
                self.vocabulary.add((row.get("category") or "").lower())
        except Exception as exc:
            self.logger.warning("Failed to build typo vocabulary from knowledge base: %s", exc)

        self._load_learned_corrections()
        for typo, corrected in self.learned_corrections.items():
            self.vocabulary.add(corrected.lower())
            self.semantic_corrections[typo.lower()] = corrected.lower()

    def _load_learned_corrections(self):
        self.learned_corrections = {}
        try:
            conn = self._connect()
            rows = conn.execute("SELECT typo, corrected FROM typo_memory ORDER BY usage_count DESC, last_seen DESC").fetchall()
            conn.close()
            for row in rows:
                self.learned_corrections[(row["typo"] or "").strip().lower()] = (row["corrected"] or "").strip().lower()
        except Exception as exc:
            self.logger.warning("Failed to load learned typo corrections: %s", exc)

    def _remember_correction(self, typo, corrected, confidence, correction_type):
        typo = (typo or "").strip().lower()
        corrected = (corrected or "").strip().lower()
        if not typo or not corrected or typo == corrected:
            return
        try:
            conn = sqlite3.connect(self.db_path)
            existing = conn.execute(
                "SELECT id, usage_count FROM typo_memory WHERE typo = ? AND corrected = ?",
                (typo, corrected)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE typo_memory SET usage_count = usage_count + 1, last_seen = CURRENT_TIMESTAMP, confidence = ?, match_type = ? WHERE id = ?",
                    (round(float(confidence), 3), correction_type, existing[0])
                )
            else:
                conn.execute(
                    "INSERT INTO typo_memory (typo, corrected, confidence, match_type, usage_count, created_at, last_seen) VALUES (?, ?, ?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                    (typo, corrected, round(float(confidence), 3), correction_type)
                )
            conn.commit()
            conn.close()
            self.learned_corrections[typo] = corrected
            self.semantic_corrections[typo] = corrected
        except Exception as exc:
            self.logger.warning("Failed to store typo memory: %s", exc)

    def _match_word(self, word):
        word = (word or "").strip().lower()
        if not word:
            return word, 1.0, "blank"

        if word in self.vocabulary:
            return word, 1.0, "exact"

        if word in self.semantic_corrections:
            corrected = self.semantic_corrections[word]
            if corrected in self.vocabulary:
                return corrected, 0.96, "semantic"

        best_candidate = None
        best_score = 0.0
        best_method = "fuzzy"

        if process is not None:
            try:
                result = process.extractOne(word, self.vocabulary, scorer=fuzz.ratio, score_cutoff=55)
                if result:
                    candidate, score, _ = result
                    best_candidate = candidate
                    best_score = score / 100.0
                    best_method = "rapidfuzz"
            except Exception as exc:
                self.logger.warning("RapidFuzz matching error: %s", exc)

        if best_candidate is None:
            matches = difflib.get_close_matches(word, list(self.vocabulary), n=1, cutoff=0.55)
            if matches:
                best_candidate = matches[0]
                best_score = difflib.SequenceMatcher(None, word, best_candidate).ratio()
                best_method = "difflib"

        if best_candidate and best_score >= 0.72:
            return best_candidate, best_score, best_method

        return word, 1.0, "none"

    def correct_text(self, text):
        original = (text or "").strip()
        if not original:
            return {
                "text": "",
                "correction_applied": False,
                "confidence": 1.0,
                "correction_level": "none",
                "corrections": [],
            }

        cleaned = re.sub(r"[^A-Za-z0-9\s']+", " ", original.lower())
        raw_tokens = re.findall(r"[A-Za-z0-9']+", cleaned)

        corrected_tokens = []
        corrections = []
        scores = []

        for token in raw_tokens:
            corrected, score, method = self._match_word(token)
            corrected_tokens.append(corrected)
            scores.append(score)
            if corrected != token:
                corrections.append({
                    "original": token,
                    "corrected": corrected,
                    "confidence": round(float(score), 3),
                    "method": method,
                })
                self._remember_correction(token, corrected, score, method)

        corrected_text = " ".join(corrected_tokens)
        correction_applied = corrected_text != " ".join(raw_tokens)
        avg_score = round(float(sum(scores) / max(1, len(scores))), 3)

        if not correction_applied:
            correction_level = "none"
        elif avg_score >= 0.9:
            correction_level = "high"
        elif avg_score >= 0.72:
            correction_level = "medium"
        else:
            correction_level = "low"

        return {
            "text": corrected_text,
            "correction_applied": correction_applied,
            "confidence": avg_score,
            "correction_level": correction_level,
            "corrections": corrections,
            "original": original,
        }
