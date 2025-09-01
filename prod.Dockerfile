FROM python:3.12

RUN apt-get update && apt-get install -y ffmpeg
# install nodejs for pytubefix project potoken generation
RUN apt-get install -y --fix-missing nodejs npm

# Set the working directory to /app
WORKDIR /app

# Copy the requirements file into the container and install dependencies
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Copy the current directory contents into the container at /app
COPY youtube_bot.py log.py dev_loop.py /app

# Define the command to run the bot when the container starts
CMD ["python", "youtube_bot.py"]
