from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, send_from_directory
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
import os
import pandas as pd
from datetime import datetime
import io
import csv
import logging

from models import db, User, Sales

# Configure logging to see errors in the console/Render logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Ensure absolute path for better environment compatibility
basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__, 
            template_folder=basedir,
            static_folder=os.path.join(basedir, 'static'))

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(basedir,
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/style.css')
def style_css():
    return send_from_directory(basedir, 'style.css')

@app.route('/main.js')
def main_js():
    return send_from_directory(basedir, 'main.js')

# Use environment variable for Secret Key on Render, fallback for local development
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_secret_key_12345')

# Ensure absolute path for SQLite database to avoid issues on different environments
database_url = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(basedir, 'site.db'))
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url

app.config['UPLOAD_FOLDER'] = os.path.join(app.static_folder, 'uploads')
app.config['ALLOWED_EXTENSIONS'] = {'csv'}

# Ensure upload directory exists
try:
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
except Exception as e:
    logger.error(f"Failed to create upload folder: {e}")

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Login unsuccessful. Please check email and password', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Check if user already exists
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
    return render_template('register.html')

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        # Use modern SQLAlchemy 2.0 select syntax
        sales_data = db.session.execute(
            db.select(Sales).filter_by(user_id=current_user.id)
        ).scalars().all()

        if not sales_data:
            flash("No sales data found. Upload a CSV file.", "info")
            return redirect(url_for('upload'))
            
        df = pd.DataFrame([s.to_dict() for s in sales_data])
        
        # Ensure correct data types for pandas operations
        df['total_price'] = pd.to_numeric(df['total_price'], errors='coerce').fillna(0)
        
        total_sales = df['total_price'].sum()
        total_orders = len(df)
        avg_order_value = df['total_price'].mean() if total_orders > 0 else 0
        top_product = df.groupby('product')['total_price'].sum().idxmax() if not df.empty else 'N/A'
        
        return render_template('dashboard.html', 
                               total_sales=total_sales, 
                               total_orders=total_orders, 
                               avg_order_value=avg_order_value, 
                               top_product=top_product,
                               sales_data=sales_data)
    except Exception as e:
        logger.error(f"Dashboard Error: {str(e)}")
        flash(f"An error occurred while loading the dashboard: {str(e)}", "danger")
        return redirect(url_for('home'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('No file part', 'danger')
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            flash('No selected file', 'danger')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)
            
            try:
                df = pd.read_csv(filepath)
                
                # Column mapping for flexibility
                column_mapping = {
                    'Date': ['Date', 'date', 'order_date'],
                    'Category': ['Category', 'category', 'Product Category'],
                    'Product': ['Product', 'product', 'item'],
                    'Quantity': ['Quantity', 'quantity', 'Qty', 'qty'],
                    'Unit Price': ['Unit Price', 'unit_price', 'Unit_Price', 'price'],
                    'Total Price': ['Total Price', 'total_price', 'Total_Sales', 'total_sales', 'sales', 'Sales']
                }

                parsed_df = pd.DataFrame()
                for standard_name, aliases in column_mapping.items():
                    found_col = None
                    for alias in aliases:
                        if alias in df.columns:
                            found_col = alias
                            break
                    if found_col:
                        parsed_df[standard_name] = df[found_col]
                    else:
                        flash(f'CSV missing required column: {standard_name} (or its common variations)', 'danger')
                        return redirect(request.url)

                for _, row in parsed_df.iterrows():
                    try:
                        # Handle potential date format issues
                        sale_date = pd.to_datetime(row['Date']).date()
                        sale = Sales(
                            date=sale_date,
                            category=row['Category'],
                            product=row['Product'],
                            quantity=int(row['Quantity']),
                            unit_price=float(row['Unit Price']),
                            total_price=float(row['Total Price']),
                            user_id=current_user.id
                        )
                        db.session.add(sale)
                    except Exception as date_err:
                        # Skip invalid rows or handle error
                        continue
                        
                db.session.commit()
                flash('File uploaded and processed successfully!', 'success')
                return redirect(url_for('dashboard'))
            except Exception as e:
                flash(f'Error processing file: {str(e)}', 'danger')
                return redirect(request.url)
    return render_template('upload.html')

@app.route('/analytics')
@login_required
def analytics():
    try:
        sales_data = db.session.execute(
            db.select(Sales).filter_by(user_id=current_user.id)
        ).scalars().all()

        if not sales_data:
            flash("No data for analytics. Upload CSV first.", "warning")
            return redirect(url_for('upload'))
            
        df = pd.DataFrame([s.to_dict() for s in sales_data])
        
        # Example Analytics: Sales per Month
        df['date'] = pd.to_datetime(df['date'])
        df['total_price'] = pd.to_numeric(df['total_price'], errors='coerce').fillna(0)
        
        monthly_sales = df.groupby(df['date'].dt.to_period('M'))['total_price'].sum().to_dict()
        # Convert period index to string
        monthly_sales = {str(k): v for k, v in monthly_sales.items()}
        
        category_sales = df.groupby('category')['total_price'].sum().to_dict()
        product_performance = df.groupby('product')['total_price'].sum().sort_values(ascending=False).head(5).to_dict()
        
        return render_template('analytics.html', 
                               monthly_sales=monthly_sales, 
                               category_sales=category_sales, 
                               product_performance=product_performance)
    except Exception as e:
        logger.error(f"Analytics Error: {str(e)}")
        flash(f"An error occurred while loading analytics: {str(e)}", "danger")
        return redirect(url_for('dashboard'))

@app.route('/reports')
@login_required
def reports():
    return render_template('reports.html')

@app.route('/download_report')
@login_required
def download_report():
    sales = Sales.query.filter_by(user_id=current_user.id).all()
    
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Date', 'Category', 'Product', 'Quantity', 'Unit Price', 'Total Price'])
    for sale in sales:
        cw.writerow([sale.date, sale.category, sale.product, sale.quantity, sale.unit_price, sale.total_price])
        
    output = io.BytesIO()
    output.write(si.getvalue().encode('utf-8'))
    output.seek(0)
    
    return send_file(output, mimetype="text/csv", as_attachment=True, download_name="sales_report.csv")


@app.route('/api/dashboard-data')
@login_required
def dashboard_data_api():
    sales_data = Sales.query.filter_by(user_id=current_user.id).order_by(Sales.date.asc()).all()
    if not sales_data:
        return jsonify({'sales_trend': {}, 'category_sales': {}})
        
    df = pd.DataFrame([s.to_dict() for s in sales_data])
    df['date'] = pd.to_datetime(df['date'])
    
    # Sales Trend (Daily)
    daily_sales = df.groupby('date')['total_price'].sum().to_dict()
    daily_sales = {k.strftime('%Y-%m-%d'): v for k, v in daily_sales.items()}
    
    # Category Sales
    category_sales = df.groupby('category')['total_price'].sum().to_dict()
    
    return jsonify({
        'sales_trend': daily_sales,
        'category_sales': category_sales
    })

@app.route('/api/analytics-data')
@login_required
def analytics_data_api():
    sales_data = Sales.query.filter_by(user_id=current_user.id).all()
    if not sales_data:
        return jsonify({'monthly_sales': {}, 'category_sales': {}, 'product_performance': {}})
        
    df = pd.DataFrame([s.to_dict() for s in sales_data])
    
    # Monthly Sales
    df['date'] = pd.to_datetime(df['date'])
    monthly_sales = df.groupby(df['date'].dt.to_period('M'))['total_price'].sum().to_dict()
    monthly_sales = {str(k): v for k, v in monthly_sales.items()}
    
    # Category Sales
    category_sales = df.groupby('category')['total_price'].sum().to_dict()
    
    # Top Products
    product_performance = df.groupby('product')['total_price'].sum().sort_values(ascending=False).head(5).to_dict()
    
    return jsonify({
        'monthly_sales': monthly_sales,
        'category_sales': category_sales,
        'product_performance': product_performance
    })

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=False)
