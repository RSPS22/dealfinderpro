import os
import pandas as pd
from flask import Flask, render_template, request, send_from_directory
from werkzeug.utils import secure_filename
from docx import Document
from datetime import datetime
import uuid

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_FOLDER'] = 'generated_lois'
app.config['TEMPLATE_PATH'] = 'Offer_Sheet_Template.docx'

# Ensure necessary folders exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    property_file = request.files['propertyFile']
    comps_file = request.files['compsFile']
    business_name = request.form.get('businessName', '')
    user_name = request.form.get('userName', '')
    user_email = request.form.get('userEmail', '')

    # Save uploaded files
    prop_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(property_file.filename))
    comps_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(comps_file.filename))
    property_file.save(prop_path)
    comps_file.save(comps_path)

    # Load property and comps data
    properties_df = pd.read_csv(prop_path)
    comps_df = pd.read_csv(comps_path)

    # Ensure required columns exist
    required_columns = ['Address', 'City', 'State', 'Zip', 'Listing Price', 'Living Square Feet']
    comps_required = ['Address', 'Living Square Feet', 'Last Sale Amount']

    if not all(col in properties_df.columns for col in required_columns):
        return 'Missing required columns in properties file.', 400
    if not all(col in comps_df.columns for col in comps_required):
        return 'Missing required columns in comps file.', 400

    # Calculate $/sqft for comps
    comps_df['$/sqft'] = comps_df['Last Sale Amount'].replace('[\$,]', '', regex=True).astype(float) / comps_df['Living Square Feet'].replace(',', '', regex=True).astype(float)

    def calculate_arv(row):
        sqft = row['Living Square Feet']
        if pd.isna(sqft):
            return None
        try:
            sqft = float(str(sqft).replace(',', ''))
        except:
            return None
        filtered_comps = comps_df[
            comps_df['Living Square Feet'].replace(',', '', regex=True).astype(float).between(sqft - 250, sqft + 250)
        ]
        if not filtered_comps.empty:
            avg_price_per_sqft = filtered_comps['$/sqft'].mean()
            return round(avg_price_per_sqft * sqft, 2)
        return None

    properties_df['ARV'] = properties_df.apply(calculate_arv, axis=1)
    properties_df['Offer Price'] = properties_df['ARV'] * 0.6
    properties_df['High Potential'] = properties_df.apply(lambda row: row['Offer Price'] <= row['ARV'] * 0.55 if not pd.isna(row['ARV']) and not pd.isna(row['Offer Price']) else False, axis=1)

    # Format prices
    properties_df['ARV'] = properties_df['ARV'].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else 'N/A')
    properties_df['Offer Price'] = properties_df['Offer Price'].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else 'N/A')

    # Generate LOI files
    for _, row in properties_df.iterrows():
        if isinstance(row['Offer Price'], str) and row['Offer Price'].startswith('$'):
            offer_price_clean = row['Offer Price'].replace('$', '').replace(',', '')
        else:
            offer_price_clean = str(row['Offer Price'])

        doc = Document(app.config['TEMPLATE_PATH'])
        for p in doc.paragraphs:
            p.text = p.text.replace('{{address}}', str(row['Address']))
            p.text = p.text.replace('{{offer_price}}', offer_price_clean)
            p.text = p.text.replace('{{user_name}}', user_name)
            p.text = p.text.replace('{{user_email}}', user_email)
            p.text = p.text.replace('{{business_name}}', business_name)

        filename = f"LOI_{uuid.uuid4().hex[:8]}.docx"
        doc_path = os.path.join(app.config['GENERATED_FOLDER'], filename)
        doc.save(doc_path)

    return 'Upload successful. LOIs generated.', 200

@app.route('/generated_lois/<filename>')
def download_loi(filename):
    return send_from_directory(app.config['GENERATED_FOLDER'], filename)

if __name__ == '__main__':
    app.run(debug=True)



