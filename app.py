import os
import pandas as pd
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
from docx import Document
from datetime import datetime

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['LOI_FOLDER'] = 'generated_lois'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['LOI_FOLDER'], exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    try:
        # Get files
        property_file = request.files['propertyFile']
        comps_file = request.files['compsFile']

        # Save uploaded files
        prop_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(property_file.filename))
        comps_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(comps_file.filename))
        property_file.save(prop_path)
        comps_file.save(comps_path)

        # Load property and comps data
        properties_df = pd.read_csv(prop_path)
        comps_df = pd.read_csv(comps_path)

        # Validate comps file for required columns
        comps_required = ['Living Square Feet', 'Last Sale Amount']
        for col in comps_required:
            if col not in comps_df.columns:
                return jsonify({'error': f'Missing required column in comps file: {col}'}), 400

        # Clean and compute comps $/sqft
        comps_df['Living Square Feet'] = comps_df['Living Square Feet'].replace('[\$,]', '', regex=True).astype(float)
        comps_df['Last Sale Amount'] = comps_df['Last Sale Amount'].replace('[\$,]', '', regex=True).astype(float)
        comps_df['$/sqft'] = comps_df['Last Sale Amount'] / comps_df['Living Square Feet']

        avg_sqft_price = comps_df['$/sqft'].mean()

        # Calculate ARV for each property
        properties_df['Living Square Feet'] = properties_df['Living Square Feet'].replace('[\$,]', '', regex=True).astype(float)
        properties_df['ARV'] = properties_df['Living Square Feet'] * avg_sqft_price

        # Offer = 60% of ARV
        properties_df['Offer Price'] = properties_df['ARV'] * 0.6

        # High Potential if Listing Price <= 55% ARV
        properties_df['High Potential'] = properties_df.apply(
            lambda row: row['Listing Price'] <= 0.55 * row['ARV'], axis=1
        )

        # Fill default LOI metadata
        user_name = request.form.get('userName', '')
        user_email = request.form.get('userEmail', '')
        business_name = request.form.get('businessName', '')

        # Generate LOIs
        for idx, row in properties_df.iterrows():
            try:
                doc = Document("templates/Offer_Sheet_Template.docx")
                for para in doc.paragraphs:
                    para.text = para.text.replace('{ADDRESS}', str(row.get('Address', '')))
                    para.text = para.text.replace('{OFFER_PRICE}', f"${row['Offer Price']:,.0f}")
                    para.text = para.text.replace('{BUYER_NAME}', user_name)
                    para.text = para.text.replace('{BUYER_EMAIL}', user_email)
                    para.text = para.text.replace('{BUYER_BUSINESS}', business_name)

                loi_filename = f"LOI_{idx}.docx"
                loi_path = os.path.join(app.config['LOI_FOLDER'], loi_filename)
                doc.save(loi_path)
            except Exception as e:
                print(f"Error generating LOI for row {idx}: {e}")

        return jsonify({'success': True, 'message': 'Upload successful', 'rowCount': len(properties_df)})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)

