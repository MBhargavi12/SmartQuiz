import os
import json
import fitz
import pytesseract
from PIL import Image
import io
import google.generativeai as genai
from dotenv import load_dotenv
 
# IMPORTANT: Update this path to where you installed Tesseract-OCR on your PC
# (this is the default install location on Windows)
import platform
if platform.system() == 'Windows':
    import platform
    if platform.system() == 'Windows':
      pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
 
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer
from authlib.integrations.flask_client import OAuth
 
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
 
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-flash-lite-latest')
app.secret_key = os.getenv('SECRET_KEY', 'dev-fallback-key-change-me')
 
database_url = os.getenv('DATABASE_URL', 'sqlite:///smartquiz.db')
if database_url.startswith('postgres://'):
    database_url = database_url.replace('postgres://', 'postgresql://', 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
db = SQLAlchemy(app)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')
 
mail = Mail(app)
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)
serializer = URLSafeTimedSerializer(app.secret_key)
 
 
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
 
 
class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    question_text = db.Column(db.String(500), nullable=False)
    option_a = db.Column(db.String(200), nullable=False)
    option_b = db.Column(db.String(200), nullable=False)
    option_c = db.Column(db.String(200), nullable=False)
    option_d = db.Column(db.String(200), nullable=False)
    correct_option = db.Column(db.String(1), nullable=False)
 
 
import gc

def extract_text_from_pdf(pdf_path):
    pdf = fitz.open(pdf_path)

    text = ""
    for page in pdf:
        text += page.get_text()

    if not text.strip():
        text = ""
        # Limit OCR to first 3 pages only — free hosting has very limited RAM
        max_ocr_pages = 3
        for i, page in enumerate(pdf):
            if i >= max_ocr_pages:
                break

            # Lower DPI = much less memory used per page
            pix = page.get_pixmap(dpi=70)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes)).convert("L")  # grayscale, smaller in memory

            text += pytesseract.image_to_string(img)

            # Explicitly free memory before moving to next page
            img.close()
            pix = None
            del img_bytes
            gc.collect()

    pdf.close()
    return text
 
 
def parse_ai_json(raw_text):
    """Clean Gemini's response and parse it as JSON"""
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
    return json.loads(raw_text)
 
 
def get_explanations(review_items):
    """Ask Gemini to generate detailed explanations for a list of Q&A"""
    questions_summary = ""
    for i, item in enumerate(review_items):
        questions_summary += f"{i+1}. Question: {item['question']}\nCorrect Answer: {item['correct_text']}\n\n"
 
    prompt = f"""For each of the following questions and their correct answers, write a very short explanation
    (strictly under 40 words, max 4 short lines) that includes the key point and a simple example to remember it.
 
    {questions_summary}
 
    Return ONLY valid JSON in this exact format, no extra text, one entry per question in the same order:
    [
      {{"explanation": "short explanation here"}}
    ]"""
 
    try:
        response = model.generate_content(prompt)
        explanations = parse_ai_json(response.text)
 
        for i, item in enumerate(review_items):
            item['explanation'] = explanations[i].get('explanation', '') if i < len(explanations) else ''
 
    except Exception:
        for item in review_items:
            item['explanation'] = ''
 
    return review_items
 
 
@app.route("/")
def home():
    return render_template("index.html")
 
 
@app.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
 
        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['user_name'] = user.name
            return redirect(url_for('welcome'))
        else:
            flash("Invalid email or password. Please try again.")
            return redirect(url_for('login'))
 
    return render_template("login.html")
 
 
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
 
        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for('register'))
 
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("Email already registered. Please login instead.")
            return redirect(url_for('register'))
 
        hashed_password = generate_password_hash(password)
        new_user = User(name=name, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
 
        flash("Registration successful! Please login.")
        return redirect(url_for('login'))
 
    return render_template('register.html')
 
 
@app.route('/welcome')
def welcome():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('welcome.html', user_name=session['user_name'])
 
 
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
 
    return render_template('dashboard.html', user_name=session['user_name'])
 
 
@app.route('/quiz/<category>', methods=['GET', 'POST'])
def quiz(category):
    if 'user_id' not in session:
        return redirect(url_for('login'))
 
    questions = Question.query.filter_by(category=category).all()
 
    if request.method == 'POST':
        score = 0
        total = len(questions)
        review = []
 
        for q in questions:
            selected_option = request.form.get(f'q{q.id}')
            is_correct = selected_option == q.correct_option
            if is_correct:
                score += 1
 
            options = {'A': q.option_a, 'B': q.option_b, 'C': q.option_c, 'D': q.option_d}
 
            review.append({
                'question': q.question_text,
                'selected': selected_option,
                'selected_text': options.get(selected_option, 'Not answered'),
                'correct': q.correct_option,
                'correct_text': options.get(q.correct_option),
                'is_correct': is_correct
            })
 
        review = get_explanations(review)
 
        session['last_review'] = review
        session['last_score'] = score
        session['last_total'] = total
        session['last_category'] = category
 
        return render_template('result.html', score=score, total=total, category=category)
 
    return render_template('quiz.html', questions=questions, category=category)
 
 
@app.route('/ai-quiz', methods=['GET', 'POST'])
def ai_quiz():
    if 'user_id' not in session:
        return redirect(url_for('login'))
 
    if request.method == 'POST':
        topic = request.form['topic']
        num_questions = int(request.form.get('num_questions', 5))
        difficulty = request.form.get('difficulty', 'Medium')
 
        if num_questions > 100:
            num_questions = 100
 
        prompt = f"""Generate {num_questions} multiple choice questions on the topic "{topic}"
        at a {difficulty} difficulty level.
        For each question, also include a short explanation (under 40 words) covering the key point
        and a simple example to make it memorable.
        Return ONLY valid JSON in this exact format, no extra text:
        [
          {{
            "question": "question text",
            "option_a": "...",
            "option_b": "...",
            "option_c": "...",
            "option_d": "...",
            "correct_option": "A",
            "explanation": "short explanation here"
          }}
        ]"""
 
        try:
            response = model.generate_content(prompt)
            questions_data = parse_ai_json(response.text)
            return render_template('ai_quiz.html', questions=questions_data, topic=topic, difficulty=difficulty)
 
        except Exception as e:
            flash(f"Error generating quiz: {e}")
            return redirect(url_for('ai_quiz'))
 
    return render_template('ai_quiz_form.html')
 
 
@app.route('/pdf-quiz', methods=['POST'])
def pdf_quiz():
    if 'user_id' not in session:
        return redirect(url_for('login'))
 
    pdf_file = request.files.get('pdf_file')
    num_questions = int(request.form.get('num_questions', 5))
    difficulty = request.form.get('difficulty', 'Medium')
 
    if num_questions > 100:
        num_questions = 100
 
    if not pdf_file:
        flash("No file uploaded.")
        return redirect(url_for('ai_quiz'))
 
    filename = secure_filename(pdf_file.filename)
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    pdf_file.save(pdf_path)
    file_size = os.path.getsize(pdf_path)
    file_size = os.path.getsize(pdf_path)
    file_size = os.path.getsize(pdf_path)
    if file_size > 15 * 1024 * 1024:  # 15MB limit
        os.remove(pdf_path)
        flash("PDF is too large. Please upload a file under 15MB.")
        return redirect(url_for('ai_quiz'))
 
    pdf_text = extract_text_from_pdf(pdf_path)
 
    if not pdf_text.strip():
        flash("Couldn't read text from this PDF (it may be a scanned image).")
        return redirect(url_for('ai_quiz'))
 
    # Safety limit - avoid huge API calls
    pdf_text = pdf_text[:8000]
 
    prompt = f"""Based on the following study material, generate {num_questions} multiple choice questions
    at a {difficulty} difficulty level.
    For each question, also include a detailed explanation (4-6 sentences) covering:
    - A short Definition of the key concept
    - The Key Point that makes the correct answer right
    - A simple real-world Example to make it memorable
    Use \\n line breaks inside the explanation to separate Definition / Key Point / Example.
    Return ONLY valid JSON in this exact format, no extra text:
    [
      {{
        "question": "question text",
        "option_a": "...",
        "option_b": "...",
        "option_c": "...",
        "option_d": "...",
        "correct_option": "A",
        "explanation": "Definition: ...\\nKey Point: ...\\nExample: ..."
      }}
    ]
 
    Study Material:
    {pdf_text}
    """
 
    try:
        response = model.generate_content(prompt)
        questions_data = parse_ai_json(response.text)
        return render_template('ai_quiz.html', questions=questions_data, topic=pdf_file.filename, difficulty=difficulty)
 
    except Exception as e:
        flash(f"Error processing PDF: {e}")
        return redirect(url_for('ai_quiz'))
 
 
@app.route('/ai-quiz-submit', methods=['POST'])
def ai_quiz_submit():
    if 'user_id' not in session:
        return redirect(url_for('login'))
 
    topic = request.form['topic']
    questions_data = json.loads(request.form['questions_json'])
 
    score = 0
    total = len(questions_data)
    review = []
 
    for i, q in enumerate(questions_data):
        selected = request.form.get(f'q{i}')
        is_correct = selected == q['correct_option']
        if is_correct:
            score += 1
 
        options = {'A': q['option_a'], 'B': q['option_b'], 'C': q['option_c'], 'D': q['option_d']}
 
        review.append({
            'question': q['question'],
            'selected': selected,
            'selected_text': options.get(selected, 'Not answered'),
            'correct': q['correct_option'],
            'correct_text': options.get(q['correct_option']),
            'is_correct': is_correct,
            'explanation': q.get('explanation', '')
        })
 
    category = f"{topic} (AI)"
 
    session['last_review'] = review
    session['last_score'] = score
    session['last_total'] = total
    session['last_category'] = category
 
    return render_template('result.html', score=score, total=total, category=category)
 
 
@app.route('/review')
def review():
    if 'user_id' not in session:
        return redirect(url_for('login'))
 
    review_data = session.get('last_review')
    if not review_data:
        flash("No quiz review available.")
        return redirect(url_for('dashboard'))
 
    return render_template('review.html',
                            review=review_data,
                            category=session.get('last_category'),
                            score=session.get('last_score'),
                            total=session.get('last_total'))
 
 
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email']
        user = User.query.filter_by(email=email).first()
 
        if user:
            token = serializer.dumps(email, salt='password-reset')
            reset_url = url_for('reset_password', token=token, _external=True)
 
            msg = Message('SmartQuiz - Password Reset', recipients=[email])
            msg.body = f"Hi {user.name},\n\nClick the link below to reset your password:\n{reset_url}\n\nThis link expires in 30 minutes.\n\nIf you didn't request this, ignore this email."
 
            try:
                mail.send(msg)
                flash("Password reset link sent! Check your email.")
            except Exception as e:
                flash(f"Couldn't send email: {e}")
        else:
            flash("No account found with that email.")
 
        return redirect(url_for('forgot_password'))
 
    return render_template('forgot_password.html')
 
 
@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = serializer.loads(token, salt='password-reset', max_age=1800)
    except Exception:
        flash("This reset link has expired or is invalid.")
        return redirect(url_for('forgot_password'))
 
    if request.method == 'POST':
        new_password = request.form['password']
        confirm_password = request.form['confirm_password']
 
        if new_password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for('reset_password', token=token))
 
        user = User.query.filter_by(email=email).first()
        user.password = generate_password_hash(new_password)
        db.session.commit()
 
        flash("Password reset successful! Please login.")
        return redirect(url_for('login'))
 
    return render_template('reset_password.html', token=token)
 
 
@app.route('/google-login')
def google_login():
    redirect_uri = url_for('google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)
 
 
@app.route('/google-callback')
def google_callback():
    token = google.authorize_access_token()
    user_info = token.get('userinfo')
 
    if not user_info:
        flash("Google login failed. Please try again.")
        return redirect(url_for('login'))
 
    email = user_info['email']
    name = user_info.get('name', email.split('@')[0])
 
    user = User.query.filter_by(email=email).first()
 
    if not user:
        random_password = generate_password_hash(os.urandom(16).hex())
        user = User(name=name, email=email, password=random_password)
        db.session.add(user)
        db.session.commit()
 
    session['user_id'] = user.id
    session['user_name'] = user.name
    return redirect(url_for('welcome'))
 
 
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))
 
 
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)