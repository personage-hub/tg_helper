import logging
import os
import sys
import time
from datetime import datetime
from http import HTTPStatus
from logging.handlers import RotatingFileHandler

import requests
import telegram
from dotenv import load_dotenv
from requests import HTTPError, RequestException
from telegram import Message, TelegramError
from telegram.error import NetworkError

load_dotenv()

LOG_FILE = os.path.expanduser('~/main.log')
MAX_BYTES = 50000000
BACKUP_COUNT = 5

PRAKTIKUM_URL = 'https://praktikum.yandex.ru/api/user_api/homework_statuses/'
TIME_PAUSE = 5 * 60

STATUSES = {
    'reviewing': 'Работа на проверке',
    'rejected': 'К сожалению, в работе нашлись ошибки.',
    'approved': 'Ревьюеру всё понравилось, работа зачтена!'
}
PARSING_ERROR = (
    'Неверный формат данных ({data}). '
    'Данные по ключу {key} не обнаружены'
)
PARSING_TYPE_ERROR = (
    'Получены данные типа {type_1}, {type_2}. Ожидаются: str'
)
WORK_NOT_FOUND = 'Работа не найдена'
VERDICT_MESSAGE = 'У вас проверили работу "{homework_name}"!\n\n{verdict}'
DATE_ERROR = 'Неверный формат даты: {error}'
SERVER_ERROR = 'Сервер вернул ошибку {error}'
REQUEST_ERROR = (
    'Запрос к серверу завершился ошибкой ({error})'
)
TELEGRAM_NETWORK_ERROR = (
    'Во время отправки сообщения возникла ошибка ({network_error}). '
    'Сообщение ({message}) не отправлено.'
)
TELEGRAM_API_ERROR = (
    'Возникла ошибка в работе с telegram_api ({telegram_error}). '
    'Сообщение ({message}) не отправлено.'
)
SERVER_RESPONSE = (
    'Получен ответ сервера {homework_statuses}, отметка времени {timestamp}'
)
SERVICE_START_MESSAGE = 'Бот начал работу, отметка времени {timestamp}'
SERVICE_SENT_MESSAGE = 'Сообщение "{message} успешно отправлено.'
SERVICE_ERROR_MESSAGE = 'Бот упал с ошибкой ({error})'

LOG_FORMAT = logging.Formatter(
    '%(asctime)s, %(levelname)s, %(message)s, %(name)s'
)


def get_console_handler() -> logging.StreamHandler:
    """
        Log handler for console logging.
        :return: StreamHandler
        """
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(LOG_FORMAT)
    return console_handler


def get_file_handler() -> RotatingFileHandler:
    """
        Rotating log handler for file logging.
        :return: RotatingFileHandler
        """
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT
    )
    file_handler.setFormatter(LOG_FORMAT)
    return file_handler


def get_logger(logger_name: str) -> logging.Logger:
    """
        Returns Logger for console and file logging.
        :param logger_name:
        :return: logging.Logger
        """
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    logger.addHandler(get_console_handler())
    logger.addHandler(get_file_handler())
    logger.propagate = False
    return logger


bot_logger: logging.Logger = get_logger(__name__)

try:
    PRAKTIKUM_TOKEN = os.environ['PRAKTIKUM_TOKEN']
    TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
    CHAT_ID = os.environ['TELEGRAM_CHAT_ID']
except KeyError as err:
    bot_logger.error(err)
    sys.exit(err)

HEADERS = {'Authorization': f'OAuth {PRAKTIKUM_TOKEN}'}

bot = telegram.Bot(token=TELEGRAM_TOKEN)


def parse_homework_status(homework: dict) -> str:
    """
    Parse homework status.
    :param homework:
    :return: message: str
    :raise KeyError, TypeError

    """
    homework_name: str = homework.get('homework_name')
    if not homework_name:
        error_message = PARSING_ERROR.format(
            data=homework,
            key='homework_name'
        )
        bot_logger.error(error_message)
        raise KeyError(error_message)
    status: str = homework.get('status')
    if not status or status not in STATUSES.keys():
        error_message = PARSING_ERROR.format(data=homework, key='status')
        bot_logger.error(error_message)
        raise KeyError(error_message)
    verdict: str = STATUSES.get(status)
    if not all((isinstance(homework_name, str), isinstance(status, str))):
        raise TypeError(
            PARSING_TYPE_ERROR.format(
                type_1=type(homework_name),
                type_2=type(status)
            )
        )
    message: str = VERDICT_MESSAGE.format(
        homework_name=homework_name, verdict=verdict
    )
    return message


def get_homeworks(current_timestamp: int) -> dict:
    """
    Get homeworks from yandex servers through API.
    :param current_timestamp: int
    :return: homeworks: dict
    :raise HTTPError, RequestException
    """
    try:
        datetime.utcfromtimestamp(current_timestamp)
    except ValueError as error:
        logging.error(DATE_ERROR.format(error=error))
    payload = {'from_date': current_timestamp}
    requests_param = {
        'url': PRAKTIKUM_URL,
        'headers': HEADERS,
        'params': payload
    }
    try:
        response = requests.get(**requests_param)
    except RequestException as error:
        logging.error(
            REQUEST_ERROR.format(
                error=error,
                **requests_param
            )
        )
    if response.status_code == HTTPStatus.NOT_FOUND:
        raise HTTPError(SERVER_ERROR.format(error=response.status_code))
    homework_statuses = response.json()
    bot_logger.debug(homework_statuses)
    if homework_statuses.get('error') or homework_statuses.get('code'):
        raise RequestException(SERVER_ERROR.format(error=homework_statuses))
    return homework_statuses


def send_message(message):
    """
    Sending a message to author telegram account.
    :param message: str
    :return message: Message
    """
    try:
        return bot.send_message(chat_id=CHAT_ID, text=message)
    except NetworkError as network_error:
        bot_logger.error(
            TELEGRAM_NETWORK_ERROR.format(
                network_error=network_error,
                message=message
            )
        )
    except TelegramError as telegram_error:
        bot_logger.error(
            TELEGRAM_API_ERROR.format(
                telegram_error=telegram_error,
                message=message
            )
        )


def main():
    current_timestamp: int = int(time.time())
    bot_logger.info(SERVICE_START_MESSAGE.format(timestamp=current_timestamp))
    while True:
        try:
            homework_statuses: dict = get_homeworks(
                current_timestamp=current_timestamp
            )
            current_timestamp: int = homework_statuses.get(
                'current_date',
                current_timestamp
            )
            bot_logger.debug(
                SERVER_RESPONSE.format(
                    homework_statuses=homework_statuses,
                    timestamp=current_timestamp
                )
            )
            homeworks: list = homework_statuses.get('homeworks')
            if not homeworks:
                bot_logger.info(WORK_NOT_FOUND)
                time.sleep(TIME_PAUSE)
                continue
            homework: dict = homeworks[0]
            message: str = parse_homework_status(homework=homework)
            sent_message: Message = send_message(message=message)
            if sent_message:
                bot_logger.info(
                    SERVICE_SENT_MESSAGE.format(
                        message=sent_message
                    )
                )
            time.sleep(TIME_PAUSE)

        except TelegramError as e:
            bot_logger.error(e, exc_info=False)
            time.sleep(TIME_PAUSE)
        except Exception as e:
            bot_logger.error(e, exc_info=True)
            send_message(message=SERVICE_ERROR_MESSAGE.format(error=e))
            time.sleep(TIME_PAUSE)


if __name__ == '__main__':
    main()
