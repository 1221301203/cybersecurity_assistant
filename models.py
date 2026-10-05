from datetime import datetime
from flask_bcrypt import Bcrypt
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
bcrypt = Bcrypt()

# Base args for MySQL Foreign Key support
extra_args = {'mysql_engine': 'InnoDB'}


# 1. USERS TABLE
class User(db.Model):
    __tablename__ = 'users'
    __table_args__ = extra_args

    user_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    preferred_language = db.Column(db.String(10), default='en')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_2fa_enabled = db.Column(db.Boolean, default=False)

    # Biometric (WebAuthn) fields
    biometric_credential_id = db.Column(db.LargeBinary, nullable=True)
    biometric_public_key = db.Column(db.LargeBinary, nullable=True)
    biometric_sign_count = db.Column(db.Integer, default=0)

    # Relationships
    sessions = db.relationship(
        'ChatbotSession',
        backref='user',
        lazy=True,
        cascade='all, delete-orphan',
    )
    quiz_results = db.relationship(
        'QuizResult', backref='user', lazy=True, cascade='all, delete-orphan'
    )
    reminders = db.relationship(
        'UserReminder', backref='user', lazy=True, cascade='all, delete-orphan'
    )


# 2. CHATBOT_SESSIONS TABLE
class ChatbotSession(db.Model):
  __tablename__ = 'chatbot_sessions'
  __table_args__ = extra_args

  session_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
  user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=False)
  started_at = db.Column(db.DateTime, default=datetime.utcnow)

  # Relationships
  messages = db.relationship(
      'ChatbotMessage', backref='session', lazy=True, cascade='all, delete-orphan'
  )


# 3. CHATBOT_MESSAGES TABLE
class ChatbotMessage(db.Model):
  __tablename__ = 'chatbot_messages'
  __table_args__ = extra_args

  message_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
  session_id = db.Column(
      db.Integer, db.ForeignKey('chatbot_sessions.session_id'), nullable=False
  )
  sender = db.Column(db.Enum('user', 'bot', name='sender_enum'), nullable=False)
  message_text = db.Column(db.Text, nullable=False)
  language_used = db.Column(db.String(10), nullable=False)
  timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# 4. QUIZZES TABLE
class Quiz(db.Model):
    __tablename__ = 'quizzes'
    __table_args__ = extra_args

    quiz_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    topic = db.Column(db.String(100), nullable=False)
    difficulty_level = db.Column(db.String(20), nullable=False)
    language = db.Column(db.String(10), nullable=False, default='en')
    generated_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship to easily fetch all questions for this quiz: quiz.questions
    questions = db.relationship('Question', backref='quiz', cascade='all, delete-orphan')

class Question(db.Model):
    __tablename__ = 'questions'
    __table_args__ = extra_args

    question_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.quiz_id'), nullable=False)
    
    question_text = db.Column(db.Text, nullable=False)
    option_a = db.Column(db.String(255), nullable=False)
    option_b = db.Column(db.String(255), nullable=False)
    option_c = db.Column(db.String(255), nullable=False)
    option_d = db.Column(db.String(255), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)
    explanation = db.Column(db.Text, nullable=True)

# 5. QUIZ_RESULTS TABLE
class QuizResult(db.Model):
    __tablename__ = 'quiz_results'
    __table_args__ = extra_args

    result_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.user_id'), nullable=True) # or depending on how you store users
    session_id = db.Column(db.String(100), nullable=True)
    
    # Link to the Quiz session (useful for grouping a whole quiz attempt)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.quiz_id'), nullable=False)
    
    # Link to the exact Question being answered
    question_id = db.Column(db.Integer, db.ForeignKey('questions.question_id'), nullable=False)
    
    user_answer = db.Column(db.String(1), nullable=False) # e.g., 'A', 'B', 'C', 'D'
    is_correct = db.Column(db.Boolean, nullable=False)
    attempted_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships for easy querying in your dashboard
    question = db.relationship('Question', backref='results')


# 6. CYBERSECURITY_TIPS TABLE
class CybersecurityTip(db.Model):
    __tablename__ = 'cybersecurity_tips'
    __table_args__ = extra_args

    # Both tip_id and language make up the composite primary key
    tip_id = db.Column(db.Integer, primary_key=True)
    language = db.Column(db.String(10), primary_key=True)
    
    title = db.Column(db.String(150), nullable=False)
    content = db.Column(db.Text, nullable=False)

    # Relationships
    user_reminders = db.relationship(
        'UserReminder', backref='tip', lazy=True, cascade='all, delete-orphan'
    )


# 7. USER_REMINDERS TABLE (Added & Fully Integrated)
class UserReminder(db.Model):
  __tablename__ = "user_reminders"

  user_reminder_id = db.Column(db.Integer, primary_key=True)
  user_id = db.Column(db.Integer, db.ForeignKey("users.user_id"), nullable=False)

  # tip_id must be nullable for custom reminders!
  tip_id = db.Column(db.Integer, nullable=True)
  language = db.Column(db.String(10), nullable=False)

  title = db.Column(db.String(150), nullable=False)
  description = db.Column(db.Text, nullable=True)
  type = db.Column(db.String(50), nullable=True)
  priority = db.Column(db.String(20), nullable=True)
  is_completed = db.Column(db.Boolean, default=False)
  completed_at = db.Column(db.DateTime, nullable=True)
  next_due_date = db.Column(db.Date, nullable=True)

  __table_args__ = (
      db.ForeignKeyConstraint(
          ["tip_id", "language"],
          ["cybersecurity_tips.tip_id", "cybersecurity_tips.language"],
          ondelete="CASCADE",
      ),
  )