import os
from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
import string

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

@app.route('/')
def index():
    return render_template('index.html')






if __name__ == '__main__':
    app.run(debug=True)