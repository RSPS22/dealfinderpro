from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import pandas as pd
import numpy as np
from docx import Document
from datetime import datetime

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_FOLDER'] = 'generated_lois'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)

def safe_float(val):
    try:
        return float(str(val).replace(',', '').replace('$', ''))
    except:
        return np.nan

def calculate_arv(comps_df):
    price_col = next((col for col in comps_df.columns if col.strip().lower() in ['last sale amount', 'sale amount', 'sold price']), None)
    sqft_col = next((col for col in comps_df.columns if col.strip().lower() in ['living area', 'sq ft', 'sqft', 'square feet']), None)
    if not price_col or not sqft_col:
        raise ValueError("Missing required columns in comps file.")
    comps_df['$/sqft'] = comps_df[price_col].apply(safe_float) / comps_df[sqft_col].apply(safe_float)
    valid_comps = comps_df[comps_df['$/sqft'].notna()]
    if valid_comps.empty:
        return 0, 0
    avg_price_per_sqft = valid_comps['$/sqft'].mean()
    return avg_price_per_sqft, len(valid_comps)

def generate_loi(property_row, business_name, user_name, user_email):
    template_path = 'Offer_Sheet_Template.docx'
    doc = Document(template_path)
    def replace_placeholder(paragraphs, key, value):
        for para in paragraphs:
            if key in para.text:
                inline = para.runs
                for i in range(len(inline)):
                    if key in inline[i].text:
                        inline[i].text = inline[i].text.replace(key, value)
    offer_price = property_row.get("Offer Price", "")
    address = property_row.get("Address", "")
    date_today = datetime.now().strftime("%B %d, %Y")
    replace_placeholder(doc.paragraphs, "{{BUSINESS_NAME}}", business_name or "—")
    replace_placeholder(doc.paragraphs, "{{USER_NAME}}", user_name or "—")
    replace_placeholder(doc.paragraphs, "{{USER_EMAIL}}", user_email or "—")
    replace_placeholder(doc.paragraphs, "{{DATE}}", date_today)
    replace_placeholder(doc.paragraphs, "{{OFFER_PRICE}}", f"${offer_price:,.0f}" if pd.notna(offer_price) else "N/A")
    replace_placeholder(doc.paragraphs, "{{PROPERTY_ADDRESS}}", address or "—")
    filename = f"{address.replace(' ', '_')}_LOI.docx"
    file_path = os.path.join(app.config['GENERATED_FOLDER'], filename)
    doc.save(file_path)
    return filename

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/upload', methods=['POST'])
def upload():
    prop_file = request.files.get('propertyFile')
    comps_file = request.files.get('compsFile')
    business_name = request.form.get('businessName', '')
    user_name = request.form.get('userName', '')
    user_email = request.form.get('userEmail', '')

    if not prop_file or not comps_file:
        return jsonify({'error': 'Missing required files'}), 400

    prop_path = os.path.join(app.config['UPLOAD_FOLDER'], prop_file.filename)
    comps_path = os.path.join(app.config['UPLOAD_FOLDER'], comps_file.filename)
    prop_file.save(prop_path)
    comps_file.save(comps_path)

    props_df = pd.read_csv(prop_path)
    comps_df = pd.read_csv(comps_path)

    avg_price_per_sqft, comps_count = calculate_arv(comps_df)
    props_df['Condition Estimate'] = props_df['Condition Override'] if 'Condition Override' in props_df.columns else 'Medium'
    props_df['ARV'] = props_df['Living Square Feet'].apply(safe_float) * avg_price_per_sqft
    props_df['Offer Price'] = props_df['ARV'] * 0.60
    props_df['High Potential'] = props_df['Offer Price'] <= (props_df['ARV'] * 0.55)
    props_df['LOI File'] = props_df.apply(lambda row: generate_loi(row, business_name, user_name, user_email), axis=1)
    props_df['Comps Count'] = comps_count
    props_df['Avg Comp $/Sqft'] = round(avg_price_per_sqft, 2)
    props_df['LOI Sent'] = False
    props_df['Follow-Up Sent'] = False
    props_df.fillna('', inplace=True)

    columns_to_return = [
        'Address', 'City', 'State', 'Zip', 'Listing Price', 'Living Square Feet',
        'Condition Estimate', 'Condition Override', 'ARV', 'Offer Price', 'High Potential',
        'LOI File', 'LOI Sent', 'Follow-Up Sent', 'Comps Count', 'Avg Comp $/Sqft',
        'Listing Agent First Name', 'Listing Agent Last Name', 'Listing Agent Email', 'Listing Agent Phone'
    ]
    filtered_df = props_df[[col for col in columns_to_return if col in props_df.columns]]
    data = filtered_df.to_dict(orient='records')
    return jsonify({'data': data})

@app.route('/download_loi/<filename>')
def download_loi(filename):
    return send_from_directory(app.config['GENERATED_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)


