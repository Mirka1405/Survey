from flask import Flask, render_template, request, redirect, url_for, flash, session, json
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import os
from datetime import datetime
import base64
from io import BytesIO
import json
app = Flask(__name__)
import config
app.secret_key = config.SECRET_KEY
users = None
# Load survey configuration
def load_config():
    with open('admins.json',"r") as f:
        global users
        users = {k:generate_password_hash(v) for k,v in json.load(f).items()}
    with open('config/survey_config.json', 'r', encoding='utf-8') as f:
        return json.load(f)
auth = HTTPBasicAuth()
CONFIG = load_config()

@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username

# Database setup
def init_db():
    conn = sqlite3.connect('survey.db')
    c = conn.cursor()
    
    # Create main responses table
    c.execute('''CREATE TABLE IF NOT EXISTS responses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  role TEXT,
                  respondent_name TEXT,
                  member_cost REAL,
                  member_amnt INTEGER,
                  team_id INTEGER)''')
    
    # Create table for rating questions
    c.execute('''CREATE TABLE IF NOT EXISTS ratings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  response_id INTEGER,
                  role TEXT,
                  category TEXT,
                  question TEXT,
                  rating INTEGER,
                  FOREIGN KEY (response_id) REFERENCES responses (id))''')
    
    # Create table for open questions
    c.execute('''CREATE TABLE IF NOT EXISTS open_answers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  response_id INTEGER,
                  question TEXT,
                  answer TEXT,
                  FOREIGN KEY (response_id) REFERENCES responses (id))''')
    
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect('survey.db')
    conn.row_factory = sqlite3.Row
    return conn

def generate_spider_chart(values, categories, title):
    """Generate a spider/radar chart"""
    # Number of variables
    N = len(categories)
    
    # Compute angle for each axis
    angles = [n / float(N) * 2 * np.pi for n in range(N)]
    angles += angles[:1]  # Complete the loop
    
    # Values should be between 0-10
    values = list(values) + values[:1]  # Complete the loop
    
    # Initialize the spider plot
    fig, ax = plt.subplots(figsize=(8, 8), subplot_kw=dict(projection='polar'))
    
    # Draw one line per variable and fill area
    ax.plot(angles, values, 'o-', linewidth=2, color='blue')
    ax.fill(angles, values, alpha=0.25, color='blue')
    
    # Set category labels
    category_labels = [CONFIG['categories'].get(cat, cat) for cat in categories]
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(category_labels, size=10)
    
    # Set y-axis limits
    ax.set_ylim(0, 10)
    ax.set_yticks(range(0, 11, 2))
    ax.set_yticklabels(map(str, range(0, 11, 2)), size=8)
    ax.grid(True)
    
    # Add title
    plt.title(title, size=15, y=1.1)
    
    # Save to BytesIO object
    img = BytesIO()
    plt.savefig(img, format='png', dpi=100, bbox_inches='tight')
    img.seek(0)
    plt.close()
    
    # Encode to base64 for embedding in HTML
    plot_url = base64.b64encode(img.getvalue()).decode()
    return plot_url

def get_average_responses_by_role(role=None,t_id=None):
    """Calculate average responses, optionally filtered by role"""
    conn = get_db_connection()
    
    if role:
        # Get all ratings for specific role
        query = f'''SELECT rt.category, AVG(rt.rating) as avg_rating
                   FROM ratings rt
                   LEFT JOIN responses r ON rt.response_id = r.id
                   WHERE rt.role = ?{' AND r.team_id = ?' if t_id else ''}
                   GROUP BY rt.category'''
        result = conn.execute(query, (role,t_id) if t_id else (role,)).fetchall()
    else:
        # Get all ratings across all roles
        query = f'''SELECT rt.category, AVG(rt.rating) as avg_rating
                   FROM ratings rt
                   LEFT JOIN responses r ON rt.response_id = r.id
                   {'WHERE r.team_id = ?' if t_id else ''}
                   GROUP BY rt.category'''
        result = conn.execute(query,(t_id,) if t_id else ()).fetchall()
    
    conn.close()
    
    if result:
        averages = {row['category']: row['avg_rating'] for row in result}
        return averages
    else:
        # Return default values if no data
        return {cat: 5 for cat in CONFIG['categories'].keys()}

def get_role_averages_for_chart(role=None,t_id=None):
    """Get averages in format suitable for spider chart"""
    averages = get_average_responses_by_role(role,t_id)
    
    # Get categories for this role or all categories
    if role and role in CONFIG:
        categories = list(CONFIG[role].keys())
    else:
        categories = list(CONFIG['categories'].keys())
    
    # Create values in the same order as categories
    values = [averages.get(cat, 5) for cat in categories]
    
    return categories, values

def get_user_responses_for_chart(response_id):
    """Get a specific user's responses for spider chart"""
    conn = get_db_connection()
    
    # Get response details
    response = conn.execute('SELECT * FROM responses WHERE id = ?', 
                           (response_id,)).fetchone()
    
    if not response:
        conn.close()
        return None, None, None
    
    # Get ratings
    ratings = conn.execute('''SELECT category, rating FROM ratings 
                              WHERE response_id = ?''', (response_id,)).fetchall()
    
    conn.close()
    
    # Organize ratings by category
    rating_dict = {row['category']: row['rating'] for row in ratings}
    
    # Get categories for this role
    if response['role'] in CONFIG:
        categories = list(CONFIG[response['role']].keys())
    else:
        categories = list(rating_dict.keys())
    
    values = [rating_dict.get(cat, 5) for cat in categories]
    
    return response, categories, values

@app.route('/')
def index():
    """Home page with role selection"""
    return render_template('role_select.html', 
                         roles=CONFIG['roles'],
                         append_t_id=f"?t={request.args.get("t")}" if "t" in request.args.keys() else "")

@app.route('/survey/<role>')
def survey(role):
    """Show survey form for selected role"""
    if role not in CONFIG:
        flash('Invalid role selected', 'error')
        return redirect(url_for('index'))
    
    role_config = CONFIG[role]
    categories = CONFIG['categories']
    open_questions = CONFIG['open_questions']
    roles = CONFIG['roles']
    
    return render_template('survey.html', 
                         role=role,
                         roles=roles,
                         role_config=role_config,
                         categories=categories,
                         open_questions=open_questions,
                         append_t_id=f"?t={request.args.get("t")}" if request.args.get("t") else "")

@app.route('/submit', methods=['POST'])
def submit():
    """Handle survey submission"""
    if request.method != 'POST': return
    role = request.form.get('role')
    respondent_name = request.form.get('respondent_name', 'Не указано')
    member_amnt = request.form.get('member_amnt', None)
    member_cost = request.form.get('member_cost', None)
    team_id = request.args.get("t")
    
    # Save main response
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO responses (timestamp, role, respondent_name, member_amnt, member_cost, team_id)
                        VALUES (?, ?, ?, ?, ?, ?)''',
                    (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                    role, respondent_name, member_amnt, member_cost, team_id))
    response_id = cursor.lastrowid
    
    # Save ratings
    for key, value in request.form.items():
        if key.startswith('rating_'):
            # Parse key format: rating_category_question
            parts = key.split('_')
            if len(parts) >= 3:
                category = parts[1]
                question_idx = parts[2]
                rating = int(value)
                
                # Get the actual question text from config
                if role in CONFIG and category in CONFIG[role]:
                    questions = CONFIG[role][category]
                    if int(question_idx) < len(questions):
                        question = questions[int(question_idx)]
                        
                        cursor.execute('''INSERT INTO ratings 
                                        (response_id, role, category, question, rating)
                                        VALUES (?, ?, ?, ?, ?)''',
                                        (response_id, role, category, question, rating))
    
    # Save open answers
    for key, value in request.form.items():
        if key.startswith('open_') and value.strip():
            # Parse key format: open_index
            parts = key.split('_')
            if len(parts) >= 2:
                question_idx = int(parts[1])
                if question_idx < len(CONFIG['open_questions']):
                    question = CONFIG['open_questions'][question_idx]
                    
                    cursor.execute('''INSERT INTO open_answers 
                                    (response_id, question, answer)
                                    VALUES (?, ?, ?)''',
                                    (response_id, question, value))
    
    conn.commit()
    conn.close()
    
    # Store in session for immediate display
    session['last_response_id'] = response_id
    
    flash('Спасибо за прохождение опроса!', 'success')
    return redirect(url_for('results'))

@app.route('/results')
def results():
    """Show individual results with spider chart"""
    if 'last_response_id' not in session:
        return redirect(url_for('index'))
    
    response_id = session['last_response_id']
    response, categories, values = get_user_responses_for_chart(response_id)
    
    if not response:
        flash('Response not found', 'error')
        return redirect(url_for('index'))
    
    role_display = CONFIG['roles'].get(response['role'], response['role'])
    title = f"Ваши результаты - {response['respondent_name']} ({role_display})"
    
    chart_url = generate_spider_chart(values, categories, title)
    
    # Get open answers
    conn = get_db_connection()
    open_answers = conn.execute('''SELECT question, answer FROM open_answers 
                                   WHERE response_id = ?''', 
                               (response_id,)).fetchall()
    conn.close()
    
    return render_template('results.html', 
                         chart_url=chart_url,
                         respondent_name=response['respondent_name'],
                         role=role_display,
                         categories=categories,
                         values=values,
                         open_answers=open_answers)

@app.route('/admin')
@auth.login_required
def admin():
    """Admin page showing all responses and average charts"""
    conn = get_db_connection()
    
    # Get all responses
    responses = conn.execute('''SELECT r.*, 
                               COUNT(DISTINCT rt.id) as rating_count,
                               COUNT(DISTINCT oa.id) as open_count
                               FROM responses r
                               LEFT JOIN ratings rt ON r.id = rt.response_id
                               LEFT JOIN open_answers oa ON r.id = oa.response_id
                               GROUP BY r.id
                               ORDER BY r.timestamp DESC''').fetchall()
    
    # Get statistics
    stats = conn.execute('''SELECT 
                           COUNT(DISTINCT r.id) as total_responses,
                           COUNT(DISTINCT rt.id) as total_ratings,
                           COUNT(DISTINCT oa.id) as total_open_answers,
                           AVG(rt.rating) as overall_avg_rating
                           FROM responses r
                           LEFT JOIN ratings rt ON r.id = rt.response_id
                           LEFT JOIN open_answers oa ON r.id = oa.response_id''').fetchone()
    
    
    
    # Generate average charts for each role
    role_charts = {}
    for role in CONFIG['roles'].keys():
        categories, values = get_role_averages_for_chart(role)
        if values:
            role_display = CONFIG['roles'][role]
            chart_url = generate_spider_chart(
                values, 
                categories, 
                f"Средние результаты - {role_display}"
            )
            role_charts[role] = {
                'display_name': role_display,
                'chart_url': chart_url,
                'categories': categories,
                'values': values
            }
    
    # Generate overall average chart
    all_categories = list(CONFIG['categories'].keys())
    all_values = []
    for cat in all_categories:
        avg = conn.execute('SELECT AVG(rating) as avg FROM ratings WHERE category = ?',
                          (cat,)).fetchone()
        all_values.append(avg['avg'] if avg and avg['avg'] else 5)
    conn.close()
    
    overall_chart = generate_spider_chart(
        all_values,
        all_categories,
        "Средний результат за все ответы"
    )
    
    return render_template('admin.html', 
                         responses=responses,
                         stats=stats,
                         role_charts=role_charts,
                         overall_chart=overall_chart,
                         roles=CONFIG['roles'])

@app.route('/logout')
def logout():
    """Log out the current user"""
    session.clear()
    
    return redirect(url_for('index'))

@app.route('/response/<int:response_id>')
def view_response(response_id):
    """View individual response with spider chart"""
    response, categories, values = get_user_responses_for_chart(response_id)
    
    if not response:
        flash('Response not found', 'error')
        return redirect(url_for('admin'))
    
    role_display = CONFIG['roles'].get(response['role'], response['role'])
    title = f"Результаты {response['respondent_name']} - {role_display} ({response['timestamp']})"
    
    chart_url = generate_spider_chart(values, categories, title)
    
    # Get ratings details
    conn = get_db_connection()
    ratings = conn.execute('''SELECT category, question, rating 
                             FROM ratings WHERE response_id = ?
                             ORDER BY category''', (response_id,)).fetchall()
    
    # Get open answers
    open_answers = conn.execute('''SELECT question, answer FROM open_answers 
                                   WHERE response_id = ?''', 
                               (response_id,)).fetchall()
    conn.close()
    
    return render_template('view_response.html',
                         response=response,
                         chart_url=chart_url,
                         ratings=ratings,
                         open_answers=open_answers,
                         role_display=role_display)

@app.route('/role/<role>')
def role_stats(role):
    """View statistics for a specific role"""
    if role not in CONFIG['roles']:
        flash('Invalid role', 'error')
        return redirect(url_for('admin'))
    
    conn = get_db_connection()
    
    # Get responses for this role
    responses = conn.execute('''SELECT r.*, 
                               COUNT(DISTINCT rt.id) as rating_count
                               FROM responses r
                               LEFT JOIN ratings rt ON r.id = rt.response_id
                               WHERE r.role = ?
                               GROUP BY r.id
                               ORDER BY r.timestamp DESC''', 
                           (role,)).fetchall()
    
    # Get statistics for this role
    stats = conn.execute('''SELECT 
                           COUNT(DISTINCT r.id) as total_responses,
                           AVG(rt.rating) as avg_rating
                           FROM responses r
                           LEFT JOIN ratings rt ON r.id = rt.response_id
                           WHERE r.role = ?''', (role,)).fetchone()
    
    # Get category averages
    category_avgs = conn.execute('''SELECT category, AVG(rating) as avg_rating,
                                   COUNT(*) as rating_count
                                   FROM ratings 
                                   WHERE role = ?
                                   GROUP BY category''', (role,)).fetchall()
    
    conn.close()
    
    # Generate spider chart for this role
    categories, values = get_role_averages_for_chart(role)
    role_display = CONFIG['roles'][role]
    chart_url = generate_spider_chart(
        values, 
        categories, 
        f"Средние результаты - {role_display}"
    )
    
    return render_template('role_stats.html',
                         role=role,
                         role_display=role_display,
                         responses=responses,
                         stats=stats,
                         category_avgs=category_avgs,
                         chart_url=chart_url,
                         categories=categories,
                         values=values)

@app.route('/group')
def group():
    """Get a group link"""
    if (t_id:=request.args.get("t")):
        conn = get_db_connection()
        
        # Get all responses
        responses = conn.execute('''SELECT r.*, 
                                COUNT(DISTINCT rt.id) as rating_count,
                                COUNT(DISTINCT oa.id) as open_count
                                FROM responses r
                                LEFT JOIN ratings rt ON r.id = rt.response_id
                                LEFT JOIN open_answers oa ON r.id = oa.response_id
                                WHERE r.team_id = ?
                                GROUP BY r.id
                                ORDER BY r.timestamp DESC''',(t_id,)).fetchall()
        
        # Get statistics
        stats = conn.execute('''SELECT 
                            COUNT(DISTINCT r.id) as total_responses,
                            COUNT(DISTINCT rt.id) as total_ratings,
                            COUNT(DISTINCT oa.id) as total_open_answers,
                            AVG(rt.rating) as overall_avg_rating
                            FROM responses r
                            LEFT JOIN ratings rt ON r.id = rt.response_id
                            LEFT JOIN open_answers oa ON r.id = oa.response_id
                            WHERE r.team_id = ?''',(t_id,)).fetchone()
        
        # Generate average charts for each role
        role_charts = {}
        for role in CONFIG['roles'].keys():
            categories, values = get_role_averages_for_chart(role,t_id)
            if values:
                role_display = CONFIG['roles'][role]
                chart_url = generate_spider_chart(
                    values, 
                    categories, 
                    f"Средние результаты - {role_display}"
                )
                role_charts[role] = {
                    'display_name': role_display,
                    'chart_url': chart_url,
                    'categories': categories,
                    'values': values
                }
        
        # Generate overall average chart
        all_categories = list(CONFIG['categories'].keys())
        all_values = []
        for cat in all_categories:
            avg = conn.execute('SELECT AVG(rating) as avg FROM ratings rt LEFT JOIN responses r on r.id = rt.response_id WHERE rt.category = ? AND r.team_id = ?',
                            (cat,t_id)).fetchone()
            all_values.append(avg['avg'] if avg and avg['avg'] else 5)
        conn.close()
        overall_chart = generate_spider_chart(
            all_values,
            all_categories,
            "Средний результат за все ответы"
        )
        return render_template('admin.html', 
                         responses=responses,
                         stats=stats,
                         role_charts=role_charts,
                         overall_chart=overall_chart,
                         roles=CONFIG['roles'])

    conn = get_db_connection()
    t_id = conn.execute("SELECT MAX(team_id) FROM responses").fetchone()[0]
    if t_id is None: t_id = -1
    link = config.URL_START+url_for("index",t=t_id+1)
    group_link = config.URL_START+url_for("group",t=t_id+1)
    return render_template('group.html', link=link, group_link=group_link)



init_db()
if __name__ == "__main__":
    app.run(debug=True)