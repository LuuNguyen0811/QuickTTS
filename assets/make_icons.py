#!/usr/bin/env python3
"""Build the app icon from the waveform, and the page and menu-bar marks from the chicken."""

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
CHICKEN = ROOT / "source-chicken.png"
DOCS_ICON = ROOT.parent / "docs" / "icon.png"
ICONSET = ROOT / "AppIcon.iconset"

# Measured from the waveform artwork, in source pixels.
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


def chicken_cover(red, green, blue):
    """How much of this pixel is the chicken, not the black tile or the navy mat."""
    if blue < 0.28 or green < 0.15:
        return 0.0
    return min(1.0, max(0.0, (min(green, blue) - 0.14) / 0.12))


def is_mat(red, green, blue):
    return (
        blue > 0.05
        and red < 0.12
        and green < 0.30
        and blue > red + 0.04
        and chicken_cover(red, green, blue) == 0.0
    )


def _components(bitmap, x, y):
    color = bitmap.colorAtX_y_(x, y)
    return (
        color.redComponent(),
        color.greenComponent(),
        color.blueComponent(),
        color.alphaComponent(),
    )


def cleaned_chicken(source) -> NSBitmapImageRep:
    """Crop the artwork and drop the navy mat around the rounded tile."""
    width = source.pixelsWide()
    height = source.pixelsHigh()
    outside = [[False] * width for _ in range(height)]
    stack = []
    for x in range(width):
        stack.append((x, 0))
        stack.append((x, height - 1))
    for y in range(height):
        stack.append((0, y))
        stack.append((width - 1, y))
    while stack:
        x, y = stack.pop()
        if x < 0 or y < 0 or x >= width or y >= height or outside[y][x]:
            continue
        red, green, blue, _alpha = _components(source, x, y)
        if not is_mat(red, green, blue):
            continue
        outside[y][x] = True
        stack.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))

    min_x, min_y, max_x, max_y = width, height, 0, 0
    for y in range(height):
        for x in range(width):
            if outside[y][x]:
                continue
            min_x, min_y = min(min_x, x), min(min_y, y)
            max_x, max_y = max(max_x, x), max(max_y, y)
    side = max(max_x - min_x + 1, max_y - min_y + 1)
    bitmap = empty_bitmap(side, side)
    clear = NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0)
    offset_x = (side - (max_x - min_x + 1)) // 2
    offset_y = (side - (max_y - min_y + 1)) // 2
    for y in range(side):
        for x in range(side):
            src_x = min_x + x - offset_x
            src_y = min_y + y - offset_y
            if (
                src_x < 0
                or src_y < 0
                or src_x >= width
                or src_y >= height
                or outside[src_y][src_x]
            ):
                bitmap.setColor_atX_y_(clear, x, y)
                continue
            red, green, blue, alpha = _components(source, src_x, src_y)
            bitmap.setColor_atX_y_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    red, green, blue, alpha
                ),
                x,
                y,
            )
    return bitmap


def chicken_template(size: int) -> NSBitmapImageRep:
    from AppKit import NSGraphicsContext, NSImageInterpolationHigh

    source = NSImage.alloc().initWithContentsOfFile_(str(CHICKEN))
    bitmap = NSBitmapImageRep.imageRepWithData_(source.TIFFRepresentation())
    width = bitmap.pixelsWide()
    height = bitmap.pixelsHigh()
    silhouette = empty_bitmap(width, height)
    min_x, min_y, max_x, max_y = width, height, 0, 0
    for y in range(height):
        for x in range(width):
            red, green, blue, alpha = _components(bitmap, x, y)
            cover = chicken_cover(red, green, blue) * alpha
            silhouette.setColor_atX_y_(
                NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, cover),
                x,
                y,
            )
            if cover > 0.2:
                min_x, min_y = min(min_x, x), min(min_y, y)
                max_x, max_y = max(max_x, x), max(max_y, y)
    art_w = max_x - min_x + 1
    art_h = max_y - min_y + 1
    pad = size * 0.08
    scale = min((size - pad * 2) / art_w, (size - pad * 2) / art_h)
    drawn_w = art_w * scale
    drawn_h = art_h * scale
    origin_x = (size - drawn_w) / 2
    origin_y = (size - drawn_h) / 2
    artwork = image_from_bitmap(silhouette)
    canvas = empty_bitmap(size, size)
    clear = NSColor.colorWithCalibratedRed_green_blue_alpha_(0, 0, 0, 0)
    for y in range(size):
        for x in range(size):
            canvas.setColor_atX_y_(clear, x, y)
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(canvas)
    NSGraphicsContext.setCurrentContext_(context)
    context.setImageInterpolation_(NSImageInterpolationHigh)
    artwork.drawInRect_fromRect_operation_fraction_(
        NSMakeRect(origin_x, origin_y, drawn_w, drawn_h),
        NSMakeRect(min_x, height - max_y - 1, art_w, art_h),
        NSCompositingOperationSourceOver,
        1.0,
    )
    NSGraphicsContext.setCurrentContext_(None)
    return canvas


def main():
    source = load_source()
    wave_bitmap = waveform_image(source)
    wave = image_from_bitmap(wave_bitmap)
    icon = render_square(wave, 1024)
    write_png(icon, ROOT / "AppIcon-1024.png")
    write_png(chicken_template(72), ROOT / "menubarTemplate.png")
    write_png(chicken_template(18), ROOT / "menubarTemplate-18.png")
    if CHICKEN.is_file():
        page = NSImage.alloc().initWithContentsOfFile_(str(CHICKEN))
        write_png(
            NSBitmapImageRep.imageRepWithData_(page.TIFFRepresentation()),
            DOCS_ICON,
        )

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
