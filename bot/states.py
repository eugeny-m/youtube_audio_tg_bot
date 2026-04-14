from aiogram.fsm.state import State, StatesGroup


class DownloadStates(StatesGroup):
    choosing_track = State()
    choosing_bitrate = State()
