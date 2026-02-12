from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, send_from_directory
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
import os
import pandas as pd
from datetime import datetime
import io
import csv
import logging
import secrets
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from models import db, User, Sales

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base directory
basedir = os.path.abspath(os.path.dirname(__file__))

# Initialize Flask - Keep templates in root, static in root for Render
app = Flask(__name__, 
           template_folder='.',  # Templates in root directory
           static_folder='.',    # Static files in root directory
           static_url_path='')   # Serve from root URL

# App Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Database Configuration
database_url = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(basedir, 'site.db'))
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
app.config['ALLOWED_EXTENSIONS'] = {'csv'}

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except:
        return None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/favicon.ico')
def favicon():
    if os.path.exists(os.path.join(basedir, 'favicon.ico')):
        return send_from_directory(basedir, 'favicon.ico')
    return '', 204

@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        try:
            user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
            if user and user.check_password(password):
                login_user(user)
                next_page = request.args.get('next')
                return redirect(next_page) if next_page else redirect(url_for('dashboard'))
            else:
                flash('Login unsuccessful. Please check email and password', 'danger')
        except Exception as e:
            logger.error(f"Login error: {e}")
            flash('Database error. Please try again.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
            if user:
                flash('Email already registered', 'warning')
                return redirect(url_for('register'))
            
            new_user = User(username=username, email=email)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            flash('Account created! You can now login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            logger.error(f"Registration error: {e}")
            flash('Registration failed. Please try again.', 'danger')
            db.session.rollback()
            
    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        sales_data = db.session.execute(db.select(Sales).filter_by(user_id=current_user.id)).scalars().all()
        if not sales_data:
            return render_template('dashboard.html', total_sales=0, total_orders=0, avg_order_value=0, top_product='N/A', sales_data=[])
            
        df = pd.DataFrame([s.to_dict() for s in sales_data])
        df['total_price'] = pd.to_numeric(df['total_price'], errors='coerce').fillna(0)
        total_sales = df['total_price'].sum()
        total_orders = len(df)
        avg_order_value = df['total_price'].mean() if total_orders > 0 else 0
        
        # Fix: Better top product handling
        top_product = 'N/A'
        if not df.empty and 'product' in df.columns and 'total_price' in df.columns:
            product_sales = df.groupby('product')['total_price'].sum()
            if not product_sales.empty:
                top_product = product_sales.idxmax()
        
        return render_template('dashboard.html', 
                             total_sales=total_sales, 
                             total_orders=total_orders, 
                             avg_order_value=avg_order_value, 
                             top_product=top_product, 
                             sales_data=sales_data)
    except Exception as e:
        logger.error(f"Dashboard Error: {str(e)}")
        flash("Error loading dashboard data", "danger")
        return redirect(url_for('upload'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part', 'danger')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No file selected', 'danger')
            return redirect(request.url)
        if not allowed_file(file.filename):
            flash('Please upload a valid CSV file.', 'danger')
            return redirect(request.url)
        
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
        file.save(filepath)
        
        try:
            # FIXED: Better CSV parsing with multiple encoding support
            try:
                df = pd.read_csv(filepath, encoding='utf-8')
            except UnicodeDecodeError:
                try:
                    df = pd.read_csv(filepath, encoding='latin1')
                except:
                    df = pd.read_csv(filepath, encoding='cp1252')
            
            # Normalize column names
            df.columns = [str(c).strip().lower().replace(' ', '_').replace('-', '_') for c in df.columns]
            
            # FIXED: Comprehensive column mapping
            column_map = {}
            
            # Date column
            date_keywords = ['date', 'order_date', 'transaction_date', 'day', 'timestamp', 'orderdate', 'sales_date']
            for col in df.columns:
                if any(keyword in col for keyword in date_keywords):
                    column_map['date'] = col
                    break
            
            # Category column
            cat_keywords = ['category', 'type', 'group', 'dept', 'department', 'product_category', 'cat']
            for col in df.columns:
                if any(keyword in col for keyword in cat_keywords):
                    column_map['category'] = col
                    break
            
            # Product column
            prod_keywords = ['product', 'item', 'name', 'sku', 'product_name', 'item_name', 'description']
            for col in df.columns:
                if any(keyword in col for keyword in prod_keywords):
                    column_map['product'] = col
                    break
            
            # Quantity column
            qty_keywords = ['quantity', 'qty', 'count', 'units', 'qty_sold', 'units_sold']
            for col in df.columns:
                if any(keyword in col for keyword in qty_keywords):
                    column_map['quantity'] = col
                    break
            
            # Unit price column
            unit_keywords = ['unit_price', 'unit price', 'price', 'rate', 'unit_cost', 'unitprice']
            for col in df.columns:
                if any(keyword in col.replace('_', ' ') for keyword in unit_keywords):
                    column_map['unit_price'] = col
                    break
            
            # Total price column
            total_keywords = ['total_price', 'total price', 'total', 'sales', 'amount', 'revenue', 'total_sales']
            for col in df.columns:
                if any(keyword in col.replace('_', ' ') for keyword in total_keywords):
                    column_map['total_price'] = col
                    break

            # Check if we have essential columns
            if 'date' not in column_map or ('product' not in column_map and 'total_price' not in column_map):
                flash('CSV format not recognized. Need at least Date and Product or Total Price columns.', 'danger')
                return redirect(request.url)

            # Clear existing data
            db.session.execute(db.delete(Sales).filter_by(user_id=current_user.id))
            
            count = 0
            for _, row in df.iterrows():
                try:
                    # Parse date
                    date_col = column_map.get('date')
                    if date_col:
                        try:
                            parsed_date = pd.to_datetime(row[date_col], errors='coerce')
                            if pd.isna(parsed_date):
                                parsed_date = datetime.now()
                        except:
                            parsed_date = datetime.now()
                    else:
                        parsed_date = datetime.now()
                    
                    # Parse total price
                    total_val = 0
                    if 'total_price' in column_map:
                        try:
                            total_str = str(row[column_map['total_price']])
                            total_str = total_str.replace('$', '').replace('€', '').replace('£', '').replace(',', '').strip()
                            total_val = float(total_str) if total_str else 0
                        except:
                            total_val = 0
                    
                    # Parse unit price and quantity
                    unit_val = 0
                    qty_val = 1
                    
                    if 'unit_price' in column_map:
                        try:
                            unit_str = str(row[column_map['unit_price']])
                            unit_str = unit_str.replace('$', '').replace('€', '').replace('£', '').replace(',', '').strip()
                            unit_val = float(unit_str) if unit_str else 0
                        except:
                            unit_val = 0
                    
                    if 'quantity' in column_map:
                        try:
                            qty_val = int(float(row[column_map['quantity']])) if pd.notna(row[column_map['quantity']]) else 1
                        except:
                            qty_val = 1
                    
                    # Calculate total if not provided
                    if total_val == 0 and unit_val > 0:
                        total_val = unit_val * qty_val
                    
                    # Skip if no valid total
                    if total_val == 0:
                        continue
                    
                    sale = Sales(
                        date=parsed_date.date(),
                        category=str(row.get(column_map.get('category', ''), 'General'))[:100],
                        product=str(row.get(column_map.get('product', ''), 'Unknown Product'))[:150],
                        quantity=qty_val,
                        unit_price=unit_val,
                        total_price=total_val,
                        user_id=current_user.id
                    )
                    db.session.add(sale)
                    count += 1
                    
                    # Commit in batches
                    if count % 100 == 0:
                        db.session.commit()
                        
                except Exception as e:
                    logger.warning(f"Skipping row: {e}")
                    continue
            
            db.session.commit()
            flash(f'Successfully imported {count} sales records!', 'success')
            return redirect(url_for('dashboard'))
            
        except Exception as e:
            logger.error(f"Processing Error: {str(e)}")
            flash(f'Error processing file: {str(e)}', 'danger')
            db.session.rollback()
        finally:
            # Clean up uploaded file
            try:
                os.remove(filepath)
            except:
                pass
                
    return render_template('upload.html')

@app.route('/analytics')
@login_required
def analytics():
    try:
        sales_data = db.session.execute(db.select(Sales).filter_by(user_id=current_user.id)).scalars().all()
        if not sales_data:
            flash('Upload data first to view analytics', 'warning')
            return redirect(url_for('upload'))
            
        df = pd.DataFrame([s.to_dict() for s in sales_data])
        df['date'] = pd.to_datetime(df['date'])
        
        # Monthly sales
        monthly_sales = df.groupby(df['date'].dt.to_period('M'))['total_price'].sum().to_dict()
        monthly_sales = {str(k): round(v, 2) for k, v in monthly_sales.items()}
        
        # Category sales
        category_sales = df.groupby('category')['total_price'].sum().to_dict()
        category_sales = {k: round(v, 2) for k, v in category_sales.items()}
        
        # Product performance
        product_perf = df.groupby('product')['total_price'].sum().sort_values(ascending=False).head(5).to_dict()
        product_perf = {k: round(v, 2) for k, v in product_perf.items()}
        
        return render_template('analytics.html', 
                             monthly_sales=monthly_sales, 
                             category_sales=category_sales, 
                             product_performance=product_perf)
    except Exception as e:
        logger.error(f"Analytics Error: {str(e)}")
        flash('Error loading analytics data', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')

@app.route('/download_report')
@login_required
def download_report():
    sales = db.session.execute(db.select(Sales).filter_by(user_id=current_user.id)).scalars().all()
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Date', 'Category', 'Product', 'Quantity', 'Unit Price', 'Total Price'])
    for s in sales:
        cw.writerow([s.date, s.category, s.product, s.quantity, s.unit_price, s.total_price])
    output = io.BytesIO()
    output.write(si.getvalue().encode('utf-8'))
    output.seek(0)
    return send_file(output, 
                    mimetype="text/csv", 
                    as_attachment=True, 
                    download_name=f"sales_report_{datetime.now().strftime('%Y%m%d')}.csv")

@app.route('/clear-data')
@login_required
def clear_data():
    try:
        db.session.execute(db.delete(Sales).filter_by(user_id=current_user.id))
        db.session.commit()
        flash('Dashboard data cleared.', 'success')
    except Exception as e:
        logger.error(f"Clear data error: {e}")
        db.session.rollback()
        flash('Error clearing data.', 'danger')
    return redirect(url_for('upload'))

@app.route('/api/dashboard-data')
@login_required
def dashboard_data_api():
    try:
        sales_data = db.session.execute(db.select(Sales).filter_by(user_id=current_user.id).order_by(Sales.date.asc())).scalars().all()
        if not sales_data:
            return jsonify({'sales_trend': {}, 'category_sales': {}})
        
        df = pd.DataFrame([s.to_dict() for s in sales_data])
        df['date'] = pd.to_datetime(df['date'])
        daily_sales = df.groupby(df['date'].dt.strftime('%Y-%m-%d'))['total_price'].sum().to_dict()
        category_sales = df.groupby('category')['total_price'].sum().to_dict()
        
        # Round values
        daily_sales = {k: round(v, 2) for k, v in daily_sales.items()}
        category_sales = {k: round(v, 2) for k, v in category_sales.items()}
        
        return jsonify({'sales_trend': daily_sales, 'category_sales': category_sales})
    except Exception as e:
        logger.error(f"API Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics-data')
@login_required
def analytics_data_api():
    try:
        sales_data = db.session.execute(db.select(Sales).filter_by(user_id=current_user.id)).scalars().all()
        if not sales_data:
            return jsonify({})
        
        df = pd.DataFrame([s.to_dict() for s in sales_data])
        df['date'] = pd.to_datetime(df['date'])
        
        monthly = df.groupby(df['date'].dt.strftime('%Y-%m'))['total_price'].sum().to_dict()
        cat = df.groupby('category')['total_price'].sum().to_dict()
        prod = df.groupby('product')['total_price'].sum().to_dict()
        
        # Round values
        monthly = {k: round(v, 2) for k, v in monthly.items()}
        cat = {k: round(v, 2) for k, v in cat.items()}
        prod = {k: round(v, 2) for k, v in prod.items()}
        
        return jsonify({
            'monthly_sales': monthly, 
            'category_sales': cat, 
            'product_performance': prod
        })
    except Exception as e:
        logger.error(f"Analytics API Error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# Create tables
with app.app_context():
    try:
        db.create_all()
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")

if __name__ == '__main__':
    app.run(debug=True)