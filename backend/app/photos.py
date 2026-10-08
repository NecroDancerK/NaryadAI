"""Bounded decoding of raster uploads. Original bytes are not rewritten."""
import asyncio
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from io import BytesIO

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

MAX_PHOTO_BYTES = 10 * 1024 * 1024
MAX_BATCH_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 24_000_000
MAX_SIDE = 8192
FORMATS = {'JPEG': ('image/jpeg', '.jpg'), 'PNG': ('image/png', '.png'), 'WEBP': ('image/webp', '.webp')}
# Set once, not inside concurrent catch_warnings contexts. Keep Pillow's own
# MAX_IMAGE_PIXELS enabled; the smaller application limit is checked before load.
warnings.filterwarnings('error', category=Image.DecompressionBombWarning)
_decoders = ThreadPoolExecutor(max_workers=2, thread_name_prefix='photo-decode')


@dataclass(frozen=True)
class ValidatedPhoto:
    data: bytes
    content_type: str
    suffix: str
    width: int
    height: int


async def read_photo(photo: UploadFile) -> bytes:
    data = await photo.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, 'Фото превышает 10 МиБ')
    return data


def validate_photo(data: bytes, declared_type: str | None) -> ValidatedPhoto:
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, 'Фото превышает 10 МиБ')
    declared = (declared_type or '').lower().split(';', 1)[0].strip()
    declared = {'image/jpg': 'image/jpeg', 'image/pjpeg': 'image/jpeg'}.get(declared, declared)
    allowed = {value[0] for value in FORMATS.values()}
    if declared not in allowed | {'', 'application/octet-stream'}:
        raise HTTPException(422, 'Нужен JPEG, PNG или WebP. HEIC, SVG, GIF и другие форматы не поддерживаются')
    try:
        with Image.open(BytesIO(data), formats=list(FORMATS)) as image:
            mime, suffix = FORMATS[image.format]
            width, height = image.size
            if width > MAX_SIDE or height > MAX_SIDE or width * height > MAX_PIXELS:
                raise HTTPException(413, 'Фото превышает 24 Мп или 8192 пикселя по стороне. Уменьшите разрешение')
            if getattr(image, 'n_frames', 1) != 1:
                raise HTTPException(422, 'Анимированные изображения не поддерживаются')
            if declared in allowed and declared != mime:
                raise HTTPException(422, 'Заявленный формат фото не совпадает с содержимым')
            image.verify()
        # verify() is not a full pixel decode, notably for JPEG. Reopen and load.
        with Image.open(BytesIO(data), formats=list(FORMATS)) as image:
            image.load()
        return ValidatedPhoto(data, mime, suffix, width, height)
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise HTTPException(413, 'Слишком большое разрешение фото. Уменьшите изображение') from error
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, TypeError) as error:
        raise HTTPException(422, 'Фото повреждено или не является поддерживаемым изображением JPEG, PNG, WebP') from error


async def decode_photo(data: bytes, declared_type: str | None) -> ValidatedPhoto:
    # Limit concurrent pixel decodes per process and keep CPU work off the event loop.
    return await asyncio.get_running_loop().run_in_executor(_decoders, validate_photo, data, declared_type)
