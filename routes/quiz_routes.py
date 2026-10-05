from flask import Blueprint, request, jsonify, session
from models import db, Quiz, QuizResult
from services.ai_quiz_service import generate_and_save_quiz

quiz_bp = Blueprint('quiz_bp', __name__)

# Route 1: Trigger AI Generation & Store Question
@quiz_bp.route('/api/quiz/generate', methods=['POST'])
def generate_quiz():
    data = request.get_json() or {}
    topic = data.get('topic', 'Cybersecurity Awareness')
    difficulty = data.get('difficulty', 'beginner')
    language = session.get('language', 'en')

    try:
        quiz = generate_and_save_quiz(topic, difficulty, language)
        return jsonify({
            "success": True,
            "quiz_id": quiz.quiz_id,
            "question": quiz.question_text,
            "options": {
                "A": quiz.option_a,
                "B": quiz.option_b,
                "C": quiz.option_c,
                "D": quiz.option_d
            }
        }), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# Route 2: Submit Chosen Answer & Store Attempt Result
@quiz_bp.route('/api/quiz/submit', methods=['POST'])
def submit_answer():
    data = request.get_json() or {}
    quiz_id = data.get('quiz_id')
    user_answer = data.get('answer', '').upper()
    user_id = session.get('user_id', 1)  # Defaults to user 1 for development testing

    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return jsonify({"success": False, "message": "Quiz record not found"}), 404

    # Evaluate if user chosen answer matches the stored correct option
    is_correct = (user_answer == quiz.correct_option)

    # Save student execution result into Quiz_Results table
    result = QuizResult(
        user_id=user_id,
        quiz_id=quiz_id,
        user_answer=user_answer,
        is_correct=is_correct
    )
    db.session.add(result)
    db.session.commit()

    return jsonify({
        "success": True,
        "is_correct": is_correct,
        "submitted_answer": user_answer,
        "correct_option": quiz.correct_option
    }), 200


# Route 3: Load Full History (For UI Review Dashboard Later)
@quiz_bp.route('/api/quiz/history', methods=['GET'])
def get_quiz_history():
    user_id = session.get('user_id', 1)

    # Join Quiz_Results with Quizzes table
    history_records = db.session.query(QuizResult, Quiz)\
        .join(Quiz, QuizResult.quiz_id == Quiz.quiz_id)\
        .filter(QuizResult.user_id == user_id)\
        .order_by(QuizResult.attempted_at.desc()).all()

    output = []
    for result, quiz in history_records:
        output.append({
            "result_id": result.result_id,
            "quiz_id": quiz.quiz_id,
            "question": quiz.question_text,
            "option_a": quiz.option_a,
            "option_b": quiz.option_b,
            "option_c": quiz.option_c,
            "option_d": quiz.option_d,
            "correct_option": quiz.correct_option,
            "user_chosen_option": result.user_answer,
            "is_correct": result.is_correct,
            "attempted_at": result.attempted_at.strftime("%Y-%m-%d %H:%M:%S")
        })

    return jsonify({"success": True, "history": output}), 200