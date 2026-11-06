# =========================================================================================
# OPENSTUDIOHUB
# Module: src/domain/render/image_formats.py
# Architectural role: Render domain / Blender image output formats
# =========================================================================================

"""Blender image output formats and their display extensions.

The list mirrors ``ImageFormatSettings.file_format`` in Blender 5.2. Video
(``FFMPEG``) is excluded because the render panel always writes frames.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImageFormat:
    identifier: str
    label: str
    extension: str
    depths: tuple[str, ...]
    modes: tuple[str, ...]
    default_depth: str
    default_mode: str
    multilayer: bool = False

    @property
    def media_type(self) -> str:
        return "MULTI_LAYER_IMAGE" if self.multilayer else "IMAGE"


IMAGE_FORMATS = (
    ImageFormat("AVIF", "AVIF", "avif", ("8", "10", "12"), ("RGB", "RGBA"), "8", "RGB"),
    ImageFormat("JPEG", "JPEG", "jpg", ("8",), ("BW", "RGB"), "8", "RGB"),
    ImageFormat("OPEN_EXR", "OpenEXR", "exr", ("16", "32"), ("RGB", "RGBA"), "16", "RGBA"),
    ImageFormat("PNG", "PNG", "png", ("8", "16"), ("BW", "RGB", "RGBA"), "8", "RGBA"),
    ImageFormat("WEBP", "WebP", "webp", ("8",), ("BW", "RGB", "RGBA"), "8", "RGBA"),
    ImageFormat("BMP", "Bitmap", "bmp", ("8",), ("BW", "RGB", "RGBA"), "8", "RGBA"),
    ImageFormat("CINEON", "Cineon", "cin", ("10",), ("RGB",), "10", "RGB"),
    ImageFormat("DPX", "DPX", "dpx", ("8", "10", "12", "16"), ("RGB", "RGBA"), "10", "RGB"),
    ImageFormat("IRIS", "Iris", "rgb", ("8", "16"), ("RGB", "RGBA"), "8", "RGB"),
    ImageFormat("JPEG2000", "JPEG 2000", "jp2", ("8", "10", "12", "16"), ("BW", "RGB", "RGBA"), "8", "RGB"),
    ImageFormat("HDR", "Radiance HDR", "hdr", ("32",), ("RGB",), "32", "RGB"),
    ImageFormat("TARGA", "Targa", "tga", ("8",), ("BW", "RGB", "RGBA"), "8", "RGBA"),
    ImageFormat("TARGA_RAW", "Targa Raw", "tga", ("8",), ("BW", "RGB", "RGBA"), "8", "RGBA"),
    ImageFormat("TIFF", "TIFF", "tif", ("8", "16", "32"), ("BW", "RGB", "RGBA"), "8", "RGBA"),
    ImageFormat(
        "OPEN_EXR_MULTILAYER",
        "OpenEXR MultiLayer",
        "exr",
        ("16", "32"),
        ("RGB", "RGBA"),
        "16",
        "RGBA",
        multilayer=True,
    ),
)

_BY_ID = {item.identifier: item for item in IMAGE_FORMATS}
_DEFAULT = _BY_ID["PNG"]


def image_format(identifier: str) -> ImageFormat:
    return _BY_ID.get(str(identifier or "").upper(), _DEFAULT)


def image_extension(identifier: str) -> str:
    return image_format(identifier).extension


def is_png(identifier: str) -> bool:
    return image_format(identifier).identifier == "PNG"
