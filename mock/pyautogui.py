from PIL import Image
def screenshot(*args, **kwargs):
    return Image.new('RGB', (1920, 1080), color='white')
