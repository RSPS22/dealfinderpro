from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import pandas as pd
import numpy as np
from docx import Document
from datetime import datetime
import logging
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
import uuid

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_FOLDER'] = 'generated_lois'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///deals.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db = SQLAlchemy(app)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create directories if they don't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)

# Allowed file extensions
ALLOWED_EXTENSIONS = {'csv', 'xlsx', 'xls'}

# Database Models
class Property(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(36), nullable=False)
    address = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(100))
    state = db.Column(db.String(50))
    zip_code = db.Column(db.String(20))
    listing_price = db.Column(db.Float)
    living_square_feet = db.Column(db.Integer)
    condition_estimate = db.Column(db.String(50))
    arv = db.Column(db.Float)
    offer_price = db.Column(db.Float)
    high_potential = db.Column(db.Boolean, default=False)
    loi_file = db.Column(db.String(200))
    loi_sent = db.Column(db.Boolean, default=False)
    follow_up_sent = db.Column(db.Boolean, default=False)
    comps_count = db.Column(db.Integer)
    avg_comp_price_sqft = db.Column(db.Float)
    listing_agent_first_name = db.Column(db.String(100))
    listing_agent_last_name = db.Column(db.String(100))
    listing_agent_email = db.Column(db.String(200))
    listing_agent_phone = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Session(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(36), unique=True, nullable=False)
    business_name = db.Column(db.String(200))
    user_name = db.Column(db.String(100))
    user_email = db.Column(db.String(200))
    total_properties = db.Column(db.Integer, default=0)
    high_potential_count = db.Column(db.Integer, default=0)
    avg_price_per_sqft = db.Column(db.Float)
    comps_used = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ---------- Utility Functions ----------

def safe_float(val):
    """Safely convert value to float, handling various formats"""
    if pd.isna(val) or val == '' or val is None:
        return np.nan
    try:
        # Remove common formatting characters
        clean_val = str(val).replace(',', '').replace('$', '').replace('%', '').strip()
        if clean_val == '':
            return np.nan
        return float(clean_val)
    except (ValueError, TypeError):
        return np.nan

def normalize_boolean(val):
    """Normalize boolean values to consistent format"""
    if pd.isna(val) or val == '' or val is None:
        return False
    
    # Convert to string and normalize
    str_val = str(val).strip().lower()
    
    # Handle various true representations
    if str_val in ['true', 'yes', '1', 'y', 't', 'on']:
        return True
    elif str_val in ['false', 'no', '0', 'n', 'f', 'off']:
        return False
    else:
        return False

def normalize_condition(val):
    """Normalize condition values to consistent format"""
    if pd.isna(val) or val == '' or val is None:
        return 'Medium'
    
    # Convert to string and normalize
    str_val = str(val).strip().lower()
    
    # Map variations to standard values
    condition_map = {
        'excellent': 'Excellent',
        'good': 'Good', 
        'fair': 'Fair',
        'poor': 'Poor',
        'medium': 'Medium',
        'average': 'Medium',
        'high': 'Good',
        'low': 'Poor'
    }
    
    return condition_map.get(str_val, 'Medium')

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
    offer_price = safe_float(property_row.get("Offer Price", 0))
    address = str(property_row.get("Address", "Unknown Address"))
    date_today = datetime.now().strftime("%B %d, %Y")
    
    # Replace placeholders
    replacements = {
        "{{BUSINESS_NAME}}": business_name or "—",
        "{{USER_NAME}}": user_name or "—",
        "{{USER_EMAIL}}": user_email or "—",
        "{{DATE}}": date_today,
        "{{OFFER_PRICE}}": f"${offer_price:,.0f}" if not pd.isna(offer_price) and offer_price > 0 else "N/A",
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

@app.route('/api/stats')
def get_stats():
    """Get current session stats"""
    try:
        # Get latest session or return empty stats
        latest_session = Session.query.order_by(Session.updated_at.desc()).first()
        
        if not latest_session:
            return jsonify({
                'uploaded': 0,
                'highPotential': 0,
                'loisSent': 0,
                'followUps': 0,
                'user': '—',
                'lastUpdated': None,
                'metadata': {}
            })
        
        # Count follow-ups and LOIs sent for this session
        properties = Property.query.filter_by(session_id=latest_session.session_id).all()
        lois_sent = sum(1 for p in properties if p.loi_file and not p.loi_file.startswith('Error:'))
        follow_ups = sum(1 for p in properties if p.follow_up_sent)
        
        return jsonify({
            'uploaded': latest_session.total_properties,
            'highPotential': latest_session.high_potential_count,
            'loisSent': lois_sent,
            'followUps': follow_ups,
            'user': latest_session.user_name or latest_session.business_name or '—',
            'lastUpdated': latest_session.updated_at.isoformat(),
            'metadata': {
                'total_properties': latest_session.total_properties,
                'high_potential_count': latest_session.high_potential_count,
                'avg_price_per_sqft': latest_session.avg_price_per_sqft,
                'comps_used': latest_session.comps_used
            }
        })
        
    except Exception as e:
        logger.error(f"Stats error: {str(e)}")
        return jsonify({'error': 'Failed to fetch stats'}), 500

@app.route('/api/properties')
def get_properties():
    """Get properties for the latest session"""
    try:
        latest_session = Session.query.order_by(Session.updated_at.desc()).first()
        if not latest_session:
            return jsonify({'data': []})
        
        properties = Property.query.filter_by(session_id=latest_session.session_id).all()
        
        data = []
        for prop in properties:
            data.append({
                'Id': prop.id,
                'Address': prop.address,
                'City': prop.city,
                'State': prop.state,
                'Zip': prop.zip_code,
                'Listing Price': prop.listing_price,
                'Living Square Feet': prop.living_square_feet,
                'Condition Estimate': prop.condition_estimate,
                'ARV': prop.arv,
                'Offer Price': prop.offer_price,
                'High Potential': prop.high_potential,
                'LOI File': prop.loi_file,
                'LOI Sent': prop.loi_sent,
                'Follow-Up Sent': prop.follow_up_sent,
                'Comps Count': prop.comps_count,
                'Avg Comp $/Sqft': prop.avg_comp_price_sqft,
                'Listing Agent First Name': prop.listing_agent_first_name,
                'Listing Agent Last Name': prop.listing_agent_last_name,
                'Listing Agent Email': prop.listing_agent_email,
                'Listing Agent Phone': prop.listing_agent_phone
            })
        
        return jsonify({'data': data})
        
    except Exception as e:
        logger.error(f"Properties error: {str(e)}")
        return jsonify({'error': 'Failed to fetch properties'}), 500

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
        
        # Create new session
        session_id = str(uuid.uuid4())
        
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
        sqft_patterns = ['living square feet', 'living area', 'sq ft', 'sqft', 'square feet', 'total sqft']
        
        for pattern in sqft_patterns:
            sqft_col = next((col for col in props_df.columns if pattern in col.strip().lower()), None)
            if sqft_col:
                break
        
        if not sqft_col:
            logger.error(f"Living square feet column not found. Available columns: {props_df.columns.tolist()}")
            return jsonify({'error': f'Living square feet column not found in property data. Available columns: {props_df.columns.tolist()}'}), 400
        
        # Calculate property metrics
        if 'Condition Override' in props_df.columns:
            props_df['Condition Estimate'] = props_df['Condition Override'].apply(normalize_condition)
        else:
            props_df['Condition Estimate'] = 'Medium'
        
        props_df['Living Square Feet Clean'] = props_df[sqft_col].apply(safe_float)
        props_df['ARV'] = props_df['Living Square Feet Clean'] * avg_price_per_sqft
        props_df['Offer Price'] = props_df['ARV'] * 0.60
        props_df['High Potential'] = (props_df['Offer Price'] <= (props_df['ARV'] * 0.55)).apply(lambda x: bool(x))
        
        # Generate LOIs and save to database
        high_potential_count = 0
        
        for idx, row in props_df.iterrows():
            try:
                loi_file = generate_loi(row, business_name, user_name, user_email)
            except Exception as e:
                logger.error(f"Error generating LOI for row {idx}: {str(e)}")
                loi_file = f"Error: {str(e)}"
            
            # Create Property record
            property_record = Property(
                session_id=session_id,
                address=str(row.get('Address', 'Unknown Address')),
                city=str(row.get('City', '')),
                state=str(row.get('State', '')),
                zip_code=str(row.get('Zip', '')),
                listing_price=safe_float(row.get('Listing Price')),
                living_square_feet=int(safe_float(row.get(sqft_col, 0))) if not pd.isna(safe_float(row.get(sqft_col, 0))) else None,
                condition_estimate=normalize_condition(row.get('Condition Estimate')),
                arv=safe_float(row.get('ARV')),
                offer_price=safe_float(row.get('Offer Price')),
                high_potential=bool(row.get('High Potential', False)),
                loi_file=loi_file,
                loi_sent=False,
                follow_up_sent=False,
                comps_count=comps_count,
                avg_comp_price_sqft=avg_price_per_sqft,
                listing_agent_first_name=str(row.get('Listing Agent First Name', '')),
                listing_agent_last_name=str(row.get('Listing Agent Last Name', '')),
                listing_agent_email=str(row.get('Listing Agent Email', '')),
                listing_agent_phone=str(row.get('Listing Agent Phone', ''))
            )
            
            if property_record.high_potential:
                high_potential_count += 1
            
            db.session.add(property_record)
        
        # Create Session record
        session_record = Session(
            session_id=session_id,
            business_name=business_name,
            user_name=user_name,
            user_email=user_email,
            total_properties=len(props_df),
            high_potential_count=high_potential_count,
            avg_price_per_sqft=avg_price_per_sqft,
            comps_used=comps_count
        )
        
        db.session.add(session_record)
        db.session.commit()
        
        # Return data for display
        data = []
        for _, row in props_df.iterrows():
            row_dict = {
                'Address': str(row.get('Address', 'Unknown Address')),
                'City': str(row.get('City', '')),
                'State': str(row.get('State', '')),
                'Zip': str(row.get('Zip', '')),
                'Listing Price': safe_float(row.get('Listing Price')),
                sqft_col: safe_float(row.get(sqft_col)),
                'Condition Estimate': normalize_condition(row.get('Condition Estimate')),
                'ARV': safe_float(row.get('ARV')),
                'Offer Price': safe_float(row.get('Offer Price')),
                'High Potential': bool(row.get('High Potential', False)),
                'LOI Sent': False,
                'Follow-Up Sent': False,
                'Comps Count': comps_count,
                'Avg Comp $/Sqft': round(avg_price_per_sqft, 2)
            }
            
            # Add optional columns if they exist
            optional_columns = ['Listing Agent First Name', 'Listing Agent Last Name', 
                              'Listing Agent Email', 'Listing Agent Phone']
            for col in optional_columns:
                if col in props_df.columns:
                    row_dict[col] = str(row.get(col, ''))
            
            data.append(row_dict)
        
        # Clean up uploaded files
        try:
            os.remove(prop_path)
            os.remove(comps_path)
        except Exception as e:
            logger.warning(f"Could not remove uploaded files: {str(e)}")
        
        logger.info(f"Successfully processed {len(data)} properties")
        return jsonify({
            'data': data, 
            'message': f'Processed {len(data)} properties successfully',
            'session_id': session_id,
            'metadata': {
                'total_properties': len(data),
                'high_potential_count': high_potential_count,
                'avg_price_per_sqft': round(avg_price_per_sqft, 2),
                'comps_used': comps_count
            }
        })
        
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return jsonify({'error': f'Processing failed: {str(e)}'}), 500

@app.route('/download_loi/<filename>')
def download_loi(filename):
    try:
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

# Initialize database
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
