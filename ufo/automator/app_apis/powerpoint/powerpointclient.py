import os
from typing import Dict, Type, List
from ufo.automator.app_apis.basic import WinCOMCommand, WinCOMReceiverBasic
from ufo.automator.basic import CommandBasic
from ufo.automator.path_validator import validate_save_path

class PowerPointWinCOMReceiver(WinCOMReceiverBasic):
    """
    The base class for Windows COM client.
    """
    _command_registry: Dict[str, Type[CommandBasic]] = {}

    def get_object_from_process_name(self) -> None:
        """
        Get the object from the process name.
        :return: The matched object.
        """
        object_name_list = [presentation.Name for presentation in self.client.Presentations]
        matched_object = self.app_match(object_name_list)
        for presentation in self.client.Presentations:
            if presentation.Name == matched_object:
                return presentation
        return None

    def set_background_color(self, color: str, slide_index: List[int]=None) -> str:
        """
        Set the background color of the slide(s).
        :param color: The hex color code (in RGB format) to set the background color.
        :param slide_index: The list of slide indexes to set the background color. If None, set the background color for all slides.
        :return: The result of setting the background color.
        """
        if not slide_index:
            slide_index = range(1, self.com_object.Slides.Count + 1)
        red = int(color[0:2], 16)
        green = int(color[2:4], 16)
        blue = int(color[4:6], 16)
        bgr_hex = (blue << 16) + (green << 8) + red
        try:
            for index in slide_index:
                if index < 1 or index > self.com_object.Slides.Count:
                    continue
                slide = self.com_object.Slides(index)
                slide.FollowMasterBackground = False
                slide.Background.Fill.Visible = True
                slide.Background.Fill.Solid()
                slide.Background.Fill.ForeColor.RGB = bgr_hex
            return f'Successfully Set the background color to {color} for slide(s) {slide_index}.'
        except Exception as e:
            raise RuntimeError(f'Failed to set the background color. Error: {e}')

    def save_as(self, file_dir: str='', file_name: str='', file_ext: str='', current_slide_only: bool=False) -> str:
        """
        Save the document to other formats.
        :param file_dir: The directory to save the file.
        :param file_name: The name of the file without extension.
        :param file_ext: The extension of the file.
        """
        ppt_ext_to_fileformat = {'.pptx': 24, '.ppt': 0, '.pdf': 32, '.xps': 33, '.potx': 25, '.pot': 5, '.ppsx': 27, '.pps': 1, '.odp': 35, '.jpg': 17, '.png': 18, '.gif': 19, '.bmp': 20, '.tif': 21, '.tiff': 21, '.rtf': 6, '.html': 12, '.mp4': 39, '.wmv': 38, '.xml': 10}
        ppt_ext_to_formatstr = {'.jpg': 'JPG', '.png': 'PNG', '.gif': 'GIF', '.bmp': 'BMP', '.tif': 'TIF', '.tiff': 'TIF'}
        if not file_dir:
            file_dir = self.document_dir()
        if not file_name:
            file_name = os.path.splitext(os.path.basename(self.com_object.FullName))[0]
        if not file_ext:
            file_ext = '.pptx'
        document_dir = self.document_dir()
        file_dir = validate_save_path(file_dir, document_dir)
        file_path = os.path.join(file_dir, file_name + file_ext)
        try:
            if self.com_object.Slides.Count == 1 and file_ext in ppt_ext_to_formatstr.keys():
                self.com_object.Slides(1).Export(file_path, ppt_ext_to_formatstr.get(file_ext, 'PNG'))
            elif current_slide_only and file_ext in ppt_ext_to_formatstr.keys():
                current_slide_idx = self._current_slide_index()
                self.com_object.Slides(current_slide_idx).Export(file_path, ppt_ext_to_formatstr.get(file_ext, 'PNG'))
            else:
                self.com_object.SaveAs(file_path, FileFormat=ppt_ext_to_fileformat.get(file_ext, 24))
            return f'Document is saved to {file_path}.'
        except Exception as e:
            raise RuntimeError(f'Failed to save document. Error: {e}')

    def _current_slide_index(self) -> int:
        """Index of the slide being shown: slideshow if running, else the editing window's slide."""
        try:
            return self.com_object.SlideShowWindow.View.Slide.SlideIndex
        except Exception:
            return self.client.ActiveWindow.View.Slide.SlideIndex

    def add_slide(self, title: str = '', body: str = '', layout: str = 'title_and_content', position: int = -1) -> str:
        """Add a slide (layout: title, title_and_content, title_only, blank) with optional title/body text."""
        layouts = {'title': 1, 'title_and_content': 2, 'title_only': 11, 'blank': 12}
        if layout not in layouts:
            raise ValueError(f'layout must be one of {sorted(layouts)}')
        slides = self.com_object.Slides
        index = slides.Count + 1 if position in (-1, None) else max(1, min(position, slides.Count + 1))
        slide = slides.Add(index, layouts[layout])
        placeholders = slide.Shapes.Placeholders
        if title and placeholders.Count >= 1:
            placeholders(1).TextFrame.TextRange.Text = title
        if body and placeholders.Count >= 2:
            placeholders(2).TextFrame.TextRange.Text = body
        return f'Added slide {index} ({layout}).'

    def set_slide_text(self, slide_index: int, placeholder_index: int, text: str) -> str:
        """Replace the text of a placeholder (1 = title, 2 = body on most layouts) on a slide."""
        slide = self.com_object.Slides(slide_index)
        placeholders = slide.Shapes.Placeholders
        if placeholder_index < 1 or placeholder_index > placeholders.Count:
            raise ValueError(f'Slide {slide_index} has {placeholders.Count} placeholders.')
        placeholders(placeholder_index).TextFrame.TextRange.Text = text
        return f'Set placeholder {placeholder_index} on slide {slide_index}.'

    def get_slides_text(self) -> str:
        """All text on every slide, one block per slide."""
        blocks = []
        for slide in self.com_object.Slides:
            texts = []
            for shape in slide.Shapes:
                try:
                    if shape.HasTextFrame and shape.TextFrame.HasText:
                        texts.append(shape.TextFrame.TextRange.Text.strip())
                except Exception:
                    continue
            blocks.append(f'Slide {slide.SlideIndex}: ' + ' | '.join(t for t in texts if t))
        return '\n'.join(blocks) if blocks else 'The presentation has no slides.'

    def insert_image(self, slide_index: int, image_path: str, left: float = 50, top: float = 100, width: float = 0) -> str:
        """Insert a picture on a slide at (left, top) points; width in points (0 keeps original size)."""
        if not os.path.isfile(image_path):
            raise FileNotFoundError(f'Image not found: {image_path}')
        slide = self.com_object.Slides(slide_index)
        shape = slide.Shapes.AddPicture(os.path.abspath(image_path), False, True, left, top)
        if width:
            shape.LockAspectRatio = True
            shape.Width = width
        return f'Inserted image {os.path.basename(image_path)} on slide {slide_index}.'

    @property
    def type_name(self):
        return 'COM/POWERPOINT'

    @property
    def xml_format_code(self) -> int:
        return 10

@PowerPointWinCOMReceiver.register
class SetBackgroundColorCommand(WinCOMCommand):
    """
    The command to set the background color of the slide(s).
    """

    def execute(self):
        """
        Execute the command to set the background color of the slide(s).
        :return: The result of setting the background color.
        """
        return self.receiver.set_background_color(self.params.get('color', ''), self.params.get('slide_index', []))

    @classmethod
    def name(cls) -> str:
        """
        The name of the command.
        """
        return 'set_background_color'

@PowerPointWinCOMReceiver.register
class SaveAsCommand(WinCOMCommand):
    """
    The command to save the document to PDF.
    """

    def execute(self):
        """
        Execute the command to save the document to PDF.
        :return: The result of saving the document to PDF.
        """
        return self.receiver.save_as(self.params.get('file_dir'), self.params.get('file_name'), self.params.get('file_ext'), self.params.get('current_slide_only', False))

    @classmethod
    def name(cls) -> str:
        """
        The name of the command.
        """
        return 'save_as'