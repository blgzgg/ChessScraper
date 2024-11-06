import os
from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import string
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)

app.secret_key = 'your_secret_key_here'

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), nullable=False)

# Routes
@app.route('/')
def index():
    return render_template('index.html')





if __name__ == '__main__':
    app.run(debug=True)