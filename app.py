from flask import Flask, render_template, request, jsonify, send_file
import os
import pandas as pd
from docx import Document

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_FOLDER'] = 'generated_lois'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/upload', methods=['POST'])
def upload():
    try:
        property_file = request.files['propertyFile']
        comps_file = request.files['compsFile']
        business_name = request.form.get('businessName', '')
        user_name = request.form.get('userName', '')
        user_email = request.form.get('userEmail', '')

        prop_path = os.path.join(app.config['UPLOAD_FOLDER'], property_file.filename)
        comps_path = os.path.join(app.config['UPLOAD_FOLDER'], comps_file.filename)
        property_file.save(prop_path)
        comps_file.save(comps_path)

        props_df = pd.read_csv(prop_path)
        comps_df = pd.read_csv(comps_path)

        comps_df.columns = comps_df.columns.str.strip()
        props_df.columns = props_df.columns.str.strip()

        price_col = next((col for col in comps_df.columns if 'last sale amount' in col.lower()), None)
        sqft_col = next((col for col in comps_df.columns if 'living square feet' in col.lower()), None)

        if not price_col or not sqft_col:
            return jsonify({'error': 'Missing required columns in comps file.'}), 400

        comps_df[price_col] = comps_df[price_col].replace('[\$,]', '', regex=True).astype(float)
        comps_df[sqft_col] = comps_df[sqft_col].replace('[\$,]', '', regex=True).astype(float)

        comps_df['$/sqft'] = comps_df[price_col] / comps_df[sqft_col]
        comps_df = comps_df[comps_df['$/sqft'].notna() & comps_df['$/sqft'] != float('inf')]
        avg_price_per_sqft = comps_df['$/sqft'].mean()

        props_df['Living Square Feet'] = props_df['Living Square Feet'].replace('[\$,]', '', regex=True).astype(float)
        props_df['ARV'] = (props_df['Living Square Feet'] * avg_price_per_sqft).round(2)
        props_df['Offer Price'] = (props_df['ARV'] * 0.6).round(2)
        props_df['High Potential'] = props_df['Offer Price'] <= (props_df['ARV'] * 0.55)

        template_path = 'templates/Offer_Sheet_Template.docx'
        for i, row in props_df.iterrows():
            try:
                doc = Document(template_path)
                for p in doc.paragraphs:
                    p.text = p.text.replace('[PROPERTY_ADDRESS]', str(row.get('Address', '')))
                    p.text = p.text.replace('[OFFER_PRICE]', f"${row.get('Offer Price', 0):,.2f}")
                    p.text = p.text.replace('[BUSINESS_NAME]', business_name)
                    p.text = p.text.replace('[USER_NAME]', user_name)
                    p.text = p.text.replace('[USER_EMAIL]', user_email)
                out_path = os.path.join(app.config['GENERATED_FOLDER'], f"LOI_{i+1}.docx")
                doc.save(out_path)
                props_df.loc[i, 'LOI File'] = f"/download_loi/LOI_{i+1}.docx"
            except Exception:
                props_df.loc[i, 'LOI File'] = 'Error'

        props_df.fillna('', inplace=True)
        props_df.to_csv(os.path.join(app.config['UPLOAD_FOLDER'], 'last_processed.csv'), index=False)

        return props_df.to_json(orient='records')
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download_loi/<filename>')
def download_loi(filename):
    return send_file(os.path.join(app.config['GENERATED_FOLDER'], filename), as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)


