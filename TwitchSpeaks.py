import concurrent.futures
import random
import pyautogui
import requests
from playsound import playsound
import os
import re
import sys
import TwitchPlays_Connection
from TwitchPlays_KeyCodes import *
import asyncio
import websockets
import json
import threading
import wave
import numpy as np
import librosa
import soundfile as sf
import uuid

##################### GAME VARIABLES #####################

# Replace this with your Twitch username. Must be all lowercase.
TWITCH_CHANNEL = 'twitchtoprpg' 

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

# Pull secrets from consts
def read_constants():
    with open('consts.json') as file:
        consts = json.load(file)
        global ELEVENLABS_API_KEY
        global ELEVENLABS_URL
        ELEVENLABS_API_KEY = consts["APIKey"]
        ELEVENLABS_URL = consts["ElevenURL"]

read_constants()

# TTS Processing Vars
# Used for elevenlabs, needed once again
CHUNK_SIZE = 1024
url = ELEVENLABS_URL

headers = {
  "Accept": "audio/mpeg",
  "Content-Type": "application/json",
  "xi-api-key": ELEVENLABS_API_KEY
}

pyautogui.FAILSAFE = False

# Too general, maybe just have a bot remove all links in chat?
linkRegex = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"

# Necessary for OBS audio capture remaining accurate
os.system('title Character TTS')

chanceToReadMessage = 1
characterMode = False
voiceMode = 0

characterToVoice = dict()
usernameToCharacterName = dict()

##########################################################

random.seed()

WS_URL = "ws://127.0.0.1:8000"

# Websocket to local server for character-username data
async def socket_handler(socket):
    print(" ")
    print("Websocket connected")
    print(" ")

    while True:
        try:
            charData = await socket.recv()
            charJson = json.loads(charData)
            if len(charJson) != 0:
                for characterID in charJson['content']:
                    character = charJson['content'][characterID]
                    if character['username'] == "":
                        if character['name'] in usernameToCharacterName.values():
                            # Username has been cleared, remove it from the list
                            for key, value in dict(usernameToCharacterName).items():
                                if value == character['name']:
                                    del usernameToCharacterName[key]
                            print(usernameToCharacterName)
                            continue
                        else:
                            # Username hasn't been assigned yet
                            continue

                    if character['username'] in usernameToCharacterName.keys():
                        if character['name'] == usernameToCharacterName[character['username']]:
                            # This is a change other than username, don't modify anything
                            continue
                        else:
                            # This is a reassignment of a current player to a new character.
                            # Remove their old character assignment.
                            usernameToCharacterName.pop(character['username'].lower())
                        
                    usernameToCharacterName[character['username'].lower()] = character['name'].lower()
                    print(usernameToCharacterName)
        except websockets.ConnectionClosed:
            print(f"Terminated")
            break

async def socketStarter():
    async with websockets.connect(WS_URL) as ws:
        await socket_handler(ws)
        await asyncio.get_running_loop().create_future()

def socketThread(id: str):
    asyncio.run(socketStarter())

    print("We shouldn't have reached here")

# Count down before starting, so you have time to load up the game
countdown = 0
while countdown > 0:
    print(countdown)
    countdown -= 1
    time.sleep(1)

# Create the text-passing websocket thread
threading.Thread(target=socketThread, args=(9000,)).start()

if STREAMING_ON_TWITCH:
    t = TwitchPlays_Connection.Twitch()
    t.twitch_connect(TWITCH_CHANNEL)
else:
    t = TwitchPlays_Connection.YouTube()
    t.youtube_connect(YOUTUBE_CHANNEL_ID, YOUTUBE_STREAM_URL)

# Experimental function to make "voices" as quickly as possible
# Stolen from https://stackoverflow.com/questions/43963982/python-change-pitch-of-wav-file
# This did not really work, keeping it for later study
def shift_pitch(filename, shiftInHZ):
    wr = wave.open(filename, 'r')
    # Set the parameters for the output file.
    par = list(wr.getparams())
    par[3] = 0  # The number of samples will be set by writeframes.
    par = tuple(par)
    ww = wave.open('pitch1.wav', 'w')
    ww.setparams(par)

    fr = 20
    sz = wr.getframerate()//fr  # Read and process 1/fr second at a time.
    # A larger number for fr means less reverb.
    c = int(wr.getnframes()/sz)  # count of the whole file
    shift = shiftInHZ//fr  # shifting 100 Hz
    for num in range(c):
        da = np.fromstring(wr.readframes(sz), dtype=np.int16)
        left, right = da[0::2], da[1::2]  # left and right channel
        lf, rf = np.fft.rfft(left), np.fft.rfft(right)
        lf, rf = np.roll(lf, shift), np.roll(rf, shift)
        lf[0:shift], rf[0:shift] = 0, 0
        nl, nr = np.fft.irfft(lf), np.fft.irfft(rf)
        ns = np.column_stack((nl, nr)).ravel().astype(np.int16)
        ww.writeframes(ns.tostring())
    wr.close()
    ww.close()

def shift_pitch_librosa(jobId, halfStepCount):
    y, sr = librosa.load(jobId + '.wav', sr=48000) # y is a numpy array of the wav file, sr = sample rate
    y_shifted = librosa.effects.pitch_shift(y, sr=sr, n_steps=halfStepCount, bins_per_octave=24) # shifted by 4 half steps
    sf.write(jobId + 'pitchShifted.wav', y_shifted, 48000, 'PCM_24')

def handle_message(message, voiceInput = ""):
    if random.randint(1, chanceToReadMessage) != 1:
        # If the chance to read a message is one, this will never fire.
        # If there's some chance the message shouldn't be read, this will kill
        # unnecessary threads.
        return

    try:
        msg = message['message'].lower()
        username = message['username'].lower()
        voice = voiceInput

        # Check if there's a link in this message,
        # And don't read it if so
        # Solved by banning all links
        # url = re.findall(linkRegex, msg)
        # print(url)
        # if str(url) != "[]":
        #     return

        print("Got this message from " + username + ": " + msg)

        if msg[0] == '!' and not characterMode:
            # Assume this is a command to swap voices
            split = msg.split()
            subsplit = split[0].split('!')
            voice = subsplit[1]

            # Now that we have the voice, remove the voice identifier
            # from the message
            split.remove(split[0])
            msg = ' '.join(split)

        if characterMode and not voiceMode == 2:
            if characterToVoice[usernameToCharacterName[username]] != "":
                voice = characterToVoice[usernameToCharacterName[username]]

        print(msg)
        print(voice)

        jobId = str(uuid.uuid4())

        if not voiceMode == 3:
            #response = requests.post(url, json=TTSData, headers=headers)
            postResponse = requests.post("http://dionysus.headass.house:8000/create-job/", params={"username": username, "message": msg, "voice": voice})

            postResponseData = postResponse.json()
            print(postResponseData)
            jobId = postResponseData['id']

            # If we're processing with voices, sleep for a little bit.
            # This reduces server spam
            if characterMode and voiceMode != 2:
                sleepLength = float(1.0 + ((len(msg) / 20) / 2))
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
                elif jobStatusData['status'] == 'pending' or jobStatusData['status'] == 'pendingVoice':
                    print("Job is still pending - messages are very backed up or this is a voice message while voices are still initializing")
                    if characterMode and voiceMode != 2:
                        time.sleep(3.0)
                    else:
                        time.sleep(0.3)
                    retryCount += 1
                elif jobStatusData['status'] == 'working':
                    # If the job is still working, sleep for a bit
                    if characterMode and voiceMode != 2:
                        time.sleep(1.0)
                    else:
                        time.sleep(0.2)
                    retryCount += 1
                else:
                    raise Exception("Got bad status code at " + jobStatusData['status'] + ", check server for issues")

            if retryCount > 40:
                raise Exception("Too many retries!")

            audioResponse = requests.get("http://dionysus.headass.house:8000/get-audio/" + jobId, params={"id": jobId})

            with open(jobId + '.wav', 'wb') as f:
                for chunk in audioResponse.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)

            if voiceMode == 2:
                shift_pitch_librosa(jobId, characterToVoice[usernameToCharacterName[username]])
        else:
            # We're in elevenlabs voicemode, so use their API
            data = {
                "text": msg,
                "model_id": voice,
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.5
                }
            }

            response = requests.post(url, json=data, headers=headers)
            with open(jobId + '.mp3', 'wb') as f:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)

        # Sometimes audio files are coming back way too long if the text wasn't words
        # Maybe do something to estimate length of audio and cut it off if too long?
        print("playsound start")
        if voiceMode == 2:
            playsound(jobId + 'pitchShifted.wav', True)
        elif voiceMode == 3:
            playsound(jobId + '.mp3', True)
        else:
            playsound(jobId + '.wav', True)
        
        print("playsound over")
        if voiceMode == 2:
            os.remove(jobId + 'pitchShifted.wav')
        
        if voiceMode == 3:
            os.remove(jobId + '.mp3')
        else:
            os.remove(jobId + '.wav')

    except Exception as e:
        print("Encountered exception: " + str(e))

def scan_messages():
    last_time = time.time()
    message_queue = []
    thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    active_tasks = []

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
                last_time = time.time()

        if not messages_to_handle:
            continue
        else:
            for message in messages_to_handle:
                # If we're in charactermode, don't process non-character-user messages
                print(usernameToCharacterName.keys())
                print(message['username'])
                if characterMode and message['username'] not in usernameToCharacterName.keys():
                    print("skipping")
                    continue

                if len(active_tasks) <= MAX_WORKERS:
                    active_tasks.append(thread_pool.submit(handle_message, message))
                else:
                    print(f'WARNING: active tasks ({len(active_tasks)}) exceeds number of workers ({MAX_WORKERS}). ({len(message_queue)} messages in the queue)')

if sys.argv[1] == "-all":
    chanceToReadMessage = 1
elif sys.argv[1] == "-some":
    if sys.argv[2]:
        chanceToReadMessage = int(sys.argv[2])
    else:
        chanceToReadMessage = 2
elif sys.argv[1] == "-charMode":
    characterMode = True
    if sys.argv[2]:
        if sys.argv[2] == "slow":
            voiceMode = 0
            characterToVoice['lachlan macdiver'] = 'lachlan'
            characterToVoice['noirbie'] = 'noirbie'
            characterToVoice['s. quatch'] = 'quatch'
        elif sys.argv[2] == "medium":
            voiceMode = 1
        elif sys.argv[2] == "fast":
            voiceMode = 2
            characterToVoice['lachlan macdiver'] = 4
            characterToVoice['noirbie'] = -4
            characterToVoice['s. quatch'] = -10
        elif sys.argv[2] == "eleven":
            voiceMode = 3
            characterToVoice['lachlan macdiver'] = "eleven_monolingual_v1"
            characterToVoice['noirbie'] = "eleven_monolingual_v1"
            characterToVoice['s. quatch'] = "eleven_monolingual_v1"
        else:
            voiceMode = 0
    else:
        voiceMode = 0


scan_messages()