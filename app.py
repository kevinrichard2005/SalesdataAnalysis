from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, send_from_directory
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.utils import secure_filename
import os
import pandas as pd
from datetime import datetime
import io
import csv
import logging
import jinja2

from models import db, User, Sales

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Base directory
basedir = os.path.abspath(os.path.dirname(__file__))

# Initialize Flask
app = Flask(__name__)

# App Configuration
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'premium_secret_key_888')
database_url = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(basedir, 'site.db'))
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'static', 'uploads')
app.config['ALLOWED_EXTENSIONS'] = {'csv'}

if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


@app.route('/favicon.ico')
def favicon():
    if os.path.exists(os.path.join(basedir, 'static', 'favicon.ico')):
        return send_from_directory(os.path.join(basedir, 'static'), 'favicon.ico')
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
        user = db.session.execute(db.select(User).filter_by(email=email)).scalar_one_or_none()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Login unsuccessful. Please check email and password', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
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
        sales_data = db.session.execute(db.select(Sales).filter_by(user_id=current_user.id)).scalars().all()
        if not sales_data:
            return render_template('dashboard.html', total_sales=0, total_orders=0, avg_order_value=0, top_product='N/A', sales_data=[])
            
        df = pd.DataFrame([s.to_dict() for s in sales_data])
        df['total_price'] = pd.to_numeric(df['total_price'], errors='coerce').fillna(0)
        total_sales = df['total_price'].sum()
        total_orders = len(df)
        avg_order_value = df['total_price'].mean() if total_orders > 0 else 0
        top_product = df.groupby('product')['total_price'].sum().idxmax() if not df.empty else 'N/A'
        return render_template('dashboard.html', total_sales=total_sales, total_orders=total_orders, avg_order_value=avg_order_value, top_product=top_product, sales_data=sales_data)
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
        if file.filename == '' or not allowed_file(file.filename):
            flash('Please upload a valid CSV file.', 'danger')
            return redirect(request.url)
        
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
        file.save(filepath)
        
        try:
            df = pd.read_csv(filepath)
            df.columns = [c.strip().lower() for c in df.columns]
            
            # Smart fuzzy mapping
            def find_col(possible_names):
                for name in possible_names:
                    if name.lower() in df.columns:
                        return name.lower()
                return None

            date_col = find_col(['date', 'order date', 'timestamp', 'day'])
            cat_col = find_col(['category', 'type', 'group', 'dept'])
            prod_col = find_col(['product', 'item', 'name', 'sku'])
            qty_col = find_col(['quantity', 'qty', 'count', 'units'])
            unit_col = find_col(['unit price', 'price', 'rate', 'cost'])
            total_col = find_col(['total price', 'total', 'sales', 'amount', 'revenue'])

            if not any([date_col, prod_col, total_col]):
                flash('CSV format not recognized. Missing essential columns like Date, Product, or Total Price.', 'danger')
                return redirect(request.url)

            db.session.execute(db.delete(Sales).filter_by(user_id=current_user.id))
            
            count = 0
            for _, row in df.iterrows():
                try:
                    total_val = float(str(row.get(total_col, 0)).replace('$', '').replace(',', '')) if total_col else 0
                    unit_val = float(str(row.get(unit_col, 0)).replace('$', '').replace(',', '')) if unit_col else 0
                    qty_val = int(row.get(qty_col, 1)) if qty_col else 1
                    
                    if total_val == 0 and unit_val > 0:
                        total_val = unit_val * qty_val

                    parsed_date = pd.to_datetime(row.get(date_col), errors='coerce')
                    if pd.isna(parsed_date):
                        parsed_date = datetime.now()
                    
                    sale = Sales(
                        date=parsed_date.date(),
                        category=str(row.get(cat_col, 'General')),
                        product=str(row.get(prod_col, 'Unknown Item')),
                        quantity=qty_val,
                        unit_price=unit_val,
                        total_price=total_val,
                        user_id=current_user.id
                    )
                    db.session.add(sale)
                    count += 1
                except Exception as e:
                    logger.warning(f"Skipping row due to error: {e}")
                    continue
            
            db.session.commit()
            flash(f'Successfully imported {count} sales records!', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f'Processing Error: {str(e)}', 'danger')
    return render_template('upload.html')

@app.route('/analytics')
@login_required
def analytics():
    sales_data = db.session.execute(db.select(Sales).filter_by(user_id=current_user.id)).scalars().all()
    if not sales_data: return redirect(url_for('upload'))
    df = pd.DataFrame([s.to_dict() for s in sales_data])
    df['date'] = pd.to_datetime(df['date'])
    monthly_sales = df.groupby(df['date'].dt.to_period('M'))['total_price'].sum().to_dict()
    category_sales = df.groupby('category')['total_price'].sum().to_dict()
    product_perf = df.groupby('product')['total_price'].sum().sort_values(ascending=False).head(5).to_dict()
    return render_template('analytics.html', monthly_sales={str(k):v for k,v in monthly_sales.items()}, category_sales=category_sales, product_performance=product_perf)

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
    for s in sales: cw.writerow([s.date, s.category, s.product, s.quantity, s.unit_price, s.total_price])
    output = io.BytesIO()
    output.write(si.getvalue().encode('utf-8'))
    output.seek(0)
    return send_file(output, mimetype="text/csv", as_attachment=True, download_name="sales_report.csv")

@app.route('/clear-data')
@login_required
def clear_data():
    db.session.execute(db.delete(Sales).filter_by(user_id=current_user.id))
    db.session.commit()
    flash('Dashboard data cleared.', 'success')
    return redirect(url_for('upload'))

@app.route('/api/dashboard-data')
@login_required
def dashboard_data_api():
    sales_data = db.session.execute(db.select(Sales).filter_by(user_id=current_user.id).order_by(Sales.date.asc())).scalars().all()
    if not sales_data: return jsonify({'sales_trend': {}, 'category_sales': {}})
    df = pd.DataFrame([s.to_dict() for s in sales_data])
    df['date'] = pd.to_datetime(df['date'])
    daily_sales = df.groupby(df['date'].dt.strftime('%Y-%m-%d'))['total_price'].sum().to_dict()
    category_sales = df.groupby('category')['total_price'].sum().to_dict()
    return jsonify({'sales_trend': daily_sales, 'category_sales': category_sales})

@app.route('/api/analytics-data')
@login_required
def analytics_data_api():
    sales_data = db.session.execute(db.select(Sales).filter_by(user_id=current_user.id)).scalars().all()
    if not sales_data: return jsonify({})
    df = pd.DataFrame([s.to_dict() for s in sales_data])
    df['date'] = pd.to_datetime(df['date'])
    monthly = df.groupby(df['date'].dt.strftime('%Y-%m'))['total_price'].sum().to_dict()
    cat = df.groupby('category')['total_price'].sum().to_dict()
    prod = df.groupby('product')['total_price'].sum().to_dict()
    return jsonify({'monthly_sales': monthly, 'category_sales': cat, 'product_performance': prod})

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
