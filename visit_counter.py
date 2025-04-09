from pathlib import Path
from log import get_logger


logger = get_logger()
DEFAULT_FILE_PATH = Path('config/first_visit_ids.txt').resolve()


class FirstVisitFileStorage:
    unique_ids = None
    file_path = None

    def __init__(self, file_path: Path = DEFAULT_FILE_PATH):
        self.file_path = file_path
        self.load_from_file()

    def load_from_file(self):
        unique_ids = set()
        if not self.file_path.exists():
            logger.info(f'File {self.file_path} does not exist. Creating a new one.')
            self.unique_ids = unique_ids
            self.file_path.touch()
            return

        with open(self.file_path, 'r') as file:
            for line in file:
                if line.strip():
                    unique_ids.add(int(line.strip()))
        self.unique_ids = unique_ids
        logger.info(f'Loaded {len(unique_ids)} unique IDs from {self.file_path}.')

    def save_ids_to_file(self):
        with open(self.file_path, 'w') as file_:
            for id_ in self.unique_ids:
                file_.write(f'{id_}\n')
        logger.info(f'Saved {len(self.unique_ids)} unique IDs to {self.file_path}.')

    def add_id(self, id_: int):
        if self.unique_ids is None:
            raise ValueError("Storage not initialized. Call load_from_file() first.")
        if id_ not in self.unique_ids:
            self.unique_ids.add(id_)
            logger.info(f'Added ID {id_} to storage.')
            self.save_ids_to_file()

    def get_users_count(self):
        return len(self.unique_ids)


STORAGE = None

def get_visit_storage() -> FirstVisitFileStorage:
    global STORAGE
    if STORAGE is None:
        STORAGE = FirstVisitFileStorage()
    return STORAGE
