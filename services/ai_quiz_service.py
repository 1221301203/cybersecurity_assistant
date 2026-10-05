import json
import logging
from models import db, Quiz

def generate_and_save_quiz(topic: str, difficulty: str, language: str = 'en') -> Quiz:
    """
    1. Prompts AI API for a JSON quiz payload.
    2. Parses response and saves it into 'Quizzes' database table.
    3. Returns the saved Quiz ORM instance.
    """
    prompt = f"""
    You are a cybersecurity assessment engine. Generate ONE 4-option multiple-choice question.
    Topic: {topic}
    Difficulty: {difficulty}
    Language: {language}

    Respond strictly in JSON format matching this schema:
    {{
        "question_text": "string",
        "option_a": "string",
        "option_b": "string",
        "option_c": "string",
        "option_d": "string",
        "correct_option": "A|B|C|D"
    }}
    Do not wrap response in markdown blocks.
    """

    # --- AI API CALL PLACEHOLDER ---
    # Replace this block with your actual AI client call (e.g., Gemini or OpenAI SDK)
    # Example mock payload for testing execution:
    raw_json_str = """
    {
        "question_text": "What is the main purpose of multi-factor authentication (MFA)?",
        "option_a": "To speed up user login times",
        "option_b": "To add an additional layer of security beyond passwords",
        "option_c": "To generate encrypted passwords automatically",
        "option_d": "To bypass firewall rules",
        "correct_option": "B"
    }
    """
    # -------------------------------

    try:
        data = json.loads(raw_json_str)

        # Save question directly into the Quizzes database table
        new_quiz = Quiz(
            difficulty_level=difficulty,
            language=language,
            question_text=data['question_text'],
            option_a=data['option_a'],
            option_b=data['option_b'],
            option_c=data['option_c'],
            option_d=data['option_d'],
            correct_option=data['correct_option'].upper()
        )
        
        db.session.add(new_quiz)
        db.session.commit()
        return new_quiz

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error saving AI quiz to database: {e}")
        raise RuntimeError(f"Failed to generate and store quiz: {e}")