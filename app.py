from datetime import date, datetime, timedelta
import json
import logging
import os
import random
import smtplib
import uuid
import time
import sqlite3  # You can remove this if no other part of your app uses raw sqlite
from werkzeug.security import check_password_hash
from flask_bcrypt import check_password_hash as bcrypt_check
from dotenv import load_dotenv
from webauthn import verify_authentication_response
from webauthn.helpers import options_to_json
from webauthn import generate_authentication_options
from webauthn.helpers.structs import PublicKeyCredentialDescriptor, UserVerificationRequirement # Import from structs!
from webauthn.helpers import options_to_json, base64url_to_bytes
from webauthn.helpers.bytes_to_base64url import bytes_to_base64url
from webauthn import generate_registration_options, verify_registration_response, options_to_json
from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from flask_bcrypt import check_password_hash, generate_password_hash
from groq import Groq
from email.message import EmailMessage
from models import db, Quiz, Question, QuizResult

# --- SINGLE CLEAN IMPORT FROM models.py ---
from models import (
    ChatbotMessage,
    ChatbotSession,
    CybersecurityTip,
    Quiz,
    QuizResult,
    User,
    UserReminder,
    bcrypt,
    db,
)
from translations import TRANSLATIONS


# Configure logging
logging.basicConfig(level=logging.INFO)

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get(
    'SECRET_KEY', 'your-secret-key-change-this'
)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'mysql+pymysql://root:@localhost/cybersecurity_db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize extensions
db.init_app(app)
bcrypt.init_app(app)

# Configure Groq Client
api_key = os.environ.get('GROQ_API_KEY')
if api_key:
    client = Groq(api_key=api_key)
else:
    client = None
    logging.warning('GROQ_API_KEY environment variable is missing!')

with app.app_context():
    db.create_all()


# Mock user class for session compatibility inside templates
class CurrentUser:
    def __init__(self, user_id=None, username=None):
        self.id = user_id
        self.username = username

    @property
    def is_authenticated(self):
        return self.id is not None


# Context processor: injects current_lang, t (translations), dir, font, and current_user into all Jinja2 templates
@app.context_processor
def inject_global_vars():
    # Priority: Query param ?lang= > session language > default ('en')
    req_lang = request.args.get('lang')
    if req_lang in TRANSLATIONS:
        session['language'] = req_lang

    current_lang = session.get('language', 'en')
    translation_data = TRANSLATIONS.get(current_lang, TRANSLATIONS.get('en', {}))
    current_user = CurrentUser(session.get('user_id'), session.get('username'))
    
    return {
        'current_lang': current_lang,
        'lang': current_lang,
        't': translation_data,
        'dir': translation_data.get('dir', 'ltr'),
        'font': translation_data.get('font', "'Open Sans', sans-serif"),
        'current_user': current_user
    }

def send_2fa_email(recipient_email, code):
    sender_email = "douaellahboukhari@gmail.com"        # Replace with your actual email
    sender_password = "sdcn gmjo hgxo wblz"  # Replace with your email's App Password
    
    msg = EmailMessage()
    msg.set_content(f"Hello,\n\nYour Two-Factor Authentication (2FA) verification code is: {code}\n\nThis code will expire shortly. Do not share it with anyone.")
    msg['Subject'] = "Your Cybersecurity App Verification Code"
    msg['From'] = sender_email
    msg['To'] = recipient_email

    try:
        # Connect to Gmail's SMTP server securely
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(sender_email, sender_password)
            smtp.send_message(msg)
        return True
    except Exception as e:
        print(f"Email sending failed: {e}")
        return False

# Language switcher endpoint
@app.route('/set_language/<lang_code>')
def set_language(lang_code):
    if lang_code in TRANSLATIONS:
        session['language'] = lang_code
        if 'user_id' in session:
            user = User.query.get(session['user_id'])
            if user:
                user.preferred_language = lang_code
                db.session.commit()
    return redirect(request.referrer or url_for('index'))

# --- MAIN LANDING & ROUTING ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_lang = session.get('language', 'en')   
    topic_dict = TRANSLATIONS.get(current_lang, TRANSLATIONS['en'])
    user = db.session.get(User, session['user_id'])
    
    all_user_results = QuizResult.query.filter_by(user_id=user.user_id).all()
    
    # 1. Group quiz results by session/batch
    quiz_sessions_map = {}
    for r in all_user_results:
        quiz_item = db.session.get(Quiz, r.quiz_id)
        if quiz_item:
            batch_key = quiz_item.generated_at
            if batch_key not in quiz_sessions_map:
                quiz_sessions_map[batch_key] = {
                    'topic': quiz_item.topic or 'Password Safety',
                    'level': quiz_item.difficulty_level or 'easy',
                    'timestamp': quiz_item.generated_at,
                    'total': 0,
                    'correct': 0
                }
            quiz_sessions_map[batch_key]['total'] += 1
            if r.is_correct == 1 or r.is_correct is True:
                quiz_sessions_map[batch_key]['correct'] += 1

    total_quizzes_done = len(quiz_sessions_map)

    # 2. Consecutive Day Streak Calculation
    streak = 0
    if all_user_results:
        active_dates = sorted(list(set(q.attempted_at.date() for q in all_user_results if q.attempted_at)), reverse=True)
        if active_dates:
            today = date.today()
            if active_dates[0] == today or active_dates[0] == today - timedelta(days=1):
                expected_date = active_dates[0]
                for active_date in active_dates:
                    if active_date == expected_date:
                        streak += 1
                        expected_date -= timedelta(days=1)
                    else:
                        break

    user.day_streak = streak

    # 3. Working Session-Matching Logic Expanded for All 4 Levels & Retakes
    standard_topics = ['Password Safety', 'Phishing Awareness', 'Online Privacy', 'Social Engineering', 'Safe Browsing']
    levels = ['easy', 'medium', 'intermediate', 'hard']

    topics_list = []
    topics_mastered_count = 0
    in_progress_count = 0

    for name in standard_topics:
        matching_sessions = [
            s for s in quiz_sessions_map.values() 
            if name.lower() in s['topic'].lower() or s['topic'].lower() in name.lower()
        ]
        
        # Track best score per level for this topic (handles retakes/improving scores)
        level_best_scores = {lvl: 0 for lvl in levels}
        
        for s in matching_sessions:
            if s['total'] > 0:
                pct = int((s['correct'] / s['total']) * 100)
                s_level = (s.get('level') or 'easy').lower()
                
                # Match session level to one of the 4 standard levels
                matched_lvl = 'easy'
                for lvl in levels:
                    if lvl in s_level:
                        matched_lvl = lvl
                        break
                        
                if pct > level_best_scores[matched_lvl]:
                    level_best_scores[matched_lvl] = pct

        # Sum percentages of all 4 levels and strictly divide by 4
        level_percentages = [level_best_scores[lvl] for lvl in levels]
        progress = int(sum(level_percentages) / 4)
        
        if progress > 100:
            progress = 100

        if progress >= 80:
            status = 'mastered'
            topics_mastered_count += 1
        elif 0 < progress < 80:
            status = 'needs_practice'
            in_progress_count += 1
        else:
            status = 'not_started'
            
        localized_topic_name = topic_dict.get(name, name)
        topics_list.append({
            'name': localized_topic_name,
            'progress': progress,
            'status': status
        })

    # Calculate overall level percentage based on topic progress
    if topics_list:
        total_topic_progress = sum(t['progress'] for t in topics_list)
        overall_level = int(total_topic_progress / len(topics_list))
    else:
        overall_level = 0
            
    if overall_level > 100:
        overall_level = 100

    user.overall_level = overall_level
    user.quizzes_done = total_quizzes_done
    user.topics_mastered = topics_mastered_count
    user.in_progress = in_progress_count
    user.topics = topics_list

    # 4. Quiz History List
    raw_history = sorted(
        list(quiz_sessions_map.values()),
        key=lambda x: x['timestamp'] if x['timestamp'] else datetime.min,
        reverse=True
    )[:5]

    quiz_history = []
    for h in raw_history:
        score_pct = int((h['correct'] / h['total']) * 100) if h['total'] > 0 else 0
        base_topic = h['topic']
        localized_h_topic = topic_dict.get(base_topic, base_topic)
        quiz_history.append({
            'topic': localized_h_topic,
            'correct': h['correct'],
            'total': h['total'],
            'score_percentage': score_pct,
            'timestamp': h['timestamp']
        })

    # 5. Chatbot Activities Integration
    recent_chats = []
    try:
        user_sessions = ChatbotSession.query.filter_by(user_id=user.user_id).all()
        session_ids = [s.session_id for s in user_sessions]
        if session_ids:
            recent_chats = ChatbotMessage.query.filter(ChatbotMessage.session_id.in_(session_ids))\
                                        .order_by(ChatbotMessage.timestamp.desc())\
                                        .limit(5).all()
    except Exception:
        pass

    score_label = "Score :" if current_lang == 'fr' else ("النتيجة:" if current_lang == 'ar' else "Score:")
    activities = []
    for qh in quiz_history:
        activities.append({
            'title': qh['topic'],
            'subtitle': f"{score_label} {qh['correct']}/{qh['total']} ({qh['score_percentage']}%)",
            'timestamp': qh['timestamp'],
            'badge': 'QUIZ',
            'is_success': qh['score_percentage'] >= 80
        })
        
    for cm in recent_chats:
        msg_preview = cm.message_text[:45] + ('...' if len(cm.message_text) > 45 else '')
        activities.append({
            'title': f"Chatbot Session ({cm.sender.capitalize()})",
            'subtitle': msg_preview,
            'timestamp': cm.timestamp,
            'badge': 'CHAT',
            'is_success': True
        })

    activities.sort(key=lambda x: x['timestamp'] if x['timestamp'] else datetime.min, reverse=True)
    recent_activities = activities[:5]

    # 6. Fetch Cybersecurity Tips from Database
    tips_list = db.session.scalars(db.select(CybersecurityTip).filter_by(language=current_lang)).all()

    return render_template(
        'dashboard.html',
        user=user,
        recent_activities=recent_activities,
        quiz_history=quiz_history,
        tips=tips_list,
        current_lang=current_lang,
        TRANSLATIONS=TRANSLATIONS
    )

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    # Assuming you store the logged-in user's ID or username in a session
    # Replace 'User' and query logic with whatever ORM/database model you are using (e.g., SQLAlchemy, SQLite, MongoDB)
    user_id = session.get('user_id') 
    user = User.query.get(user_id) # Example using Flask-SQLAlchemy

    if request.method == 'POST':
        # Get data submitted from the form
        new_name = request.form.get('name')
        new_email = request.form.get('email')

        # Update database fields
        user.name = new_name
        user.email = new_email
        
        # Commit changes to your database
        db.session.commit() # Change this to match your database saving method

        flash('Changes saved successfully!', 'success')

        return redirect(url_for('settings'))

    return render_template('settings.html', user=user)

@app.route('/settings/security', methods=['GET', 'POST'])
def security_settings():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    user = User.query.get(session['user_id'])

    if request.method == 'POST':
        # Check if the user is submitting password change or 2FA toggle
        action = request.form.get('action')

        if action == 'change_password':
            current_pass = request.form.get('current_password')
            new_pass = request.get_form('new_password') if hasattr(request, 'get_form') else request.form.get('new_password')
            confirm_pass = request.form.get('confirm_password')

            if not check_password_hash(user.password_hash, current_pass):
                flash('Current password is incorrect.', 'danger')
            elif new_pass != confirm_pass:
                flash('New passwords do not match.', 'danger')
            else:
                user.password_hash = generate_password_hash(new_pass)
                db.session.commit()
                flash('Password updated successfully!', 'success')

        elif action == 'toggle_2fa':
            # Checkbox value handling
            user.is_2fa_enabled = True if request.form.get('enable_2fa') == 'on' else False
            db.session.commit()
            status = "enabled" if user.is_2fa_enabled else "disabled"
            flash(f'Two-Factor Authentication has been {status}.', 'success')

        return redirect(url_for('security_settings'))

    return render_template('security_settings.html', user=user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        authenticated = False
        if user:
            try:
                # Try checking with Bcrypt first
                authenticated = bcrypt_check(user.password_hash, password)
            except ValueError:
                try:
                    # Fallback to Werkzeug (scrypt/pbkdf2 format)
                    authenticated = werkzeug_check(user.password_hash, password)
                except Exception:
                    authenticated = False
        
        if user and authenticated:
            if user.is_2fa_enabled:
                code = str(random.randint(100000, 999999))
                session['temp_2fa_user_id'] = user.user_id
                session['expected_2fa_code'] = code
                
                email_sent = send_2fa_email(user.email, code)
                
                if email_sent:
                    flash(f'Verification code has been sent to {user.email}', 'success')
                else:
                    flash('Failed to send email. Please check server logs.', 'danger')
                    
                return redirect(url_for('verify_2fa'))
            
            session['user_id'] = user.user_id
            session['user_name'] = user.name
            flash('Logged in successfully!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid email or password.', 'danger')
            
    return render_template('login.html')


@app.route('/login-biometric', methods=['POST'])
def login_biometric():
    data = request.get_json()
    email = data.get('email')
    credential_data = data.get('credential')

    if not email or not credential_data:
        return jsonify({'success': False, 'message': 'Missing email or credential data'}), 400

    # 1. Fetch the user from the database by email
    user = User.query.filter_by(email=email).first()
    if not user or not user.biometric_public_key:
        return jsonify({'success': False, 'message': 'User not found or biometrics not configured'}), 404

    try:
        # 2. Verify the authentication response
        verification = verify_authentication_response(
            credential=credential_data,
            expected_challenge=session.get('biometric_login_challenge'),
            expected_rp_id=request.host.split(':')[0],
            expected_origin=f"http://{request.host}",
            credential_public_key=user.biometric_public_key,
            credential_current_sign_count=user.biometric_sign_count
        )
        
        # 3. Update sign count to prevent replay attacks
        user.biometric_sign_count = verification.new_sign_count
        db.session.commit()

        # 4. Log user in by setting the session
        session['user_id'] = user.user_id
        session['user_name'] = user.name
        session['language'] = user.preferred_language

        return jsonify({'success': True, 'redirect': url_for('index')})

    except Exception as e:
        print(f"Biometric auth error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 400

@app.route('/login-biometric-options', methods=['POST'])
def login_biometric_options():
    try:
        data = request.get_json()
        email = data.get('email')
        
        if not email:
            return jsonify({'success': False, 'message': 'Email is required'}), 400
            
        user = User.query.filter_by(email=email).first()
        if not user or not user.biometric_credential_id:
            return jsonify({'success': False, 'message': 'User not found or biometrics not configured'}), 404

        cred_id = user.biometric_credential_id
        if isinstance(cred_id, str):
            cred_id = base64url_to_bytes(cred_id)

        # Generate options using the proper Enum for user_verification
        options = generate_authentication_options(
            rp_id=request.host.split(':')[0],
            allow_credentials=[
                PublicKeyCredentialDescriptor(id=cred_id)
            ],
            user_verification=UserVerificationRequirement.REQUIRED
        )
        
        # Store challenge in session
        session['biometric_login_challenge'] = options.challenge
        
        return options_to_json(options), 200, {'Content-Type': 'application/json'}
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)}), 500
    
@app.route('/verify-2fa', methods=['GET', 'POST'])
def verify_2fa():
    if 'temp_2fa_user_id' not in session:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        entered_code = request.form.get('code')
        expected_code = session.get('expected_2fa_code')
        
        if entered_code == expected_code:
            # 2FA passed! Log the user in fully
            user_id = session.pop('temp_2fa_user_id')
            session.pop('expected_2fa_code', None)
            
            user = User.query.get(user_id)
            session['user_id'] = user.user_id
            session['user_name'] = user.name
            
            flash('Two-factor authentication successful!', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid verification code. Please try again.', 'danger')
            
    return render_template('verify_2fa.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()  
        email = request.form.get('email')
        password = request.form.get('password')
        language = request.form.get('language', session.get('language', 'en'))
        biometric_cred_json = request.form.get('biometric_credential')

        # Check if email already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email already exists!', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)
        
        # Create new user mapping directly to your table columns
        new_user = User(
            name=name, 
            email=email, 
            password_hash=hashed_password, 
            preferred_language=language
        )
        
        # Verify and attach biometric credentials if provided during signup
        if biometric_cred_json and 'biometric_reg_challenge' in session:
            try:
                cred_data = json.loads(biometric_cred_json)
                
                # NOTE: Parameter must be 'credential=', not 'query='
                verification = verify_registration_response(
                    credential=cred_data,
                    expected_challenge=session.get('biometric_reg_challenge'),
                    expected_rp_id=request.host.split(':')[0],
                    expected_origin=f"http://{request.host}"
                )
                
                new_user.biometric_credential_id = verification.credential_id
                new_user.biometric_public_key = verification.credential_public_key
                new_user.biometric_sign_count = verification.sign_count
                print("Biometric credential successfully verified and mapped!")
                
            except Exception as e:
                print(f"CRITICAL Biometric registration error: {e}")
        else:
            print("No biometric credential JSON or challenge found in session.")
        
        db.session.add(new_user)
        db.session.commit() # Commit first to generate new_user.user_id

        # Define specific priorities and types for each tip_id
        tip_metadata = {
            1: {"type": "Password", "priority": "High"},
            2: {"type": "Authentication", "priority": "Medium"},
            3: {"type": "Security", "priority": "Medium"},
            4: {"type": "Updates", "priority": "High"},
            5: {"type": "Backup", "priority": "Low"}
        }

        # Fetch all tips across all languages from the cybersecurity_tips table
        all_tips = CybersecurityTip.query.all()

        # Seed user_reminders using tips text + your reminder metadata across all languages
        for tip in all_tips:
            meta = tip_metadata.get(tip.tip_id, {"type": "Security", "priority": "Medium"})
            
            default_rem = UserReminder(
                user_id=new_user.user_id,  
                tip_id=tip.tip_id,
                language=tip.language,    # Pulls language directly from the tip row (en, fr, ar)
                title=tip.title,           # Pulls localized title from cybersecurity_tips
                description=tip.content,   # Pulls localized content from cybersecurity_tips
                type=meta["type"],         # Assigned from metadata
                priority=meta["priority"], # Assigned from metadata
                is_completed=False,
                next_due_date=datetime.utcnow().date() + timedelta(days=30),
            )
            db.session.add(default_rem)
        db.session.commit()

        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/register-biometric-options', methods=['POST'])
def register_biometric_options():
    data = request.get_json() or {}
    email = data.get('email')
    name = data.get('name')
    
    if not email or not name:
        return jsonify({'success': False, 'message': 'Name and email are required first.'}), 400
        
    # Dynamically grab the host from the request header (e.g., "127.0.0.1:5000" or "localhost:5000")
    host = request.host.split(':')[0]
    
    options = generate_registration_options(
        rp_id=host,  # This will now perfectly match "127.0.0.1" or "localhost" automatically!
        rp_name="CyberLearn",
        user_id=email.encode('utf-8'),
        user_name=email,
        user_display_name=name
    )
    
    session['biometric_reg_challenge'] = options.challenge
    return options_to_json(options), 200, {'ContentType': 'application/json'}


@app.route('/register-biometric-finish', methods=['POST'])
def register_biometric_finish():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    user = User.query.get(session['user_id'])
    data = request.get_json()
    
    try:
        verification = verify_registration_response(
            query=data.get('credential'),
            expected_challenge=session.get('biometric_reg_challenge'),
            expected_rp_id="localhost",  # Change to your domain in production
            expected_origin="http://localhost:5000"  # Change to your domain in production
        )
        
        # Save credential details to the user record
        user.biometric_credential_id = verification.credential_id
        user.biometric_public_key = verification.credential_public_key
        user.biometric_sign_count = verification.sign_count
        db.session.commit()
        
        return jsonify({'success': True, 'message': 'Biometric passkey registered successfully!'})
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/chat')
def chat():
    return render_template('chat.html')

@app.route('/api/chat', methods=['POST'])
def api_chat():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized. Please log in.'}), 401

    if not client:
        return jsonify({'error': 'Groq API client is not configured.'}), 500

    data = request.get_json() or {}
    user_message = data.get('message', '').strip()
    
    if not user_message:
        return jsonify({'error': 'Message content cannot be empty.'}), 400

    user_id = session['user_id']
    user_lang = session.get('language', 'en')

    # 1. Get or create an active chatbot session for this user
    active_session = ChatbotSession.query.filter_by(user_id=user_id).order_by(ChatbotSession.started_at.desc()).first()
    
    if not active_session:
        active_session = ChatbotSession(user_id=user_id, started_at=datetime.utcnow())
        db.session.add(active_session)
        db.session.commit()

    # 2. Save the User's message into chatbot_messages
    user_msg_record = ChatbotMessage(
        session_id=active_session.session_id,
        sender='user',
        message_text=user_message,
        language_used=user_lang,
        timestamp=datetime.utcnow()
    )
    db.session.add(user_msg_record)
    db.session.commit()

    system_instruction = (
        f"You are an expert Cybersecurity Virtual Assistant and Educational Tutor. "
        f"Your goal is to explain cybersecurity concepts (phishing, malware, password safety, network defense) clearly. "
        f"Respond strictly in the user's selected language code: '{user_lang.upper()}'. "
        f"If asked about non-cybersecurity topics, politely steer the conversation back to cybersecurity."
    )

    try:
        # 3. Generate response from Groq (Llama 3.3 Versatile)
        completion = client.chat.completions.create(
            model="openai/gpt-oss-20b",  # <--- Active Groq production model ID
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_message}  # <--- Fixed variable name here
            ],
            temperature=0.3,
            max_tokens=1024
        )
        bot_reply_text = completion.choices[0].message.content

        # 4. Save the Assistant's reply into chatbot_messages
        bot_msg_record = ChatbotMessage(
            session_id=active_session.session_id,
            sender='bot',
            message_text=bot_reply_text,
            language_used=user_lang,
            timestamp=datetime.utcnow()
        )
        db.session.add(bot_msg_record)
        db.session.commit()

        return jsonify({
            'response': bot_reply_text,
            'session_id': active_session.session_id
        })

    except Exception as e:
        db.session.rollback()
        logging.error(f"Chat API Error: {e}")
        return jsonify({'error': 'Failed to process chat response. Please try again.'}), 500

# --- AI QUIZ ENGINE ROUTES ---

@app.route('/quiz')
def quiz():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_id = session['user_id']
    
    # Fetch all user quiz results from the database
    all_user_results = QuizResult.query.filter_by(user_id=user_id).all()
    
    # 1. Group quiz results by session/batch
    quiz_sessions_map = {}
    for r in all_user_results:
        quiz_item = Quiz.query.get(r.quiz_id)
        if quiz_item:
            batch_key = quiz_item.generated_at
            if batch_key not in quiz_sessions_map:
                quiz_sessions_map[batch_key] = {
                    'topic': quiz_item.topic or 'Password Safety',
                    'level': quiz_item.difficulty_level or 'easy',
                    'timestamp': quiz_item.generated_at,
                    'total': 0,
                    'correct': 0
                }
            quiz_sessions_map[batch_key]['total'] += 1
            if r.is_correct == 1 or r.is_correct is True:
                quiz_sessions_map[batch_key]['correct'] += 1

    # 2. 4-Level Strict Averaged Progress Calculations
    standard_topics = ['Password Safety', 'Phishing Awareness', 'Online Privacy', 'Social Engineering', 'Safe Browsing']
    levels = ['easy', 'medium', 'intermediate', 'hard']
    topics_list = []
    
    for name in standard_topics:
        matching_sessions = [
            s for s in quiz_sessions_map.values() 
            if name.lower() in s['topic'].lower() or s['topic'].lower() in name.lower()
        ]
        
        # Track best score per level for this topic (supports retakes)
        level_best_scores = {lvl: 0 for lvl in levels}
        
        for s in matching_sessions:
            if s['total'] > 0:
                pct = int((s['correct'] / s['total']) * 100)
                s_level = (s.get('level') or 'easy').lower()
                
                matched_lvl = 'easy'
                for lvl in levels:
                    if lvl in s_level:
                        matched_lvl = lvl
                        break
                        
                if pct > level_best_scores[matched_lvl]:
                    level_best_scores[matched_lvl] = pct

        # Sum percentages of all 4 levels and strictly divide by 4
        level_percentages = [level_best_scores[lvl] for lvl in levels]
        progress = int(sum(level_percentages) / 4)
        
        if progress > 100:
            progress = 100
            
        if progress >= 80:
            status = 'mastered'
        elif 0 < progress < 80:
            status = 'needs_practice'
        else:
            status = 'not_started'
            
        topics_list.append({
            'name': name,
            'progress': progress,
            'status': status
        })

    return render_template('quiz.html', topics_list=topics_list)

@app.route('/questions')
def questions():
    topic = request.args.get('topic') or 'Cybersecurity Fundamentals'
    difficulty = request.args.get('difficulty') or 'easy'
    
    user_lang = session.get('language', 'en')
    
    print(f"DEBUG -> Loaded Topic: {topic}, Difficulty: {difficulty}, Language: {user_lang}")
    
    # Check if questions already exist in the database for this specific topic and difficulty
    existing_questions = Quiz.query.filter_by(topic=topic, difficulty_level=difficulty).all()
    
    return render_template(
        'questions.html', 
        topic=topic, 
        difficulty=difficulty, 
        questions=existing_questions,
        user_lang=user_lang,
        TRANSLATIONS=TRANSLATIONS
    )

@app.route('/api/quiz/generate_session', methods=['POST'])
def generate_quiz_session():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    if not client:
        return jsonify({'error': 'Groq API client is not configured.'}), 500

    data = request.get_json(silent=True) or request.form or request.args
    
    topic = data.get('topic') or 'Cybersecurity Fundamentals'
    difficulty = data.get('difficulty') or 'easy'
    
    print(f"DEBUG -> Active Topic: {topic}, Difficulty: {difficulty}")
    user_lang = session.get('language', 'en')

    quiz_session_id = str(uuid.uuid4())

    prompt = f"""
    You are an advanced cybersecurity examination system.
    Generate a JSON array of EXACTLY 10 multiple-choice quiz questions based on the topic: '{topic}' and difficulty level: '{difficulty}'.
    Respond strictly in language code: '{user_lang}'.

    Return ONLY a valid raw JSON array matching this schema:
    [
        {{
            "question_text": "Question here",
            "option_a": "First choice",
            "option_b": "Second choice",
            "option_c": "Third choice",
            "option_d": "Fourth choice",
            "correct_option": "A",
            "explanation": "Short explanation why the answer is correct."
        }}
    ]
    """

    response_text = None
    max_retries = 2
    retry_delay = 1

    for attempt in range(max_retries):
        try:
            completion = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=[
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2048
            )
            response_text = completion.choices[0].message.content
            if response_text:
                break
        except Exception as e:
            logging.warning(f"Groq API attempt {attempt + 1} failed: {e}")
            time.sleep(retry_delay)

    if not response_text:
        return jsonify({
            "success": False, 
            "error": "API Error: Groq service is currently unavailable."
        }), 503

    try:
        clean_text = response_text.strip().removeprefix("```json").removesuffix("```").strip()
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3].strip()
        
        questions_list = json.loads(clean_text)

        # 1. Create the parent Quiz container first
        new_quiz_session = Quiz(
            topic=topic,
            difficulty_level=difficulty,
            language=user_lang
        )
        db.session.add(new_quiz_session)
        db.session.flush() # This populates new_quiz_session.quiz_id

        formatted_questions = []
        for q_data in questions_list:
            # 2. Create individual Question records linked to the parent Quiz
            new_question = Question(
                quiz_id=new_quiz_session.quiz_id,
                question_text=q_data['question_text'],
                option_a=q_data['option_a'],
                option_b=q_data['option_b'],
                option_c=q_data['option_c'],
                option_d=q_data['option_d'],
                correct_option=str(q_data['correct_option']).strip().upper(),
                explanation=q_data.get('explanation', 'No explanation provided.')
            )
            db.session.add(new_question)
            db.session.flush()

            formatted_questions.append({
                "quiz_id": new_question.question_id,  # or new_question.question_id depending on frontend
                "question_text": new_question.question_text,
                "option_a": new_question.option_a,
                "option_b": new_question.option_b,
                "option_c": new_question.option_c,
                "option_d": new_question.option_d,
                "correct_option": new_question.correct_option,
                "explanation": new_question.explanation
            })

        db.session.commit()

        return jsonify({
            "success": True,
            "session_id": quiz_session_id,
            "questions": formatted_questions
        }), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"JSON Parsing or DB Save Error: {e}")
        return jsonify({"success": False, "error": "Failed to parse generated questions. Please try again."}), 500
    
@app.route('/api/quiz/<int:quiz_id>', methods=['GET'])
def get_quiz_question(quiz_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    quiz = Quiz.query.get(quiz_id)
    if not quiz:
        return jsonify({'success': False, 'message': 'Question not found'}), 404

    return jsonify({
        "success": True,
        "quiz_id": quiz.quiz_id,
        "difficulty_level": quiz.difficulty_level,
        "question": quiz.question_text,
        "options": {
            "A": quiz.option_a,
            "B": quiz.option_b,
            "C": quiz.option_c,
            "D": quiz.option_d
        }
    }), 200

@app.route('/api/quiz/submit', methods=['POST'])
def submit_quiz_answer():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json() or {}
    user_id = session.get('user_id')
    
    # The frontend passes the question's ID (often labeled quiz_id or question_id)
    q_id = data.get('quiz_id') or data.get('question_id')
    
    # Fetch the question to get its parent quiz_id and question_id
    question = Question.query.get(q_id)
    if not question:
        return jsonify({'success': False, 'error': 'Question not found'}), 404

    try:
        new_result = QuizResult(
            user_id=user_id,
            session_id=data.get('session_id'),
            quiz_id=question.quiz_id,         # Parent quiz container ID
            question_id=question.question_id, # Specific question ID
            user_answer=data.get('answer'),
            is_correct=data.get('is_correct')
        )
        db.session.add(new_result)
        db.session.commit()
        return jsonify({'success': True}), 200
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error saving quiz result: {e}")
        return jsonify({'success': False, 'error': 'Failed to save answer'}), 500

@app.route('/api/quiz/session_results', methods=['GET'])
def get_quiz_session_results():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    session_id = request.args.get('session_id')
    user_id = session.get('user_id')

    user_results = QuizResult.query.filter_by(user_id=user_id, session_id=session_id).all()

    if not user_results:
        return jsonify({'success': False, 'error': 'Session results not found'}), 404

    total_questions = len(user_results)
    correct_count = sum(1 for r in user_results if r.is_correct)
    score_percentage = int((correct_count / total_questions) * 100) if total_questions > 0 else 0

    formatted_results = []
    for r in user_results:
        # Fetch from the Question table using question_id
        question_item = Question.query.get(r.question_id) if r.question_id else Question.query.filter_by(quiz_id=r.quiz_id).first()
        if question_item:
            formatted_results.append({
                "question": question_item.question_text,
                "correct_option": question_item.correct_option,
                "user_chosen_option": r.user_answer,
                "is_correct": r.is_correct
            })

    return jsonify({
        "success": True,
        "total_questions": total_questions,
        "correct_count": correct_count,
        "score_percentage": score_percentage,
        "results": formatted_results
    }), 200

@app.route('/select-topic')  # Replace with your actual route path
def select_topic():
    # 1. MAKE SURE YOU FETCH THE USER'S SESSIONS FROM THE DB FIRST:
    # (Adjust this query to match how your app fetches quiz results/sessions)
    user_sessions = QuizSession.query.filter_by(user_id=current_user.id).all() # or session.get(...)
    
    # Map them so the loop can read them
    quiz_sessions_map = {s.id: {'topic': s.topic, 'correct': s.correct_answers, 'total': s.total_questions} for s in user_sessions}
    
    # 2. THEN RUN THE STANDARD TOPICS CALCULATION:
    standard_topics = ['Password Safety', 'Phishing Awareness', 'Online Privacy', 'Social Engineering', 'Safe Browsing']
    topics_list = []
    
    for name in standard_topics:
        matching_sessions = [
            s for s in quiz_sessions_map.values() 
            if name.lower() in s['topic'].lower() or s['topic'].lower() in name.lower()
        ]
        
        if not matching_sessions:
            progress = 0
        else:
            topic_percentages = [int((s['correct'] / s['total']) * 100) for s in matching_sessions if s['total'] > 0]
            progress = int(sum(topic_percentages) / len(topic_percentages)) if topic_percentages else 0
            if progress > 100:
                progress = 100
                
        if progress >= 80:
            status = 'mastered'
        elif 0 < progress < 80:
            status = 'needs_practice'
        else:
            status = 'not_started'
            
        topics_list.append({
            'name': name,
            'progress': progress,
            'status': status
        })
        
    # Quick debug print to verify in your terminal:
    print("DEBUG TOPICS LIST:", topics_list)

    # 3. PASS IT TO THE TEMPLATE:
    return render_template('your_template_name.html', topics_list=topics_list)


@app.route("/reminders")
def reminders():
  if "user_id" not in session:
    return redirect(url_for("login"))

  user_id = session["user_id"]
  current_lang = session.get("language", "en")
  t = TRANSLATIONS.get(current_lang, TRANSLATIONS.get("en", {}))

  # Fetch active reminders for the logged-in user
  active_reminders = UserReminder.query.filter_by(
      user_id=user_id, is_completed=False, language=current_lang
  ).all()

  # Count statistics for dashboard cards
  completed_count = UserReminder.query.filter_by(
      user_id=user_id, is_completed=True, language=current_lang
  ).count()
  high_priority_count = UserReminder.query.filter_by(
      user_id=user_id, is_completed=False, priority="High", language=current_lang
  ).count()

  return render_template(
      "reminders.html",
      active_reminders=active_reminders,
      completed_count=completed_count,
      high_priority_count=high_priority_count,
      current_lang=current_lang,
      t=t,
  )


@app.route("/api/reminders", methods=["POST"])
def add_reminder_api():
  if "user_id" not in session:
    return jsonify({"error": "Unauthorized"}), 401

  data = request.json
  user_id = session["user_id"]
  current_lang = session.get("language", "en")  # Get active language

  try:
    new_rem = UserReminder(
        user_id=user_id,
        tip_id=None,  # NULL for manual custom reminders
        language=current_lang,  # Save with the current active language!
        title=data.get("title"),
        description=data.get("description"),
        type=data.get("type"),
        priority=data.get("priority"),
        next_due_date=datetime.strptime(
            data.get("due_date"), "%Y-%m-%d"
        ).date(),
        is_completed=False,
    )
    db.session.add(new_rem)
    db.session.commit()
    return jsonify({"success": True})
  except Exception as e:
    return jsonify({"success": False, "error": str(e)}), 400


@app.route("/api/reminders/<int:reminder_id>/complete", methods=["POST"])
def complete_reminder_api(reminder_id):
  if "user_id" not in session:
    return jsonify({"error": "Unauthorized"}), 401

  reminder = UserReminder.query.get_or_404(reminder_id)
  if reminder.user_id != session["user_id"]:
    return jsonify({"error": "Forbidden"}), 403

  reminder.is_completed = True
  reminder.completed_at = datetime.utcnow()
  db.session.commit()
  return jsonify({"success": True})


@app.route("/api/reminders/<int:reminder_id>", methods=["DELETE"])
def delete_reminder_api(reminder_id):
  if "user_id" not in session:
    return jsonify({"error": "Unauthorized"}), 401

  reminder = UserReminder.query.get_or_404(reminder_id)
  if reminder.user_id != session["user_id"]:
    return jsonify({"error": "Forbidden"}), 403

  db.session.delete(reminder)
  db.session.commit()
  return jsonify({"success": True})

@app.route('/logout')
def logout():
    # Clear the session variables
    session.clear()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('index')) # Adjust 'login' if your login route function is named differently (e.g., 'signin')

# 👇 ADD THESE TWO LINES AT THE VERY BOTTOM 👇
if __name__ == '__main__':
    app.run(debug=True)