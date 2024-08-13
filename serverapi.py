from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
import torch
from TTS.api import TTS
from uuid import uuid4
from collections import deque
from starlette.status import HTTP_201_CREATED, HTTP_202_ACCEPTED
import threading
import time
import os

device = "cuda" if torch.cuda.is_available() else "cpu"

voices = dict(default="VoiceClone.wav", tori="ToriNormal.wav", corey="CoreyNormal.wav")

queues = dict(pending=deque(), working=deque(), finished=deque(), cleanup=deque())

tts = TTS("tts_models/multilingual/en/speedy-speech").to(device)
tts2 = TTS("tts_models/multilingual/en/speedy-speech").to(device)
tts3 = TTS("tts_models/multilingual/en/speedy-speech").to(device)

ttsProcessors = [tts, tts2, tts3]

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
            print('sleeping cleanup thread, no files to clean')
            time.sleep(5.0)

def process_audio(threadID):
    ttsProcessor = ttsProcessors[int(threadID / 1000)]

    while True:
        if len(queues['pending']) > 0:
            # pop left side with append right means oldest first
            newJob = queues['pending'].popleft()
            queues['working'].append(newJob)
            newJob['status'] = 'working'
            filePath = newJob['id'] + '.wav'
            print('thread ' + str(threadID) + 'picked up new job with id: ' + newJob['id'])
            
            # Check which voice we should use
            voiceToUse = voices['default']
            if newJob['voice'] != "":
                voiceToUse = voices[newJob['voice']]
            
            ttsProcessor.tts_to_file(text=newJob['_message'], speaker_wav=voiceToUse, language="en", file_path=filePath)
            newJob['status'] = 'finished'
            queues['working'].remove(newJob)
            queues['finished'].append(newJob)
            print('File processed')
        else:
            time.sleep(0.5)

def get_job(id: str, queue: str = None, order=['finished', 'working', 'pending']):
    _id = str(id)

    for queue in order:
        for job in queues[queue]:
            print(job['id'])
            if str(job['id']) == _id:
                return job, queue

    return 'not found', None # Don't let it reach this point

app = FastAPI()

# Create the audio processor threads
threading.Thread(target=process_audio, args=(1000,)).start()
threading.Thread(target=process_audio, args=(2000,)).start()
threading.Thread(target=process_audio, args=(3000,)).start()

# Create the cleanup thread
threading.Thread(target=cleanup_files, args=(80000,)).start()

class BaseJob(BaseModel):
    id: str
    _message: str = None
    voice: str = ""

class JobStatus(BaseModel):
    id: str
    status: str
    _message: str = None
    result: int = -1
    voice: str = ""

@app.get("/jobs/{id}", response_model=JobStatus, status_code=HTTP_202_ACCEPTED)
async def read_job(id: str):
    job, status = get_job(id)
    d = dict(id=job['id'], status=status, result=job.get('result', -1))
    return d

@app.post("/create-job/", response_model=JobStatus, status_code=HTTP_201_CREATED)
async def create_job(username: str, message: str, voice: str = ""):
    _job = dict(id=str(uuid4()), status='pending', _message=message, voice=voice)
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

@app.get("/get-audio")
def audio(username: str):
    return FileResponse(path=username + '.wav', filename=username + '.wav', media_type='text/wav')

@app.post("/send-text")
async def queue_text(username: str, message: str):
    tts.tts_to_file(text=message, speaker_wav="VoiceClone.wav", language="en", file_path=username + '.wav')
    return FileResponse(path=username + '.wav', filename=username + '.wav', media_type='text/wav')
