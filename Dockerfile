# Use official Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy all files to container
COPY . .

# Install dependencies (if you have requirements.txt)
RUN pip install --no-cache-dir -r requirements.txt

# Expose port (change if your app uses another port)
EXPOSE 8000

# Run the app
CMD ["python", "app.py"]
