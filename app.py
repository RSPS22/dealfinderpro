import os
import pandas as pd
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from docx import Document
import uuid

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_FOLDER'] = 'generated'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)

def format_currency(value):
    try:
        return "${:,.0f}".format(float(value))
    except:
        return "N/A"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    property_file = request.files.get('propertyFile')
    comps_file = request.files.get('compsFile')
    business_name = request.form.get('businessName', '')
    user_name = request.form.get('userName', '')
    user_email = request.form.get('userEmail', '')

    if not property_file or not comps_file:
        return jsonify({'error': 'Missing required files'}), 400

    prop_filename = secure_filename(property_file.filename)
    comps_filename = secure_filename(comps_file.filename)

    property_path = os.path.join(app.config['UPLOAD_FOLDER'], prop_filename)
    comps_path = os.path.join(app.config['UPLOAD_FOLDER'], comps_filename)

    property_file.save(property_path)
    comps_file.save(comps_path)

    try:
        df = pd.read_csv(property_path)
        comps_df = pd.read_csv(comps_path)

        if 'Living Square Feet' not in comps_df.columns or 'Last Sale Amount' not in comps_df.columns:
            return jsonify({'error': 'Missing required columns in comps file.'}), 400

        comps_df['$/sqft'] = comps_df['Last Sale Amount'].replace('[\$,]', '', regex=True).astype(float) / comps_df['Living Square Feet'].replace('[\$,]', '', regex=True).astype(float)
        avg_price_per_sqft = comps_df['$/sqft'].mean()

        df['ARV'] = df['Living Square Feet'].replace('[\$,]', '', regex=True).astype(float) * avg_price_per_sqft
        df['Offer Price'] = df['ARV'] * 0.6
        df['High Potential'] = df['Offer Price'] <= df['ARV'] * 0.55

        df['ARV'] = df['ARV'].apply(format_currency)
        df['Offer Price'] = df['Offer Price'].apply(format_currency)

        results = df.to_dict(orient='records')

        return jsonify({
            'data': results,
            'message': 'Upload and processing successful.',
            'businessName': business_name,
            'userName': user_name,
            'userEmail': user_email
        })

    except Exception as e:
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500

@app.route('/generate-loi', methods=['POST'])
def generate_loi():
    try:
        data = request.json
        address = data.get('Address')
        offer_price = data.get('Offer Price')
        business_name = data.get('Business Name')
        user_name = data.get('User Name')
        user_email = data.get('User Email')

        template_path = 'templates/Offer_Sheet_Template.docx'
        doc = Document(template_path)

        for para in doc.paragraphs:
            if "{{address}}" in para.text:
                para.text = para.text.replace("{{address}}", address or "")
            if "{{offer_price}}" in para.text:
                para.text = para.text.replace("{{offer_price}}", offer_price or "")
            if "{{business_name}}" in para.text:
                para.text = para.text.replace("{{business_name}}", business_name or "")
            if "{{user_name}}" in para.text:
                para.text = para.text.replace("{{user_name}}", user_name or "")
            if "{{user_email}}" in para.text:
                para.text = para.text.replace("{{user_email}}", user_email or "")

        filename = f"LOI_{uuid.uuid4().hex}.docx"
        filepath = os.path.join(app.config['GENERATED_FOLDER'], filename)
        doc.save(filepath)

        return jsonify({'downloadUrl': f'/download/{filename}'})

    except Exception as e:
        return jsonify({'error': f'Failed to generate LOI: {str(e)}'}), 500

@app.route('/download/<filename>')
def download_file(filename):
    filepath = os.path.join(app.config['GENERATED_FOLDER'], filename)
    return send_file(filepath, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
