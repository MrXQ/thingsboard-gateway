import unittest
from PIL import Image


class TestIcons(unittest.TestCase):
    def test_create_status_icon_returns_pil_image(self):
        from tb_gateway_windows.icons import create_status_icon
        icon = create_status_icon("green")
        self.assertIsInstance(icon, Image.Image)
        self.assertEqual(icon.size, (64, 64))

    def test_create_status_icon_all_colors(self):
        from tb_gateway_windows.icons import create_status_icon
        for color in ["green", "yellow", "red", "orange", "grey"]:
            icon = create_status_icon(color)
            self.assertIsInstance(icon, Image.Image)

    def test_create_status_icon_has_alpha_channel(self):
        from tb_gateway_windows.icons import create_status_icon
        icon = create_status_icon("green")
        self.assertEqual(icon.mode, "RGBA")


if __name__ == '__main__':
    unittest.main()
