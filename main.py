from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import os
from datetime import datetime
import base64
from io import BytesIO

app = Flask(__name__)
import config
app.secret_key = config.SECRET_KEY

# Database setup
def init_db():
    conn = sqlite3.connect('survey.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS responses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  timestamp TEXT,
                  name TEXT,
                  q1 INTEGER, q2 INTEGER, q3 INTEGER, 
                  q4 INTEGER, q5 INTEGER, q6 INTEGER,
                  q7 INTEGER, q8 INTEGER)''')
    conn.commit()
    conn.close()

# Questions for the survey
QUESTIONS = [
    "How satisfied are you with the product quality?",
    "How would you rate the customer service?",
    "How likely are you to recommend us to others?",
    "How easy was the product to use?",
    "How would you rate the value for money?",
    "How satisfied are you with the delivery time?",
    "How would you rate the website experience?",
    "How likely are you to purchase from us again?"
]

# Category labels for the spider chart
CATEGORIES = [
    'Quality', 'Service', 'Recommend', 'Ease of Use',
    'Value', 'Delivery', 'Website', 'Loyalty'
]

def get_db_connection():
    conn = sqlite3.connect('survey.db')
    conn.row_factory = sqlite3.Row
    return conn

def generate_spider_chart(values, title, filename=None):
    """Generate a spider/radar chart"""
    # Number of variables
    N = len(CATEGORIES)
    
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
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(CATEGORIES, size=10)
    
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

def get_average_responses():
    """Calculate average responses from all users"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''SELECT AVG(q1) as q1_avg, AVG(q2) as q2_avg, AVG(q3) as q3_avg,
                        AVG(q4) as q4_avg, AVG(q5) as q5_avg, AVG(q6) as q6_avg,
                        AVG(q7) as q7_avg, AVG(q8) as q8_avg
                 FROM responses''')
    result = c.fetchone()
    conn.close()
    
    if result and result[0] is not None:  # Check if there's data
        averages = [result[0], result[1], result[2], result[3],
                   result[4], result[5], result[6], result[7]]
        return averages
    else:
        return [5, 5, 5, 5, 5, 5, 5, 5]  # Default values if no data

@app.route('/')
def index():
    """Home page with survey form"""
    return render_template('survey.html', questions=QUESTIONS)

@app.route('/submit', methods=['POST'])
def submit():
    """Handle survey submission"""
    if request.method == 'POST':
        # Get form data
        name = request.form.get('name', 'Anonymous')
        responses = []
        for i in range(1, 9):
            responses.append(int(request.form.get(f'q{i}', 5)))
        
        # Save to database
        conn = get_db_connection()
        c = conn.cursor()
        c.execute('''INSERT INTO responses (timestamp, name, q1, q2, q3, q4, q5, q6, q7, q8)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                  (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), name,
                   responses[0], responses[1], responses[2], responses[3],
                   responses[4], responses[5], responses[6], responses[7]))
        conn.commit()
        response_id = c.lastrowid
        conn.close()
        
        # Store in session for immediate display
        session['last_response'] = {
            'id': response_id,
            'name': name,
            'responses': responses
        }
        
        flash('Thank you for completing the survey!', 'success')
        return redirect(url_for('results'))

@app.route('/results')
def results():
    """Show individual results with spider chart"""
    if 'last_response' not in session:
        return redirect(url_for('index'))
    
    response = session['last_response']
    chart_url = generate_spider_chart(
        response['responses'], 
        f"Your Results - {response['name']}"
    )
    
    return render_template('results.html', 
                         chart_url=chart_url,
                         name=response['name'],
                         responses=response['responses'],
                         categories=CATEGORIES)

@app.route('/admin')
def admin():
    """Admin page showing all responses and average spider chart"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM responses ORDER BY timestamp DESC')
    responses = c.fetchall()
    conn.close()
    
    # Generate average spider chart
    avg_responses = get_average_responses()
    avg_chart_url = generate_spider_chart(
        avg_responses, 
        "Average Results Across All Users"
    )
    
    return render_template('admin.html', 
                         responses=responses,
                         avg_chart_url=avg_chart_url,
                         categories=CATEGORIES)

@app.route('/response/<int:response_id>')
def view_response(response_id):
    """View individual response with spider chart (for admin)"""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT * FROM responses WHERE id = ?', (response_id,))
    response = c.fetchone()
    conn.close()
    
    if not response:
        flash('Response not found', 'error')
        return redirect(url_for('admin'))
    
    responses = [response[3], response[4], response[5], response[6],
                response[7], response[8], response[9], response[10]]
    
    chart_url = generate_spider_chart(
        responses, 
        f"Results for {response[2]} - {response[1]}"
    )
    
    return render_template('view_response.html',
                         response=response,
                         chart_url=chart_url,
                         responses=responses,
                         categories=CATEGORIES)

# def main():
init_db()
#     app.run(debug=True)
# if __name__ == '__main__': main()