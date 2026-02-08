# Sales Data Analytics Web Application

A complete Sales Data Analytics dashboard built with Python (Flask), HTML, CSS, and JavaScript.

## Tech Stack
- **Backend:** Python Flask
- **Database:** SQLite (SQLAlchemy)
- **Frontend:** HTML5, CSS3, JavaScript
- **Charts:** Chart.js
- **Data Processing:** Pandas

## Features
- **User Authentication:** Login, Register, Logout.
- **Dashboard:** Overview of sales, total orders, average order value, and charts.
- **Data Upload:** Upload CSV files to populate the database.
- **Analytics:** Detailed breakdown of sales by month, category, and top products.
- **Reports:** Download standardized reports in CSV format.
- **Responsive Design:** Works on mobile, tablet, and desktop.

## Project Structure
```
/project
  /templates          # HTML templates
  /static
    /css              # Stylesheets
    /js               # JavaScript files
    /uploads          # Uploaded files directory
  app.py              # Main application logic
  models.py           # Database models
  requirements.txt    # Python dependencies
  Procfile            # Render deployment configuration
  sample_data.csv     # Sample CSV for testing
```

## Setup Instructions

### 1. Install Dependencies
Ensure you have Python installed. Run:
```bash
pip install -r requirements.txt
```

### 2. Run the Application
```bash
python app.py
```
Visit `http://127.0.0.1:5000` in your browser.

### 3. Usage
1.  **Register** a new account.
2.  **Login** with your credentials.
3.  Go to **Upload Data** page.
4.  Upload the `sample_data.csv` file provided in the root directory.
5.  Navigate to **Dashboard** and **Analytics** to view the insights.

## Deployment on Render
1.  Push this code to a GitHub repository.
2.  Log in to [Render](https://render.com/).
3.  Click **New +** -> **Web Service**.
4.  Connect your GitHub repository.
5.  Render will automatically detect the `Procfile` and `requirements.txt`.
6.  Click **Create Web Service**.

## CSV Format
If uploading your own data, ensure the CSV columns match exactly:
`Date, Category, Product, Quantity, Unit Price, Total Price`
- **Date**: YYYY-MM-DD
