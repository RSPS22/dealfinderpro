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

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/upload', methods=['POST'])
def upload():
    property_file = request.files.get('propertyFile')
    comps_file = request.files.get('compsFile')
    business_name = request.form.get('businessName', '')
    user_name = request.form.get('userName', '')
    user_email = request.form.get('userEmail', '')

    if not property_file or not comps_file:
        return jsonify({'error': 'Missing property or comps file.'}), 400

    try:
        property_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(property_file.filename))
        comps_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(comps_file.filename))
        property_file.save(property_path)
        comps_file.save(comps_path)

        props_df = pd.read_csv(property_path)
        comps_df = pd.read_csv(comps_path)

        required_cols = ['Address', 'Listing Price', 'Living Square Feet']
        comp_required_cols = ['Address', 'Last Sale Amount', 'Living Square Feet']

        if not all(col in comps_df.columns for col in comp_required_cols):
            return jsonify({'error': 'Missing required columns in comps file.'}), 400
        if not all(col in props_df.columns for col in required_cols):
            return jsonify({'error': 'Missing required columns in properties file.'}), 400

        # Clean and prepare comps
        comps_df['Last Sale Amount'] = comps_df['Last Sale Amount'].replace('[\$,]', '', regex=True).astype(float)
        comps_df['Living Square Feet'] = comps_df['Living Square Feet'].replace(',', '', regex=True).astype(float)
        comps_df['$/sqft'] = comps_df['Last Sale Amount'] / comps_df['Living Square Feet']
        comps_df.dropna(subset=['$/sqft'], inplace=True)

        avg_price_per_sqft = comps_df['$/sqft'].mean()
        props_df['Living Square Feet'] = props_df['Living Square Feet'].replace(',', '', regex=True).astype(float)
        props_df['ARV'] = props_df['Living Square Feet'] * avg_price_per_sqft
        props_df['Offer Price'] = props_df['ARV'] * 0.6

        props_df['High Potential'] = props_df['Offer Price'] <= props_df['Listing Price'] * 0.55
        props_df['LOI Sent'] = False
        props_df['Follow-Up Sent'] = False

        # Fill missing columns for display and LOI generation
        display_columns = ['Address', 'City', 'State', 'Zip Code', 'Listing Price', 'Living Square Feet', 
                           'ARV', 'Offer Price', 'High Potential', 'LOI Sent', 'Follow-Up Sent']
        for col in display_columns:
            if col not in props_df.columns:
                props_df[col] = ''

        props_df.fillna('', inplace=True)

        # Generate LOIs
        template_path = os.path.join('templates', 'Offer_Sheet_Template.docx')
        for index, row in props_df.iterrows():
            doc = Document(template_path)
            for paragraph in doc.paragraphs:
                if '[Address]' in paragraph.text:
                    paragraph.text = paragraph.text.replace('[Address]', str(row['Address']))
                if '[OfferPrice]' in paragraph.text:
                    paragraph.text = paragraph.text.replace('[OfferPrice]', f"${row['Offer Price']:,.0f}")
                if '[BusinessName]' in paragraph.text:
                    paragraph.text = paragraph.text.replace('[BusinessName]', business_name)
                if '[UserName]' in paragraph.text:
                    paragraph.text = paragraph.text.replace('[UserName]', user_name)
                if '[UserEmail]' in paragraph.text:
                    paragraph.text = paragraph.text.replace('[UserEmail]', user_email)
            loi_filename = f"LOI_{index}_{secure_filename(str(row['Address']))}.docx"
            doc.save(os.path.join(app.config['LOI_FOLDER'], loi_filename))

        # Store processed data
        props_df.to_csv('uploads/processed_properties.csv', index=False)
        return props_df.to_json(orient='records')

    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)


