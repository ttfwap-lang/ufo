"""
PDF Reader MCP Server
Provides MCP server for PDF text extraction operations.
"""
import platform
import sys
if platform.system() != 'Windows':
    import logging
    logging.warning(f'pdf_reader_mcp_server.py requires Windows platform. Current: {platform.system()}. Skipping module initialization.')
    sys.exit(0)
import os
import time
import random
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional
import pypdf
from fastmcp import FastMCP
from fastmcp.client import Client
from pydantic import Field
from ufo.automator.path_validator import validate_path_not_sensitive
from ufo.client.mcp.mcp_registry import MCPRegistry
from ufo.config import get_config
configs = get_config()

@MCPRegistry.register_factory_decorator('PDFReaderExecutor')
@MCPRegistry.register_factory_decorator('pdf_reader_mcp_server')
def create_pdf_reader_mcp_server(*args, **kwargs) -> FastMCP:
    """
    Create and return the PDF Reader MCP server instance.
    :return: FastMCP instance for PDF operations.
    """

    def _extract_text_from_pdf(pdf_path: str, simulate_human: bool = False) -> str:
        """
        Extract text content cleanly and deterministically from a single PDF file.
        :param pdf_path: Path to the PDF file.
        :param simulate_human: Deprecated compatibility flag (ignored to protect UI focus).
        :return: Extracted text content.
        """
        try:
            validate_path_not_sensitive(pdf_path)
            with open(pdf_path, 'rb') as file:
                pdf_reader = pypdf.PdfReader(file)
                text_content = ''
                for page_num in range(len(pdf_reader.pages)):
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text() or ''
                    text_content += f'\n--- Page {page_num + 1} ---\n'
                    text_content += page_text
            return text_content.strip()
        except Exception as e:
            return f'Error reading PDF {pdf_path}: {str(e)}'

    def _extract_text_from_pdf_batch(pdf_paths: List[str], simulate_human: bool=True) -> Dict[str, str]:
        """
        Extract text from multiple PDF files with human simulation.
        :param pdf_paths: List of PDF file paths.
        :param simulate_human: Whether to simulate human-like behavior.
        :return: Dictionary mapping filenames to extracted text.
        """
        results = {}
        total_files = len(pdf_paths)
        if simulate_human:
            print(f'📚 Starting batch processing of {total_files} PDF files...')
            print('🤖 Simulating human-like document review process...')
        for i, pdf_path in enumerate(pdf_paths, 1):
            file_name = os.path.basename(pdf_path)
            if simulate_human:
                print(f'\n📂 Processing file {i}/{total_files}: {file_name}')
                if i > 1:
                    between_files_wait = random.uniform(1.0, 3.0)
                    print(f'⏳ Taking a brief break between files... {between_files_wait:.1f}s')
                    time.sleep(between_files_wait)
            text_content = _extract_text_from_pdf(pdf_path, simulate_human)
            results[file_name] = text_content
            if simulate_human:
                print(f'✅ Completed: {file_name}')
        if simulate_human:
            print(f'\n🎉 Batch processing completed! Processed {total_files} files.')
        return results

    def _get_pdf_files_in_directory(directory_path: str) -> List[str]:
        """
        Get all PDF files in the specified directory.
        :param directory_path: Path to the directory.
        :return: List of PDF file paths.
        """
        try:
            validate_path_not_sensitive(directory_path)
            pdf_files = []
            directory = Path(directory_path)
            if not directory.exists():
                return []
            for file_path in directory.iterdir():
                if file_path.is_file() and file_path.suffix.lower() == '.pdf':
                    pdf_files.append(str(file_path))
            return sorted(pdf_files)
        except Exception as e:
            print(f'Error scanning directory {directory_path}: {str(e)}')
            return []
    mcp = FastMCP('UFO PDF Reader MCP Server')

    @mcp.tool(tags={'PDF'})
    def extract_pdf_text(pdf_path: Annotated[str, Field(description='The full path to the PDF file to extract text from.')], simulate_human: Annotated[bool, Field(description='Whether to simulate human-like behavior (opening, reading, closing PDF). Default: True')]=True) -> Annotated[str, Field(description='The extracted text content from the PDF file.')]:
        """
        Extract text content from a single PDF file with optional human simulation.
        When simulate_human is True, the process will:
        1. Open the PDF file with default application
        2. Wait for a realistic reading time (2-5 seconds)
        3. Extract text with page-by-page delays
        4. Close the PDF file
        This simulates a human manually reviewing the document.
        """
        try:
            validate_path_not_sensitive(pdf_path)
        except Exception as ve:
            return f'Error: Access denied to path {pdf_path}: {ve}'
        if not os.path.exists(pdf_path):
            return f'Error: PDF file not found at {pdf_path}'
        if not pdf_path.lower().endswith('.pdf'):
            return f'Error: File {pdf_path} is not a PDF file'
        return _extract_text_from_pdf(pdf_path, simulate_human)

    @mcp.tool(tags={'PDF'})
    def list_pdfs_in_directory(directory_path: Annotated[str, Field(description='The directory path to scan for PDF files.')]) -> Annotated[List[str], Field(description='A list of PDF file paths found in the directory.')]:
        """
        List all PDF files in the specified directory.
        Returns a list of full paths to PDF files found in the directory.
        """
        try:
            validate_path_not_sensitive(directory_path)
        except Exception as ve:
            return []
        if not os.path.exists(directory_path):
            return []
        if not os.path.isdir(directory_path):
            return []
        return _get_pdf_files_in_directory(directory_path)

    @mcp.tool(tags={'PDF'})
    def extract_all_pdfs_text(directory_path: Annotated[str, Field(description='The directory path containing PDF files to extract text from.')], simulate_human: Annotated[bool, Field(description='Whether to simulate human-like behavior for each PDF. Default: True')]=True) -> Annotated[Dict[str, str], Field(description='A dictionary mapping PDF file paths to their extracted text content.')]:
        """
        Extract text content from all PDF files in the specified directory with human simulation.
        When simulate_human is True, the process will simulate a human reviewing each document:
        - Opening each PDF file
        - Taking realistic reading time
        - Taking breaks between files
        - Closing each PDF file
        Returns a dictionary where keys are PDF file paths and values are the extracted text content.
        """
        try:
            validate_path_not_sensitive(directory_path)
        except Exception as ve:
            return {'error': f'Access denied to path {directory_path}: {ve}'}
        if not os.path.exists(directory_path):
            return {'error': f'Directory not found: {directory_path}'}
        if not os.path.isdir(directory_path):
            return {'error': f'Path is not a directory: {directory_path}'}
        pdf_files = _get_pdf_files_in_directory(directory_path)
        if not pdf_files:
            return {'message': f'No PDF files found in directory: {directory_path}'}
        return _extract_text_from_pdf_batch(pdf_files, simulate_human)
    return mcp
if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.ERROR)
    mcp = create_pdf_reader_mcp_server()
    mcp.run()