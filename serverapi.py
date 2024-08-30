from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import torch
from TTS.api import TTS
from uuid import uuid4
from collections import deque
from starlette.status import HTTP_201_CREATED, HTTP_202_ACCEPTED
import threading
import time
import os
import asyncio
import websockets

device = "cuda" if torch.cuda.is_available() else "cpu"

voices = dict(default="VoiceClone.wav", dawn="ToriNormal.wav", corey="CoreyNormal.wav", brit="VoiceClone.wav")

queues = dict(pending=deque(), pendingVoice=deque(), working=deque(), finished=deque(), cleanup=deque())

activeUsernames = []
lastActiveUsernameMessage = dict()

textConnections = set()

tts = TTS("tts_models/en/ljspeech/tacotron2-DDC_ph").to(device)
tts2 = TTS("tts_models/en/ljspeech/tacotron2-DDC_ph").to(device)
tts3 = TTS("tts_models/en/ljspeech/tacotron2-DDC_ph").to(device)

voice1 = ""#TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
voice2 = ""#TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
voice3 = ""#TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

ttsProcessors = [tts, tts2, tts3]
ttsVoiceProcess = [voice1, voice2, voice3]

def cleanup_files(threadID):
    while True:
        if len(queues['cleanup']) > 0:
            print('got file to cleanup')
            newJob = queues['cleanup'].popleft()

            # If the requester never takes their file,
            # we should eventually delete it
            # Until that limit, wait for it to be marked as cleanup
            retryCount = 0
            while True:
                if newJob['status'] == 'cleanup':
                    print('file marked as cleanup')
                    break
                else:
                    retryCount += 1
                    if retryCount > 20:
                        break
                    time.sleep(5.0)
            # sleep for a bit to ensure the file isn't still being streamed
            time.sleep(5.0)
            filePath = newJob['id'] + '.wav'
            os.remove(filePath)
        else:
            time.sleep(5.0)

def process_audio(threadID):
    ttsProcessor = ttsProcessors[int(threadID / 1000) - 1]

    while True:
        if len(queues['pending']) > 0:
            # pop left side with append right means oldest first
            newJob = queues['pending'].popleft()

            # Check if this is a voiced message, and if so
            # pass it off to the other tts processor type
            voiceToUse = voices['default']
            if newJob['voice'] != "":
                queues['pendingVoice'].append(newJob)
            else:
                queues['working'].append(newJob)
                newJob['status'] = 'working'
                filePath = newJob['id'] + '.wav'
                print('thread ' + str(threadID) + 'picked up new job with id: ' + newJob['id'])

                ttsProcessor.tts_to_file(text=newJob['_message'], speaker_wav=voiceToUse, file_path=filePath)
                newJob['status'] = 'finished'
                queues['working'].remove(newJob)
                queues['finished'].append(newJob)
                print('File processed')
        else:
            time.sleep(0.5)

def process_audio_voice(threadID):
    ttsProcessor = ttsVoiceProcess[int(threadID / 10000) - 1]

    print("TTS for thread " + str(threadID) + " initialized.")

    while True:
        if len(queues['pendingVoice']) > 0:
            # pop left side with append right means oldest first
            newJob = queues['pendingVoice'].popleft()
            queues['working'].append(newJob)
            newJob['status'] = 'working'
            filePath = newJob['id'] + '.wav'
            print('thread ' + str(threadID) + 'picked up new job with id: ' + newJob['id'])
            
            # Check which voice we should use
            voiceToUse = voices['default']
            if newJob['voice'] != "":
                if newJob['voice'] in voices:
                    voiceToUse = voices[newJob['voice']]
            
            ttsProcessor.tts_to_file(text=newJob['_message'], speaker_wav=voiceToUse, language="en", file_path=filePath)
            newJob['status'] = 'finished'
            queues['working'].remove(newJob)
            queues['finished'].append(newJob)

            # Check if this text should be saved for the current
            # active username
            if newJob['_username'].lower() in activeUsernames:
                lastActiveUsernameMessage[newJob['_username'].lower()] = newJob['_message']

            print('File processed')
        else:
            time.sleep(0.5)

def get_job(id: str, queue: str = None, order=['finished', 'working', 'pendingVoice', 'pending']):
    _id = str(id)

    for queue in order:
        for job in queues[queue]:
            if str(job['id']) == _id:
                return job, queue

    return 'not found', None # Don't let it reach this point

def get_finished_job_by_username(user: str):
    for job in queues['finished']:
        if job['_username'] == user:
            return job

    return 'not found' "Don't let it reach this point"

# Experimental websockets for text
async def socket_handler(socket):
    if socket not in textConnections:
        textConnections.add(socket)
    data = await socket.recv()
    reply = ""
    if data.username.lower() in activeUsernames:
        reply = lastActiveUsernameMessage[data.username.lower()]
    await socket.send(reply)

def socketThread(id: str):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    asyncio.get_event_loop().run_until_complete(websockets.serve(socket_handler, "localhost", 8051))
    asyncio.get_event_loop().run_forever()

app = FastAPI()

# Solve CORS errors and up security by defining what can access the server
# But I don't think I can add my desktop as a specific domain, so I guess it's wildcard time
# In future, update to allow_origins_regex with some pattern matching Dionysus

app.add_middleware(CORSMiddleware,
                   allow_origins=["*"],
                   allow_credentials=True,
                   allow_methods=["*"],
                   allow_headers=["*"])

# Create the basic audio processor threads
threading.Thread(target=process_audio, args=(1000,)).start()
threading.Thread(target=process_audio, args=(2000,)).start()
threading.Thread(target=process_audio, args=(3000,)).start()

# Create the voiced audio processor threads
# threading.Thread(target=process_audio_voice, args=(10000,)).start()
# threading.Thread(target=process_audio_voice, args=(20000,)).start()
# threading.Thread(target=process_audio_voice, args=(30000,)).start()

# Create the cleanup thread
threading.Thread(target=cleanup_files, args=(80000,)).start()

# Create the text-passing websocket thread
threading.Thread(target=socketThread, args=(90000,)).start()

class BaseJob(BaseModel):
    id: str
    _message: str = None
    voice: str = ""
    _username: str = None

class JobStatus(BaseModel):
    id: str
    status: str
    _message: str = None
    result: int = -1
    voice: str = ""
    _username: str = None

@app.get("/jobs/{id}", response_model=JobStatus, status_code=HTTP_202_ACCEPTED)
async def read_job(id: str):
    job, status = get_job(id)
    d = dict(id=job['id'], status=status, result=job.get('result', -1))
    return d

@app.post("/create-job/", response_model=JobStatus, status_code=HTTP_201_CREATED)
async def create_job(username: str, message: str, voice: str = ""):
    _job = dict(id=str(uuid4()), status='pending', _message=message, voice=voice, _username=username.lower())
    # Don't make threads here - have 3-5 permanent worker threads checking the queue
    queues['pending'].append(_job)
    return(_job)

@app.get("/get-root")
async def read_root():
    return {"Message": "test"}

@app.get("/get-audio/{id}")
def audioById(id: str):
    # We shouldn't ever call this from client until the job is complete
    job, status = get_job(id)
    filePath = job['id'] + '.wav'
    job['status'] = 'cleanup'
    queues['finished'].remove(job)
    queues['cleanup'].append(job)
    return FileResponse(path=filePath, filename=filePath, media_type='text/wav')

@app.post("/set-username/", status_code=HTTP_201_CREATED)
async def set_username_as_active(username: str):
    activeUsernames.append(username.lower())

@app.post("/remove-username/", status_code=HTTP_201_CREATED)
async def remove_username_as_active(username: str):
    if username.lower() in lastActiveUsernameMessage:
        lastActiveUsernameMessage.pop(username.lower())

    if username.lower() in activeUsernames:
        activeUsernames.remove(username.lower())

@app.post("/clear-usernames/", status_code=HTTP_201_CREATED)
async def clear_active_usernames():
    lastActiveUsernameMessage.clear()
    activeUsernames.clear()

# @app.get("/get-text/{username}")
# async def get_text_for_active_username(username: str):
#     if username.lower() in activeUsernames:
#         if username.lower() in lastActiveUsernameMessage:
#             return {"Message": lastActiveUsernameMessage[username.lower()]}
#         else:
#             return {"Message": ""}
#     else:
#         return {"Message": ""}

# asyncio.get_event_loop().run_until_complete(start_server)
# asyncio.get_event_loop().run_forever()

# Deprecated
@app.get("/get-audio")
def audio(username: str):
    return FileResponse(path=username + '.wav', filename=username + '.wav', media_type='text/wav')

# Deprecated
@app.post("/send-text")
async def queue_text(username: str, message: str):
    tts.tts_to_file(text=message, speaker_wav="VoiceClone.wav", language="en", file_path=username + '.wav')
    return FileResponse(path=username + '.wav', filename=username + '.wav', media_type='text/wav')
