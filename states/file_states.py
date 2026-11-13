"""FSM states for steps that need text typed in the chat (widgets have no text input)."""
from aiogram.fsm.state import State, StatesGroup


class ToolInput(StatesGroup):
    # data: file_id (int), tool (str), chat_id (int)
    waiting = State()
