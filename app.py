import os
import pandas as pd
from flask import Flask, render_template, request, send_file, redirect, url_for, session, jsonify
from werkzeug.utils import secure_filename
from docx import Document
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'your_secret_key'

UPLOAD_FOLDER = 'uploads'
GENERATED_FOLDER = 'generated_lois'
TEMPLATE_PATH = 'Offer_Sheet_Template.docx'

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(GENERATED_FOLDER, exist_ok=True)

@app.route('/')
def index():
    props = session.get('properties', [])
    return render_template('index.html', properties=props)

@app.route('/dashboard')
def dashboard():
    props = session.get('properties', [])
    total = len(props)
    high_potential = sum(1 for p in props if p.get('High Potential') == 'Yes')
    loi_sent = sum(1 for p in props if p.get('LOI Sent') == True)
    followup_sent = sum(1 for p in props if p.get('Follow-Up Sent') == True)
    return render_template('dashboard.html', total=total, high_potential=high_potential,
                           loi_sent=loi_sent, followup_sent=followup_sent)

@app.route('/upload', methods=['POST'])
def upload():
    prop_file = request.files.get('propertyFile')
    if not prop_file:
        return 'No property file provided', 400

    prop_filename = secure_filename(prop_file.filename)
    prop_path = os.path.join(UPLOAD_FOLDER, prop_filename)
    prop_file.save(prop_path)

    try:
        props_df = pd.read_csv(prop_path)
        props_df.fillna('', inplace=True)

        # Add columns if not present
        for col in ['LOI Sent', 'Follow-Up Sent', 'High Potential']:
            if col not in props_df.columns:
                props_df[col] = False if col != 'High Potential' else ''

        # Determine high potential (Offer Price <= 55% of ARV)
        def flag_high(row):
            try:
                return 'Yes' if float(row.get('Offer Price', 0)) <= 0.55 * float(row.get('ARV', 0)) else 'No'
            except:
                return 'No'

        props_df['High Potential'] = props_df.apply(flag_high, axis=1)
        session['properties'] = props_df.to_dict(orient='records')
        return redirect(url_for('index'))

    except Exception as e:
        return f"Error processing file: {e}", 500

@app.route('/generate_loi/<int:prop_id>', methods=['POST'])
def generate_loi(prop_id):
    props = session.get('properties', [])
    if 0 <= prop_id < len(props):
        prop = props[prop_id]
        doc = Document(TEMPLATE_PATH)

        # Replace placeholders
        for p in doc.paragraphs:
            for key, val in prop.items():
                placeholder = f'{{{{{key}}}}}'
                if placeholder in p.text:
                    p.text = p.text.replace(placeholder, str(val))

        filename = f"LOI_{prop.get('Address', 'Property')}_{datetime.now().strftime('%Y%m%d%H%M%S')}.docx"
        filepath = os.path.join(GENERATED_FOLDER, filename)
        doc.save(filepath)

        props[prop_id]['LOI Sent'] = True
        session['properties'] = props
        return send_file(filepath, as_attachment=True)

    return "Invalid property index", 400

@app.route('/update_status/<int:prop_id>', methods=['POST'])
def update_status(prop_id):
    status_type = request.form.get('type')
    props = session.get('properties', [])
    if 0 <= prop_id < len(props) and status_type in ['LOI Sent', 'Follow-Up Sent']:
        props[prop_id][status_type] = True
        session['properties'] = props
        return jsonify(success=True)
    return jsonify(success=False)

if __name__ == '__main__':
    app.run(debug=True)



