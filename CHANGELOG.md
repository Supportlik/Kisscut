# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-01

First release.

### Added

- Browser studio (`kisscut serve`): crop, straighten, trace, cut out, pick a
  die, set the border, preview on light and dark chat backgrounds, save.
- Command line (`kisscut make`) with the same render path as the studio.
- Photo repair for pictures of prints: tilt detection, gray-world white
  balance, black point, shadow lift, haze removal through large-radius local
  contrast, and unsharp masking. Four looks: `as-shot` (the default, which
  leaves the colours alone), `natural`, `print` (the full chain, selected
  automatically when a tilted print is detected) and `punchy`.
- Five cutout models via rembg, a freehand lasso, and reading a red pen outline
  off a marked copy of the photo.
- Eight dies: silhouette, circle, rounded, square, speech bubble, seal, heart,
  burst - with the subject allowed to overlap a geometric edge.
- Even border via distance transform, optional drop shadow, any border colour.
- Download as 512x512 PNG or WebP straight from the studio, with WebP quality
  stepped down to stay under WhatsApp's 100 KB limit for static stickers, or
  save both to a folder.
- Generated sample photos so the whole pipeline can be tried without supplying
  a private picture.
