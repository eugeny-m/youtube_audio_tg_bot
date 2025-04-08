# syntax=docker/dockerfile:experimental
# Use an official Python runtime as a parent image
FROM python:3.12.4

RUN apt-get update && apt-get install -y ffmpeg

# Set the working directory to /app
WORKDIR /app

# Copy the requirements file into the container and install dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY youtube_bot.py /app

# Define the command to run the bot when the container starts
CMD ["python3", "youtube_bot.py"]
