import os
import pandas as pd
from flask import Flask, request, render_template, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from docx import Document
from datetime import datetime

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_LOIS_FOLDER'] = 'generated_lois'
app.config['TEMPLATE_FILE'] = 'Offer_Sheet_Template.docx'

# Ensure folders exist
if not os.path.isdir(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

if not os.path.isdir(app.config['GENERATED_LOIS_FOLDER']):
    os.makedirs(app.config['GENERATED_LOIS_FOLDER'])

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    try:
        property_file = request.files['propertyFile']
        comps_file = request.files['compsFile']
        business_name = request.form.get('businessName', '')
        user_name = request.form.get('userName', '')
        user_email = request.form.get('userEmail', '')

        # Save property and comps files
        property_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(property_file.filename))
        comps_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(comps_file.filename))
        property_file.save(property_path)
        comps_file.save(comps_path)

        # Load data
        properties_df = pd.read_csv(property_path)
        comps_df = pd.read_csv(comps_path)

        # Ensure required columns
        required_cols = ['Address', 'City', 'State', 'Zip', 'Listing Price', 'Living Square Feet']
        for col in required_cols:
            if col not in properties_df.columns:
                return jsonify({'error': f"Missing column in property file: {col}"}), 400

        if 'Last Sale Amount' not in comps_df.columns or 'Living Square Feet' not in comps_df.columns:
            return jsonify({'error': "Missing required columns in comps file."}), 400

        # Clean and calculate $/sqft in comps
        comps_df['Last Sale Amount'] = comps_df['Last Sale Amount'].replace('[\$,]', '', regex=True).astype(float)
        comps_df['Living Square Feet'] = comps_df['Living Square Feet'].replace(',', '', regex=True).astype(float)
        comps_df['$/sqft'] = comps_df['Last Sale Amount'] / comps_df['Living Square Feet']

        avg_sqft_price = comps_df['$/sqft'].mean()

        # Calculate ARV and offer price
        properties_df['Living Square Feet'] = properties_df['Living Square Feet'].replace(',', '', regex=True).astype(float)
        properties_df['ARV'] = properties_df['Living Square Feet'] * avg_sqft_price
        properties_df['Offer Price'] = properties_df['ARV'] * 0.60

        # Format prices
        properties_df['ARV'] = properties_df['ARV'].apply(lambda x: f"${x:,.0f}")
        properties_df['Offer Price'] = properties_df['Offer Price'].apply(lambda x: f"${x:,.0f}")

        # High Potential
        properties_df['High Potential'] = (
            properties_df['Offer Price'].replace('[\$,]', '', regex=True).astype(float) <=
            0.55 * properties_df['ARV'].replace('[\$,]', '', regex=True).astype(float)
        )

        # Generate LOIs
        loi_paths = []
        for idx, row in properties_df.iterrows():
            doc = Document(app.config['TEMPLATE_FILE'])
            for para in doc.paragraphs:
                para.text = para.text.replace('{property_address}', row['Address'])
                para.text = para.text.replace('{offer_price}', row['Offer Price'])
                para.text = para.text.replace('{business_name}', business_name)
                para.text = para.text.replace('{user_name}', user_name)
                para.text = para.text.replace('{user_email}', user_email)
            loi_filename = f"LOI_{idx}.docx"
            loi_path = os.path.join(app.config['GENERATED_LOIS_FOLDER'], loi_filename)
            doc.save(loi_path)
            loi_paths.append(loi_filename)

        return jsonify({'message': 'Upload successful', 'files': loi_paths})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/generated_lois/<filename>')
def download_loi(filename):
    return send_from_directory(app.config['GENERATED_LOIS_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)

