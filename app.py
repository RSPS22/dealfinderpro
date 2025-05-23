import os
import pandas as pd
from flask import Flask, render_template, request, send_from_directory, jsonify
from werkzeug.utils import secure_filename
from docx import Document
from datetime import datetime

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_LOIS_FOLDER'] = 'generated_lois'
app.config['OFFER_TEMPLATE_PATH'] = 'Offer_Sheet_Template.docx'

# Ensure folders exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_LOIS_FOLDER'], exist_ok=True)

def calculate_offer_price(arv, condition):
    condition_discounts = {
        'Light': 0.70,
        'Medium': 0.60,
        'Heavy': 0.50
    }
    discount = condition_discounts.get(condition, 0.60)
    return round(arv * discount)

def calculate_arv(property_row, comps_df):
    sqft_col = 'Living Area'
    price_col = 'Last Sale Amount'
    if sqft_col not in comps_df.columns or price_col not in comps_df.columns:
        return None, 0, 0, "Missing Columns"
    try:
        comps_df[price_col] = comps_df[price_col].replace('[\$,]', '', regex=True).astype(float)
        comps_df[sqft_col] = comps_df[sqft_col].replace('[\$,]', '', regex=True).astype(float)
    except Exception:
        return None, 0, 0, "Parse Error"

    comps_df = comps_df[comps_df[sqft_col] > 0]
    comps_df['$/sqft'] = comps_df[price_col] / comps_df[sqft_col]
    comps_df = comps_df.dropna(subset=['$/sqft'])

    if comps_df.empty:
        return None, 0, 0, "No Comps"

    avg_price_per_sqft = comps_df['$/sqft'].mean()
    property_sqft = property_row.get('Living Square Feet', 0)
    try:
        property_sqft = float(str(property_sqft).replace(',', ''))
    except Exception:
        property_sqft = 0

    arv = avg_price_per_sqft * property_sqft if property_sqft else 0
    return round(arv), len(comps_df), round(avg_price_per_sqft, 2), "OK"

def generate_loi(data, template_path, output_path):
    doc = Document(template_path)
    placeholders = {
        '[PROPERTY_ADDRESS]': data.get('Address', ''),
        '[OFFER_PRICE]': f"${int(data.get('Offer Price', 0)):,}",
        '[BUYER_NAME]': data.get('User Name', ''),
        '[BUYER_EMAIL]': data.get('User Email', ''),
        '[BUSINESS_NAME]': data.get('Business Name', ''),
        '[DATE]': datetime.now().strftime("%B %d, %Y")
    }
    for p in doc.paragraphs:
        for key, val in placeholders.items():
            if key in p.text:
                p.text = p.text.replace(key, val)
    doc.save(output_path)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    try:
        prop_file = request.files.get('propertyFile')
        comps_file = request.files.get('compsFile')
        business_name = request.form.get('businessName', '')
        user_name = request.form.get('userName', '')
        user_email = request.form.get('userEmail', '')

        prop_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(prop_file.filename))
        comps_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(comps_file.filename))
        prop_file.save(prop_path)
        comps_file.save(comps_path)

        properties = pd.read_csv(prop_path)
        comps = pd.read_csv(comps_path)

        properties['Condition Override'] = properties.get('Condition Override', 'Medium')
        results = []

        for idx, row in properties.iterrows():
            condition = row.get('Condition Override', 'Medium')
            arv, comps_used, avg_ppsf, arv_status = calculate_arv(row, comps)
            offer = calculate_offer_price(arv, condition)
            listing_price = row.get('Listing Price', 0)
            try:
                listing_price = float(str(listing_price).replace(',', '').replace('$', ''))
            except:
                listing_price = 0

            high_potential = offer <= (arv * 0.55) if arv else False
            loi_filename = f"LOI_{idx}.docx"
            loi_path = os.path.join(app.config['GENERATED_LOIS_FOLDER'], loi_filename)

            loi_data = {
                **row.to_dict(),
                'Offer Price': offer,
                'Business Name': business_name,
                'User Name': user_name,
                'User Email': user_email
            }

            generate_loi(loi_data, app.config['OFFER_TEMPLATE_PATH'], loi_path)

            results.append({
                **row,
                'ARV': arv,
                'Offer Price': offer,
                'Comps Used': comps_used,
                'Avg Comp $/Sqft': avg_ppsf,
                'High Potential': high_potential,
                'LOI File': loi_filename
            })

        results_df = pd.DataFrame(results)
        output_path = os.path.join(app.config['UPLOAD_FOLDER'], 'results.csv')
        results_df.to_csv(output_path, index=False)
        return results_df.to_json(orient='records')

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download-loi/<filename>')
def download_loi(filename):
    return send_from_directory(app.config['GENERATED_LOIS_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)


