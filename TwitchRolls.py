from TwitchSpeaks import TWITCH_CHANNEL, MAX_WORKERS, STREAMING_ON_TWITCH, MESSAGE_RATE, MAX_QUEUE_LENGTH, handle_message
import TwitchPlays_Connection
import concurrent.futures
import time
import random
import pyautogui
import playsound

globalCharacterList = []

last_time = time.time()
message_queue = []
thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
active_tasks = []
pyautogui.FAILSAFE = False

if STREAMING_ON_TWITCH:
    t = TwitchPlays_Connection.Twitch()
    t.twitch_connect(TWITCH_CHANNEL)

class Character:
    def __init__(self, name, voice, maxHealth) -> None:
        self.name = name
        self.voice = voice

        # With the user data initialized, init the standard data
        self.assignedUser = ''
        self.maxHealth = maxHealth
        self.health = maxHealth
        self.dice = dict(weapons=4, brawl=4, hot=4, drive=4, stunts=4, wits=4, tech=4, tough=4, sneak=4)
        globalCharacterList.append(self)

    def assignUser(self, username):
        self.assignedUser = username

    def die(self):
        pass

    def heal(self, amount):
        self.health += amount
        if self.health > self.maxHealth:
            self.health = self.maxHealth

    def takeDamage(self, amount):
        self.health -= amount
        if self.health <= 0:
            self.die()

    def roll(self, skill):
        value = random.randrange(1, self.dice[skill])
        if value == self.dice[skill]:
            # Dice explodes! play an explosion sound and upgrade die
            # recursive in case it explodes again
            playsound("explosion.mp3")
            value += self.roll(skill)
        return value
    
    def reset(self):
        self.dice = dict(weapons=4, brawl=4, hot=4, drive=4, stunts=4, wits=4, tech=4, tough=4, sneak=4)
        self.health = self.maxHealth

character1 = Character("Test One", "dawn", 5)
character2 = Character("Test Two", "brit", 3)

character1.assignUser("Yakman333")
character2.assignUser("Yakman333")

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
                for character in globalCharacterList:
                    if message['username'].lower() == character.assignedUser.lower():
                        print(character.name)
                        active_tasks.append(thread_pool.submit(handle_message, message, character.voice))
            else:
                print(f'WARNING: active tasks ({len(active_tasks)}) exceeds number of workers ({MAX_WORKERS}). ({len(message_queue)} messages in the queue)')