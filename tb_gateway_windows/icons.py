"""Generate system tray status icons using Pillow."""

from PIL import Image, ImageDraw

# Status color mapping
STATUS_COLORS = {
    "green": (76, 175, 80),      # Connected
    "yellow": (255, 193, 7),     # Starting
    "red": (244, 67, 54),        # Disconnected
    "orange": (255, 152, 0),     # Connector(s) down
    "grey": (158, 158, 158),     # Stopped
}

ICON_SIZE = 64


def create_status_icon(color_name: str) -> Image.Image:
    """Create a circle icon with the given status color.

    Args:
        color_name: One of 'green', 'yellow', 'red', 'orange', 'grey'

    Returns:
        A 64x64 RGBA PIL Image with a colored circle and dark border.
    """
    rgb = STATUS_COLORS.get(color_name, STATUS_COLORS["grey"])

    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw outer border circle (dark)
    margin = 4
    draw.ellipse(
        [margin, margin, ICON_SIZE - margin - 1, ICON_SIZE - margin - 1],
        fill=rgb + (255,),
        outline=(50, 50, 50, 255),
        width=3,
    )

    # Draw inner highlight for 3D effect
    highlight_margin = margin + 8
    highlight_color = tuple(min(c + 60, 255) for c in rgb) + (100,)
    draw.ellipse(
        [highlight_margin, highlight_margin,
         ICON_SIZE // 2 + 4, ICON_SIZE // 2 + 4],
        fill=highlight_color,
    )

    return img
