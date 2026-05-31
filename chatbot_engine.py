import json
import logging
import random
import re
import sqlite3

from escalation_manager import EscalationManager, should_escalate
from intent_classifier import IntentClassifier, detect_intent, is_greeting, is_question
from knowledge_base import KnowledgeBase
from semantic_search import SemanticSearch
from typo_correction import TypoCorrector


logger = logging.getLogger(__name__)
_chatbot_engines = {}


def get_chatbot_engine(db_path="database.db"):
    if db_path not in _chatbot_engines:
        _chatbot_engines[db_path] = ChatbotEngine(db_path)
    return _chatbot_engines[db_path]


def get_ai_response(message, user_id=None, session_id=None, db_path="database.db"):
    text = (message or "").strip()
    if not text:
        return {
            "response": "Please enter your question so I can help.",
            "intent": "unknown/general questions",
            "confidence": 0.2,
            "escalated": False,
            "clarification": None,
            "toxicity_flag": False,
            "context": [],
        }

    # Lightweight in-memory cache for common questions
    if not hasattr(get_ai_response, "_cache"):
        get_ai_response._cache = {
            "how do i apply": "To apply for internships, go to Jobs section, find a position, and click Apply.",
            "deadlines": "Upcoming deadlines are shown on your dashboard.",
            "profile help": "Go to Profile > Edit Profile to update your information.",
        }

    def get_cached_response(message_text):
        m = (message_text or "").lower().strip()
        for k, v in get_ai_response._cache.items():
            if k in m:
                return v
        return None

    # Check cache first
    cached = get_cached_response(text)
    if cached:
        return {
            "response": cached,
            "intent": "cached",
            "confidence": 0.99,
            "escalated": False,
            "clarification": None,
            "toxicity_flag": False,
            "context": [],
        }

    # Run model with timeout fallback
    try:
        engine = get_chatbot_engine(db_path)
        correction = engine.correct_message(text)
        corrected_text = correction["text"]

        intent_data = detect_intent(corrected_text, db_path=db_path)
        escalate_flag = should_escalate(corrected_text, intent=intent_data["intent"], confidence=intent_data["confidence"], db_path=db_path)

        # Run expensive processing but enforce a 5s timeout fallback
        import concurrent.futures

        def run_process():
            return engine.process_message(corrected_text, user_id=user_id, session_id=session_id)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(run_process)
            try:
                result = fut.result(timeout=5)
            except concurrent.futures.TimeoutError:
                # Timeout fallback: simple canned reply
                fallback = "Sorry, I'm taking too long. Try rephrasing or check Jobs and Profile sections."
                return {
                    "response": fallback,
                    "intent": "timeout/fallback",
                    "confidence": 0.1,
                    "escalated": False,
                    "clarification": None,
                    "toxicity_flag": False,
                    "context": [],
                }

        result["correction"] = correction
        result["escalated"] = bool(result.get("escalated") or escalate_flag)
        result["confidence"] = float(result.get("confidence") or intent_data["confidence"] or 0.0)
        return result
    except Exception as exc:
        logger.exception("Failed to generate AI response: %s", exc)
        return {
            "response": "I’m here to help with internships, profile updates, recruiter questions, verification, and portal support.",
            "intent": "unknown/general questions",
            "confidence": 0.0,
            "escalated": False,
            "clarification": None,
            "toxicity_flag": False,
            "context": [],
        }


class ChatbotEngine:
    def __init__(self, db_path="database.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.intent_classifier = IntentClassifier(db_path)
        self.knowledge_base = KnowledgeBase(db_path)
        self.semantic_search = SemanticSearch(db_path)
        self.escalation_manager = EscalationManager(db_path)
        self.typo_corrector = TypoCorrector(db_path)

    def correct_message(self, text):
        return self.typo_corrector.correct_text(text)

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _get_recent_context(self, user_id=None, session_id=None, limit=5):
        conn = self._connect()
        query = "SELECT role, content, created_at FROM chatbot_memory WHERE 1=1"
        params = []
        if session_id:
            query += " AND session_id = ?"
            params.append(str(session_id))
        if user_id is not None:
            query += " AND user_id = ?"
            try:
                params.append(int(user_id))
            except (TypeError, ValueError):
                params.append(str(user_id))
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(row) for row in reversed(rows)]

    def _store_memory(self, user_id, session_id, role, content, metadata=None):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute(
                """
                INSERT INTO chatbot_memory (session_id, user_id, role, content, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (str(session_id), user_id, role, content, json.dumps(metadata or {}))
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            self.logger.warning("Failed to store chatbot memory: %s", exc)

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
            self.logger.warning("Failed to record intent: %s", exc)

    def _greeting_response(self, text):
        if is_greeting(text):
            greeting_options = [
                "Hello! I’m your Alumni Internship & Placement assistant, here to help with internships, profiles, recruiter questions, verification, and portal navigation.",
                "Hi there! I’m your placement assistant, ready to help with internship guidance, CV support, recruiter questions, and portal navigation.",
                "Good day! I’m your assistant for internships, profile help, recruiter support, verification, and campus portal navigation."
            ]
            return random.choice(greeting_options)
        return None

    def _clarification_prompt(self, text, intent):
        lowered = (text or "").lower()
        if "internship" in lowered:
            return "Are you looking to apply for internships or post internships?"
        if "profile" in lowered or "cv" in lowered or "resume" in lowered:
            return "Are you trying to edit your profile details or upload your CV?"
        if "login" in lowered or "password" in lowered or "register" in lowered:
            return "Are you having trouble logging in, resetting your password, or registering a new account?"
        if intent == "unknown/general questions":
            return "Could you tell me whether you need help with internships, profiles, applications, recruiter approvals, or verification?"
        return "Could you share a little more detail so I can assist accurately?"

    def _fallback_response(self, intent):
        if intent == "internship inquiries":
            return "I can help with internship applications, requirements, and navigation. If you need specific guidance, tell me whether you are applying, checking status, or reviewing requirements."
        if intent == "profile help":
            return "You can update your profile and CV from Edit Profile. If you need help with uploads or verification, I can walk you through it."
        if intent == "recruiter inquiries":
            return "Recruiter decisions are based on profile completeness, academic records, skills, and how well your background matches the role."
        if intent == "technical support":
            return "For technical issues, please check your login details, reset your password if needed, and try again. If the problem continues, I can escalate you to admin."
        if intent == "complaints":
            return "I’m sorry to hear that. I can help document the issue, and I can escalate it to admin if needed."
        return "I can help with internships, profile updates, recruiter questions, verification, and general portal support."

    def _compute_confidence(self, intent_confidence, best_similarity):
        if best_similarity is None:
            return round(float(intent_confidence), 3)
        return round(float((0.4 * intent_confidence) + (0.6 * best_similarity)), 3)

    def process_message(self, user_message, user_id=None, session_id=None):
        try:
            original_text = (user_message or "").strip()
            if not original_text:
                response = "Please enter your question so I can help."
                return {
                    "response": response,
                    "intent": "unknown/general questions",
                    "confidence": 0.2,
                    "escalated": False,
                    "clarification": None,
                    "toxicity_flag": False,
                }

            if session_id is None:
                session_id = f"chat_{user_id or 'anon'}"

            correction = self.correct_message(original_text)
            corrected_text = correction["text"]
            typo_confidence = correction["confidence"]
            typo_level = correction["correction_level"]
            typo_corrections = correction["corrections"]

            if correction["correction_applied"] and typo_level == "medium":
                suggestion = typo_corrections[0]["corrected"] if typo_corrections else corrected_text
                response = f"Did you mean '{suggestion}'?"
                confidence = round(max(typo_confidence, 0.55), 3)
                escalated = False
                toxicity_flag = False
                clarification = response
                intent = "unknown/general questions"
                context = self._get_recent_context(user_id=user_id, session_id=session_id, limit=5)
                self._store_memory(user_id, session_id, "user", original_text, {
                    "intent": intent,
                    "confidence": confidence,
                    "toxicity_flag": toxicity_flag,
                    "correction_applied": True,
                    "corrected_text": corrected_text,
                    "typo_confidence": typo_confidence,
                    "correction_level": typo_level,
                })
                self._store_memory(user_id, session_id, "assistant", response, {
                    "intent": intent,
                    "confidence": confidence,
                    "escalated": escalated,
                    "toxicity_flag": toxicity_flag,
                    "correction_applied": True,
                    "corrected_text": corrected_text,
                    "typo_confidence": typo_confidence,
                    "correction_level": typo_level,
                })
                return {
                    "response": response,
                    "intent": intent,
                    "confidence": confidence,
                    "escalated": escalated,
                    "clarification": clarification,
                    "toxicity_flag": toxicity_flag,
                    "context": context,
                    "correction": correction,
                }

            if correction["correction_applied"] and typo_level == "low":
                response = "I’m not sure I understood that. Could you please clarify what you need?"
                confidence = round(max(typo_confidence, 0.35), 3)
                escalated = False
                toxicity_flag = False
                clarification = response
                intent = "unknown/general questions"
                context = self._get_recent_context(user_id=user_id, session_id=session_id, limit=5)
                self._store_memory(user_id, session_id, "user", original_text, {
                    "intent": intent,
                    "confidence": confidence,
                    "toxicity_flag": toxicity_flag,
                    "correction_applied": True,
                    "corrected_text": corrected_text,
                    "typo_confidence": typo_confidence,
                    "correction_level": typo_level,
                })
                self._store_memory(user_id, session_id, "assistant", response, {
                    "intent": intent,
                    "confidence": confidence,
                    "escalated": escalated,
                    "toxicity_flag": toxicity_flag,
                    "correction_applied": True,
                    "corrected_text": corrected_text,
                    "typo_confidence": typo_confidence,
                    "correction_level": typo_level,
                })
                return {
                    "response": response,
                    "intent": intent,
                    "confidence": confidence,
                    "escalated": escalated,
                    "clarification": clarification,
                    "toxicity_flag": toxicity_flag,
                    "context": context,
                    "correction": correction,
                }

            text = corrected_text if correction["correction_applied"] else original_text

            context = self._get_recent_context(user_id=user_id, session_id=session_id, limit=5)
            intent, intent_confidence = self.intent_classifier.classify(text)
            self._record_intent(text, intent, intent_confidence)

            if "remove profile" in text or "delete profile" in text:
                response = "I understand you want to remove your profile. I can help with that, but I’ll need your password to confirm before deleting anything."
                confidence = 0.9
                escalated = False
                toxicity_flag = False
                clarification = None
            else:
                greeting = self._greeting_response(text.lower())
                if greeting:
                    response = greeting
                    confidence = 0.96
                    escalated = False
                    toxicity_flag = False
                    clarification = None
                else:
                    vague_patterns = [
                        (re.compile(r"\b(i need internship|need internship|internship help)\b"), "Are you looking to apply for internships or post internships?"),
                        (re.compile(r"\b(i need profile|need profile|profile help)\b"), "Are you trying to edit your profile details or upload your CV?"),
                        (re.compile(r"\b(i need login|need login|login help)\b"), "Are you having trouble logging in, resetting your password, or registering a new account?"),
                    ]
                    handled_vague = False
                    vague_prompt = None
                    best_result = None
                    best_similarity = 0.0
                    failed_attempts = 0
                    for pattern, prompt in vague_patterns:
                        if pattern.search(text.lower()):
                            vague_prompt = prompt
                            handled_vague = True
                            break

                    if handled_vague:
                        response = vague_prompt
                        confidence = 0.70
                        escalated = False
                        toxicity_flag = False
                        clarification = response
                    else:
                        best_match = self.semantic_search.search(text, self.knowledge_base.load_knowledge(), top_k=3)
                        best_result = best_match[0] if best_match else None
                        best_similarity = float(best_result["similarity"]) if best_result else 0.0

                        confidence = self._compute_confidence(intent_confidence, best_similarity)
                        if confidence < self.escalation_manager.low_confidence_threshold:
                            failed_attempts = self.escalation_manager.record_failure(session_id, user_id)
                        else:
                            self.escalation_manager.clear_failure_count(session_id, user_id)

                    toxicity_flag = self.escalation_manager.is_toxic(text)

                    if toxicity_flag:
                        response = "I’m sorry, but that language is not appropriate. Please keep the conversation respectful."
                        escalated = True
                        clarification = None
                    elif handled_vague:
                        response = vague_prompt
                        escalated = False
                        clarification = response
                    else:
                        action, escalation_response = self.escalation_manager.determine_action(text, intent, confidence, failed_attempts)

                        if action == "escalate":
                            if escalation_response:
                                response = escalation_response
                            else:
                                response = "I’m connecting you with an admin for specialist support."
                            escalated = True
                            clarification = None
                        elif confidence < self.escalation_manager.low_confidence_threshold:
                            response = self._clarification_prompt(text, intent)
                            escalated = False
                            clarification = response
                        elif best_result and best_similarity >= 0.55:
                            response = best_result["answer"]
                            escalated = False
                            clarification = None
                        else:
                            general_match = self.semantic_search.search(text, self.knowledge_base.get_general_knowledge(), top_k=1)
                            if general_match:
                                response = general_match[0]["answer"]
                            else:
                                response = self._fallback_response(intent)
                            escalated = False
                            clarification = None

                    if confidence < self.escalation_manager.low_confidence_threshold and not escalated:
                        response = self._clarification_prompt(text, intent)
                        clarification = response

                    if intent == "unknown/general questions" and best_result and best_similarity >= 0.55:
                        response = best_result["answer"]
                        escalated = False

            self._store_memory(user_id, session_id, "user", original_text, {
                "intent": intent,
                "confidence": confidence,
                "toxicity_flag": toxicity_flag,
                "correction_applied": correction["correction_applied"],
                "corrected_text": corrected_text,
                "typo_confidence": typo_confidence,
                "correction_level": typo_level,
            })
            self._store_memory(user_id, session_id, "assistant", response, {
                "intent": intent,
                "confidence": confidence,
                "escalated": escalated,
                "toxicity_flag": toxicity_flag,
                "correction_applied": correction["correction_applied"],
                "corrected_text": corrected_text,
                "typo_confidence": typo_confidence,
                "correction_level": typo_level,
            })

            return {
                "response": response,
                "intent": intent,
                "confidence": confidence,
                "escalated": escalated,
                "clarification": clarification,
                "toxicity_flag": toxicity_flag,
                "context": context,
                "correction": correction,
            }
        except Exception as exc:
            self.logger.exception("Chatbot processing failed: %s", exc)
            return {
                "response": "I’m here to help with internships, profile updates, recruiter questions, verification, and portal support.",
                "intent": "unknown/general questions",
                "confidence": 0.0,
                "escalated": False,
                "clarification": None,
                "toxicity_flag": False,
                "context": [],
            }
