from collections import Counter
from pathlib import Path
from log import get_logger


logger = get_logger()
FIRST_VISIT_FILE_PATH = Path('config/first_visit_ids.txt').resolve()
BOT_USAGE_FILE_PATH = Path('config/bot_usage.txt').resolve()


class FirstVisitFileStorage:
    unique_ids = None
    file_path = None

    def __init__(self, file_path: Path = FIRST_VISIT_FILE_PATH):
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


class BotUsageLogger:
    def __init__(self, file_path: Path = BOT_USAGE_FILE_PATH):
        self.file_path = Path(file_path)
        if not self.file_path.exists():
            logger.info(f'File {self.file_path} does not exist. Creating a new one.')
            self.file_path.touch()

    def append(self, user_id: int):
        """Append a new user ID to the file."""
        with self.file_path.open('a', encoding='utf-8') as f:
            f.write(f"{user_id}\n")

    def count_ids(self) -> dict:
        """Count occurrences of each user ID in the file."""
        if not self.file_path.exists():
            return {}
        with self.file_path.open('r', encoding='utf-8') as f:
            ids = [int(line.strip()) for line in f if line.strip()]
        return dict(Counter(ids))

    def top_counts(self, counts: dict[int, int], min_count: int = 1, limit: int = 30) -> list[int]:
        """
        Return up to `limit` usage counts greater than `min_count`,
        sorted from most to least frequent.
        """
        filtered_counts = [count_ for count_ in counts.values() if count_ > min_count]
        return sorted(filtered_counts, reverse=True)[:limit]

    def get_stats(self, all_users_set: set[int]) -> tuple[tuple]:
        counts = self.count_ids()

        usage_analytics = []
        max_usage = 10
        for i in range(1, max_usage + 1):
            users_count = len([user_id for user_id, count_ in counts.items() if count_ == i])
            if not users_count:
                continue
            usage_analytics.append(f'{users_count} used {i} times')
        users_count = len([user_id for user_id, count_ in counts.items() if count_ > max_usage])
        usage_analytics.append(f'{users_count} used > {i} times')

        result = (
            ("all_users_count", len(all_users_set)),
            ("users_who_used_bot", len(counts)),
            ('usage_analytics', usage_analytics),
        )
        return result

    @staticmethod
    def get_analytics_formatted_string(analytics: tuple[tuple]):
        readable = ''
        for key, value in analytics:
            if isinstance(value, list):
                readable += f'{key}:\n'
                for sub_val in value:
                    readable += f'    {sub_val}\n'
                continue
            
            readable += f'{key}: {value}\n'
        return readable


# Singleton instance of FirstVisitFileStorage
STORAGE = None

def get_visit_storage() -> FirstVisitFileStorage:
    global STORAGE
    if STORAGE is None:
        STORAGE = FirstVisitFileStorage()
    return STORAGE
