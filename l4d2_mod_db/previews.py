"""Bounded local JPEG/PNG/GIF-first-frame previews, isolated from scanners/SQL/Tk."""

from collections import OrderedDict
from io import BytesIO
import warnings

try:
    from PIL import Image
except ImportError:
    Image = None


class PreviewCache:
    def __init__(self):
        self.cache = OrderedDict()

    def load(self, access, package):
        if Image is None or package.preview is None: return None
        key = (str(access.validated_root),package.file.filename,package.file.signature,package.preview.signature)
        # A fresh validated observation is required even for a memory cache hit.
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        try:
            data = access.read_preview(package.file,package.preview)
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(BytesIO(data),formats=('JPEG','PNG','GIF')) as image:
                    width,height = image.size
                    if width < 1 or height < 1 or width > 4096 or height > 4096 or width*height > 16000000:
                        raise ValueError('Image dimensions exceed limits')
                    image.verify()
                with Image.open(BytesIO(data),formats=('JPEG','PNG','GIF')) as image:
                    image.draft('RGB',(128,128))
                    image.thumbnail((96,72))
                    image = image.convert('RGB')
                    # PPM is bounded decoded pixels; Tk never decodes untrusted JPEG.
                    result = f'P6\n{image.width} {image.height}\n255\n'.encode()+image.tobytes()
        except (OSError,ValueError,SyntaxError,Image.DecompressionBombWarning,Image.DecompressionBombError):
            result = None
        self.cache[key] = result
        while len(self.cache)>128: self.cache.popitem(last=False)
        return result
