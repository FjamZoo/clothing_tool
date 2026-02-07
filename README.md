Everything including this readme is ai generated, just a quick internal tool I created to make screenshotting clothing a lot nicer and might aswell share it, probably a lot of bloat/etc but who cares aslong as the tool works dosnt need to work the best way possible.

# Clothing Tool

Extracts diffuse textures from GTA V `.ytd` files and renders 3D previews for a FiveM clothing shop.

## Requirements

- Python 3.10+
- Pillow >= 10.2.0 (`pip install -r requirements.txt`)
- Blender 4.x with [Sollumz](https://github.com/Sollumz/Sollumz) addon (for 3D rendering)
- Node.js 18+ (for GUI only)

## CLI

```bash
pip install -r requirements.txt

# Full run with 3D rendering
python cli.py --input ./stream --output ./output --base-game ./base_game

# Flat textures only (no Blender needed)
python cli.py --input ./stream --output ./output --no-render-3d

# Dry run
python cli.py --dry-run

# See all options
python cli.py --help
```

## GUI

```bash
cd gui
npm install
npm start
```

Or double-click `rungui.bat` from the project root.
