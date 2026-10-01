"""Tests that need no model files - they run offline, in CI, on a cold machine."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw

from kisscut import Recipe, Workshop, as_png, as_webp, cutout, photo, shapes
from kisscut.workshop import OUTPUT_EDGE, add_border


def photo_of_print(angle: float = 7.0, size=(420, 520)) -> Image.Image:
    """A dark picture lying on bright paper, rotated - what tilt_angle expects."""
    paper = Image.new("RGB", (int(size[0] * 1.3), int(size[1] * 1.3)), (242, 239, 232))
    inner = Image.new("RGB", size, (70, 90, 120))
    paper.paste(inner, ((paper.width - size[0]) // 2, int(size[1] * 0.18)))
    return paper.rotate(-angle, resample=Image.BICUBIC, expand=True, fillcolor=(240, 237, 230))


def busy_photo(size=(360, 300)) -> Image.Image:
    img = Image.new("RGB", size, (60, 70, 80))
    draw = ImageDraw.Draw(img)
    for x in range(0, size[0], 24):
        draw.rectangle((x, 0, x + 12, size[1]), fill=(120, 60, 50))
    draw.ellipse((120, 90, 240, 210), fill=(230, 220, 200))
    return img


# ------------------------------------------------------------------- photo

def test_tilt_angle_finds_a_rotated_print():
    assert photo.tilt_angle(photo_of_print(7.0)) == pytest.approx(7.0, abs=0.6)


def test_tilt_angle_ignores_an_ordinary_photo():
    assert photo.tilt_angle(busy_photo()) == 0.0


def test_deskew_reports_what_it_did():
    straightened, angle = photo.deskew(photo_of_print(9.0))
    assert angle == pytest.approx(9.0, abs=0.6)
    assert photo.tilt_angle(straightened) == pytest.approx(0.0, abs=0.6)


def test_develop_removes_a_colour_cast():
    tinted = np.full((80, 80, 3), 120, np.uint8)
    tinted[..., 2] = 200                                   # heavy blue cast
    before = np.asarray(Image.fromarray(tinted)).astype(float)
    after = np.asarray(photo.develop(Image.fromarray(tinted), "print")).astype(float)
    assert after[..., 2].mean() - after[..., 0].mean() < before[..., 2].mean() - before[..., 0].mean()


# ------------------------------------------------------------------ shapes

@pytest.mark.parametrize("shape", [s for s in shapes.SHAPES if s != "silhouette"])
def test_every_die_cuts_a_real_shape(shape):
    """Each geometric die covers a good part of the square, but not all of it."""
    mask = shapes.die(shape, 96)
    assert mask.size == (96, 96)
    coverage = np.asarray(mask).mean() / 255
    assert 0.25 < coverage < 0.999


def test_circle_die_keeps_the_corners_empty():
    a = np.asarray(shapes.die("circle", 128))
    assert a[2, 2] == 0 and a[-3, -3] == 0
    assert a[64, 64] == 255


# ------------------------------------------------------------------ cutout

def test_lasso_mask_follows_the_polygon():
    mask = cutout.by_lasso((200, 200), [(40, 40), (160, 40), (160, 160), (40, 160)])
    a = np.asarray(mask)
    assert a[100, 100] == 255
    assert a[5, 5] == 0


def test_red_line_outline_is_filled_in():
    img = Image.new("RGB", (240, 240), (90, 110, 130))
    ImageDraw.Draw(img).ellipse((50, 50, 190, 190), outline=(255, 0, 0), width=7)
    mask = np.asarray(cutout.by_red_line(img))
    assert mask[120, 120] == 255          # inside
    assert mask[5, 5] == 0                # outside


def test_red_line_without_a_line_returns_nothing():
    assert np.asarray(cutout.by_red_line(busy_photo())).max() == 0


def test_tidy_drops_specks_and_fills_holes():
    raw = np.zeros((200, 200), np.uint8)
    raw[50:150, 50:150] = 255
    raw[90:110, 90:110] = 0               # hole
    raw[10:14, 10:14] = 255               # speck
    tidied = np.asarray(cutout.tidy(Image.fromarray(raw)))
    assert tidied[100, 100] == 255
    assert tidied[12, 12] == 0


# ------------------------------------------------------------------ border

def test_border_is_as_wide_in_a_corner_as_on_an_edge():
    motif = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    ImageDraw.Draw(motif).rectangle((30, 30, 90, 90), fill=(200, 60, 60, 255))
    bordered = add_border(motif, 10, (255, 255, 255))
    alpha = np.asarray(bordered.split()[3])
    ys, xs = np.where(alpha > 128)
    # a square grown by 10 in every direction, corners included
    assert (xs.max() - xs.min()) == pytest.approx(60 + 20, abs=3)
    assert (ys.max() - ys.min()) == pytest.approx(60 + 20, abs=3)


# ---------------------------------------------------------------- workshop

def test_render_is_square_transparent_and_centred():
    shop = Workshop(busy_photo(), "sample")
    sticker = shop.render(Recipe(source="full", shape="circle", border=12, shadow=False))
    assert sticker.size == (OUTPUT_EDGE, OUTPUT_EDGE)
    alpha = np.asarray(sticker.split()[3])
    assert alpha[0, 0] == 0 and alpha[-1, -1] == 0
    assert alpha[OUTPUT_EDGE // 2, OUTPUT_EDGE // 2] == 255


def test_border_colour_reaches_the_edge_of_the_die():
    shop = Workshop(busy_photo(), "sample")
    sticker = shop.render(Recipe(source="full", shape="square", border=20,
                                 border_color="#ff0000", shadow=False))
    row = np.asarray(sticker.convert("RGBA"))[OUTPUT_EDGE // 2]
    opaque = np.where(row[:, 3] > 200)[0]
    assert tuple(row[opaque[0]][:3]) == (255, 0, 0)


def test_recipe_keys_separate_cheap_changes_from_expensive_ones():
    base = Recipe()
    wider = Recipe(border=30)
    other_crop = Recipe(crop=[0.1, 0.1, 0.9, 0.9])
    assert base.image_key == wider.image_key        # border never re-develops
    assert base.mask_key == wider.mask_key          # nor re-segments
    assert base.mask_key != other_crop.mask_key     # a crop does


def test_webp_stays_under_the_whatsapp_limit():
    shop = Workshop(busy_photo(), "sample")
    sticker = shop.render(Recipe(source="full", shape="rounded"))
    data, quality = as_webp(sticker)
    assert len(data) <= 99_000
    assert 40 <= quality <= 92
    assert as_png(sticker)[:8] == b"\x89PNG\r\n\x1a\n"


def test_unknown_shape_falls_back_to_a_full_square():
    shop = Workshop(busy_photo(), "sample")
    sticker = shop.render(Recipe(source="full", shape="nonsense", border=0, shadow=False))
    assert np.asarray(sticker.split()[3]).mean() > 200


@pytest.mark.models
def test_model_cutout_produces_a_mask():
    shop = Workshop(busy_photo(), "sample")
    sticker = shop.render(Recipe(source="model", model="isnet-general-use"))
    assert np.asarray(sticker.split()[3]).max() == 255


def test_as_shot_leaves_the_colours_alone():
    """The default look must not wash a photo out - it only sharpens.

    Sharpening lifts local contrast and with it a little saturation, so the
    test asks what actually matters: as-shot has to stay far closer to the
    original than print, which is allowed to rebuild the whole image.
    """
    source = busy_photo()
    before = np.asarray(source.convert("HSV")).astype(float)

    def drift(look):
        after = np.asarray(photo.develop(source, look).convert("HSV")).astype(float)
        return (abs(after[..., 2].mean() - before[..., 2].mean()) / before[..., 2].mean(),
                abs(after[..., 1].mean() - before[..., 1].mean()) / before[..., 1].mean())

    light, colour = drift("as-shot")
    print_light, print_colour = drift("print")
    assert light < 0.05, f"as-shot shifted brightness by {light:.0%}"
    assert light < print_light and colour < print_colour


def test_print_look_is_the_one_that_corrects():
    """...while `print` is allowed to change plenty, that is its job."""
    tinted = np.full((80, 80, 3), 120, np.uint8)
    tinted[..., 2] = 200
    out = np.asarray(photo.develop(Image.fromarray(tinted), "print")).astype(float)
    assert out[..., 2].mean() - out[..., 0].mean() < 80


def test_curved_border_is_antialiased():
    """A round die must not come out as a staircase."""
    motif = Image.new("RGBA", (300, 300), (40, 90, 160, 0))
    motif.putalpha(shapes.die("circle", 300))
    alpha = np.asarray(add_border(motif, 12, (255, 255, 255)).split()[3]).astype(int)
    soft = ((alpha > 8) & (alpha < 247)).sum()
    circumference = 2 * np.pi * (150 + 12)
    assert soft > circumference * 0.8, f"only {soft} soft pixels along {circumference:.0f}"
