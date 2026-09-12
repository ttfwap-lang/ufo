from . import basic
import os
import logging
from langchain_community.document_loaders import UnstructuredXMLLoader
from langchain_core.documents import Document
import defusedxml.ElementTree as ET
logger = logging.getLogger(__name__)

class XMLLoader(basic.BasicDocumentLoader):
    """
    Class to load XML documents.
    """

    def __init__(self, directory: str=None):
        """
        Create a new XMLLoader.
        """
        super().__init__()
        self.extensions = '.xml'
        self.directory = directory

    def get_microsoft_document_metadata(self, file: str):
        """
        Get the metadata for the given file.
        :param file: The file to get the metadata for.
        :return: The metadata for the given file.
        """
        if not os.path.exists(file):
            return {'title': os.path.basename(file), 'summary': os.path.basename(file)}
        tree = ET.parse(file)
        root = tree.getroot()
        if root.find('title') is not None:
            title = root.find('title').text
        else:
            title = None
        if root.find('Content-Summary') is not None:
            summary = root.find('Content-Summary').attrib['value']
        else:
            summary = None
        return {'title': title, 'summary': summary}

    def get_microsoft_document_text(self, file: str):
        """
        Get the text for the given file.
        :param file: The file to get the text for.
        :return: The text for the given file.
        """
        try:
            doc_text = UnstructuredXMLLoader(file).load()[0].page_content
        except Exception as e:
            logger.warning(f'XML parse error: {e}')
            doc_text = None
        return doc_text

    def construct_document(self):
        """
        Construct a langchain document list.
        :return: The langchain document list.
        """
        documents = []
        for file in self.load_file_name():
            text = self.get_microsoft_document_text(file)
            metadata = self.get_microsoft_document_metadata(file + '.meta')
            title = metadata['title']
            summary = metadata['summary']
            page_content = '{title} - {summary}'.format(title=title, summary=summary)
            metadata = {'title': title, 'summary': summary, 'text': text}
            document = Document(page_content=page_content, metadata=metadata)
            documents.append(document)
        return documents