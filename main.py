from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

import sys
sys.stderr = open('survey_err.txt', 'w')

from flask import Flask, render_template, request, redirect, url_for, flash, session, json, jsonify
from flask_sslify import SSLify
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import random
from datetime import datetime
import base64
from io import BytesIO
import json
app = Flask(__name__)
sslify = SSLify(app)
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
    
    # Create main responses table with survey_id
    c.execute('''CREATE TABLE IF NOT EXISTS responses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  survey_id TEXT,
                  role TEXT,
                  respondent_name TEXT,
                  member_cost REAL,
                  member_amnt INTEGER,
                  team_id TEXT,
                  mail TEXT,
                  industry TEXT,
                  company TEXT,
                  job TEXT)''')
    
    # Create table for rating questions with survey_id
    c.execute('''CREATE TABLE IF NOT EXISTS ratings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  response_id INTEGER,
                  role TEXT,
                  category TEXT,
                  question TEXT,
                  rating INTEGER,
                  FOREIGN KEY (response_id) REFERENCES responses (id))''')
    
    # Create table for open questions with survey_id
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

def send_by_email(subject,text,image:BytesIO,is_plaintext=True,target=config.EMAIL_TARGET):
    """Send the collected answers via email"""
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = config.EMAIL["sender_email"]
    msg['To'] = target
    if is_plaintext:
        msg.attach(MIMEText(text,"plain"))
        image.seek(0)
        img = MIMEImage(image.read())
        img.add_header("Content-ID", "<image1>")
        img.add_header('Content-Disposition', 'inline')
        msg.attach(img)
    else:
        msg.attach(MIMEText(text,"html"))
        image.seek(0)
        img = MIMEImage(image.read())
        img.add_header("Content-ID", "<image1>")
        img.add_header('Content-Disposition', 'inline')
        msg.attach(img)
    try:
        with smtplib.SMTP_SSL(config.EMAIL['smtp_server'], config.EMAIL['smtp_port']) as server:
            server.login(config.EMAIL['sender_email'], config.EMAIL["email_key"])
            server.send_message(msg)
    except Exception as e:
        print(f"Failed to send email: {e}")

def generate_spider_chart(name, values, categories, title, color_id=0):
    """Generate a spider/radar chart"""
    TITLE_FORMAT = CONFIG[name]["chart_title"]
    CATEG_FORMAT = CONFIG[name]["chart_categories"]

    TYPE = CONFIG[name].get("chart_type","spider")
    values_adj=None
    if "category_weights" in CONFIG[name].keys():
        weights = {CONFIG[name]["categories"][c]:w for c,w in CONFIG[name]["category_weights"].items()}
        w_avg = sum(weights.values())/len(weights.values())
        # factor = weights[category]/w_avg
        values_adj = [i*weights[c]/w_avg for i,c in zip(values,categories)]
    else: values_adj = values

    if TYPE == "bar":
        fig, ax = plt.subplots()
        colors = ['#ff9999', '#66b3ff', '#99ff99', '#ffcc99', '#ff99cc']
        bars = ax.bar([i+1 for i in range(len(categories))], values_adj, color=colors, label=[f"{i+1}. {v}" for i,v in enumerate(categories)])
        ax.legend(loc="lower center",bbox_to_anchor=(0.5,-0.5),fontsize=12,frameon=False)
        ax.bar_label(bars,[round(i,1) if i else "" for i in values_adj],label_type='center')

        # plt.xticks(rotation=20, ha='right', fontsize=14)
        ax.set_ylim(CONFIG[name].get("min_score",0), CONFIG[name].get("max_score",10))

        plt.title(TITLE_FORMAT.format(title,f"{sum(values_adj)/len(values_adj):.1f}"), size=20, y=1.1)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.yaxis.set_visible(False)
        img = BytesIO()
        plt.savefig(img, format='png', dpi=100, bbox_inches='tight')
        img.seek(0)
        plt.close()
        return img
    if TYPE == "pie":
        colors = ['#ff9999', '#66b3ff', '#99ff99', '#ffcc99', '#ff99cc']

        plt.figure(figsize=(10, 8))
        plt.pie(values_adj,
                labels=None,
                colors=colors,
                autopct='%1.0f%%',
                textprops={'fontsize': 18},
                startangle=90)
        fig.set_ylim(CONFIG[name].get("min_score",0), CONFIG[name].get("max_score",10))

        s=sum(values)
        legends = [f"{i}: {round(j/s*100)}%" for i,j in zip(categories,values)]
        plt.legend(legends, loc="lower center",bbox_to_anchor=(0.5,-0.3),fontsize=18)
        plt.title(TITLE_FORMAT.format(title,f"{sum(values_adj)/len(values_adj):.1f}"), size=26, y=1.1)
        plt.axis('equal')
        img = BytesIO()
        plt.savefig(img, format='png', dpi=100, bbox_inches='tight')
        img.seek(0)
        plt.close()
        return img

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
    colors = ['#ff9999', "#4427ff", "#9F0087", '#ffb347', "#fff369", "#00aaed"]
    ax.plot(angles, values, 'o-', linewidth=2, color=colors[color_id%len(colors)])
    ax.fill(angles, values, alpha=0.25, color=colors[color_id%len(colors)])
    
    # Set category labels
    category_labels = [CATEG_FORMAT.format(CONFIG[name]['categories'].get(cat, cat),f"{values[i]:.1f}") for i,cat in enumerate(categories)]
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(category_labels, size=10)
    
    # Set y-axis limits
    ax.set_ylim(CONFIG[name].get("min_score",0), CONFIG[name].get("max_score",10))
    ax.set_yticks(range(CONFIG[name].get("min_score",0), CONFIG[name].get("max_score",10)+1, CONFIG[name].get("max_score",10)//5))
    ax.set_yticklabels(map(str, range(CONFIG[name].get("min_score",0), CONFIG[name].get("max_score",10)+1, CONFIG[name].get("max_score",10)//5)), size=8)
    ax.grid(True)
    
    # Add title
    plt.title(TITLE_FORMAT.format(title,f"{sum(values_adj)/len(values_adj):.1f}"), size=15, y=1.1)
    
    # Save to BytesIO object
    img = BytesIO()
    plt.savefig(img, format='png', dpi=100, bbox_inches='tight')
    img.seek(0)
    plt.close()
    
    return img

def generate_multi_spider_chart(name, datasets, categories, title):
    """
    Generate a spider/radar chart with multiple datasets
    
    Args:
        name: Configuration key
        datasets: List of tuples (dataset_name, values_list)
        categories: List of category names
        title: Chart title
    """
    TYPE = CONFIG[name].get("chart_type", "spider")
    
    # Define colors for different datasets
    colors = ['#ff9999', "#4427ff", "#9F0087", '#ffb347', "#fff369", "#00aaed"]
    
    # Apply category weights if specified
    datasets_adj = []
    if "category_weights" in CONFIG[name].keys():
        weights = {CONFIG[name]["categories"][c]: w for c, w in CONFIG[name]["category_weights"].items()}
        w_avg = sum(weights.values()) / len(weights.values())
        for dataset_name, values in datasets:
            values_adj = [i * weights[c] / w_avg for i, c in zip(values, categories)]
            datasets_adj.append((dataset_name, values_adj))
    else:
        datasets_adj = [(name, values) for name, values in datasets]
    
    if TYPE == "bar":
        fig, ax = plt.subplots(figsize=(10, 6))
        
        n_categories = len(categories)
        n_datasets = len(datasets_adj)
        bar_width = 0.8 / n_datasets
        
        # Create bars for each dataset
        for idx, (dataset_name, values_adj) in enumerate(datasets_adj):
            x_positions = [i + 1 + (idx - n_datasets/2 + 0.5) * bar_width for i in range(n_categories)]
            bars = ax.bar(x_positions, values_adj, bar_width, 
                         color=colors[idx % len(colors)], 
                         label=dataset_name,
                         alpha=0.8)
            ax.bar_label(bars, [round(i, 1) if i else "" for i in values_adj], 
                        label_type='center', fontsize=8)
        
        # Set x-axis ticks to category positions
        ax.set_xticks([i + 1 for i in range(n_categories)])
        ax.set_xticklabels(categories, rotation=20, ha='right', fontsize=14)
        
        ax.set_ylim(CONFIG[name].get("min_score", 0), CONFIG[name].get("max_score", 10))
        plt.title(title, size=20, y=1.1)
        
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_visible(False)
        ax.yaxis.set_visible(False)
        ax.legend(loc="lower center", bbox_to_anchor=(0.5, -0.3), fontsize=12, frameon=False, ncol=min(3, n_datasets))
        
        img = BytesIO()
        plt.savefig(img, format='png', dpi=100, bbox_inches='tight')
        img.seek(0)
        plt.close()
        return img
    
    if TYPE == "pie":
        n_datasets = len(datasets_adj)
        n_cols = min(3, n_datasets)
        n_rows = (n_datasets - 1) // n_cols + 1
        
        fig, axes = plt.subplots(n_rows, n_cols, figsize=(6 * n_cols, 6 * n_rows))
        if n_datasets == 1:
            axes = [axes]
        else:
            axes = axes.flatten()
        
        for idx, (dataset_name, values_adj) in enumerate(datasets_adj):
            ax = axes[idx]
            original_values = datasets[idx][1]  # Get original values for percentage calculation
            
            wedges, texts, autotexts = ax.pie(values_adj,
                                           labels=None,
                                           colors=colors[:len(categories)],
                                           autopct='%1.0f%%',
                                           textprops={'fontsize': 14},
                                           startangle=90)
            
            s = sum(original_values)
            legends = [f"{i}: {round(j/s*100)}%" for i, j in zip(categories, original_values)]
            ax.legend(legends, loc="lower center", bbox_to_anchor=(0.5, -0.3), fontsize=14)
            ax.set_title(dataset_name, size=18, y=1.05)
        
        for idx in range(n_datasets, len(axes)):
            axes[idx].set_visible(False)
        
        plt.suptitle(title, size=24, y=1.02)
        plt.tight_layout()
        
        img = BytesIO()
        plt.savefig(img, format='png', dpi=100, bbox_inches='tight')
        img.seek(0)
        plt.close()
        return img
    
    # Spider/radar chart (default)
    N = len(categories)
    angles = [n / float(N) * 2 * np.pi for n in range(N)]
    angles += angles[:1]  # Complete the loop
    
    fig, ax = plt.subplots(figsize=(10, 10), subplot_kw=dict(projection='polar'))
    
    for idx, (dataset_name, values_adj) in enumerate(datasets_adj):
        values = list(values_adj) + values_adj[:1]  # Complete the loop
        color = colors[idx % len(colors)]
        
        ax.plot(angles, values, 'o-', linewidth=2, color=color, label=dataset_name)
        ax.fill(angles, values, alpha=0.1, color=color)

        for angle, value in zip(angles[:-1], values_adj):
            offset = 0.5
            text_x = angle
            text_y = value + offset
            
            ax.annotate(f'{value:.1f}', 
                    xy=(angle, value), 
                    xytext=(text_x, text_y),
                    color=color,
                    fontsize=9,
                    ha='center',
                    va='bottom',
                    fontweight='bold',
                    bbox=dict(boxstyle='round,pad=0.2', facecolor='grey', alpha=0.7, edgecolor='none'))
    
    category_labels = []
    for cat in categories:
        category_labels.append(CONFIG[name]['categories'].get(cat, cat))
    
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(category_labels, size=10)
    
    # Set y-axis limits
    ax.set_ylim(CONFIG[name].get("min_score", 0), CONFIG[name].get("max_score", 10))
    ax.set_yticks(range(CONFIG[name].get("min_score", 0), CONFIG[name].get("max_score", 10) + 1, 
                        CONFIG[name].get("max_score", 10) // 5))
    ax.set_yticklabels(map(str, range(CONFIG[name].get("min_score", 0), CONFIG[name].get("max_score", 10) + 1, 
                                    CONFIG[name].get("max_score", 10) // 5)), size=8)
    ax.grid(True)
    
    # Add legend
    ax.legend(loc='upper right', bbox_to_anchor=(1.3, 1.1), fontsize=12)
    
    # Calculate average for all datasets combined and add to title
    all_avgs = [sum(vals)/len(vals) for _, vals in datasets_adj]
    plt.title(title, size=15, y=1.1)
    
    img = BytesIO()
    plt.savefig(img, format='png', dpi=100, bbox_inches='tight')
    img.seek(0)
    plt.close()
    
    return img

def get_average_responses_by_role(name, role=None, t_id=None):
    """Calculate average responses, optionally filtered by role"""
    conn = get_db_connection()
    
    if role:
        # Get all ratings for specific role
        query = f'''SELECT rt.category, AVG(rt.rating) as avg_rating
                   FROM ratings rt
                   LEFT JOIN responses r ON rt.response_id = r.id
                   WHERE r.survey_id = ? AND rt.role = ?{' AND r.team_id = ?' if t_id else ''}
                   GROUP BY rt.category'''
        params = [name, role]
        if t_id:
            params.append(t_id)
        result = conn.execute(query, params).fetchall()
    else:
        # Get all ratings across all roles
        query = f'''SELECT rt.category, AVG(rt.rating) as avg_rating
                   FROM ratings rt
                   LEFT JOIN responses r ON rt.response_id = r.id
                   WHERE r.survey_id = ?{' AND r.team_id = ?' if t_id else ''}
                   GROUP BY rt.category'''
        params = [name]
        if t_id:
            params.append(t_id)
        result = conn.execute(query, params).fetchall()
    
    conn.close()
    
    if result:
        averages = {row['category']: row['avg_rating'] for row in result}
        return averages
    else:
        # Return default values if no data
        return {cat: 5 for cat in CONFIG[name]['categories'].keys()}

def get_role_averages_for_chart(name, role=None, t_id=None):
    """Get averages in format suitable for spider chart"""
    averages = get_average_responses_by_role(name, role, t_id)
    
    # Get categories for this role or all categories
    if role and role in CONFIG[name]['questions']:
        categories = CONFIG[name]['questions'][role].keys()
    else:
        categories = list(CONFIG[name]['categories'].keys())
    
    # Create values in the same order as categories
    values = [averages.get(cat, 5) for cat in categories]

    categories = [CONFIG[name]['categories'][i] for i in categories]
    
    return categories, values

def get_user_responses_for_chart(response_id):
    """Get a specific user's responses for spider chart"""
    conn = get_db_connection()
    
    response = conn.execute('SELECT * FROM responses WHERE id = ?', 
                           (response_id,)).fetchone()
    
    if not response:
        conn.close()
        return None, None, None
    
    name = response["survey_id"]
    
    ratings = conn.execute('''SELECT category,AVG(rating) FROM ratings 
                              WHERE response_id = ?
                              GROUP BY category''', 
                              (response_id,)).fetchall()
    answers = conn.execute('''SELECT category,question,rating FROM ratings 
                              WHERE response_id = ?''', 
                              (response_id,)).fetchall()
    conn.close()
    
    rating_dict = {row['category']: row['AVG(rating)'] for row in ratings}
    answer_dict = {row['question']: {"rate":row['rating'],"cat":row['category']} for row in answers}
    
    if response['role'] in CONFIG[name]['questions']:
        categories = list(CONFIG[name]['questions'][response['role']].keys())
    else:
        categories = list(rating_dict.keys())
    
    values = [rating_dict[cat] for cat in categories]
    
    return response, categories, values, name, answer_dict

@app.route('/')
def index():
    """Home page"""
    return render_template('homepage.html',
                         surveys=CONFIG)
@app.route('/agreement')
def agreement():
    """Agreement page"""
    return render_template('agreement.html')
@app.route('/select/<name>') 
def select(name):
    session["survey_name"] = name
    # session["team_id"] = request.args.get("t")
    t_id = request.args.get("t",None)
    if "skip_role_selection" in CONFIG[name]:
        return redirect(f"/survey/{name}/{CONFIG[name]["skip_role_selection"]}{'?t='+t_id if t_id else ''}")
    return render_template(CONFIG[name]["page"],
                         data=CONFIG[name],
                         append_t_id=f"?t={request.args.get('t')}" if request.args.get("t") else "")
@app.route('/survey/<name>/<role>')
def survey(name,role):
    """Show survey form for selected role"""
    if role not in CONFIG[name]['roles']:
        flash('Invalid role selected', 'error')
        return redirect(url_for('index'))
    
    role_config = CONFIG[name]['questions'][role]
    categories = CONFIG[name]['categories']
    open_questions = CONFIG[name]['open_questions']
    roles = CONFIG[name]['roles']
    preamble=""

    if 'preamble' in CONFIG[name]:
        with open(f'templates/preambles/{CONFIG[name]['preamble']}.html',encoding="utf-8") as f:
            preamble=f.read()
    
    session["survey_name"] = name
    return render_template(CONFIG[name].get('survey_page', 'survey.html'),
                         data=CONFIG[name],
                         role=role,
                         roles=roles,
                         role_config=role_config,
                         categories=categories,
                         open_questions=open_questions,
                         preamble=preamble,
                         require_name=CONFIG[name].get("require_name",True),
                         require_job=CONFIG[name].get("require_job",True),
                         require_mail=CONFIG[name].get("require_mail",True),
                         survey_name=CONFIG[name]['name'],
                         score_min=CONFIG[name].get("min_score",1),
                         score_max=CONFIG[name].get("max_score",10),
                         append_t_id=f"?t={request.args.get('t')}" if request.args.get("t") else "")

@app.route('/submit/', methods=['POST'])
def submit():
    """Handle survey submission"""
    if request.method != 'POST': 
        return redirect(url_for('index'))
    
    name = session["survey_name"]
    
    role = request.form.get('role')
    respondent_name = request.form.get('respondent_name', 'Не указано')
    respondent_company = request.form.get('respondent_company', 'Не указано')
    respondent_job = request.form.get('respondent_job', 'Не указано')
    respondent_mail = request.form.get('respondent_mail', None)
    member_amnt = request.form.get('member_amnt', None)
    member_cost = request.form.get('member_cost', None)
    industry = request.form.get('industry', None)
    team_id = request.args.get("t")

    session["respondent_contacts"] = [respondent_name,respondent_company,respondent_job,respondent_mail]
    
    # Save main response
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''INSERT INTO responses (timestamp, survey_id, role, respondent_name, member_amnt, member_cost, team_id, mail, industry, company, job)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                    (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                    name, role, respondent_name, member_amnt, member_cost, team_id, respondent_mail, industry, respondent_company, respondent_job))
    response_id = cursor.lastrowid
    
    weights = CONFIG[name]["category_weights"] if "category_weights" in CONFIG[name].keys() else {c:1 for c in CONFIG[name]["categories"].keys()}
    w_avg = sum(weights.values())/len(weights.values())
    for key, value in request.form.items():
        if key.startswith('rating_'):
            parts = key.split('_')
            if len(parts) >= 3:
                category = parts[1]
                question_idx = parts[2]
                rating = int(value)
                
                if role in CONFIG[name]['questions'] and category in CONFIG[name]['questions'][role]:
                    questions = CONFIG[name]['questions'][role][category]
                    if CONFIG[name].get("question_response_type","int")=="string":
                        questions = list(questions.keys())
                    
                    if int(question_idx) < len(questions):
                        question = questions[int(question_idx)]
                        
                        factor = weights[category]/w_avg
                        cursor.execute('''INSERT INTO ratings 
                                        (response_id, role, category, question, rating)
                                        VALUES (?, ?, ?, ?, ?)''',
                                        (response_id, role, category, question, rating*factor))
    
    # Save open answers
    for key, value in request.form.items():
        if key.startswith('open_') and value.strip():
            # Parse key format: open_index
            parts = key.split('_')
            if len(parts) >= 2:
                question_idx = int(parts[1])
                if question_idx < len(CONFIG[name]['open_questions']):
                    question = CONFIG[name]['open_questions'][question_idx]
                    
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

@app.route('/spider/', methods=['POST'])
def spider():
    """Generate spider chart from submitted answers and return as base64 image"""
    data = request.get_json()

    name = session["survey_name"]
    
    if not data or 'role' not in data or 'ratings' not in data:
        return jsonify({'error': 'Missing required data'}), 400
    
    role = data['role']
    ratings = data['ratings']
    
    if role not in CONFIG[name]['roles']:
        return jsonify({'error': 'Invalid role'}), 400
    
    categories = []
    values = []

    category_values = {}
    
    for key, value in ratings.items():
        parts = key.split('_')
        if len(parts) >= 3:
            category_id = parts[1]
            if category_id not in category_values:
                category_values[category_id] = []
            category_values[category_id].append(value)
    
    for category_id, question_values in category_values.items():
        if category_id in CONFIG[name]['categories']:
            category_name = CONFIG[name]['categories'][category_id]
            categories.append(category_name)
            avg_value = sum(question_values) / len(question_values)
            values.append(avg_value)
    
    role_display = CONFIG[name]['roles'].get(role, role)
    title = CONFIG[name].get('chart_name',"Предварительные результаты - {0}").format(role_display) #f"Предварительные результаты - {role_display}"
    
    chart_url = generate_spider_chart(name, values, categories, title)
    
    return jsonify({
        'image': base64.b64encode(chart_url.getvalue()).decode()
    })

@app.route('/results/')
def results():
    """Show individual results with spider chart"""
    if 'last_response_id' not in session:
        return redirect(url_for('index'))
    
    response_id = session['last_response_id']
    response, categories, values, name, answer_dict = get_user_responses_for_chart(response_id)
    
    if not response:
        flash('Response not found', 'error')
        return redirect(url_for('index'))
    
    role_display = CONFIG[name]['roles'].get(response['role'], response['role'])
    title = CONFIG[name].get('chart_name',"Ваши результаты - ({0})").format(role_display)
    
    if categories[0] in CONFIG[name]["categories"]: # given keys rather than display names
        categories = [CONFIG[name]["categories"][c] for c in categories]
    weights = {CONFIG[name]["categories"][c]:w for c,w in CONFIG[name]["category_weights"].items()} if "category_weights" in CONFIG[name].keys() else {c:1 for c in CONFIG[name]["categories"].values()}
    w_avg = sum(weights.values())/len(weights.values())
    values_adj = [i/weights[c]*w_avg for i,c in zip(values,categories)]
    image = generate_spider_chart(name, values_adj, categories, title)
    
    # Get open answers
    conn = get_db_connection()
    open_answers = conn.execute('''SELECT question, answer FROM open_answers
                                   WHERE response_id = ?''', 
                               (response_id,)).fetchall()
    conn.close()

    values_adj = [round(i,1) for i in values_adj]
    
    text = """
Имя: {0}
Компания: {1}
Должность: {2}
Почта: {3}

Развернутые ответы, если есть:
{4}

Числовые ответы:
{5}""".format(*session["respondent_contacts"],"\n".join([f"{i["question"]}: {i["answer"]}" for i in open_answers]),
              "\n\n".join(f"{CONFIG[name]["categories"][v['cat']]} - {i}: {v['rate']}" for i,v in answer_dict.items()))
    
    send_by_email(f"Результаты {CONFIG[name]['name']}: {response['respondent_name']} из {response['company']}",text,image)
    if response["mail"]:
        with open("templates/email.html","r",encoding="utf-8") as f:
            send_by_email(f"Результаты {CONFIG[name]['name']}: {response['respondent_name']}",f.read(),image,is_plaintext=False,target=response["mail"])

    return render_template('results.html', 
                         score_max=CONFIG[name].get("max_score",10),
                         chart_url=base64.b64encode(image.getvalue()).decode(),
                         respondent_name=response['respondent_name'],
                         role=role_display,
                         categories=categories,
                         values=values_adj,
                         open_answers=open_answers,
                         survey_name=CONFIG[name]['name'])

@app.route('/admin/')
@auth.login_required
def admin():
    """Admin page showing all responses and average charts"""
    session["authorised_response_ids"] = "*"
    name = session["survey_name"]
    conn = get_db_connection()
    
    # Get all responses for this survey
    responses = conn.execute('''SELECT r.*, 
                               COUNT(DISTINCT rt.id) as rating_count,
                               COUNT(DISTINCT oa.id) as open_count
                               FROM responses r
                               LEFT JOIN ratings rt ON r.id = rt.response_id
                               LEFT JOIN open_answers oa ON r.id = oa.response_id
                               WHERE r.survey_id = ?
                               GROUP BY r.id
                               ORDER BY r.timestamp DESC''', 
                               (name,)).fetchall()
    
    # Get statistics for this survey
    stats = conn.execute('''SELECT 
                           COUNT(DISTINCT r.id) as total_responses,
                           COUNT(DISTINCT rt.id) as total_ratings,
                           COUNT(DISTINCT oa.id) as total_open_answers,
                           AVG(rt.rating) as overall_avg_rating
                           FROM responses r
                           LEFT JOIN ratings rt ON r.id = rt.response_id
                           LEFT JOIN open_answers oa ON r.id = oa.response_id
                           WHERE r.survey_id = ?''', 
                           (name,)).fetchone()
    
    # Generate average charts for each role
    role_charts = {}
    for i,role in enumerate(CONFIG[name]['roles'].keys()):
        categories, values = get_role_averages_for_chart(name, role)
        if values:
            role_display = CONFIG[name]['roles'][role]
            chart_url = generate_spider_chart(
                name,
                values, 
                categories, 
                f"Средние результаты - {role_display}",
                color_id=i
            )
            role_charts[role] = {
                'display_name': role_display,
                'chart_url': chart_url,
                'categories': categories,
                'values': values
            }
    
    # Generate overall average chart
    all_categories = list(CONFIG[name]['categories'].keys())
    all_values = []
    for cat in all_categories:
        avg = conn.execute('SELECT AVG(rating) as avg FROM ratings WHERE survey_id = ? AND category = ?',
                          (name, cat)).fetchone()
        all_values.append(avg['avg'] if avg and avg['avg'] else 5)
    conn.close()
    
    overall_chart = generate_spider_chart(
        name,
        all_values,
        all_categories,
        "Средний результат за все ответы"
    )
    
    return render_template('admin.html', 
                         responses=responses,
                         stats=stats,
                         role_charts=role_charts,
                         overall_chart=overall_chart,
                         roles=CONFIG[name]['roles'],
                         survey_name=CONFIG[name]['name'])

@app.route('/logout')
def logout():
    """Log out the current user"""
    session.clear()
    
    return redirect(url_for('index'))

@app.route('/response/<int:response_id>')
def view_response(response_id):
    """View individual response with spider chart"""
    if not (session["authorised_response_ids"]=="*" or response_id in session["authorised_response_ids"]):
        flash('Вы не можете смотреть этот id', 'error')
        return redirect("/")

    response, categories, values, name, answer_dict = get_user_responses_for_chart(response_id)
    
    if not response:
        flash('Response not found', 'error')
        return redirect(url_for('admin'))
    
    role_display = CONFIG[name]['roles'].get(response['role'], response['role'])
    title = f"Результаты {response['respondent_name']} - {role_display} ({response['timestamp']})"

    categories = [CONFIG[name]["categories"][c] for c in categories]
    
    chart_url = generate_spider_chart(name, values, categories, title)
    
    # Get ratings details
    conn = get_db_connection()
    ratings = conn.execute('''SELECT category, question, rating 
                             FROM ratings 
                             WHERE response_id = ?
                             ORDER BY category''', 
                             (response_id,)).fetchall()
    
    # Get open answers
    open_answers = conn.execute('''SELECT question, answer FROM open_answers 
                                   WHERE response_id = ?''', 
                               (response_id,)).fetchall()
    conn.close()
    
    return render_template('view_response.html',
                         response=response,
                         chart_url=base64.b64encode(chart_url.getvalue()).decode(),
                         ratings=ratings,
                         open_answers=open_answers,
                         role_display=role_display)

@app.route('/role/<role>')
def role_stats(role):
    """View statistics for a specific role"""
    name = session["survey_name"]
    if role not in CONFIG[name]['roles']:
        flash('Invalid role', 'error')
        return redirect(url_for('admin'))
    
    conn = get_db_connection()
    
    # Get responses for this role and survey
    responses = conn.execute('''SELECT r.*, 
                               COUNT(DISTINCT rt.id) as rating_count
                               FROM responses r
                               LEFT JOIN ratings rt ON r.id = rt.response_id AND r.survey_id = ?
                               WHERE r.survey_id = ? AND r.role = ?
                               GROUP BY r.id
                               ORDER BY r.timestamp DESC''', 
                           (name, name, role)).fetchall()
    
    # Get statistics for this role
    stats = conn.execute('''SELECT 
                           COUNT(DISTINCT r.id) as total_responses,
                           AVG(rt.rating) as avg_rating
                           FROM responses r
                           LEFT JOIN ratings rt ON r.id = rt.response_id AND r.survey_id = ?
                           WHERE r.survey_id = ? AND r.role = ?''', 
                           (name, name, role)).fetchone()
    
    # Get category averages
    category_avgs = conn.execute('''SELECT rt.category, AVG(rt.rating) as avg_rating,
                                   COUNT(*) as rating_count
                                   FROM ratings rt
                                   LEFT JOIN responses r ON r.id = rt.response_id
                                   WHERE r.survey_id = ? AND rt.role = ?
                                   GROUP BY rt.category''', 
                                   (name, role)).fetchall()
    
    conn.close()
    
    # Generate spider chart for this role
    categories, values = get_role_averages_for_chart(name, role)
    role_display = CONFIG[name]['roles'][role]
    chart_url = generate_spider_chart(
        name,
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
                         values=values,
                         survey_name=CONFIG[name]['name'])

@app.route('/group/<name>/')
def group_w_name(name):
    if (t_id:=request.args.get("t")):
        conn = get_db_connection()
        
        # Get all responses for this survey and team
        responses_rows = conn.execute('''SELECT r.*,
                                COUNT(DISTINCT oa.id) as open_count,
                                AVG(rt.rating) as avg_rating
                                FROM responses r
                                LEFT JOIN ratings rt ON r.id = rt.response_id
                                LEFT JOIN open_answers oa ON r.id = oa.response_id
                                WHERE r.survey_id = ? AND r.team_id = ?
                                GROUP BY r.id
                                ORDER BY r.timestamp DESC''',
                                (name, t_id)).fetchall()
        
        session["authorised_response_ids"] = [i["id"] for i in responses_rows]

        single_open_answers = conn.execute('''SELECT oa.response_id, oa.question, oa.answer 
                                            FROM open_answers oa
                                            LEFT JOIN responses r ON r.id = oa.response_id
                                            WHERE r.survey_id = ? AND r.team_id = ?
                                            GROUP BY oa.response_id, oa.question, oa.answer
                                            HAVING COUNT(DISTINCT oa.id) = 1''',
                                            (name, t_id)).fetchall()
        ids = {i[0]:i[2] for i in single_open_answers}
        responses = []
        for i in responses_rows:
            responses.append(dict(i))
            if i["id"] in ids: responses[-1]["open_count"] = ids[i["id"]]
        
        # Get statistics for this survey and team
        stats = conn.execute('''SELECT 
                            COUNT(DISTINCT r.id) as total_responses,
                            COUNT(DISTINCT rt.id) as total_ratings,
                            COUNT(DISTINCT oa.id) as total_open_answers,
                            AVG(rt.rating) as overall_avg_rating
                            FROM responses r
                            LEFT JOIN ratings rt ON r.id = rt.response_id
                            LEFT JOIN open_answers oa ON r.id = oa.response_id
                            WHERE r.survey_id = ? AND r.team_id = ?''',
                            (name, t_id)).fetchone()
        
        # Generate average charts for each role
        role_charts = {}
        for color_id,role in enumerate(CONFIG[name]['roles'].keys()):
            categories, values = get_role_averages_for_chart(name, role, t_id)
            if values:
                role_display = CONFIG[name]['roles'][role]
                chart_url = generate_spider_chart(
                    name,
                    values, 
                    categories, 
                    f"Средние результаты - {role_display}",
                    color_id=color_id
                )
                role_charts[role] = {
                    'display_name': role_display,
                    'chart_url': base64.b64encode(chart_url.getvalue()).decode(),
                    'categories': categories,
                    'values': values
                }
        
        all_categories = list(CONFIG[name]['categories'].keys())
        categ_locales = list(CONFIG[name]['categories'].values())
        datasets = []

        all_values = []
        for cat in all_categories:
            avg = conn.execute('''SELECT AVG(rt.rating) as avg 
                                FROM ratings rt 
                                LEFT JOIN responses r on r.id = rt.response_id 
                                WHERE r.survey_id = ? AND rt.category = ? AND r.team_id = ?''',
                            (name, cat, t_id)).fetchone()
            all_values.append(avg['avg'] if avg and avg['avg'] else 5)
        # datasets.append(("Общий результат", all_values))

        for role in CONFIG[name]['roles'].keys():
            role_categories, role_values = get_role_averages_for_chart(name, role, t_id)
            if role_values:
                role_display = CONFIG[name]['roles'][role]
                datasets.append((role_display, role_values))

        conn.close()

        overall_chart = generate_multi_spider_chart(
            name,
            datasets,
            categ_locales,
            "Средние результаты по всем ролям"
        )
        return render_template('admin.html', 
                            responses=responses,
                            stats=stats,
                            role_charts=role_charts,
                            overall_chart=base64.b64encode(overall_chart.getvalue()).decode(),
                            roles=CONFIG[name]['roles'],
                            survey_name=CONFIG[name]['name'],
                            deny_detailed_view=True)

    conn = get_db_connection()
    t_id: str | int = conn.execute("SELECT MAX(team_id) FROM responses").fetchone()[0]
    if t_id is None: 
        t_id = 0
    elif isinstance(t_id,str) and not t_id.isnumeric():
        t_id = random.randint(100000,999999)
    else:
        t_id+=1
    link = config.URL_START + url_for("index", t=t_id)
    group_link = config.URL_START + url_for("group", t=t_id)
    conn.close()
    return render_template('group.html', link=link, group_link=group_link, survey_name=CONFIG[name]['name'])
    
@app.route('/group/')
def group():
    """Get a group link"""
    if 'survey_name' not in session: return redirect(url_for("index"))
    return redirect(url_for(f"group/{session['survey_name']}",t=request.args.get("t",None)))

init_db()

if __name__ == "__main__":
    app.run(debug=True)