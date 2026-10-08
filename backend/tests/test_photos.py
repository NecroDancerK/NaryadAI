import struct
import unittest
import zlib
from io import BytesIO
from unittest.mock import patch

from fastapi import HTTPException
from PIL import Image

from app.photos import MAX_PHOTO_BYTES, validate_photo


def raster(format='PNG',size=(16,16),color='gray'):
    output=BytesIO()
    Image.new('RGB',size,color).save(output,format=format)
    return output.getvalue()


def header_dimensions(width,height):
    data=raster()
    header=struct.pack('>II',width,height)+data[24:29]
    return data[:16]+header+struct.pack('>I',zlib.crc32(b'IHDR'+header))+data[33:]


class PhotoValidationTest(unittest.TestCase):
    def assert_rejected(self,data,mime,status=422):
        with self.assertRaises(HTTPException) as error:
            validate_photo(data,mime)
        self.assertEqual(error.exception.status_code,status)

    def test_real_formats_are_decoded_without_rewriting(self):
        for format,mime,suffix in [('JPEG','image/jpeg','.jpg'),('PNG','image/png','.png'),('WEBP','image/webp','.webp')]:
            data=raster(format)
            checked=validate_photo(data,mime)
            self.assertEqual(checked.data,data)
            self.assertEqual(checked.content_type,mime)
            self.assertEqual(checked.suffix,suffix)
            self.assertEqual((checked.width,checked.height),(16,16))

    def test_empty_unknown_mime_can_be_inferred_but_mismatch_is_rejected(self):
        for mime in [None,'','application/octet-stream']:
            self.assertEqual(validate_photo(raster(),mime).content_type,'image/png')
        self.assert_rejected(raster(),'image/jpeg')
        self.assertEqual(validate_photo(raster('JPEG'),'image/jpg').content_type,'image/jpeg')

    def test_disguised_svg_html_gif_and_empty_file_are_rejected(self):
        for data in [b'<svg xmlns="http://www.w3.org/2000/svg"/>',b'<html>not a photo</html>',raster('GIF'),b'',b'\xff\xd8\xffheader-only']:
            self.assert_rejected(data,'image/jpeg')
        self.assert_rejected(raster(),'image/heic')

    def test_size_limit_is_checked_before_decode(self):
        self.assert_rejected(b'x'*(MAX_PHOTO_BYTES+1),'image/jpeg',413)

    def test_resolution_and_side_limits_are_checked_before_pixel_decode(self):
        for width,height in [(8193,1),(6000,4001),(20000,20000)]:
            data=header_dimensions(width,height)
            with patch.object(Image.Image,'load',side_effect=AssertionError('Must not decode pixels')):
                self.assert_rejected(data,'image/png',413)

    def test_truncated_png_and_jpeg_are_rejected_by_verify_or_full_load(self):
        self.assert_rejected(raster()[:-15],'image/png')
        self.assert_rejected(raster('JPEG')[:-12],'image/jpeg')

    def test_animation_is_rejected(self):
        output=BytesIO()
        Image.new('RGB',(16,16),'red').save(output,format='PNG',save_all=True,append_images=[Image.new('RGB',(16,16),'blue')],duration=100,loop=0)
        self.assert_rejected(output.getvalue(),'image/png')


if __name__=='__main__':
    unittest.main()
