# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

import logging
from typing import Type, Optional

from ufo.automator.app_apis.basic import WinCOMReceiverBasic, ReceiverBasic
from ufo.automator.app_apis.excel.excelclient import ExcelWinCOMReceiver
from ufo.automator.app_apis.powerpoint.powerpointclient import PowerPointWinCOMReceiver
from ufo.automator.app_apis.shell.shell_client import ShellReceiver
from ufo.automator.app_apis.telegram.telegram_receiver import TelegramReceiver
from ufo.automator.app_apis.web.webclient import WebReceiver
from ufo.automator.app_apis.word.wordclient import WordWinCOMReceiver
from ufo.automator.basic import ReceiverFactory
from ufo.automator.puppeteer import ReceiverManager
from ufo.automation.factory import get_desktop_automation

logger = logging.getLogger(__name__)


class APIReceiverFactory(ReceiverFactory):
    """
    The factory class for the API receiver.
    """

    @classmethod
    def is_api(cls) -> bool:
        """
        Check if the receiver is API.
        """
        return True


@ReceiverManager.register
class COMReceiverFactory(APIReceiverFactory):
    """
    The factory class for the COM receiver.
    """

    def create_receiver(
        self, app_root_name: str, process_name: str
    ) -> WinCOMReceiverBasic:
        """
        Create the wincom receiver.
        :param app_root_name: The app root name.
        :param process_name: The process name.
        :return: The receiver.
        """

        com_receiver = self.__com_client_mapper(app_root_name)
        clsid = self.__app_root_mappping(app_root_name)

        if clsid is None or com_receiver is None:

            return None

        return com_receiver(app_root_name, process_name, clsid)

    def __com_client_mapper(self, app_root_name: str) -> Type[WinCOMReceiverBasic]:
        """
        Map the app root to the corresponding COM client.
        :param app_root_name: The app root name.
        :return: The COM client.
        """
        win_com_client_mapping = {
            "WINWORD.EXE": WordWinCOMReceiver,
            "EXCEL.EXE": ExcelWinCOMReceiver,
            "POWERPNT.EXE": PowerPointWinCOMReceiver,
        }

        com_receiver = win_com_client_mapping.get(app_root_name, None)

        return com_receiver

    def __app_root_mappping(self, app_root_name: str) -> str:
        """
        Map the app root to the corresponding app.
        :return: The CLSID of the COM object.
        """

        win_com_map = {
            "WINWORD.EXE": "Word.Application",
            "EXCEL.EXE": "Excel.Application",
            "POWERPNT.EXE": "PowerPoint.Application",
            "olk.exe": "Outlook.Application",
        }

        return win_com_map.get(app_root_name, None)

    @classmethod
    def name(cls) -> str:
        """
        The name of the factory.
        """
        return "COM"


@ReceiverManager.register
class WebReceiverFactory(APIReceiverFactory):
    """
    The factory class for the COM receiver.
    """

    def create_receiver(self, app_root_name: str, *args, **kwargs) -> ReceiverBasic:
        """
        Create the web receiver.
        :param app_root_name: The app root name.
        :param process_name: The process name.
        :return: The receiver.
        """

        if app_root_name not in self.supported_app_roots:
            return None

        web_receiver = WebReceiver()
        logger.info(f"Web receiver created for {app_root_name}.")

        return web_receiver

    @property
    def supported_app_roots(self):
        """
        Get the supported app roots.
        """
        return ["msedge.exe", "chrome.exe"]

    @classmethod
    def name(cls) -> str:
        """
        The name of the factory.
        """
        return "Web"


@ReceiverManager.register
class ShellReceiverFactory(APIReceiverFactory):
    """
    The factory class for the API receiver.
    """

    def create_receiver(self, *args, **kwargs) -> ReceiverBasic:
        """
        Create the web receiver.
        :param app_root_name: The app root name.
        :return: The receiver.
        """

        return ShellReceiver()

    @property
    def supported_app_roots(self):
        """
        Get the supported app roots.
        """
        return

    @classmethod
    def name(cls) -> str:
        """
        The name of the factory.
        """
        return "Shell"


@ReceiverManager.register
class TelegramReceiverFactory(APIReceiverFactory):
    """
    The factory class for the Telegram Desktop GUI receiver.
    Uses hybrid UIA + Keyboard + Visual automation.
    """

    def create_receiver(
        self, app_root_name: str, process_name: str, *args, **kwargs
    ) -> Optional[ReceiverBasic]:
        """
        Create the Telegram GUI receiver.
        :param app_root_name: The app root name (e.g., "Telegram.exe").
        :param process_name: The process name.
        :return: The receiver or None if not supported.
        """

        if app_root_name not in self.supported_app_roots:
            return None

        # Get the appropriate desktop automation backend
        desktop = get_desktop_automation(process_name)
        
        telegram_receiver = TelegramReceiver(app_root_name, process_name, desktop)
        logger.info(f"Telegram GUI receiver created for {app_root_name}.")

        return telegram_receiver

    @property
    def supported_app_roots(self):
        """
        Get the supported app roots.
        """
        return ["Telegram.exe", "telegram.exe"]

    @classmethod
    def name(cls) -> str:
        """
        The name of the factory.
        """
        return "TelegramGUI"
