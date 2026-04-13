# Global state object the voice pipeline writes to and the UI reads from
state = {
    "status": "idle",              # idle | wake | listening | thinking | responding
    "transcript": "",
    "response": "",
    "second_brain_status": "ready" # ready | working | error
}
