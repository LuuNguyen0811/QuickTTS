#!/usr/bin/env python3
"""Build a macOS squircle app icon and a menu-bar template from the waveform."""

from pathlib import Path

from AppKit import (
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSCalibratedRGBColorSpace,
    NSColor,
    NSCompositeSourceOver,
    NSCompositingOperationSourceOver,
    NSImage,
    NSMakeRect,
    NSZeroRect,
)
from Foundation import NSMakeSize

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source-waveform.png"
ICONSET = ROOT / "AppIcon.iconset"

# Measured from the source artwork, in source pixels.
BARS = (
    (62, 95, 173, 270),
    (120, 154, 103, 340),
    (178, 213, 39, 403),
    (236, 271, 125, 318),
    (295, 329, 77, 366),
    (353, 387, 157, 286),
)
ART_BOX = (62, 39, 387, 403)


def load_source():
    image = NSImage.alloc().initWithContentsOfFile_(str(SOURCE))
    return NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())


def empty_bitmap(width, height):
    return NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None,
        width,
        height,
        8,
        4,
        True,
        False,
        NSCalibratedRGBColorSpace,
        0,
        0,
    )


def waveform_image(source):
    x0, y0, x1, y1 = ART_BOX
    width = x1 - x0 + 1
    height = y1 - y0 + 1
    bitmap = empty_bitmap(width, height)
    clear = NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0)
    for y in range(height):
        for x in range(width):
            bitmap.setColor_atX_y_(clear, x, y)
    for sx in range(x0, x1 + 1):
        for sy in range(y0, y1 + 1):
            color = source.colorAtX_y_(sx, sy)
            red = color.redComponent()
            green = color.greenComponent()
            blue = color.blueComponent()
            strength = max(red, green, blue)
            if strength < 0.05:
                continue
            alpha = min(1.0, (strength - 0.05) / 0.25)
            pixel = NSColor.colorWithCalibratedRed_green_blue_alpha_(
                red, green, blue, alpha
            )
            bitmap.setColor_atX_y_(pixel, sx - x0, sy - y0)
    return bitmap


def write_png(bitmap, path: Path):
    data = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
    data.writeToFile_atomically_(str(path), True)


def image_from_bitmap(bitmap) -> NSImage:
    image = NSImage.alloc().initWithSize_(
        NSMakeSize(bitmap.pixelsWide(), bitmap.pixelsHigh())
    )
    image.addRepresentation_(bitmap)
    return image


def render_square(waveform: NSImage, size: int) -> NSBitmapImageRep:
    canvas = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
    canvas.lockFocus()
    radius = size * 0.2237
    path = __import__("AppKit").NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(0, 0, size, size), radius, radius
    )
    NSColor.blackColor().set()
    path.fill()
    inset = size * 0.20
    dest = NSMakeRect(inset, inset, size - inset * 2, size - inset * 2)
    waveform.drawInRect_fromRect_operation_fraction_(
        dest, NSZeroRect, NSCompositingOperationSourceOver, 1.0
    )
    canvas.unlockFocus()
    return NSBitmapImageRep.imageRepWithData_(canvas.TIFFRepresentation())


def render_menubar(size: int) -> NSBitmapImageRep:
    from AppKit import NSBezierPath

    x0, y0, x1, y1 = ART_BOX
    art_w = x1 - x0 + 1
    art_h = y1 - y0 + 1
    pad = size * 0.06
    scale = min((size - pad * 2) / art_w, (size - pad * 2) / art_h)
    drawn_w = art_w * scale
    drawn_h = art_h * scale
    origin_x = (size - drawn_w) / 2
    origin_y = (size - drawn_h) / 2
    canvas = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
    canvas.lockFocus()
    NSColor.blackColor().set()
    for left, right, top, bottom in BARS:
        rx = origin_x + (left - x0) * scale
        rw = (right - left + 1) * scale
        cocoa_top = origin_y + (y1 - top) * scale
        cocoa_bottom = origin_y + (y1 - bottom) * scale
        rect = NSMakeRect(rx, cocoa_bottom, rw, cocoa_top - cocoa_bottom)
        radius = rw / 2
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            rect, radius, radius
        ).fill()
    canvas.unlockFocus()
    return NSBitmapImageRep.imageRepWithData_(canvas.TIFFRepresentation())


def main():
    source = load_source()
    wave_bitmap = waveform_image(source)
    wave = image_from_bitmap(wave_bitmap)
    icon = render_square(wave, 1024)
    write_png(icon, ROOT / "AppIcon-1024.png")
    write_png(render_menubar(36), ROOT / "menubarTemplate.png")
    write_png(render_menubar(18), ROOT / "menubarTemplate-18.png")

    ICONSET.mkdir(exist_ok=True)
    master = NSImage.alloc().initWithContentsOfFile_(str(ROOT / "AppIcon-1024.png"))
    sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for name, pixels in sizes.items():
        if pixels == 1024:
            write_png(icon, ICONSET / name)
            continue
        small = NSImage.alloc().initWithSize_(NSMakeSize(pixels, pixels))
        small.lockFocus()
        master.drawInRect_fromRect_operation_fraction_(
            NSMakeRect(0, 0, pixels, pixels),
            NSZeroRect,
            NSCompositeSourceOver,
            1.0,
        )
        small.unlockFocus()
        write_png(
            NSBitmapImageRep.imageRepWithData_(small.TIFFRepresentation()),
            ICONSET / name,
        )
    print("wrote icons")


if __name__ == "__main__":
    main()
