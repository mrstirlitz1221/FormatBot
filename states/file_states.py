"""FSM states for steps that need the chat (widgets have no text input and cannot receive files)."""
from aiogram.fsm.state import State, StatesGroup


class ToolInput(StatesGroup):
    # data: file_id (int), tool (str)
    waiting = State()


class CollectFiles(StatesGroup):
    # data: file_id (int, the first file), tool (str), kind (str), extra (list[int]), prompt_id (int)
    waiting = State()


MAX_COLLECTED_FILES = 19  # plus the first file = 20
