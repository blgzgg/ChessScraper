# Use the official Python image (Python 3.12)
FROM python:3.12-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements.txt file into the container
COPY requirements.txt .

#Upgrade pip
RUN pip install --upgrade pip

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt


# Add selenium dependencies (optional)
RUN apt-get update && apt-get install -y \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*


# Copy the current directory contents into the container at /app
COPY . .

# Set environment variables for Flask
ENV FLASK_APP=app.py
ENV FLASK_ENV=development

# Expose the port the Flask app will run on
EXPOSE 5000

# Run the application
CMD ["flask", "run", "--host=0.0.0.0"]



