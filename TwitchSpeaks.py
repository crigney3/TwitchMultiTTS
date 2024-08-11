import concurrent.futures
import random
import pyautogui
import requests
from playsound import playsound
import os
import TwitchPlays_Connection
from TwitchPlays_KeyCodes import *

##################### GAME VARIABLES #####################

# Replace this with your Twitch username. Must be all lowercase.
TWITCH_CHANNEL = 'yakman333' 

# If streaming on Youtube, set this to False
STREAMING_ON_TWITCH = True

# Replace this with your Youtube's Channel ID
# Find this by clicking your Youtube profile pic -> Settings -> Advanced Settings
YOUTUBE_CHANNEL_ID = "YOUTUBE_CHANNEL_ID_HERE" 

# If you're using an Unlisted stream to test on Youtube, replace "None" below with your stream's URL in quotes.
# Otherwise you can leave this as "None"
YOUTUBE_STREAM_URL = None

##################### MESSAGE QUEUE VARIABLES #####################

# MESSAGE_RATE controls how fast we process incoming Twitch Chat messages. It's the number of seconds it will take to handle all messages in the queue.
# This is used because Twitch delivers messages in "batches", rather than one at a time. So we process the messages over MESSAGE_RATE duration, rather than processing the entire batch at once.
# A smaller number means we go through the message queue faster, but we will run out of messages faster and activity might "stagnate" while waiting for a new batch. 
# A higher number means we go through the queue slower, and messages are more evenly spread out, but delay from the viewers' perspective is higher.
# You can set this to 0 to disable the queue and handle all messages immediately. However, then the wait before another "batch" of messages is more noticeable.
MESSAGE_RATE = 0.5
# MAX_QUEUE_LENGTH limits the number of commands that will be processed in a given "batch" of messages. 
# e.g. if you get a batch of 50 messages, you can choose to only process the first 10 of them and ignore the others.
# This is helpful for games where too many inputs at once can actually hinder the gameplay.
# Setting to ~50 is good for total chaos, ~5-10 is good for 2D platformers
MAX_QUEUE_LENGTH = 20
MAX_WORKERS = 100 # Maximum number of threads you can process at a time 

# TTS Processing Vars
# Used for elevenlabs, no longer needed
CHUNK_SIZE = 1024
url = "https://api.elevenlabs.io/v1/text-to-speech/pqHfZKP75CvOlQylNhV4"

headers = {
  "Accept": "audio/mpeg",
  "Content-Type": "application/json",
  "xi-api-key": "sk_af4a39d82eea6f20d5d30723168cf529172c9593251c6217"
}

last_time = time.time()
message_queue = []
thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
active_tasks = []
pyautogui.FAILSAFE = False

##########################################################

# Count down before starting, so you have time to load up the game
countdown = 0
while countdown > 0:
    print(countdown)
    countdown -= 1
    time.sleep(1)

if STREAMING_ON_TWITCH:
    t = TwitchPlays_Connection.Twitch()
    t.twitch_connect(TWITCH_CHANNEL)
else:
    t = TwitchPlays_Connection.YouTube()
    t.youtube_connect(YOUTUBE_CHANNEL_ID, YOUTUBE_STREAM_URL)

def handle_message(message):
    try:
        msg = message['message'].lower()
        username = message['username'].lower()
        voice = ""

        print("Got this message from " + username + ": " + msg)

        # Deprecated
        TTSData = {
          "text": msg,
          "model_id": "eleven_multilingual_v2",
          "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.5
          }
        }

        if msg[0] == '!':
            # Assume this is a command to swap voices
            split = msg.split()
            subsplit = split[0].split('!')
            voice = subsplit[1]

            # Now that we have the voice, remove the voice identifier
            # from the message
            split.remove(split[0])
            msg = ' '.join(split)

        print(msg)
        print(voice)

        #response = requests.post(url, json=TTSData, headers=headers)
        postResponse = requests.post("http://dionysus.headass.house:8000/create-job/", params={"username": "yakman333", "message": msg, "voice": voice})

        postResponseData = postResponse.json()
        print(postResponseData)
        jobId = postResponseData['id']

        # TTS seems to take a min of 2 seconds to process.
        # Basic guess is that it takes another second per 20 characters.
        # This sleep keeps the script from spamming the server to check if its
        # file is ready yet.
        sleepLength = float(2 + (len(msg) / 10))
        print("sleeping for: " + str(sleepLength))
        time.sleep(sleepLength)

        # keep a count to ensure we don't fail unexpectedly and ping forever
        retryCount = 0
        while True:
            if retryCount > 40:
                break
            jobStatus = requests.get('http://dionysus.headass.house:8000/jobs/' + jobId, params={"id": jobId})
            jobStatusData = jobStatus.json()
            if jobStatusData['status'] == 'finished':
                break
            elif jobStatusData['status'] == 'pending':
                print("Job is still pending - are messages very backed up?")
                time.sleep(sleepLength)
                retryCount += 1
            elif jobStatusData['status'] == 'working':
                # If the job is still working, sleep for a bit
                time.sleep(1.0)
                retryCount += 1
            else:
                raise Exception("Got bad status code, check server for issues")
        
        if retryCount > 40:
            raise Exception("Too many retries!")

        audioResponse = requests.get("http://dionysus.headass.house:8000/get-audio/" + jobId, params={"id": jobId})

        #response = requests.get("http://dionysus.headass.house:8000/get-audio", params={"username": "yakman333"})
        with open(jobId + '.wav', 'wb') as f:
            for chunk in audioResponse.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
            
            #f.close()

        print("playsound start")
        playsound(jobId + '.wav', True)
        print("playsound over")
        os.remove(jobId + '.wav')

    except Exception as e:
        print("Encountered exception: " + str(e))


# TODO: Add thread that handles playing the sound files as a queue which the messages worker will assign to.
# Could maybe also handle the TTS request, which would provide tracking and pacing of sending the requests so no more than 2 are ever active
# Queue response thread can check if it's currently processing a message by username and not process the next one by username until it's finished

while True:

    active_tasks = [t for t in active_tasks if not t.done()]

    #Check for new messages
    new_messages = t.twitch_receive_messages();
    if new_messages:
        message_queue += new_messages; # New messages are added to the back of the queue
        message_queue = message_queue[-MAX_QUEUE_LENGTH:] # Shorten the queue to only the most recent X messages

    messages_to_handle = []
    if not message_queue:
        # No messages in the queue
        last_time = time.time()
    else:
        # Determine how many messages we should handle now
        r = 1 if MESSAGE_RATE == 0 else (time.time() - last_time) / MESSAGE_RATE
        n = int(r * len(message_queue))
        if n > 0:
            # Pop the messages we want off the front of the queue
            messages_to_handle = message_queue[0:n]
            del message_queue[0:n]
            last_time = time.time();

    if not messages_to_handle:
        continue
    else:
        for message in messages_to_handle:
            if len(active_tasks) <= MAX_WORKERS:
                active_tasks.append(thread_pool.submit(handle_message, message))
            else:
                print(f'WARNING: active tasks ({len(active_tasks)}) exceeds number of workers ({MAX_WORKERS}). ({len(message_queue)} messages in the queue)')