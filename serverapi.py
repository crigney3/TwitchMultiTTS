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

device = "cuda" if torch.cuda.is_available() else "cpu"

print(device)

queues = dict(pending=deque(), working=deque(), finished=deque())

tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

def process_audio(threadID):
    while True:
        if len(queues['pending']) > 0:
            # pop left side with append right means oldest first
            newJob = queues['pending'].popleft()
            queues['working'].append(newJob)
            newJob['status'] = 'working'
            filePath = newJob['id'] + '.wav'
            print('thread ' + str(threadID) + 'picked up new job with id: ' + newJob['id'])
            tts.tts_to_file(text=newJob['_message'], speaker_wav="VoiceClone.wav", language="en", file_path=filePath)
            newJob['status'] = 'finished'
            queues['working'].remove(newJob)
            queues['finished'].append(newJob)
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

threading.Thread(target=process_audio, args=(1000,)).start()
threading.Thread(target=process_audio, args=(2000,)).start()
threading.Thread(target=process_audio, args=(3000,)).start()

class BaseJob(BaseModel):
    id: str
    _message: str = None

class JobStatus(BaseModel):
    id: str
    status: str
    _message: str = None
    result: int = -1

@app.get("/jobs/{id}", response_model=JobStatus, status_code=HTTP_202_ACCEPTED)
async def read_job(id: str):
    job, status = get_job(id)
    d = dict(id=job['id'], status=status, result=job.get('result', -1))
    return d

@app.post("/create-job/", response_model=JobStatus, status_code=HTTP_201_CREATED)
async def create_job(username: str, message: str):
    _job = dict(id=str(uuid4()), status='pending', _message=message)
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
    return FileResponse(path=filePath, filename=filePath, media_type='text/wav')

@app.get("/get-audio")
def audio(username: str):
    return FileResponse(path=username + '.wav', filename=username + '.wav', media_type='text/wav')

@app.post("/send-text")
async def queue_text(username: str, message: str):
    tts.tts_to_file(text=message, speaker_wav="VoiceClone.wav", language="en", file_path=username + '.wav')
    return FileResponse(path=username + '.wav', filename=username + '.wav', media_type='text/wav')
