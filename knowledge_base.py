import json
import logging
import sqlite3


class KnowledgeBase:
    def __init__(self, db_path="database.db"):
        self.db_path = db_path
        self.logger = logging.getLogger(__name__)
        self.ensure_tables()
        self.seed_defaults()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def ensure_tables(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chatbot_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                user_id INTEGER,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chatbot_memory_session ON chatbot_memory(session_id, created_at)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chatbot_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                user_id INTEGER,
                rating INTEGER,
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chatbot_feedback_user ON chatbot_feedback(user_id, created_at)")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chatbot_intents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                intent TEXT NOT NULL,
                example TEXT,
                confidence REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chatbot_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                category TEXT NOT NULL,
                source TEXT DEFAULT 'seeded',
                confidence REAL DEFAULT 0.9,
                tags TEXT,
                embedding TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS typo_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                typo TEXT NOT NULL,
                corrected TEXT NOT NULL,
                confidence REAL DEFAULT 0.0,
                match_type TEXT,
                usage_count INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_typo_memory_lookup ON typo_memory(typo, corrected)")

        knowledge_cols = [row[1] for row in conn.execute("PRAGMA table_info(chatbot_knowledge)").fetchall()]
        if 'embedding' not in knowledge_cols:
            conn.execute("ALTER TABLE chatbot_knowledge ADD COLUMN embedding TEXT")

        conn.commit()
        conn.close()

    def seed_defaults(self):
        seed_rows = [
            {
                "question": "how to apply for internships",
                "answer": "To apply for internships, visit the Jobs page, review the internship listing, click the job posting, and submit your application. Make sure your profile is complete and your CV is uploaded so recruiters can review your application.",
                "category": "internship inquiries",
                "source": "faq",
                "confidence": 0.96,
                "tags": "apply,internship,cv,profile"
            },
            {
                "question": "how to edit profile",
                "answer": "Go to your dashboard, open Edit Profile, update your personal information, upload your CV, and save your changes. This is also where you can submit academic results for verification.",
                "category": "profile help",
                "source": "faq",
                "confidence": 0.96,
                "tags": "profile,edit,cv,upload"
            },
            {
                "question": "how recruiters approve students",
                "answer": "Recruiters review student profiles, academic records, skills, internship interests, and portfolio evidence. If a student matches the role requirements and passes verification checks, the recruiter can approve or shortlist them for opportunities.",
                "category": "recruiter inquiries",
                "source": "faq",
                "confidence": 0.95,
                "tags": "recruiter,approve,review,shortlist"
            },
            {
                "question": "how GPA matching works",
                "answer": "The portal compares academic performance, GPA, and relevant skills against internship or job requirements. Students with stronger academic standing and aligned experience are prioritized for recommendations and recruiter consideration.",
                "category": "internship inquiries",
                "source": "faq",
                "confidence": 0.94,
                "tags": "gpa,matching,academic,skills"
            },
            {
                "question": "how AI recommendation works",
                "answer": "The recommendation layer uses skills, internship interests, profile data, and past engagement patterns to rank opportunities that best match your academic background and career goals.",
                "category": "general knowledge",
                "source": "faq",
                "confidence": 0.92,
                "tags": "AI,recommendation,skills"
            },
            {
                "question": "internship requirements",
                "answer": "Common internship requirements include a current student or alumni status, relevant skills, a complete profile, CV upload, and any specific academic or experience requirements listed on the job posting.",
                "category": "internship inquiries",
                "source": "faq",
                "confidence": 0.93,
                "tags": "requirements,internship,cv"
            },
            {
                "question": "portal navigation",
                "answer": "Use the dashboard to access Jobs, Profile, Companies, Messages, and Verification. The portal is organized so students can apply, monitor progress, and communicate with recruiters from one place.",
                "category": "general knowledge",
                "source": "faq",
                "confidence": 0.9,
                "tags": "navigation,dashboard,portal"
            },
            {
                "question": "registration login issues",
                "answer": "If you are having trouble logging in, check your email and password, reset your password if needed, and confirm your account is active. For repeated login failures, contact the portal support team.",
                "category": "technical support",
                "source": "faq",
                "confidence": 0.91,
                "tags": "login,password,reset"
            },
            {
                "question": "academic verification questions",
                "answer": "Academic verification checks the uploaded results, certificates, and transcripts against your student record. Once reviewed, your verification status is updated on your profile.",
                "category": "general knowledge",
                "source": "faq",
                "confidence": 0.93,
                "tags": "verification,results,transcript"
            },
            {
                "question": "how do I upload my CV",
                "answer": "Upload your CV from Edit Profile by selecting the CV upload area, choosing the file, and saving it. Accepted formats include PDF or DOC files.",
                "category": "profile help",
                "source": "faq",
                "confidence": 0.95,
                "tags": "cv,upload,resume"
            },
            {
                "question": "where can I add resume",
                "answer": "You can add or update your resume in Edit Profile under the CV upload section. Make sure the file is readable and saved before applying.",
                "category": "profile help",
                "source": "faq",
                "confidence": 0.95,
                "tags": "resume,cv,edit profile"
            },
            {
                "question": "can I submit my resume",
                "answer": "Yes, you can submit your resume through the profile upload section. Upload it in Edit Profile and then use it when applying for internships or jobs.",
                "category": "profile help",
                "source": "faq",
                "confidence": 0.95,
                "tags": "resume,submit,cv"
            },
            {
                "question": "university guidance",
                "answer": "For university guidance, focus on maintaining strong academic records, building relevant skills, and connecting with internship opportunities that match your field of study.",
                "category": "general knowledge",
                "source": "general",
                "confidence": 0.88,
                "tags": "university,advice,career"
            },
            {
                "question": "internship advice",
                "answer": "A good internship strategy is to tailor your CV, keep your profile updated, apply early, and highlight practical projects or skills that match employer needs.",
                "category": "general knowledge",
                "source": "general",
                "confidence": 0.88,
                "tags": "advice,internship,cv"
            },
            {
                "question": "CV advice",
                "answer": "A strong CV should list academic achievements, relevant projects, technical skills, and internship or volunteer experience in a clear, professional format.",
                "category": "general knowledge",
                "source": "general",
                "confidence": 0.89,
                "tags": "cv,advice,resume"
            },
            {
                "question": "career tips",
                "answer": "Use your profile to showcase projects, keep learning current tools, and apply strategically to roles that fit your skill level and career goals.",
                "category": "general knowledge",
                "source": "general",
                "confidence": 0.88,
                "tags": "career,skills,goals"
            },
            {
                "question": "programming basics",
                "answer": "Programming basics include understanding variables, loops, conditionals, functions, debugging, and writing clear code that solves small problems step by step.",
                "category": "general knowledge",
                "source": "general",
                "confidence": 0.87,
                "tags": "programming,basics,code"
            },
            {
                "question": "software engineering basics",
                "answer": "Software engineering basics cover problem solving, version control, structured code, testing, documentation, and building maintainable applications.",
                "category": "general knowledge",
                "source": "general",
                "confidence": 0.87,
                "tags": "software engineering,testing,maintenance"
            },
            {
                "question": "AI basics",
                "answer": "AI basics involve building systems that learn patterns from data, make predictions, and support tasks like recommendation, classification, and natural language understanding.",
                "category": "general knowledge",
                "source": "general",
                "confidence": 0.86,
                "tags": "AI,basics,learning"
            },
            {
                "question": "how do I improve my CV",
                "answer": "To strengthen your CV, highlight academic achievements, relevant projects, technical skills, internships, and measurable outcomes. Keep it concise, professional, and tailored to the role you want.",
                "category": "cv guidance",
                "source": "faq",
                "confidence": 0.95,
                "tags": "cv,guidance,resume,skills"
            },
            {
                "question": "what is internship advice",
                "answer": "Good internship advice is to tailor your application, keep your profile current, upload your CV, and apply early for roles that match your skills and academic focus.",
                "category": "internship advice",
                "source": "faq",
                "confidence": 0.94,
                "tags": "internship,advice,apply,cv"
            },
            {
                "question": "how do I navigate the portal",
                "answer": "Use the dashboard to access Jobs, Profile, Companies, Messages, and Verification. This keeps your applications, uploads, and recruiter communication in one place.",
                "category": "portal navigation",
                "source": "faq",
                "confidence": 0.94,
                "tags": "portal,navigation,dashboard,verification"
            },
            {
                "question": "how do recruiters help students",
                "answer": "Recruiters review student profiles, academic records, skills, and internship interests to identify strong matches and provide structured feedback or approvals.",
                "category": "recruiter help",
                "source": "faq",
                "confidence": 0.93,
                "tags": "recruiter,students,help,review"
            },
            {
                "question": "how do students get help",
                "answer": "Students can use the portal to update profiles, upload documents, review internship opportunities, and contact support when they need help with account or application issues.",
                "category": "student help",
                "source": "faq",
                "confidence": 0.92,
                "tags": "student,help,portal,profile"
            }
        ]

        conn = sqlite3.connect(self.db_path)
        for row in seed_rows:
            conn.execute(
                """
                INSERT OR IGNORE INTO chatbot_knowledge (
                    question, answer, category, source, confidence, tags
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    row["question"],
                    row["answer"],
                    row["category"],
                    row["source"],
                    row["confidence"],
                    row["tags"]
                )
            )
        conn.commit()
        conn.close()

    def load_knowledge(self):
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, question, answer, category, source, confidence, tags, embedding FROM chatbot_knowledge ORDER BY id"
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_general_knowledge(self):
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, question, answer, category, source, confidence, tags, embedding FROM chatbot_knowledge WHERE category = 'general knowledge' ORDER BY id"
        ).fetchall()
        conn.close()
        return [dict(row) for row in rows]
