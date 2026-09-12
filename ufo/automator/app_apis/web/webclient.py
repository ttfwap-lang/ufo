from __future__ import annotations
import logging
from typing import Any, Dict, Type
import html2text
import requests
from ufo.automator.basic import CommandBasic, ReceiverBasic
from ufo.utils.url_security import safe_get
logger = logging.getLogger(__name__)

class WebReceiver(ReceiverBasic):
    """
    The base class for Web COM client using crawl4ai.
    """
    _command_registry: Dict[str, Type[WebCommand]] = {}

    def __init__(self) -> None:
        """
        Initialize the Web COM client.
        """
        self._headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
        self.browser = None
        self.current_page = None

    def web_crawler(self, url: str, ignore_link: bool) -> str:
        """
        Run the crawler with various options.
        :param url: The URL of the webpage.
        :param ignore_link: Whether to ignore the links.
        :return: The result markdown content.
        """
        try:
            response = safe_get(url, headers=self._headers)
            response.raise_for_status()
            html_content = response.text
            h = html2text.HTML2Text()
            h.ignore_links = ignore_link
            markdown_content = h.handle(html_content)
            return markdown_content
        except ValueError as e:
            logger.warning('Blocked URL request: %s', e)
            return f'Error fetching the URL: {e}'
        except requests.RequestException as e:
            logger.warning('Error fetching the URL: %s', e)
            return f'Error fetching the URL: {e}'

    def navigate_to_url(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Navigate browser to a specific URL.
        """
        url = params.get('url')
        try:
            response = safe_get(url, headers=self._headers)
            response.raise_for_status()
            self.current_page = response.text
            return {'success': True, 'url': url, 'status_code': response.status_code}
        except ValueError as e:
            logger.warning('Blocked URL request: %s', e)
            return {'error': f'Failed to navigate to URL: {e}', 'url': url}
        except Exception as e:
            return {'error': f'Failed to navigate to URL: {str(e)}', 'url': url}

    def get_page_content(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get the text content of the current web page.
        """
        selector = params.get('selector')
        try:
            if not self.current_page:
                return {'error': 'No page loaded. Use navigate_to_url first.'}
            if selector:
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(self.current_page, 'html.parser')
                    elements = soup.select(selector)
                    content = [elem.get_text().strip() for elem in elements]
                    return {'selector': selector, 'content': content}
                except ImportError:
                    return {'error': 'BeautifulSoup not available for CSS selectors'}
            else:
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(self.current_page, 'html.parser')
                    text_content = soup.get_text()
                    return {'content': text_content.strip()}
                except ImportError:
                    h = html2text.HTML2Text()
                    h.ignore_links = True
                    text_content = h.handle(self.current_page)
                    return {'content': text_content}
        except Exception as e:
            return {'error': f'Failed to get page content: {str(e)}'}

    def get_page_title(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get the title of the current web page.
        """
        try:
            if not self.current_page:
                return {'error': 'No page loaded. Use navigate_to_url first.'}
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(self.current_page, 'html.parser')
                title = soup.find('title')
                title_text = title.get_text().strip() if title else 'No title found'
                return {'title': title_text}
            except ImportError:
                import re
                title_match = re.search('<title[^>]*>([^<]+)</title>', self.current_page, re.IGNORECASE)
                title_text = title_match.group(1) if title_match else 'No title found'
                return {'title': title_text}
        except Exception as e:
            return {'error': f'Failed to get page title: {str(e)}'}

    def get_element_text(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get the text content of a specific element.
        """
        selector = params.get('selector')
        try:
            if not self.current_page:
                return {'error': 'No page loaded. Use navigate_to_url first.'}
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(self.current_page, 'html.parser')
                element = soup.select_one(selector)
                if element:
                    return {'selector': selector, 'text': element.get_text().strip()}
                else:
                    return {'error': f'Element not found: {selector}'}
            except ImportError:
                return {'error': 'BeautifulSoup not available for CSS selectors'}
        except Exception as e:
            return {'error': f'Failed to get element text: {str(e)}'}

    def get_element_attribute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get an attribute value of a specific element.
        """
        selector = params.get('selector')
        attribute = params.get('attribute')
        try:
            if not self.current_page:
                return {'error': 'No page loaded. Use navigate_to_url first.'}
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(self.current_page, 'html.parser')
                element = soup.select_one(selector)
                if element:
                    attr_value = element.get(attribute)
                    return {'selector': selector, 'attribute': attribute, 'value': attr_value}
                else:
                    return {'error': f'Element not found: {selector}'}
            except ImportError:
                return {'error': 'BeautifulSoup not available for CSS selectors'}
        except Exception as e:
            return {'error': f'Failed to get element attribute: {str(e)}'}

    @property
    def type_name(self):
        return 'WEB'

    @property
    def xml_format_code(self) -> int:
        return 0

class WebCommand(CommandBasic):
    """
    The base class for Web commands.
    """

    def __init__(self, receiver: WebReceiver, params: Dict[str, Any]) -> None:
        """
        Initialize the Web command.
        :param receiver: The receiver of the command.
        :param params: The parameters of the command.
        """
        super().__init__(receiver, params)
        self.receiver = receiver

    @classmethod
    def name(cls) -> str:
        """
        The name of the command.
        """
        return 'web'

@WebReceiver.register
class WebCrawlerCommand(WebCommand):
    """
    The command to run the crawler with various options.
    """

    def execute(self):
        """
        Execute the command to run the crawler.
        :return: The result content.
        """
        return self.receiver.web_crawler(url=self.params.get('url'), ignore_link=self.params.get('ignore_link', False))

    @classmethod
    def name(cls) -> str:
        """
        The name of the command.
        """
        return 'web_crawler'

@WebReceiver.register
class NavigateToUrlCommand(WebCommand):

    def execute(self):
        return self.receiver.navigate_to_url(params=self.params)

    @classmethod
    def name(cls) -> str:
        return 'navigate_to_url'

@WebReceiver.register
class GetPageContentCommand(WebCommand):

    def execute(self):
        return self.receiver.get_page_content(params=self.params)

    @classmethod
    def name(cls) -> str:
        return 'get_page_content'

@WebReceiver.register
class GetPageTitleCommand(WebCommand):

    def execute(self):
        return self.receiver.get_page_title(params=self.params)

    @classmethod
    def name(cls) -> str:
        return 'get_page_title'

@WebReceiver.register
class GetElementTextCommand(WebCommand):

    def execute(self):
        return self.receiver.get_element_text(params=self.params)

    @classmethod
    def name(cls) -> str:
        return 'get_element_text'

@WebReceiver.register
class GetElementAttributeCommand(WebCommand):

    def execute(self):
        return self.receiver.get_element_attribute(params=self.params)

    @classmethod
    def name(cls) -> str:
        return 'get_element_attribute'