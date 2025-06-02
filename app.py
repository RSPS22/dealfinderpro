from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import pandas as pd
import numpy as np
from docx import Document
from datetime import datetime
import logging
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_FOLDER'] = 'generated_lois'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create directories if they don't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------- Utility Functions ----------

def safe_float(val):
    """Safely convert value to float, handling various formats"""
    if pd.isna(val) or val == '':
        return np.nan
    try:
        # Remove common formatting characters
        clean_val = str(val).replace(',', '').replace('$', '').replace('%', '').strip()
        return float(clean_val)
    except (ValueError, TypeError):
        return np.nan

def read_file(file_path):
    """Read CSV or Excel file with error handling"""
    try:
        if file_path.endswith('.csv'):
            return pd.read_csv(file_path)
        elif file_path.endswith(('.xlsx', '.xls')):
            return pd.read_excel(file_path)
        else:
            raise ValueError(f"Unsupported file format: {file_path}")
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {str(e)}")
        raise

def calculate_arv(comps_df):
    """Calculate ARV from comps data with improved column matching"""
    if comps_df.empty:
        logger.warning("Comps dataframe is empty")
        return 0, 0
    
    # Robust matching for price columns
    price_patterns = ['last sale amount', 'sale amount', 'sold price', 'sale price', 'price']
    price_col = None
    for pattern in price_patterns:
        price_col = next((col for col in comps_df.columns if pattern in col.strip().lower()), None)
        if price_col:
            break
    
    # Robust matching for square footage columns
    sqft_patterns = ['living square feet', 'living area', 'sq ft', 'sqft', 'square feet', 'total sqft']
    sqft_col = None
    for pattern in sqft_patterns:
        sqft_col = next((col for col in comps_df.columns if pattern in col.strip().lower()), None)
        if sqft_col:
            break
    
    if not price_col or not sqft_col:
        logger.error(f"Missing required columns. Available columns: {comps_df.columns.tolist()}")
        logger.error(f"Price column found: {price_col}, SqFt column found: {sqft_col}")
        raise ValueError(f"Missing required columns. Found price column: {price_col}, sqft column: {sqft_col}")
    
    # Calculate price per square foot
    comps_df['price_clean'] = comps_df[price_col].apply(safe_float)
    comps_df['sqft_clean'] = comps_df[sqft_col].apply(safe_float)
    
    # Filter out invalid data
    valid_mask = (comps_df['price_clean'].notna() & 
                  comps_df['sqft_clean'].notna() & 
                  (comps_df['price_clean'] > 0) & 
                  (comps_df['sqft_clean'] > 0))
    
    valid_comps = comps_df[valid_mask].copy()
    
    if valid_comps.empty:
        logger.warning("No valid comps found after filtering")
        return 0, 0
    
    # Calculate price per sqft
    valid_comps['price_per_sqft'] = valid_comps['price_clean'] / valid_comps['sqft_clean']
    
    # Remove outliers (optional - you can adjust this logic)
    q1 = valid_comps['price_per_sqft'].quantile(0.25)
    q3 = valid_comps['price_per_sqft'].quantile(0.75)
    iqr = q3 - q1
    lower_bound = q1 - 1.5 * iqr
    upper_bound = q3 + 1.5 * iqr
    
    filtered_comps = valid_comps[
        (valid_comps['price_per_sqft'] >= lower_bound) & 
        (valid_comps['price_per_sqft'] <= upper_bound)
    ]
    
    if filtered_comps.empty:
        # If no comps after outlier removal, use all valid comps
        filtered_comps = valid_comps
    
    avg_price_per_sqft = filtered_comps['price_per_sqft'].mean()
    
    logger.info(f"Calculated ARV: ${avg_price_per_sqft:.2f}/sqft from {len(filtered_comps)} comps")
    
    return avg_price_per_sqft, len(filtered_comps)

def generate_loi(property_row, business_name, user_name, user_email):
    """Generate LOI document with error handling"""
    template_path = 'Offer_Sheet_Template.docx'
    
    # Check if template exists
    if not os.path.exists(template_path):
        logger.error(f"Template file not found: {template_path}")
        raise FileNotFoundError(f"Template file not found: {template_path}")
    
    try:
        doc = Document(template_path)
    except Exception as e:
        logger.error(f"Error opening template: {str(e)}")
        raise
    
    def replace_placeholder(paragraphs, key, value):
        """Replace placeholder text in document paragraphs"""
        for para in paragraphs:
            if key in para.text:
                for run in para.runs:
                    if key in run.text:
                        run.text = run.text.replace(key, str(value))
    
    # Get property details with safe defaults
    offer_price = property_row.get("Offer Price", 0)
    address = property_row.get("Address", "Unknown Address")
    date_today = datetime.now().strftime("%B %d, %Y")
    
    # Replace placeholders
    replacements = {
        "{{BUSINESS_NAME}}": business_name or "—",
        "{{USER_NAME}}": user_name or "—",
        "{{USER_EMAIL}}": user_email or "—",
        "{{DATE}}": date_today,
        "{{OFFER_PRICE}}": f"${offer_price:,.0f}" if pd.notna(offer_price) and offer_price > 0 else "N/A",
        "{{PROPERTY_ADDRESS}}": address or "—"
    }
    
    for key, value in replacements.items():
        replace_placeholder(doc.paragraphs, key, value)
    
    # Generate safe filename
    safe_address = secure_filename(address.replace(' ', '_'))
    filename = f"{safe_address}_LOI.docx"
    file_path = os.path.join(app.config['GENERATED_FOLDER'], filename)
    
    try:
        doc.save(file_path)
        logger.info(f"LOI generated: {filename}")
        return filename
    except Exception as e:
        logger.error(f"Error saving LOI: {str(e)}")
        raise

# ---------- Routes ----------

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/upload', methods=['POST'])
def upload():
    try:
        # Validate files
        prop_file = request.files.get('propertyFile')
        comps_file = request.files.get('compsFile')
        
        if not prop_file or not comps_file:
            return jsonify({'error': 'Missing required files'}), 400
        
        if not allowed_file(prop_file.filename) or not allowed_file(comps_file.filename):
            return jsonify({'error': 'Invalid file format. Please upload CSV or Excel files.'}), 400
        
        # Get form data
        business_name = request.form.get('businessName', '').strip()
        user_name = request.form.get('userName', '').strip()
        user_email = request.form.get('userEmail', '').strip()
        
        # Save uploaded files
        prop_filename = secure_filename(prop_file.filename)
        comps_filename = secure_filename(comps_file.filename)
        
        prop_path = os.path.join(app.config['UPLOAD_FOLDER'], prop_filename)
        comps_path = os.path.join(app.config['UPLOAD_FOLDER'], comps_filename)
        
        prop_file.save(prop_path)
        comps_file.save(comps_path)
        
        # Read files
        props_df = read_file(prop_path)
        comps_df = read_file(comps_path)
        
        logger.info(f"Properties loaded: {len(props_df)} rows")
        logger.info(f"Comps loaded: {len(comps_df)} rows")
        
        # Calculate ARV
        avg_price_per_sqft, comps_count = calculate_arv(comps_df)
        
        if avg_price_per_sqft == 0:
            return jsonify({'error': 'Unable to calculate ARV from comps data'}), 400
        
        # Find living square feet column
        sqft_col = None
        for col in props_df.columns:
            if 'living square feet' in col.lower() or 'living area' in col.lower() or 'sqft' in col.lower():
                sqft_col = col
                break
        
        if not sqft_col:
            return jsonify({'error': 'Living square feet column not found in property data'}), 400
        
        # Calculate property metrics
        props_df['Condition Estimate'] = props_df.get('Condition Override', 'Medium').fillna('Medium')
        props_df['Living Square Feet Clean'] = props_df[sqft_col].apply(safe_float)
        props_df['ARV'] = props_df['Living Square Feet Clean'] * avg_price_per_sqft
        props_df['Offer Price'] = props_df['ARV'] * 0.60  # 60% of ARV
        props_df['High Potential'] = props_df['Offer Price'] <= (props_df['ARV'] * 0.55)  # 55% or less
        
        # Generate LOIs
        loi_files = []
        for idx, row in props_df.iterrows():
            try:
                loi_file = generate_loi(row, business_name, user_name, user_email)
                loi_files.append(loi_file)
            except Exception as e:
                logger.error(f"Error generating LOI for row {idx}: {str(e)}")
                loi_files.append(f"Error: {str(e)}")
        
        props_df['LOI File'] = loi_files
        props_df['Comps Count'] = comps_count
        props_df['Avg Comp $/Sqft'] = round(avg_price_per_sqft, 2)
        props_df['LOI Sent'] = False
        props_df['Follow-Up Sent'] = False
        
        # Clean up data for frontend
        props_df = props_df.fillna('')
        
        # Select columns to return
        columns_to_return = [
            'Address', 'City', 'State', 'Zip', 'Listing Price', sqft_col,
            'Condition Estimate', 'Condition Override', 'ARV', 'Offer Price', 'High Potential',
            'LOI File', 'LOI Sent', 'Follow-Up Sent', 'Comps Count', 'Avg Comp $/Sqft',
            'Listing Agent First Name', 'Listing Agent Last Name', 'Listing Agent Email', 'Listing Agent Phone'
        ]
        
        # Filter columns that actually exist
        available_columns = [col for col in columns_to_return if col in props_df.columns]
        filtered_df = props_df[available_columns]
        
        # Convert to JSON-serializable format
        data = filtered_df.to_dict(orient='records')
        
        # Clean up uploaded files
        try:
            os.remove(prop_path)
            os.remove(comps_path)
        except Exception as e:
            logger.warning(f"Could not remove uploaded files: {str(e)}")
        
        return jsonify({'data': data, 'message': f'Processed {len(data)} properties successfully'})
        
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500

@app.route('/download_loi/<filename>')
def download_loi(filename):
    try:
        # Security check - ensure filename is safe
        safe_filename = secure_filename(filename)
        file_path = os.path.join(app.config['GENERATED_FOLDER'], safe_filename)
        
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
            
        return send_from_directory(app.config['GENERATED_FOLDER'], safe_filename, as_attachment=True)
    except Exception as e:
        logger.error(f"Download error: {str(e)}")
        return jsonify({'error': 'Download failed'}), 500

@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'File too large. Maximum size is 16MB.'}), 413

if __name__ == '__main__':
    app.run(debug=True)


