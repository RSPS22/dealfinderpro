from flask import Flask, render_template, request, jsonify, send_file
import os
import pandas as pd
from docx import Document
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_FOLDER'] = 'generated_lois'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)

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

        prop_filename = secure_filename(property_file.filename)
        comps_filename = secure_filename(comps_file.filename)

        prop_path = os.path.join(app.config['UPLOAD_FOLDER'], prop_filename)
        comps_path = os.path.join(app.config['UPLOAD_FOLDER'], comps_filename)

        property_file.save(prop_path)
        comps_file.save(comps_path)

        properties_df = pd.read_csv(prop_path)
        comps_df = pd.read_csv(comps_path)

        # Clean and convert comps data
        if 'Sold Price' not in comps_df.columns or 'Living Square Feet' not in comps_df.columns:
            return jsonify({'error': 'Missing required columns in comps file.'}), 400

        comps_df['Sold Price'] = comps_df['Sold Price'].replace('[\$,]', '', regex=True)
        comps_df['Sold Price'] = pd.to_numeric(comps_df['Sold Price'], errors='coerce')

        comps_df['Living Square Feet'] = comps_df['Living Square Feet'].replace(',', '', regex=True)
        comps_df['Living Square Feet'] = pd.to_numeric(comps_df['Living Square Feet'], errors='coerce')

        comps_df.dropna(subset=['Sold Price', 'Living Square Feet'], inplace=True)

        comps_df['$/sqft'] = comps_df['Sold Price'] / comps_df['Living Square Feet']
        average_price_per_sqft = comps_df['$/sqft'].mean()

        # Compute ARV and Offer Price
        if 'Living Square Feet' in properties_df.columns:
            properties_df['Living Square Feet'] = properties_df['Living Square Feet'].replace(',', '', regex=True)
            properties_df['Living Square Feet'] = pd.to_numeric(properties_df['Living Square Feet'], errors='coerce')

        properties_df['ARV'] = properties_df['Living Square Feet'] * average_price_per_sqft
        properties_df['Offer Price'] = properties_df['ARV'] * 0.60

        # Identify High Potential
        properties_df['High Potential'] = properties_df.apply(
            lambda row: row['Offer Price'] <= row['ARV'] * 0.55 if pd.notna(row['Offer Price']) and pd.notna(row['ARV']) else False,
            axis=1
        )

        # Generate LOIs
        lois = []
        template_path = os.path.join('templates', 'Offer_Sheet_Template.docx')
        for i, row in properties_df.iterrows():
            if pd.notna(row.get('Address')) and pd.notna(row.get('Offer Price')):
                try:
                    doc = Document(template_path)
                    for paragraph in doc.paragraphs:
                        paragraph.text = paragraph.text.replace('[Property Address]', str(row.get('Address')))
                        paragraph.text = paragraph.text.replace('[Buyer Name]', user_name)
                        paragraph.text = paragraph.text.replace('[Buyer Email]', user_email)
                        paragraph.text = paragraph.text.replace('[Business Name]', business_name)
                        paragraph.text = paragraph.text.replace('[Purchase Price]', f"${row.get('Offer Price'):,.0f}")

                    file_name = f"LOI_{i}_{datetime.now().strftime('%Y%m%d%H%M%S')}.docx"
                    file_path = os.path.join(app.config['GENERATED_FOLDER'], file_name)
                    doc.save(file_path)
                    lois.append(file_name)
                except Exception as e:
                    continue

        return jsonify({
            'success': True,
            'loisGenerated': lois,
            'highPotentialCount': int(properties_df['High Potential'].sum())
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
